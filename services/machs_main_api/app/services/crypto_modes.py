import base64
import os
from dataclasses import dataclass
from typing import Dict

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.services import fabeo_client, kms_client

AUTH_TAG_LENGTH = 16
NONCE_LENGTH = 12


@dataclass
class CipherResult:
    encrypted_payload: bytes
    iv: bytes
    auth_tag: bytes
    wrapped_key: bytes
    wrapped_key_meta: dict
    mode_meta: dict


def _as_bytes(value: object) -> bytes:
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, bytes):
        return value
    return bytes(value)


def encrypt_payload(payload_json: str, policy_expression: str) -> CipherResult:
    cpabe = fabeo_client.encapsulate_dek(policy_expression)
    dek = base64.b64decode(cpabe["dek_b64"])

    iv = os.urandom(NONCE_LENGTH)
    sealed = AESGCM(dek).encrypt(iv, payload_json.encode("utf-8"), None)
    encrypted_payload = sealed[:-AUTH_TAG_LENGTH]
    auth_tag = sealed[-AUTH_TAG_LENGTH:]

    return CipherResult(
        encrypted_payload=encrypted_payload,
        iv=iv,
        auth_tag=auth_tag,
        wrapped_key=base64.b64decode(cpabe["wrapped_key_b64"]),
        wrapped_key_meta=cpabe.get("wrapped_key_meta", {}),
        mode_meta={"fabeo_mode": cpabe.get("mode"), "flow": "cp_abe_fabeo_hybrid"},
    )


def decrypt_for_client(row: Dict[str, object], usk_ref: str) -> dict:
    wrapped_key_b64 = base64.b64encode(_as_bytes(row["wrapped_key"])).decode("ascii")
    dek_out = kms_client.unwrap_dek(usk_ref, wrapped_key_b64)
    dek = base64.b64decode(dek_out["dek_b64"])

    ciphertext = _as_bytes(row["encrypted_payload"])
    iv = _as_bytes(row["iv"])
    auth_tag = _as_bytes(row["auth_tag"])
    plaintext = AESGCM(dek).decrypt(iv, ciphertext + auth_tag, None).decode("utf-8")

    return {
        "flow": "cp_abe_fabeo_decrypt",
        "resource_json": plaintext,
        "client_decrypt_required": False,
    }
