import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Dict

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


def _b64_secret(env_name: str, fallback: bytes) -> bytes:
    value = os.getenv(env_name)
    if not value:
        return fallback
    return base64.b64decode(value)


MSK = _b64_secret("KMS_MSK_B64", b"MACHS2_MSK_DEFAULT_2026")
MQK = _b64_secret("KMS_MQK_B64", b"MACHS2_MQK_DEFAULT_2026")
MPK = os.getenv("KMS_MPK_B64", "TUFDSFMyX01QS19ERUZBVUxUXzIwMjY=")
INTERNAL_TOKEN = os.getenv("KMS_INTERNAL_TOKEN", "change_me_internal_token")
CURRENT_EPOCH = os.getenv("MAIN_API_CURRENT_EPOCH", "epoch.2026")
ENABLE_EXPERIMENTAL_REVOCATION = os.getenv("MAIN_API_ENABLE_EXPERIMENTAL_REVOCATION", "false").lower() == "true"

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


class SessionUskResponse(BaseModel):
    usk: str
    expires_at_epoch_seconds: int
    issued_epoch: str


class EpochRotateRequest(BaseModel):
    new_epoch: str


def verify_internal_token(x_internal_token: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_internal_token, INTERNAL_TOKEN):
        raise HTTPException(status_code=403, detail="invalid internal token")


def derive_blind_index(field: str, normalized_value: str) -> str:
    msg = (field + "|" + normalized_value).encode("utf-8")
    digest = hmac.new(MQK, msg, hashlib.sha256).hexdigest()
    return digest


def derive_usk(username: str, attributes: list[str], session_id: str) -> str:
    joined = "|".join(sorted(attributes))
    msg = (username + "|" + session_id + "|" + joined + "|" + CURRENT_EPOCH).encode("utf-8")
    digest = hmac.new(MSK, msg, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "machs_minimal_kms"}


@app.get("/public-mpk")
def public_mpk() -> Dict[str, str]:
    return {"mpk_b64": MPK, "mode": "fabeo22cp"}


@app.post("/blind-index", response_model=BlindIndexResponse)
def blind_index(payload: BlindIndexRequest, _: None = Depends(verify_internal_token)) -> BlindIndexResponse:
    return BlindIndexResponse(blind_index=derive_blind_index(payload.field, payload.normalized_value))


@app.post("/session-usk", response_model=SessionUskResponse)
def session_usk(payload: SessionUskRequest, _: None = Depends(verify_internal_token)) -> SessionUskResponse:
    expires = int(time.time()) + 3600
    usk = derive_usk(payload.username, payload.attributes, payload.session_id)
    return SessionUskResponse(usk=usk, expires_at_epoch_seconds=expires, issued_epoch=CURRENT_EPOCH)


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
