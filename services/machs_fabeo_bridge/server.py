# -*- coding: utf-8 -*-
import BaseHTTPServer
import base64
import hashlib
import json
import os
import re
import traceback
import uuid

from charm.core.engine.util import bytesToObject, objectToBytes
from charm.toolbox.pairinggroup import GT, PairingGroup
from FABEO.fabeo22cp import FABEO22CPABE

HOST = '0.0.0.0'
PORT = int(os.environ.get('FABEO_PORT', '8200'))
FABEO_MODE = os.environ.get('FABEO_MODE', 'fabeo22cp')
INTERNAL_TOKEN = os.environ.get('FABEO_INTERNAL_TOKEN', os.environ.get('KMS_INTERNAL_TOKEN', 'change_me_internal_token'))
UNDERSCORE_ESCAPE = '0x5f0'

ATTR_RE = re.compile(r'^[a-z]+\.[a-z0-9_]+$')
POLICY_TOKEN_RE = re.compile(r'\s*(\(|\)|AND|OR|[A-Za-z]+\.[A-Za-z0-9_]+)\s*', re.IGNORECASE)

PAIRING_GROUP = None
ABE = None
MPK = None
MSK = None
STARTUP_ERROR = None
SESSION_KEYS = {}


class InternalTokenError(Exception):
    pass


def _b64encode(raw):
    return base64.b64encode(raw)


def _b64decode(value):
    if isinstance(value, unicode):
        value = value.encode('utf-8')
    return base64.b64decode(value)


def normalize_attr(attr):
    token = attr.strip().lower()
    if not ATTR_RE.match(token):
        raise ValueError('invalid attribute token')
    if '=' in token or ':' in token:
        raise ValueError('invalid attribute syntax')
    if isinstance(token, unicode):
        return token.encode('ascii')
    return token


def encode_attr(token):
    return token.replace('_', UNDERSCORE_ESCAPE).upper()


def normalize_policy(policy, encode_for_abe=False):
    if not isinstance(policy, basestring):
        raise ValueError('policy must be a string')
    if '=' in policy or ':' in policy:
        raise ValueError('invalid policy syntax: use dot notation')

    pos = 0
    tokens = []
    while pos < len(policy):
        match = POLICY_TOKEN_RE.match(policy, pos)
        if not match:
            if policy[pos].isspace():
                pos += 1
                continue
            raise ValueError('invalid policy syntax near position {0}'.format(pos))
        token = match.group(1)
        upper = token.upper()
        if upper == 'AND':
            tokens.append('and')
        elif upper == 'OR':
            tokens.append('or')
        elif token in ('(', ')'):
            tokens.append(token)
        else:
            normalized_attr = normalize_attr(token)
            tokens.append(encode_attr(normalized_attr) if encode_for_abe else normalized_attr)
        pos = match.end()

    normalized = ' '.join(tokens).strip()
    if not normalized:
        raise ValueError('empty policy')
    if isinstance(normalized, unicode):
        normalized = normalized.encode('ascii')
    if encode_for_abe:
        ABE.util.createPolicy(normalized)
    else:
        ABE.util.createPolicy(normalize_policy(normalized, encode_for_abe=True))
    return normalized


def merge_epoch(attributes, epoch):
    normalized = []
    for attr in attributes:
        token = normalize_attr(attr)
        if token.startswith('epoch.'):
            continue
        normalized.append(encode_attr(token))
    normalized.append(encode_attr(normalize_attr(epoch)))
    normalized = sorted(set(normalized))
    return normalized


def derive_dek(msg):
    msg_bytes = objectToBytes(msg, PAIRING_GROUP)
    return hashlib.sha256(msg_bytes).digest()


def serialize_element(elem):
    return _b64encode(PAIRING_GROUP.serialize(elem))


def deserialize_element(value):
    return PAIRING_GROUP.deserialize(_b64decode(value))


def serialize_ciphertext(ciphertext, policy_display, policy_abe):
    payload = {
        'policy_display': policy_display,
        'policy_abe': policy_abe,
        'g2_s1': serialize_element(ciphertext['g2_s1']),
        'g2_sprime': serialize_element(ciphertext['g2_sprime']),
        'Cp': serialize_element(ciphertext['Cp']),
        'ct': dict((attr, serialize_element(value)) for attr, value in ciphertext['ct'].items()),
    }
    return json.dumps(payload, sort_keys=True)


def deserialize_ciphertext(raw):
    payload = json.loads(raw)
    policy_abe = payload['policy_abe']
    policy_display = payload['policy_display']
    if isinstance(policy_abe, unicode):
        policy_abe = policy_abe.encode('ascii')
    if isinstance(policy_display, unicode):
        policy_display = policy_display.encode('ascii')
    return {
        'policy': ABE.util.createPolicy(policy_abe),
        'policy_str': policy_display,
        'g2_s1': deserialize_element(payload['g2_s1']),
        'g2_sprime': deserialize_element(payload['g2_sprime']),
        'Cp': deserialize_element(payload['Cp']),
        'ct': dict((attr, deserialize_element(value)) for attr, value in payload['ct'].items()),
    }


def runtime_ready():
    return STARTUP_ERROR is None and PAIRING_GROUP is not None and ABE is not None and MPK is not None and MSK is not None


def ensure_runtime():
    if not runtime_ready():
        raise ValueError('real FABEO runtime unavailable')


def initialize_runtime():
    global PAIRING_GROUP, ABE, MPK, MSK, STARTUP_ERROR
    try:
        if FABEO_MODE != 'fabeo22cp':
            raise ValueError('only fabeo22cp is supported')
        PAIRING_GROUP = PairingGroup('MNT224')
        ABE = FABEO22CPABE(PAIRING_GROUP)
        MPK, MSK = ABE.setup()
        STARTUP_ERROR = None
    except Exception as exc:
        STARTUP_ERROR = '{0}: {1}'.format(exc.__class__.__name__, str(exc))
        raise


def require_internal_token(headers):
    token = headers.getheader('x-internal-token', '')
    if not INTERNAL_TOKEN or token != INTERNAL_TOKEN:
        raise InternalTokenError('invalid internal token')


def issue_session_usk(username, session_id, attributes, epoch):
    ensure_runtime()
    merged = merge_epoch(attributes, epoch)
    usk = ABE.keygen(MPK, MSK, merged)
    usk_ref = str(uuid.uuid4())
    SESSION_KEYS[usk_ref] = {
        'username': username,
        'session_id': session_id,
        'epoch': normalize_attr(epoch),
        'attributes': merged,
        'usk': usk,
    }
    return usk_ref, merged


def encapsulate_dek(policy):
    ensure_runtime()
    normalized_display = normalize_policy(policy, encode_for_abe=False)
    normalized_abe = normalize_policy(policy, encode_for_abe=True)
    gt_secret = PAIRING_GROUP.random(GT)
    ciphertext = ABE.encrypt(MPK, gt_secret, normalized_abe)
    return {
        'policy': normalized_display,
        'dek_b64': _b64encode(derive_dek(gt_secret)),
        'wrapped_key_b64': _b64encode(serialize_ciphertext(ciphertext, normalized_display, normalized_abe)),
        'wrapped_key_meta': {
            'cpabe_scheme': FABEO_MODE,
            'kdf': 'sha256(gt_secret)',
        },
    }


def unwrap_dek(usk_ref, wrapped_key_b64):
    ensure_runtime()
    session = SESSION_KEYS.get(usk_ref)
    if not session:
        raise ValueError('session usk missing')

    usk = session['usk']
    ciphertext = deserialize_ciphertext(_b64decode(wrapped_key_b64))
    gt_secret = ABE.decrypt(MPK, ciphertext, usk)
    if gt_secret is None:
        raise ValueError('cp-abe key unwrap failed')
    return {
        'dek_b64': _b64encode(derive_dek(gt_secret)),
        'policy': ciphertext['policy_str'],
    }


class Handler(BaseHTTPServer.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _write_json(self, code, obj):
        body = json.dumps(obj)
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.getheader('Content-Length', '0'))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_GET(self):
        if self.path == '/health':
            if runtime_ready():
                self._write_json(
                    200,
                    {
                        'status': 'ok',
                        'service': 'machs_fabeo_service',
                        'mode': FABEO_MODE,
                        'real_cpabe': True,
                        'session_keys_loaded': len(SESSION_KEYS),
                    },
                )
                return
            self._write_json(
                503,
                {
                    'status': 'error',
                    'service': 'machs_fabeo_service',
                    'mode': FABEO_MODE,
                    'real_cpabe': False,
                    'error': STARTUP_ERROR or 'runtime unavailable',
                },
            )
            return

        if self.path == '/public-mpk':
            ensure_runtime()
            self._write_json(200, {'mpk_b64': _b64encode(objectToBytes(MPK, PAIRING_GROUP)), 'mode': FABEO_MODE})
            return

        self._write_json(404, {'error': 'not found'})

    def do_POST(self):
        try:
            require_internal_token(self.headers)

            if self.path == '/validate-policy':
                data = self._read_json()
                normalized = normalize_policy(data.get('policy', ''), encode_for_abe=False)
                self._write_json(200, {'valid': True, 'normalized': normalized, 'mode': FABEO_MODE})
                return

            if self.path == '/session-keygen':
                data = self._read_json()
                usk_ref, merged = issue_session_usk(
                    data.get('username', ''),
                    data.get('session_id', ''),
                    data.get('attributes', []),
                    data.get('epoch', 'epoch.2026'),
                )
                self._write_json(200, {'usk_ref': usk_ref, 'attributes': merged, 'mode': FABEO_MODE})
                return

            if self.path == '/encapsulate-dek':
                data = self._read_json()
                out = encapsulate_dek(data.get('policy', ''))
                out['mode'] = FABEO_MODE
                self._write_json(200, out)
                return

            if self.path == '/unwrap-dek':
                data = self._read_json()
                out = unwrap_dek(data.get('usk_ref', ''), data.get('wrapped_key_b64', ''))
                out['mode'] = FABEO_MODE
                self._write_json(200, out)
                return

            self._write_json(404, {'error': 'not found'})
        except InternalTokenError as exc:
            self._write_json(403, {'error': str(exc)})
        except ValueError as exc:
            self._write_json(403, {'error': str(exc)})
        except Exception as exc:
            self._write_json(
                400,
                {
                    'error': str(exc),
                    'type': exc.__class__.__name__,
                    'trace': traceback.format_exc(),
                },
            )


if __name__ == '__main__':
    initialize_runtime()
    httpd = BaseHTTPServer.HTTPServer((HOST, PORT), Handler)
    httpd.serve_forever()
