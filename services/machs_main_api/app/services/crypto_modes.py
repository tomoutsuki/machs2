import base64
import json
import os
from dataclasses import dataclass
from typing import Dict

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.settings import settings
from app.services import fabeo_client


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


def _random_bytes(size: int) -> bytes:
    return os.urandom(size)


def _wrap_data_key(data_key: bytes) -> tuple[bytes, dict]:
    iv = _random_bytes(12)
    aes = AESGCM(settings.app_envelope_key)
    wrapped = aes.encrypt(iv, data_key, b"machs2-wrap")
    return iv + wrapped, {"wrap_alg": "AES-256-GCM", "aad": "machs2-wrap"}


def _unwrap_data_key(wrapped_key: bytes, wrapped_key_meta: dict) -> bytes:
    del wrapped_key_meta
    iv = wrapped_key[:12]
    body = wrapped_key[12:]
    aes = AESGCM(settings.app_envelope_key)
    return aes.decrypt(iv, body, b"machs2-wrap")


def encrypt_payload(mode: str, payload_json: str, policy_expression: str) -> CipherResult:
    if mode == "fabeo":
        enc = fabeo_client.encrypt(payload_json, policy_expression)
        data = enc["ciphertext_b64"].encode("utf-8")
        return CipherResult(
            encrypted_payload=data,
            iv=b"",
            auth_tag=b"",
            wrapped_key=b"",
            wrapped_key_meta={},
            mode_meta={"fabeo_mode": enc.get("mode"), "simulated": enc.get("simulated", False)},
        )

    data_key = _random_bytes(32)
    iv = _random_bytes(12)
    aes = AESGCM(data_key)
    ciphertext_and_tag = aes.encrypt(iv, payload_json.encode("utf-8"), b"machs2-ehr")
    ciphertext = ciphertext_and_tag[:-16]
    tag = ciphertext_and_tag[-16:]

    wrapped_key, wrapped_meta = _wrap_data_key(data_key)
    return CipherResult(
        encrypted_payload=ciphertext,
        iv=iv,
        auth_tag=tag,
        wrapped_key=wrapped_key,
        wrapped_key_meta=wrapped_meta,
        mode_meta={"mode_family": "aes_gcm_envelope", "requested_mode": mode},
    )


def decrypt_for_client(mode: str, row: Dict[str, object], user_attrs: list[str], usk: str) -> dict:
    if mode == "fabeo":
        cipher_b64 = _as_bytes(row["encrypted_payload"]).decode("utf-8")
        out = fabeo_client.decrypt(cipher_b64, user_attrs, usk)
        return {
            "flow": "server_decrypt_for_fabeo_bridge",
            "resource_json": out["payload"],
            "client_decrypt_required": False,
        }

    wrapped_meta = row.get("wrapped_key_meta") or {}
    if isinstance(wrapped_meta, str):
        wrapped_meta = json.loads(wrapped_meta)
    data_key = _unwrap_data_key(_as_bytes(row["wrapped_key"]), wrapped_meta)
    return {
        "flow": "client_side_decrypt_simulated",
        "client_decrypt_required": True,
        "algorithm": "AES-256-GCM",
        "aad": base64.b64encode(b"machs2-ehr").decode("ascii"),
        "data_key_b64": base64.b64encode(data_key).decode("ascii"),
        "ciphertext_b64": base64.b64encode(_as_bytes(row["encrypted_payload"])).decode("ascii"),
        "iv_b64": base64.b64encode(_as_bytes(row["iv"])).decode("ascii"),
        "tag_b64": base64.b64encode(_as_bytes(row["auth_tag"])).decode("ascii"),
    }
