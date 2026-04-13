# -*- coding: utf-8 -*-
import BaseHTTPServer
import base64
import json
import os
import re

HOST = '0.0.0.0'
PORT = int(os.environ.get('FABEO_PORT', '8200'))
FABEO_MODE = os.environ.get('FABEO_MODE', 'fabeo22cp')
ALLOW_SIM = os.environ.get('FABEO_ALLOW_SIMULATION', 'true').lower() == 'true'

TOKEN_RE = re.compile(r'^[a-z]+\.[a-z0-9_]+$')


def normalize_attr(attr):
    token = attr.strip().lower()
    if not TOKEN_RE.match(token):
        raise ValueError('invalid attribute token')
    if '=' in token or ':' in token:
        raise ValueError('invalid syntax: use dot notation')
    return token


def normalize_policy(policy):
    if '=' in policy or ':' in policy:
        raise ValueError('invalid policy syntax: use dot notation')
    compact = policy.replace('(', ' ').replace(')', ' ')
    parts = re.split(r'\s+(AND|OR)\s+', compact.strip())
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if p in ['AND', 'OR']:
            out.append(p)
        else:
            out.append(normalize_attr(p))
    if not out:
        raise ValueError('empty policy')
    return ' '.join(out)


def eval_policy(policy, attrs):
    attrs_set = set(attrs)
    tokens = policy.replace('(', ' ').replace(')', ' ').split()
    if len(tokens) == 1:
        return tokens[0] in attrs_set
    result = None
    op = None
    for t in tokens:
        if t in ['AND', 'OR']:
            op = t
            continue
        cur = t in attrs_set
        if result is None:
            result = cur
        elif op == 'AND':
            result = result and cur
        elif op == 'OR':
            result = result or cur
    return bool(result)


def do_encrypt(payload_str, policy):
    if FABEO_MODE != 'fabeo22cp':
        raise ValueError('only fabeo22cp is supported')

    # This bridge runs in a FABEO-built container. For local MVP comparisons,
    # serialization envelope keeps policy-bound behavior deterministic.
    if ALLOW_SIM:
        packed = json.dumps({'policy': policy, 'payload': payload_str})
        return base64.b64encode(packed)

    raise ValueError('FABEO runtime bridge requires simulation=true in this MVP')


def do_decrypt(ciphertext_b64, attrs, usk):
    del usk
    raw = base64.b64decode(ciphertext_b64)
    obj = json.loads(raw)
    policy = obj['policy']
    if not eval_policy(policy, attrs):
        raise ValueError('attribute policy mismatch')
    return obj['payload']


class Handler(BaseHTTPServer.BaseHTTPRequestHandler):
    def _write_json(self, code, obj):
        body = json.dumps(obj)
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        l = int(self.headers.getheader('Content-Length', '0'))
        if l == 0:
            return {}
        raw = self.rfile.read(l)
        return json.loads(raw)

    def do_GET(self):
        if self.path == '/health':
            self._write_json(200, {'status': 'ok', 'service': 'machs_fabeo_service', 'mode': FABEO_MODE, 'source': 'FABEO-submodule-image'})
            return
        self._write_json(404, {'error': 'not found'})

    def do_POST(self):
        try:
            if self.path == '/validate-policy':
                data = self._read_json()
                p = normalize_policy(data.get('policy', ''))
                self._write_json(200, {'valid': True, 'normalized': p})
                return

            if self.path == '/encrypt':
                data = self._read_json()
                policy = normalize_policy(data.get('policy', ''))
                payload = data.get('payload', '')
                ciphertext = do_encrypt(payload, policy)
                self._write_json(200, {'ciphertext_b64': ciphertext, 'policy': policy, 'mode': FABEO_MODE, 'simulated': ALLOW_SIM})
                return

            if self.path == '/decrypt':
                data = self._read_json()
                attrs = [normalize_attr(a) for a in data.get('attributes', [])]
                payload = do_decrypt(data.get('ciphertext_b64', ''), attrs, data.get('usk', ''))
                self._write_json(200, {'payload': payload, 'mode': FABEO_MODE, 'simulated': ALLOW_SIM})
                return

            self._write_json(404, {'error': 'not found'})
        except ValueError as exc:
            self._write_json(403, {'error': str(exc)})
        except Exception as exc:
            self._write_json(400, {'error': str(exc)})


if __name__ == '__main__':
    httpd = BaseHTTPServer.HTTPServer((HOST, PORT), Handler)
    httpd.serve_forever()
