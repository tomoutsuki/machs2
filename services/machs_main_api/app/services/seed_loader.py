import glob
import json
import os
from typing import Dict, Optional

import yaml

from app.core.security import hash_password
from app.core.settings import settings
from app.db import repository
from app.services import fhir, kms_client
from app.services.crypto_modes import encrypt_payload


def _seed_root() -> str:
    return "/workspace/resources/seeds"


def _users_seed_path() -> str:
    return "/workspace/resources/users_seed.yaml"


def _choose_policy(resource_type: str) -> str:
    mapping = {
        "Patient": "(role.receptionist OR role.nurse OR role.doctor) AND clearance.demographics AND epoch.2026",
        "Observation": "(role.lab_technician OR role.lab_scientist OR role.doctor) AND clearance.labs AND epoch.2026",
        "Condition": "(role.nurse OR role.doctor) AND clearance.clinical_notes AND epoch.2026",
        "Encounter": "(role.nurse OR role.doctor) AND clearance.clinical_notes AND epoch.2026",
        "MedicationRequest": "role.doctor AND clearance.medications AND epoch.2026",
    }
    return mapping.get(resource_type, "role.doctor AND epoch.2026")


def _index_values(resource: Dict) -> Dict[str, str]:
    extracted = fhir.derive_search_fields(resource)
    return {
        "bidx_name": kms_client.blind_index("name", extracted["name"]) if extracted.get("name") else "",
        "bidx_cpf": kms_client.blind_index("cpf", extracted["cpf"]) if extracted.get("cpf") else "",
        "bidx_birthdate": kms_client.blind_index("birthdate", extracted["birthdate"]) if extracted.get("birthdate") else "",
    }


def load_users_seed() -> None:
    path = _users_seed_path()
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    for user in data.get("users", []):
        repository.upsert_user(
            username=user["username"],
            full_name=user["full_name"],
            role=user["role"],
            password_hash=hash_password(user["password"]),
            attributes=user["attributes"],
        )


def _load_json_file(path: str) -> Optional[Dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _seed_file_for_all_modes(resource: Dict, owner_username: str) -> None:
    valid, _ = fhir.validate_fhir_resource(resource)
    if not valid:
        return

    resource_json = fhir.serialize_fhir_json(resource)
    policy = _choose_policy(resource["resourceType"])
    idx = _index_values(resource)

    for mode in ["fabeo", "aes_gcm", "tde", "column_level", "app_level"]:
        cipher = encrypt_payload(mode, resource_json, policy)
        repository.insert_entry(
            mode,
            {
                "resource_type": resource["resourceType"],
                "policy_expression": policy,
                "epoch_label": settings.current_epoch,
                "owner_username": owner_username,
                "bidx_name": idx["bidx_name"],
                "bidx_cpf": idx["bidx_cpf"],
                "bidx_birthdate": idx["bidx_birthdate"],
                "encrypted_payload": cipher.encrypted_payload,
                "iv": cipher.iv,
                "auth_tag": cipher.auth_tag,
                "wrapped_key": cipher.wrapped_key,
                "wrapped_key_meta": cipher.wrapped_key_meta,
                "mode_meta": cipher.mode_meta,
            },
        )


def load_resource_seeds(owner_username: str = "doctor_general_clinic") -> None:
    root = _seed_root()
    paths = [
        os.path.join(root, "patient_example_brazilian_HL7.json"),
        *glob.glob(os.path.join(root, "patients", "*.json")),
        *glob.glob(os.path.join(root, "observations", "*.json")),
        *glob.glob(os.path.join(root, "conditions", "*.json")),
        *glob.glob(os.path.join(root, "encounters", "*.json")),
        *glob.glob(os.path.join(root, "medication_requests", "*.json")),
    ]

    for path in paths:
        payload = _load_json_file(path)
        if payload:
            _seed_file_for_all_modes(payload, owner_username)


def deterministic_reset_and_seed() -> None:
    repository.clear_all_entries()
    load_users_seed()
    load_resource_seeds()
