import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Dict

import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


def _b64_secret(env_name: str, fallback: bytes) -> bytes:
    value = os.getenv(env_name)
    if not value:
        return fallback
    return base64.b64decode(value)


MQK = _b64_secret("KMS_MQK_B64", b"MACHS2_MQK_DEFAULT_2026")
INTERNAL_TOKEN = os.getenv("KMS_INTERNAL_TOKEN", "change_me_internal_token")
CURRENT_EPOCH = os.getenv("MAIN_API_CURRENT_EPOCH", "epoch.2026")
ENABLE_EXPERIMENTAL_REVOCATION = os.getenv("MAIN_API_ENABLE_EXPERIMENTAL_REVOCATION", "false").lower() == "true"
FABEO_HOST = os.getenv("FABEO_HOST", "machs_fabeo_service")
FABEO_PORT = int(os.getenv("FABEO_PORT", "8200"))

app = FastAPI(title="machs_minimal_kms", version="0.1.0")


class BlindIndexRequest(BaseModel):
    field: str = Field(min_length=1)
    normalized_value: str = Field(min_length=1)


class BlindIndexResponse(BaseModel):
    blind_index: str


class SessionUskRequest(BaseModel):
    username: str
    attributes: list[str]
    session_id: str
    epoch: str = Field(default=CURRENT_EPOCH)


class SessionUskResponse(BaseModel):
    usk_ref: str
    expires_at_epoch_seconds: int
    issued_epoch: str


class EpochRotateRequest(BaseModel):
    new_epoch: str


class UnwrapDekRequest(BaseModel):
    usk_ref: str = Field(min_length=1)
    wrapped_key_b64: str = Field(min_length=1)


class UnwrapDekResponse(BaseModel):
    dek_b64: str
    policy: str
    mode: str


def verify_internal_token(x_internal_token: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_internal_token, INTERNAL_TOKEN):
        raise HTTPException(status_code=403, detail="invalid internal token")


def _bridge_headers() -> Dict[str, str]:
    return {"x-internal-token": INTERNAL_TOKEN}


def _bridge_url(path: str) -> str:
    return "http://{0}:{1}{2}".format(FABEO_HOST, FABEO_PORT, path)


def derive_blind_index(field: str, normalized_value: str) -> str:
    msg = (field + "|" + normalized_value).encode("utf-8")
    digest = hmac.new(MQK, msg, hashlib.sha256).hexdigest()
    return digest


def bridge_health() -> Dict[str, object]:
    resp = requests.get(_bridge_url("/health"), timeout=5)
    if resp.status_code >= 400:
        raise HTTPException(status_code=503, detail="fabeo bridge unavailable")
    payload = resp.json()
    if not payload.get("real_cpabe"):
        raise HTTPException(status_code=503, detail="fabeo bridge not running real cp-abe")
    return payload


def bridge_session_keygen(username: str, attributes: list[str], session_id: str, epoch: str) -> str:
    resp = requests.post(
        _bridge_url("/session-keygen"),
        json={"username": username, "attributes": attributes, "session_id": session_id, "epoch": epoch},
        headers=_bridge_headers(),
        timeout=15,
    )
    if resp.status_code >= 400:
        raise HTTPException(status_code=503, detail=resp.json().get("error", "fabeo keygen failed"))
    return resp.json()["usk_ref"]


def bridge_unwrap_dek(usk_ref: str, wrapped_key_b64: str) -> Dict[str, str]:
    resp = requests.post(
        _bridge_url("/unwrap-dek"),
        json={"usk_ref": usk_ref, "wrapped_key_b64": wrapped_key_b64},
        headers=_bridge_headers(),
        timeout=20,
    )
    if resp.status_code == 403:
        raise HTTPException(status_code=403, detail=resp.json().get("error", "cp-abe key unwrap failed"))
    if resp.status_code >= 400:
        raise HTTPException(status_code=503, detail=resp.json().get("error", "fabeo unwrap failed"))
    return resp.json()


def bridge_public_mpk() -> Dict[str, str]:
    resp = requests.get(_bridge_url("/public-mpk"), timeout=5)
    if resp.status_code >= 400:
        raise HTTPException(status_code=503, detail="fabeo public mpk unavailable")
    return resp.json()


@app.get("/health")
def health() -> Dict[str, object]:
    bridge = bridge_health()
    return {
        "status": "ok",
        "service": "machs_minimal_kms",
        "bridge_mode": bridge.get("mode"),
        "bridge_real_cpabe": bridge.get("real_cpabe", False),
    }


@app.get("/public-mpk")
def public_mpk() -> Dict[str, str]:
    return bridge_public_mpk()


@app.post("/blind-index", response_model=BlindIndexResponse)
def blind_index(payload: BlindIndexRequest, _: None = Depends(verify_internal_token)) -> BlindIndexResponse:
    return BlindIndexResponse(blind_index=derive_blind_index(payload.field, payload.normalized_value))


@app.post("/session-usk", response_model=SessionUskResponse)
def session_usk(payload: SessionUskRequest, _: None = Depends(verify_internal_token)) -> SessionUskResponse:
    expires = int(time.time()) + 3600
    usk_ref = bridge_session_keygen(payload.username, payload.attributes, payload.session_id, payload.epoch)
    return SessionUskResponse(usk_ref=usk_ref, expires_at_epoch_seconds=expires, issued_epoch=payload.epoch)


@app.post("/unwrap-dek", response_model=UnwrapDekResponse)
def unwrap_dek(payload: UnwrapDekRequest, _: None = Depends(verify_internal_token)) -> UnwrapDekResponse:
    out = bridge_unwrap_dek(payload.usk_ref, payload.wrapped_key_b64)
    return UnwrapDekResponse(**out)


@app.get("/epoch")
def epoch(_: None = Depends(verify_internal_token)) -> Dict[str, str | bool]:
    return {
        "current_epoch": CURRENT_EPOCH,
        "experimental_revocation_enabled": ENABLE_EXPERIMENTAL_REVOCATION,
    }


@app.post("/rotate-epoch")
def rotate_epoch(payload: EpochRotateRequest, _: None = Depends(verify_internal_token)) -> Dict[str, str]:
    if not ENABLE_EXPERIMENTAL_REVOCATION:
        raise HTTPException(status_code=400, detail="experimental revocation mode disabled")
    if not payload.new_epoch.startswith("epoch."):
        raise HTTPException(status_code=400, detail="epoch must start with epoch.")

    global CURRENT_EPOCH
    CURRENT_EPOCH = payload.new_epoch
    return {"current_epoch": CURRENT_EPOCH}
