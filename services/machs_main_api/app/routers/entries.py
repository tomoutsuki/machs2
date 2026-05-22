import json
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.settings import settings
from app.db import repository
from app.routers.auth import get_current_user
from app.services import fhir, kms_client
from app.services.crypto_modes import decrypt_for_client, encrypt_payload
from app.services.normalization import normalize_birthdate, normalize_cpf, normalize_name
from app.services.policy import evaluate_policy, normalize_policy_expression

router = APIRouter(prefix="/entries", tags=["entries"])


class CreateEntryRequest(BaseModel):
    mode: str = Field(default="fabeo", pattern="^fabeo$")
    resource: Dict[str, Any]
    policy_expression: Optional[str] = None


@router.post("")
def create_entry(payload: CreateEntryRequest, user: dict = Depends(get_current_user)) -> dict:
    valid, msg = fhir.validate_fhir_resource(payload.resource)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    resource_json = fhir.serialize_fhir_json(payload.resource)
    resource_type = payload.resource["resourceType"]

    if payload.policy_expression:
        policy_expression = normalize_policy_expression(payload.policy_expression)
    else:
        sample_policies = {
            "Patient": "(role.receptionist OR role.nurse OR role.doctor) AND clearance.demographics AND epoch.2026",
            "Observation": "(role.lab_technician OR role.lab_scientist OR role.doctor) AND clearance.labs AND epoch.2026",
            "Condition": "(role.nurse OR role.doctor) AND clearance.clinical_notes AND epoch.2026",
            "Encounter": "(role.nurse OR role.doctor) AND clearance.clinical_notes AND epoch.2026",
            "MedicationRequest": "role.doctor AND clearance.medications AND epoch.2026",
        }
        policy_expression = sample_policies[resource_type]

    extracted = fhir.derive_search_fields(payload.resource)
    bidx_name = kms_client.blind_index("name", extracted["name"]) if extracted.get("name") else ""
    bidx_cpf = kms_client.blind_index("cpf", extracted["cpf"]) if extracted.get("cpf") else ""
    bidx_birth = kms_client.blind_index("birthdate", extracted["birthdate"]) if extracted.get("birthdate") else ""

    cipher = encrypt_payload(payload.mode, resource_json, policy_expression)

    entry_id = repository.insert_entry(
        payload.mode,
        {
            "resource_type": resource_type,
            "policy_expression": policy_expression,
            "epoch_label": settings.current_epoch,
            "owner_username": user["username"],
            "bidx_name": bidx_name,
            "bidx_cpf": bidx_cpf,
            "bidx_birthdate": bidx_birth,
            "encrypted_payload": cipher.encrypted_payload,
            "iv": cipher.iv,
            "auth_tag": cipher.auth_tag,
            "wrapped_key": cipher.wrapped_key,
            "wrapped_key_meta": cipher.wrapped_key_meta,
            "mode_meta": cipher.mode_meta,
        },
    )

    return {
        "entry_id": entry_id,
        "mode": payload.mode,
        "resource_type": resource_type,
        "policy_expression": policy_expression,
    }


@router.get("/search")
def search_entries(
    mode: str = Query("fabeo", pattern="^fabeo$"),
    name: Optional[str] = None,
    cpf: Optional[str] = None,
    birthdate: Optional[str] = None,
    user: dict = Depends(get_current_user),
) -> dict:
    del user

    norm = {
        "name": normalize_name(name) if name else None,
        "cpf": normalize_cpf(cpf) if cpf else None,
        "birthdate": normalize_birthdate(birthdate) if birthdate else None,
    }

    bidx_name = kms_client.blind_index("name", norm["name"]) if norm["name"] else ""
    bidx_cpf = kms_client.blind_index("cpf", norm["cpf"]) if norm["cpf"] else ""
    bidx_birth = kms_client.blind_index("birthdate", norm["birthdate"]) if norm["birthdate"] else ""

    items = repository.search_entries(mode, bidx_name, bidx_cpf, bidx_birth)
    return {"count": len(items), "items": items}


@router.get("/meta/policies")
def policy_examples(user: dict = Depends(get_current_user)) -> dict:
    del user
    return {"items": repository.get_policy_examples()}


@router.post("/meta/epoch/rotate")
def rotate_epoch(new_epoch: str, user: dict = Depends(get_current_user)) -> dict:
    if user["role"] not in {"doctor_cardiologist", "doctor_general_clinic"}:
        raise HTTPException(status_code=403, detail="only predefined doctors can rotate epoch in MVP")
    if not settings.enable_experimental_revocation:
        raise HTTPException(status_code=400, detail="experimental revocation mode disabled")
    out = kms_client.rotate_epoch(new_epoch)
    return {"status": "ok", "kms": out}


@router.get("/{entry_id}/cipher")
def get_cipher(entry_id: uuid.UUID, mode: str = Query("fabeo", pattern="^fabeo$"), user: dict = Depends(get_current_user)) -> dict:
    del user
    row = repository.get_entry(mode, str(entry_id))
    if not row:
        raise HTTPException(status_code=404, detail="entry not found")

    return {
        "entry_id": str(row["entry_id"]),
        "resource_type": row["resource_type"],
        "policy_expression": row["policy_expression"],
        "epoch_label": row["epoch_label"],
        "mode_meta": row.get("mode_meta") or {},
    }


@router.post("/{entry_id}/decrypt-package")
def decrypt_package(entry_id: uuid.UUID, mode: str = Query("fabeo", pattern="^fabeo$"), user: dict = Depends(get_current_user)) -> dict:
    row = repository.get_entry(mode, str(entry_id))
    if not row:
        raise HTTPException(status_code=404, detail="entry not found")

    attrs = list(user["attributes"])

    policy = str(row["policy_expression"])
    if settings.enable_experimental_revocation and row["epoch_label"] != settings.current_epoch:
        raise HTTPException(status_code=403, detail="ciphertext stale epoch, re-encryption required")

    if not evaluate_policy(policy, attrs):
        raise HTTPException(status_code=403, detail="policy mismatch: decrypt denied")

    try:
        pkg = decrypt_for_client(mode, row, attrs, user["usk"])
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return {
        "entry_id": str(row["entry_id"]),
        "mode": mode,
        "policy_expression": policy,
        "result": pkg,
    }
