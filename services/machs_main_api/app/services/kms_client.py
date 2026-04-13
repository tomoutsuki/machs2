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
        json={"username": username, "attributes": attributes, "session_id": session_id},
        headers=_headers(),
        timeout=5,
    )
    resp.raise_for_status()
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
