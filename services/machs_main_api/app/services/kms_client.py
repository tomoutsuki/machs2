from typing import Dict

import requests

from app.core.settings import settings


def _headers() -> Dict[str, str]:
    return {"x-internal-token": settings.kms_internal_token}


def blind_index(field: str, normalized_value: str) -> str:
    if normalized_value is None:
        return ""
    resp = requests.post(
        settings.kms_url + "/blind-index",
        json={"field": field, "normalized_value": normalized_value},
        headers=_headers(),
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()["blind_index"]


def issue_session_usk(username: str, attributes: list[str], session_id: str) -> dict:
    resp = requests.post(
        settings.kms_url + "/session-usk",
        json={
            "username": username,
            "attributes": attributes,
            "session_id": session_id,
            "epoch": settings.current_epoch,
        },
        headers=_headers(),
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()


def unwrap_dek(usk_ref: str, wrapped_key_b64: str) -> dict:
    resp = requests.post(
        settings.kms_url + "/unwrap-dek",
        json={"usk_ref": usk_ref, "wrapped_key_b64": wrapped_key_b64},
        headers=_headers(),
        timeout=20,
    )
    if resp.status_code >= 400:
        raise ValueError(resp.json().get("detail", "cp-abe key unwrap failed"))
    return resp.json()


def get_epoch() -> dict:
    resp = requests.get(settings.kms_url + "/epoch", headers=_headers(), timeout=5)
    resp.raise_for_status()
    return resp.json()


def rotate_epoch(new_epoch: str) -> dict:
    resp = requests.post(
        settings.kms_url + "/rotate-epoch",
        json={"new_epoch": new_epoch},
        headers=_headers(),
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()


def assert_kms_ready() -> dict:
    resp = requests.get(settings.kms_url + "/health", timeout=5)
    if resp.status_code >= 400:
        raise RuntimeError("kms unavailable")
    payload = resp.json()
    if not payload.get("bridge_real_cpabe"):
        raise RuntimeError("kms bridge backend is not ready for real cp-abe")
    return payload
