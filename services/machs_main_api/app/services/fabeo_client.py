import requests

from app.core.settings import settings


def validate_policy(policy: str) -> str:
    resp = requests.post(settings.fabeo_url + "/validate-policy", json={"policy": policy}, timeout=8)
    if resp.status_code >= 400:
        raise ValueError(resp.json().get("error", "invalid policy"))
    return resp.json()["normalized"]


def encrypt(payload: str, policy: str) -> dict:
    resp = requests.post(
        settings.fabeo_url + "/encrypt",
        json={"payload": payload, "policy": policy},
        timeout=20,
    )
    if resp.status_code >= 400:
        raise ValueError(resp.json().get("error", "fabeo encryption failed"))
    return resp.json()


def decrypt(ciphertext_b64: str, attributes: list[str], usk: str) -> dict:
    resp = requests.post(
        settings.fabeo_url + "/decrypt",
        json={"ciphertext_b64": ciphertext_b64, "attributes": attributes, "usk": usk},
        timeout=20,
    )
    if resp.status_code >= 400:
        raise ValueError(resp.json().get("error", "fabeo decryption failed"))
    return resp.json()
