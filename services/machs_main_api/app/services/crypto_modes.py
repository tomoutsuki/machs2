from dataclasses import dataclass
from typing import Dict

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


def encrypt_payload(mode: str, payload_json: str, policy_expression: str) -> CipherResult:
    if mode != "fabeo":
        raise ValueError("invalid mode")
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


def decrypt_for_client(mode: str, row: Dict[str, object], user_attrs: list[str], usk: str) -> dict:
    if mode != "fabeo":
        raise ValueError("invalid mode")
    cipher_b64 = _as_bytes(row["encrypted_payload"]).decode("utf-8")
    out = fabeo_client.decrypt(cipher_b64, user_attrs, usk)
    return {
        "flow": "server_decrypt_for_fabeo_bridge",
        "resource_json": out["payload"],
        "client_decrypt_required": False,
    }
