from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.core.security import create_access_token, decode_access_token, new_session_id, verify_password
from app.core.settings import settings
from app.db import repository
from app.services import kms_client

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    session_id: str
    username: str
    full_name: str
    role: str
    attributes: list[str]
    current_epoch: str


def get_current_user(request: Request) -> dict:
    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    username = payload.get("sub")
    session_id = payload.get("sid")
    if not username or not session_id:
        raise HTTPException(status_code=401, detail="invalid token payload")

    user = repository.get_user(username)
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="invalid user")

    usk = repository.get_usk(session_id)
    if not usk or usk.get("username") != username:
        raise HTTPException(status_code=401, detail="session usk missing")
    if usk.get("expires_at") < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="session expired")

    user["session_id"] = session_id
    user["usk_ref"] = usk.get("usk_ref")
    return user


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, response: Response) -> LoginResponse:
    user = repository.get_user(payload.username)
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="invalid credentials")

    if not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid credentials")

    session_id = new_session_id()
    attrs = list(user["attributes"])
    usk_out = kms_client.issue_session_usk(user["username"], attrs, session_id)
    repository.upsert_usk(session_id, user["username"], usk_out["usk_ref"], usk_out["expires_at_epoch_seconds"])

    token = create_access_token({"sub": user["username"], "sid": session_id})
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.jwt_exp_minutes * 60,
    )

    return LoginResponse(
        access_token=token,
        session_id=session_id,
        username=user["username"],
        full_name=user["full_name"],
        role=user["role"],
        attributes=attrs,
        current_epoch=usk_out["issued_epoch"],
    )


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(settings.cookie_name)
    return {"status": "ok"}


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return {
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
        "attributes": user["attributes"],
        "session_id": user["session_id"],
    }
