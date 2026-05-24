from typing import Dict

import requests

from app.core.settings import settings


def _headers() -> Dict[str, str]:
    return {"x-internal-token": settings.kms_internal_token}


def assert_bridge_ready() -> dict:
    resp = requests.get(settings.fabeo_url + "/health", timeout=5)
    if resp.status_code >= 400:
        raise RuntimeError("fabeo bridge unavailable")
    payload = resp.json()
    if not payload.get("real_cpabe"):
        raise RuntimeError("fabeo bridge not running real cp-abe")
    return payload


def validate_policy(policy: str) -> str:
    resp = requests.post(
        settings.fabeo_url + "/validate-policy",
        json={"policy": policy},
        headers=_headers(),
        timeout=8,
    )
    if resp.status_code >= 400:
        raise ValueError(resp.json().get("error", "invalid policy"))
    return resp.json()["normalized"]


def encapsulate_dek(policy: str) -> dict:
    resp = requests.post(
        settings.fabeo_url + "/encapsulate-dek",
        json={"policy": policy},
        headers=_headers(),
        timeout=20,
    )
    if resp.status_code >= 400:
        raise ValueError(resp.json().get("error", "fabeo encapsulation failed"))
    return resp.json()
