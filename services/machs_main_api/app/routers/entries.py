import json
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app.core.settings import settings
from app.db import repository
from app.routers.auth import get_current_user
from app.services import fabeo_client, fhir, kms_client
from app.services.crypto_modes import decrypt_for_client, encrypt_payload
from app.services.normalization import normalize_birthdate, normalize_cpf, normalize_name

router = APIRouter(prefix="/entries", tags=["entries"])


class CreateEntryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Optional[str] = None
    resource: Dict[str, Any]
    policy_expression: Optional[str] = None


def _default_policy(resource_type: str) -> str:
    sample_policies = {
        "Patient": "(role.receptionist OR role.nurse OR role.doctor) AND clearance.demographics AND {epoch}",
        "Observation": "(role.lab_technician OR role.lab_scientist OR role.doctor) AND clearance.labs AND {epoch}",
        "Condition": "(role.nurse OR role.doctor) AND clearance.clinical_notes AND {epoch}",
        "Encounter": "(role.nurse OR role.doctor) AND clearance.clinical_notes AND {epoch}",
        "MedicationRequest": "role.doctor AND clearance.medications AND {epoch}",
    }
    return sample_policies[resource_type].format(epoch=settings.current_epoch)


def _enforce_mode(mode: Optional[str]) -> None:
    if mode not in {None, "fabeo"}:
        raise HTTPException(status_code=400, detail="invalid mode")


@router.post("")
def create_entry(payload: CreateEntryRequest, user: dict = Depends(get_current_user)) -> dict:
    _enforce_mode(payload.mode)
    valid, msg = fhir.validate_fhir_resource(payload.resource)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    resource_json = fhir.serialize_fhir_json(payload.resource)
    resource_type = payload.resource["resourceType"]
    requested_policy = payload.policy_expression or _default_policy(resource_type)

    try:
        policy_expression = fabeo_client.validate_policy(requested_policy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    extracted = fhir.derive_search_fields(payload.resource)
    bidx_name = kms_client.blind_index("name", extracted["name"]) if extracted.get("name") else ""
    bidx_cpf = kms_client.blind_index("cpf", extracted["cpf"]) if extracted.get("cpf") else ""
    bidx_birth = kms_client.blind_index("birthdate", extracted["birthdate"]) if extracted.get("birthdate") else ""

    try:
        cipher = encrypt_payload(resource_json, policy_expression)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    entry_id = repository.insert_entry(
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
        }
    )

    return {
        "entry_id": entry_id,
        "mode": "fabeo",
        "resource_type": resource_type,
        "policy_expression": policy_expression,
    }


@router.get("/search")
def search_entries(
    mode: Optional[str] = Query(default=None),
    name: Optional[str] = None,
    cpf: Optional[str] = None,
    birthdate: Optional[str] = None,
    user: dict = Depends(get_current_user),
) -> dict:
    del user
    _enforce_mode(mode)

    norm = {
        "name": normalize_name(name) if name else None,
        "cpf": normalize_cpf(cpf) if cpf else None,
        "birthdate": normalize_birthdate(birthdate) if birthdate else None,
    }

    bidx_name = kms_client.blind_index("name", norm["name"]) if norm["name"] else ""
    bidx_cpf = kms_client.blind_index("cpf", norm["cpf"]) if norm["cpf"] else ""
    bidx_birth = kms_client.blind_index("birthdate", norm["birthdate"]) if norm["birthdate"] else ""

    items = repository.search_entries(bidx_name, bidx_cpf, bidx_birth)
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
def get_cipher(
    entry_id: uuid.UUID,
    mode: Optional[str] = Query(default=None),
    user: dict = Depends(get_current_user),
) -> dict:
    _enforce_mode(mode)
    del user
    row = repository.get_entry(str(entry_id))
    if not row:
        raise HTTPException(status_code=404, detail="entry not found")

    return {
        "entry_id": str(row["entry_id"]),
        "mode": "fabeo",
        "resource_type": row["resource_type"],
        "policy_expression": row["policy_expression"],
        "epoch_label": row["epoch_label"],
        "mode_meta": row.get("mode_meta") or {},
    }


@router.post("/{entry_id}/decrypt-package")
def decrypt_package(
    entry_id: uuid.UUID,
    mode: Optional[str] = Query(default=None),
    user: dict = Depends(get_current_user),
) -> dict:
    _enforce_mode(mode)
    row = repository.get_entry(str(entry_id))
    if not row:
        raise HTTPException(status_code=404, detail="entry not found")

    try:
        pkg = decrypt_for_client(row, user["usk_ref"])
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    resource_json = pkg["resource_json"]
    try:
        resource_json = json.loads(resource_json)
    except Exception:
        pass

    return {
        "entry_id": str(row["entry_id"]),
        "mode": "fabeo",
        "policy_expression": row["policy_expression"],
        "result": {
            "flow": "cp_abe_fabeo_decrypt",
            "resource_json": resource_json,
            "client_decrypt_required": False,
        },
    }
