import json
from typing import Any, Dict, Optional, Tuple

from app.services.normalization import normalize_birthdate, normalize_cpf, normalize_name

SUPPORTED_TYPES = {
    "Patient",
    "Observation",
    "Condition",
    "Encounter",
    "MedicationRequest",
}


def validate_fhir_resource(resource: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(resource, dict):
        return False, "FHIR payload must be a JSON object"
    resource_type = resource.get("resourceType")
    if not resource_type:
        return False, "resourceType is required"
    if resource_type not in SUPPORTED_TYPES:
        return False, "Unsupported resourceType: {0}".format(resource_type)
    return True, "ok"


def serialize_fhir_json(resource: Dict[str, Any]) -> str:
    return json.dumps(resource, ensure_ascii=False, separators=(",", ":"))


def _extract_patient_name(resource: Dict[str, Any]) -> Optional[str]:
    names = resource.get("name")
    if not isinstance(names, list) or not names:
        return None
    name_obj = names[0]
    if not isinstance(name_obj, dict):
        return None
    given = name_obj.get("given") or []
    family = name_obj.get("family")
    chunks = []
    if isinstance(given, list):
        chunks.extend(str(x) for x in given)
    if family:
        chunks.append(str(family))
    if not chunks:
        return None
    return " ".join(chunks)


def _extract_patient_cpf(resource: Dict[str, Any]) -> Optional[str]:
    identifiers = resource.get("identifier")
    if not isinstance(identifiers, list):
        return None
    for ident in identifiers:
        if not isinstance(ident, dict):
            continue
        system = str(ident.get("system", ""))
        if "cpf" in system.lower():
            return str(ident.get("value", ""))
    return None


def _extract_birthdate(resource: Dict[str, Any]) -> Optional[str]:
    value = resource.get("birthDate")
    if value is None:
        return None
    return str(value)


def derive_search_fields(resource: Dict[str, Any]) -> Dict[str, Optional[str]]:
    rt = resource.get("resourceType")

    name = None
    cpf = None
    birthdate = None

    if rt == "Patient":
        name = _extract_patient_name(resource)
        cpf = _extract_patient_cpf(resource)
        birthdate = _extract_birthdate(resource)

    return {
        "name": normalize_name(name),
        "cpf": normalize_cpf(cpf),
        "birthdate": normalize_birthdate(birthdate),
    }
