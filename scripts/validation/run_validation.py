from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import os
import random
import re
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

try:
    import yaml
except Exception:  # pragma: no cover - optional at runtime only if package missing
    yaml = None

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception:  # pragma: no cover - optional DB observer path
    psycopg2 = None
    RealDictCursor = None

MODES = ["fabeo"]
SUPPORTED_RESOURCE_TYPES = ["Patient", "Observation", "Condition", "Encounter", "MedicationRequest"]
DEFAULT_USERS_PATH = Path(__file__).resolve().parents[2] / "resources" / "users_seed.yaml"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "output"


@dataclass
class ValidationConfig:
    base_url: str = "http://localhost:8000"
    iterations: int = 500
    mode: str = "fabeo"
    out_dir: Path = DEFAULT_OUT_DIR
    seed: int = 2026
    db_dsn: Optional[str] = None


@dataclass
class UserProfile:
    username: str
    password: Optional[str]
    full_name: str
    role: str
    attributes: List[str]
    available: bool = True
    note: str = ""


@dataclass
class ResourceTemplate:
    resource_type: str
    resource: Dict[str, Any]
    search_filters: Dict[str, str]
    label: str


@dataclass
class PolicyTemplate:
    name: str
    expression: str
    resource_types: List[str]
    description: str


@dataclass
class AttemptRecord:
    iteration: int
    mode: str
    user: str
    resource_type: str
    resource_id: str
    policy_name: str
    policy_expression: str
    expected_allowed: Optional[bool]
    expected_reason: str
    observed_status: int
    observed_allowed: bool
    classification: str
    integrity_ok: Optional[bool] = None
    original_sha256: Optional[str] = None
    recovered_sha256: Optional[str] = None
    search_status: Optional[int] = None
    search_time_ms: Optional[float] = None
    login_time_ms: Optional[float] = None
    create_time_ms: Optional[float] = None
    cipher_time_ms: Optional[float] = None
    decrypt_time_ms: Optional[float] = None
    request_payload_bytes: Optional[int] = None
    cipher_response_bytes: Optional[int] = None
    decrypt_response_bytes: Optional[int] = None
    decrypted_plaintext: Optional[str] = None
    entry_id: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ScenarioResult:
    name: str
    k_tentativa: int = 0
    n_bloqueio: int = 0
    n_exposicao: int = 0
    unavailable: bool = False
    unavailable_reason: str = ""
    notes: List[str] = field(default_factory=list)

    @property
    def rho_bloqueio(self) -> float:
        if self.k_tentativa == 0:
            return 0.0
        return (self.n_bloqueio / self.k_tentativa) * 100.0

    @property
    def rho_exposicao(self) -> float:
        if self.k_tentativa == 0:
            return 0.0
        return (self.n_exposicao / self.k_tentativa) * 100.0


@dataclass
class ValidationState:
    config: ValidationConfig
    rng: random.Random
    users: Dict[str, UserProfile]
    resources_by_type: Dict[str, List[ResourceTemplate]]
    policies: List[PolicyTemplate]
    smoke: Dict[str, Any] = field(default_factory=dict)
    attempts: List[AttemptRecord] = field(default_factory=list)
    insider: Dict[str, ScenarioResult] = field(default_factory=dict)
    quantitative: Dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    revocation_enabled: bool = False
    current_epoch: str = ""
    final_pass: bool = False
    final_reason: str = ""


STATE: Optional[ValidationState] = None


def load_seed_users(path: Path) -> Dict[str, UserProfile]:
    if not path.exists():
        raise FileNotFoundError(f"users seed file not found: {path}")
    users: Dict[str, UserProfile] = {}
    data: Dict[str, Any] = {}
    if yaml is not None:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    else:
        current: Optional[Dict[str, Any]] = None
        current_key: Optional[str] = None
        with path.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.rstrip("\n")
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped == "users:":
                    continue
                if stripped.startswith("- username:"):
                    if current:
                        data.setdefault("users", []).append(current)
                    current = {"username": stripped.split(":", 1)[1].strip()}
                    current_key = None
                    continue
                if current is None:
                    continue
                if stripped == "attributes:":
                    current["attributes"] = []
                    current_key = "attributes"
                    continue
                if current_key == "attributes" and stripped.startswith("- "):
                    current.setdefault("attributes", []).append(stripped[2:].strip())
                    continue
                if ":" in stripped:
                    key, value = stripped.split(":", 1)
                    current[key.strip()] = value.strip()
                    current_key = key.strip()
        if current:
            data.setdefault("users", []).append(current)

    for item in data.get("users", []):
        users[item["username"]] = UserProfile(
            username=item["username"],
            password=item.get("password"),
            full_name=item.get("full_name", item["username"]),
            role=item.get("role", item["username"]),
            attributes=list(item.get("attributes", [])),
            available=True,
        )
    users["db_admin"] = UserProfile(
        username="db_admin",
        password=None,
        full_name="DB Admin (sintético)",
        role="db_admin",
        attributes=["role.db_admin", "department.it", "clearance.high", "epoch.2026"],
        available=False,
        note="usuário indisponível no seed atual",
    )
    return users


def build_resources(rng: random.Random) -> Dict[str, List[ResourceTemplate]]:
    counters = defaultdict(int)

    def next_id(prefix: str) -> str:
        counters[prefix] += 1
        return f"{prefix}-{counters[prefix]:03d}-{rng.randint(1000, 9999)}"

    resources: Dict[str, List[ResourceTemplate]] = {key: [] for key in SUPPORTED_RESOURCE_TYPES}

    for idx in range(6):
        cpf = f"{rng.randint(10000000000, 99999999999)}"
        patient = {
            "resourceType": "Patient",
            "id": next_id("patient"),
            "meta": {"profile": ["https://hl7.org/fhir/R4/Patient"]},
            "identifier": [{"system": "https://saude.gov.br/fhir/sid/cpf", "value": cpf}],
            "name": [{"family": f"Paciente{idx}", "given": [f"Teste{idx}"]}],
            "gender": rng.choice(["male", "female"]),
            "birthDate": f"19{rng.randint(70, 99)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
        }
        resources["Patient"].append(
            ResourceTemplate(
                resource_type="Patient",
                resource=patient,
                search_filters={
                    "cpf": cpf,
                    "name": f"Teste{idx} Paciente{idx}",
                    "birthdate": patient["birthDate"],
                },
                label=f"patient-{idx}",
            )
        )

        resources["Observation"].append(
            ResourceTemplate(
                resource_type="Observation",
                resource={
                    "resourceType": "Observation",
                    "id": next_id("obs"),
                    "status": "final",
                    "code": {"text": rng.choice(["Blood Pressure", "Heart Rate", "Glucose"])},
                    "subject": {"reference": f"Patient/{patient['id']}"},
                    "effectiveDateTime": f"2026-04-{rng.randint(1, 28):02d}T10:30:00Z",
                    "valueQuantity": {"value": round(rng.uniform(10, 180), 1), "unit": rng.choice(["mmHg", "bpm", "mg/dL"])},
                },
                search_filters={},
                label=f"observation-{idx}",
            )
        )

        resources["Condition"].append(
            ResourceTemplate(
                resource_type="Condition",
                resource={
                    "resourceType": "Condition",
                    "id": next_id("cond"),
                    "clinicalStatus": {"text": "active"},
                    "verificationStatus": {"text": "confirmed"},
                    "code": {"text": rng.choice(["Hypertension", "Diabetes", "Asthma"])},
                    "subject": {"reference": f"Patient/{patient['id']}"},
                    "onsetDateTime": f"2025-0{rng.randint(1, 9)}-{rng.randint(10, 28):02d}T00:00:00Z",
                },
                search_filters={},
                label=f"condition-{idx}",
            )
        )

        resources["Encounter"].append(
            ResourceTemplate(
                resource_type="Encounter",
                resource={
                    "resourceType": "Encounter",
                    "id": next_id("enc"),
                    "status": "finished",
                    "class": {"code": rng.choice(["AMB", "IMP"])},
                    "subject": {"reference": f"Patient/{patient['id']}"},
                    "period": {"start": f"2026-03-{rng.randint(1, 28):02d}T08:00:00Z"},
                },
                search_filters={},
                label=f"encounter-{idx}",
            )
        )

        resources["MedicationRequest"].append(
            ResourceTemplate(
                resource_type="MedicationRequest",
                resource={
                    "resourceType": "MedicationRequest",
                    "id": next_id("med"),
                    "status": "active",
                    "intent": "order",
                    "medicationCodeableConcept": {"text": rng.choice(["Metformin", "Atorvastatin", "Losartan"])},
                    "subject": {"reference": f"Patient/{patient['id']}"},
                    "authoredOn": f"2026-04-{rng.randint(1, 28):02d}",
                },
                search_filters={},
                label=f"medication-request-{idx}",
            )
        )

    return resources


def build_policies() -> List[PolicyTemplate]:
    return [
        PolicyTemplate(
            name="patient_demographics",
            expression="(role.receptionist OR role.nurse OR role.doctor) AND clearance.demographics AND epoch.2026",
            resource_types=["Patient"],
            description="dados demográficos de prontuário",
        ),
        PolicyTemplate(
            name="patient_frontdesk",
            expression="role.receptionist AND department.frontdesk AND clearance.demographics AND epoch.2026",
            resource_types=["Patient"],
            description="demografia restrita à recepção",
        ),
        PolicyTemplate(
            name="clinical_notes",
            expression="(role.nurse OR role.doctor) AND clearance.clinical_notes AND epoch.2026",
            resource_types=["Condition", "Encounter"],
            description="notas clínicas e atendimentos",
        ),
        PolicyTemplate(
            name="clinical_cardiology",
            expression="role.doctor AND department.cardiology AND specialty.cardiology AND clearance.clinical_notes AND epoch.2026",
            resource_types=["Condition", "Encounter"],
            description="acesso clínico cardiológico",
        ),
        PolicyTemplate(
            name="labs_shared",
            expression="(role.lab_technician OR role.lab_scientist OR role.doctor) AND department.laboratory AND clearance.labs AND epoch.2026",
            resource_types=["Observation"],
            description="resultados laboratoriais",
        ),
        PolicyTemplate(
            name="medications_doctor",
            expression="role.doctor AND clearance.medications AND epoch.2026",
            resource_types=["MedicationRequest"],
            description="prescrições médicas",
        ),
        PolicyTemplate(
            name="medications_clinic",
            expression="role.doctor AND department.clinic AND clearance.medications AND epoch.2026",
            resource_types=["MedicationRequest"],
            description="prescrições de clínica geral",
        ),
        PolicyTemplate(
            name="high_confidentiality",
            expression="role.db_admin AND clearance.high AND epoch.2026",
            resource_types=SUPPORTED_RESOURCE_TYPES,
            description="cenário sintético de alta confidencialidade",
        ),
    ]


def canonical_json_hash(obj: Any) -> str:
    def _normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
        if isinstance(value, list):
            return [_normalize(item) for item in value]
        if isinstance(value, tuple):
            return [_normalize(item) for item in value]
        return value

    normalized = _normalize(obj)
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


TOKEN_RE = re.compile(r"^[a-z]+\.[a-z0-9_]+$")


def evaluate_expected_access(user_attributes: Iterable[str], policy_expression: str) -> bool:
    attrs = {str(attr).strip().lower() for attr in user_attributes}
    expression = policy_expression.strip()
    if not expression:
        return False

    tokens = re.findall(r"\(|\)|\bAND\b|\bOR\b|[^\s()]+", expression)
    position = 0

    def parse_expression() -> bool:
        nonlocal position
        value = parse_term()
        while position < len(tokens) and tokens[position] == "OR":
            position += 1
            value = value or parse_term()
        return value

    def parse_term() -> bool:
        nonlocal position
        value = parse_factor()
        while position < len(tokens) and tokens[position] == "AND":
            position += 1
            value = value and parse_factor()
        return value

    def parse_factor() -> bool:
        nonlocal position
        if position >= len(tokens):
            return False
        token = tokens[position]
        position += 1
        if token == "(":
            value = parse_expression()
            if position < len(tokens) and tokens[position] == ")":
                position += 1
            return value
        if token == ")":
            return False
        normalized = token.strip().lower()
        if not TOKEN_RE.match(normalized):
            return False
        return normalized in attrs

    result = parse_expression()
    return bool(result)


def _base_url() -> str:
    if STATE is None:
        return "http://localhost:8000"
    return STATE.config.base_url.rstrip("/")


def _timeout(seconds: float = 15.0) -> float:
    return seconds


def login(username: str, password: str) -> requests.Session:
    session = requests.Session()
    response = session.post(
        f"{_base_url()}/auth/login",
        json={"username": username, "password": password},
        timeout=_timeout(15),
    )
    response.raise_for_status()
    return session


def create_entry(session: requests.Session, resource: Dict[str, Any], policy_expression: str, mode: str) -> requests.Response:
    response = session.post(
        f"{_base_url()}/entries",
        json={"mode": mode, "resource": resource, "policy_expression": policy_expression},
        timeout=_timeout(30),
    )
    response.raise_for_status()
    return response


def search_entry(session: requests.Session, mode: str, filtros: Dict[str, str]) -> requests.Response:
    params = {"mode": mode}
    for key in ("name", "cpf", "birthdate"):
        if filtros.get(key):
            params[key] = filtros[key]
    response = session.get(f"{_base_url()}/entries/search", params=params, timeout=_timeout(10))
    response.raise_for_status()
    return response


def get_cipher_metadata(session: requests.Session, entry_id: str, mode: str) -> requests.Response:
    response = session.get(
        f"{_base_url()}/entries/{entry_id}/cipher",
        params={"mode": mode},
        timeout=_timeout(10),
    )
    response.raise_for_status()
    return response


def decrypt_package(session: requests.Session, entry_id: str, mode: str) -> requests.Response:
    response = session.post(
        f"{_base_url()}/entries/{entry_id}/decrypt-package",
        params={"mode": mode},
        timeout=_timeout(30),
    )
    return response


def _decrypt_observed_plaintext(mode: str, response_json: Dict[str, Any]) -> str:
    result = response_json.get("result") or {}
    if mode == "fabeo":
        plaintext = result.get("resource_json")
        if not isinstance(plaintext, str):
            raise ValueError("fabeo decrypt response missing plaintext resource_json")
        return plaintext
    raise ValueError(f"invalid mode: {mode}")


def _ensure_mode_selection(mode: str) -> List[str]:
    if mode != "fabeo":
        raise ValueError(f"invalid mode: {mode}")
    return ["fabeo"]


def _match_policy_to_resource(policy: PolicyTemplate, resource_type: str) -> bool:
    return resource_type in policy.resource_types or policy.resource_types == SUPPORTED_RESOURCE_TYPES


def _login_user(user: UserProfile) -> Tuple[requests.Session, float]:
    if not user.available or not user.password:
        raise RuntimeError(f"user unavailable: {user.username}")
    t0 = time.perf_counter()
    session = login(user.username, user.password)
    elapsed = (time.perf_counter() - t0) * 1000.0
    return session, elapsed


def _perform_search_if_applicable(session: requests.Session, mode: str, resource: ResourceTemplate) -> Tuple[Optional[requests.Response], Optional[float]]:
    if resource.resource_type != "Patient":
        return None, None
    if not resource.search_filters:
        return None, None
    t0 = time.perf_counter()
    response = search_entry(session, mode, resource.search_filters)
    elapsed = (time.perf_counter() - t0) * 1000.0
    return response, elapsed


def _make_policy_choice(resource_type: str, policies: List[PolicyTemplate], rng: random.Random) -> PolicyTemplate:
    candidates = [policy for policy in policies if _match_policy_to_resource(policy, resource_type)]
    if not candidates:
        return rng.choice(policies)
    return rng.choice(candidates)


def run_smoke_test(config: ValidationConfig) -> Dict[str, Any]:
    report: Dict[str, Any] = {}
    base_url = config.base_url.rstrip("/")

    health_response = requests.get(f"{base_url}/health", timeout=10)
    health_response.raise_for_status()
    report["health"] = health_response.json()

    smoke_user = "doctor_general_clinic"
    smoke_password = "DocGeral2026!"
    session = requests.Session()

    login_response = session.post(
        f"{base_url}/auth/login",
        json={"username": smoke_user, "password": smoke_password},
        timeout=15,
    )
    login_response.raise_for_status()
    report["login"] = login_response.json()

    me_response = session.get(f"{base_url}/auth/me", timeout=10)
    me_response.raise_for_status()
    report["me"] = me_response.json()

    policies_response = session.get(f"{base_url}/entries/meta/policies", timeout=10)
    policies_response.raise_for_status()
    report["policies"] = policies_response.json()

    return report


def run_abe_functional_validation() -> Dict[str, Any]:
    if STATE is None:
        raise RuntimeError("validation state not initialized")

    config = STATE.config
    rng = STATE.rng
    selected_modes = _ensure_mode_selection(config.mode)
    users = [user for user in STATE.users.values() if user.available]

    total_expected_allowed = 0
    total_expected_denied = 0
    correct_decryptions = 0
    correct_denials = 0
    false_positives = 0
    false_negatives = 0
    integrity_ok_count = 0
    attempted_count = 0
    unavailable_count = 0

    for i in range(config.iterations):
        mode = selected_modes[0] if len(selected_modes) == 1 else rng.choice(selected_modes)
        user = rng.choice(users)
        resource_type = rng.choice(SUPPORTED_RESOURCE_TYPES)
        resource = rng.choice(STATE.resources_by_type[resource_type])
        policy = _make_policy_choice(resource.resource_type, STATE.policies, rng)

        expected_allowed = evaluate_expected_access(user.attributes, policy.expression)
        if expected_allowed:
            total_expected_allowed += 1
        else:
            total_expected_denied += 1

        record = AttemptRecord(
            iteration=i + 1,
            mode=mode,
            user=user.username,
            resource_type=resource.resource_type,
            resource_id=resource.resource["id"],
            policy_name=policy.name,
            policy_expression=policy.expression,
            expected_allowed=expected_allowed,
            expected_reason="user attributes satisfy policy" if expected_allowed else "user attributes do not satisfy policy",
            observed_status=0,
            observed_allowed=False,
            classification="pending",
        )

        try:
            session, login_ms = _login_user(user)
            record.login_time_ms = login_ms
            create_t0 = time.perf_counter()
            create_resp = create_entry(session, resource.resource, policy.expression, mode)
            record.create_time_ms = (time.perf_counter() - create_t0) * 1000.0
            record.entry_id = create_resp.json()["entry_id"]
            record.request_payload_bytes = len(json.dumps(resource.resource, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

            cipher_t0 = time.perf_counter()
            cipher_resp = get_cipher_metadata(session, record.entry_id, mode)
            record.cipher_time_ms = (time.perf_counter() - cipher_t0) * 1000.0
            record.cipher_response_bytes = len(cipher_resp.content)

            search_resp, search_ms = _perform_search_if_applicable(session, mode, resource)
            if search_resp is not None:
                record.search_status = search_resp.status_code
                record.search_time_ms = search_ms

            decrypt_t0 = time.perf_counter()
            decrypt_resp = decrypt_package(session, record.entry_id, mode)
            record.decrypt_time_ms = (time.perf_counter() - decrypt_t0) * 1000.0
            record.decrypt_response_bytes = len(decrypt_resp.content)
            record.observed_status = decrypt_resp.status_code

            if decrypt_resp.status_code == 403:
                record.observed_allowed = False
                if expected_allowed:
                    false_negatives += 1
                else:
                    correct_denials += 1
            elif decrypt_resp.ok:
                record.observed_allowed = True
                payload = decrypt_resp.json()
                plaintext = _decrypt_observed_plaintext(mode, payload)
                record.decrypted_plaintext = plaintext
                record.original_sha256 = canonical_json_hash(resource.resource)
                record.recovered_sha256 = canonical_json_hash(json.loads(plaintext))
                record.integrity_ok = record.original_sha256 == record.recovered_sha256
                if record.integrity_ok:
                    integrity_ok_count += 1
                if expected_allowed:
                    correct_decryptions += 1
                else:
                    false_positives += 1
            else:
                record.observed_allowed = False
                record.error = decrypt_resp.text[:500]
                if expected_allowed:
                    false_negatives += 1
                else:
                    correct_denials += 1

            record.classification = "correct_authorized" if (expected_allowed and record.observed_allowed and record.integrity_ok) else (
                "correct_denied" if ((expected_allowed is False) and (not record.observed_allowed)) else (
                    "false_negative" if expected_allowed and not record.observed_allowed else (
                        "false_positive" if (not expected_allowed) and record.observed_allowed else "inconclusive"
                    )
                )
            )
            attempted_count += 1

            quantitative = STATE.quantitative.setdefault(mode, {
                "login_ms": [],
                "create_ms": [],
                "search_ms": [],
                "cipher_ms": [],
                "decrypt_ms": [],
                "payload_bytes": [],
                "cipher_response_bytes": [],
                "decrypt_response_bytes": [],
            })
            if record.login_time_ms is not None:
                quantitative["login_ms"].append(record.login_time_ms)
            if record.create_time_ms is not None:
                quantitative["create_ms"].append(record.create_time_ms)
            if record.search_time_ms is not None:
                quantitative["search_ms"].append(record.search_time_ms)
            if record.cipher_time_ms is not None:
                quantitative["cipher_ms"].append(record.cipher_time_ms)
            if record.decrypt_time_ms is not None:
                quantitative["decrypt_ms"].append(record.decrypt_time_ms)
            if record.request_payload_bytes is not None:
                quantitative["payload_bytes"].append(record.request_payload_bytes)
            if record.cipher_response_bytes is not None:
                quantitative["cipher_response_bytes"].append(record.cipher_response_bytes)
            if record.decrypt_response_bytes is not None:
                quantitative["decrypt_response_bytes"].append(record.decrypt_response_bytes)

        except requests.HTTPError as exc:
            record.error = f"HTTPError: {exc.response.status_code} {exc.response.text[:500]}"
            if expected_allowed:
                false_negatives += 1
            else:
                correct_denials += 1
        except Exception as exc:  # noqa: BLE001
            record.error = str(exc)
            if expected_allowed:
                false_negatives += 1
            else:
                correct_denials += 1
        finally:
            STATE.attempts.append(record)

    correct_rate = (correct_decryptions / total_expected_allowed * 100.0) if total_expected_allowed else 0.0
    denial_rate = (correct_denials / total_expected_denied * 100.0) if total_expected_denied else 0.0

    return {
        "iterations": config.iterations,
        "expected_allowed": total_expected_allowed,
        "expected_denied": total_expected_denied,
        "correct_decryptions": correct_decryptions,
        "correct_denials": correct_denials,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "decryption_correct_rate_pct": correct_rate,
        "denial_correct_rate_pct": denial_rate,
        "integrity_ok_count": integrity_ok_count,
        "attempted_count": attempted_count,
        "unavailable_count": unavailable_count,
    }


def _observer_plaintext_exposed(row: Dict[str, Any], plaintext: str) -> bool:
    row_text = json.dumps(row, default=str, ensure_ascii=False)
    return plaintext in row_text


def _db_observer_read_only(mode: str, entry_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not STATE or not STATE.config.db_dsn or psycopg2 is None:
        return None, "observer unavailable"
    if mode not in MODES:
        return None, "invalid mode"
    schema = mode
    conn = psycopg2.connect(STATE.config.db_dsn)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT entry_id, resource_type, policy_expression, epoch_label, owner_username, encrypted_payload, iv, auth_tag, wrapped_key, wrapped_key_meta, mode_meta FROM {schema}.entries WHERE entry_id = %s",
                (entry_id,),
            )
            row = cur.fetchone()
        return dict(row) if row else None, None
    finally:
        conn.close()


def run_insider_validation() -> Dict[str, Any]:
    if STATE is None:
        raise RuntimeError("validation state not initialized")

    config = STATE.config
    rng = STATE.rng
    selected_modes = _ensure_mode_selection(config.mode)
    test_mode = selected_modes[0]
    results: Dict[str, ScenarioResult] = {}

    def scenario(name: str, k: int = 1) -> ScenarioResult:
        return ScenarioResult(name=name, k_tentativa=k)

    scenarios = {
        "insider_role_insufficient": scenario("insider_role_insufficient"),
        "insider_other_department": scenario("insider_other_department"),
        "insider_partial_privilege": scenario("insider_partial_privilege"),
        "receptionist_clinical_data": scenario("receptionist_clinical_data"),
        "doctor_wrong_context": scenario("doctor_wrong_context"),
        "db_observer": scenario("db_observer"),
        "revoked_user": scenario("revoked_user"),
        "search_allowed_decrypt_denied": scenario("search_allowed_decrypt_denied"),
    }

    for key, value in scenarios.items():
        results[key] = value

    user = STATE.users["receptionist"]
    policy = next(item for item in STATE.policies if item.name == "medications_doctor")
    resource = rng.choice(STATE.resources_by_type["MedicationRequest"])
    session, _ = _login_user(user)
    entry_id = create_entry(session, resource.resource, policy.expression, test_mode).json()["entry_id"]
    decrypt_resp = decrypt_package(session, entry_id, test_mode)
    if decrypt_resp.status_code == 403:
        results["insider_role_insufficient"].n_bloqueio += 1
    else:
        results["insider_role_insufficient"].n_exposicao += 1
        results["insider_role_insufficient"].notes.append("critical exposure: plaintext returned")

    user = STATE.users["doctor_general_clinic"]
    policy = next(item for item in STATE.policies if item.name == "clinical_cardiology")
    resource = rng.choice(STATE.resources_by_type["Encounter"])
    session, _ = _login_user(user)
    entry_id = create_entry(session, resource.resource, policy.expression, test_mode).json()["entry_id"]
    decrypt_resp = decrypt_package(session, entry_id, test_mode)
    if decrypt_resp.status_code == 403:
        results["insider_other_department"].n_bloqueio += 1
    else:
        results["insider_other_department"].n_exposicao += 1

    user = STATE.users["medical_laboratory_scientist"]
    policy = next(item for item in STATE.policies if item.name == "clinical_notes")
    resource = rng.choice(STATE.resources_by_type["Condition"])
    session, _ = _login_user(user)
    entry_id = create_entry(session, resource.resource, policy.expression, test_mode).json()["entry_id"]
    decrypt_resp = decrypt_package(session, entry_id, test_mode)
    if decrypt_resp.status_code == 403:
        results["insider_partial_privilege"].n_bloqueio += 1
    else:
        results["insider_partial_privilege"].n_exposicao += 1

    user = STATE.users["receptionist"]
    policy = next(item for item in STATE.policies if item.name == "clinical_notes")
    resource = rng.choice(STATE.resources_by_type["Condition"])
    session, _ = _login_user(user)
    entry_id = create_entry(session, resource.resource, policy.expression, test_mode).json()["entry_id"]
    decrypt_resp = decrypt_package(session, entry_id, test_mode)
    if decrypt_resp.status_code == 403:
        results["receptionist_clinical_data"].n_bloqueio += 1
    else:
        results["receptionist_clinical_data"].n_exposicao += 1

    user = STATE.users["doctor_general_clinic"]
    policy = next(item for item in STATE.policies if item.name == "clinical_cardiology")
    resource = rng.choice(STATE.resources_by_type["Encounter"])
    session, _ = _login_user(user)
    entry_id = create_entry(session, resource.resource, policy.expression, test_mode).json()["entry_id"]
    decrypt_resp = decrypt_package(session, entry_id, test_mode)
    if decrypt_resp.status_code == 403:
        results["doctor_wrong_context"].n_bloqueio += 1
    else:
        results["doctor_wrong_context"].n_exposicao += 1

    user = STATE.users["doctor_cardiologist"]
    policy = next(item for item in STATE.policies if item.name == "patient_demographics")
    resource = rng.choice(STATE.resources_by_type["Patient"])
    session, _ = _login_user(user)
    entry_id = create_entry(session, resource.resource, policy.expression, test_mode).json()["entry_id"]
    row, observer_reason = _db_observer_read_only(test_mode, entry_id)
    if row is None:
        results["db_observer"].unavailable = True
        results["db_observer"].unavailable_reason = observer_reason or "observer unavailable"
    else:
        plaintext = json.dumps(resource.resource, ensure_ascii=False, separators=(",", ":"))
        if _observer_plaintext_exposed(row, plaintext):
            results["db_observer"].n_exposicao += 1
            results["db_observer"].notes.append("critical exposure: plaintext found in database observer query")
        else:
            results["db_observer"].n_bloqueio += 1

    if STATE.revocation_enabled:
        user = STATE.users["doctor_cardiologist"]
        policy = next(item for item in STATE.policies if item.name == "patient_demographics")
        resource = rng.choice(STATE.resources_by_type["Patient"])
        session, _ = _login_user(user)
        entry_id = create_entry(session, resource.resource, policy.expression, test_mode).json()["entry_id"]
        rotate_resp = session.post(f"{_base_url()}/entries/meta/epoch/rotate", params={"new_epoch": "epoch.2027"}, timeout=15)
        if rotate_resp.status_code >= 400:
            results["revoked_user"].unavailable = True
            results["revoked_user"].unavailable_reason = f"epoch rotation failed: {rotate_resp.status_code}"
        else:
            decrypt_resp = decrypt_package(session, entry_id, test_mode)
            if decrypt_resp.status_code == 403:
                results["revoked_user"].n_bloqueio += 1
            else:
                results["revoked_user"].n_exposicao += 1
                results["revoked_user"].notes.append("critical exposure: revoked user recovered plaintext")
    else:
        results["revoked_user"].unavailable = True
        results["revoked_user"].unavailable_reason = "experimental revocation disabled"

    user = STATE.users["doctor_general_clinic"]
    policy = next(item for item in STATE.policies if item.name == "patient_frontdesk")
    resource = rng.choice(STATE.resources_by_type["Patient"])
    session, _ = _login_user(user)
    create_resp = create_entry(session, resource.resource, policy.expression, test_mode)
    entry_id = create_resp.json()["entry_id"]
    search_resp = search_entry(session, test_mode, resource.search_filters)
    if search_resp.status_code == 200:
        results["search_allowed_decrypt_denied"].notes.append("search executed successfully")
    decrypt_resp = decrypt_package(session, entry_id, test_mode)
    if decrypt_resp.status_code == 403:
        results["search_allowed_decrypt_denied"].n_bloqueio += 1
    else:
        results["search_allowed_decrypt_denied"].n_exposicao += 1

    STATE.insider = results
    return {key: dataclasses.asdict(value) for key, value in results.items()}


def _stats(values: Sequence[float]) -> Dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "minimum": 0.0, "maximum": 0.0, "stdev": 0.0}
    if len(values) == 1:
        return {
            "mean": float(values[0]),
            "median": float(values[0]),
            "minimum": float(values[0]),
            "maximum": float(values[0]),
            "stdev": 0.0,
        }
    return {
        "mean": float(statistics.mean(values)),
        "median": float(statistics.median(values)),
        "minimum": float(min(values)),
        "maximum": float(max(values)),
        "stdev": float(statistics.stdev(values)),
    }


def run_quantitative_analysis() -> Dict[str, Any]:
    if STATE is None:
        raise RuntimeError("validation state not initialized")
    result: Dict[str, Any] = {}
    for mode, samples in STATE.quantitative.items():
        result[mode] = {
            "login_ms": _stats(samples["login_ms"]),
            "create_ms": _stats(samples["create_ms"]),
            "search_ms": _stats(samples["search_ms"]),
            "cipher_ms": _stats(samples["cipher_ms"]),
            "decrypt_ms": _stats(samples["decrypt_ms"]),
            "payload_bytes": _stats(samples["payload_bytes"]),
            "cipher_response_bytes": _stats(samples["cipher_response_bytes"]),
            "decrypt_response_bytes": _stats(samples["decrypt_response_bytes"]),
        }
    return result


def _build_overall_result(abe: Dict[str, Any]) -> Dict[str, Any]:
    if STATE is None:
        raise RuntimeError("validation state not initialized")
    return {
        "total_attempts": len(STATE.attempts),
        "expected_allowed": abe["expected_allowed"],
        "expected_denied": abe["expected_denied"],
        "correct_decryptions": abe["correct_decryptions"],
        "correct_denials": abe["correct_denials"],
        "false_positives": abe["false_positives"],
        "false_negatives": abe["false_negatives"],
        "decryption_correct_rate_pct": abe["decryption_correct_rate_pct"],
        "denial_correct_rate_pct": abe["denial_correct_rate_pct"],
        "integrity_ok_count": abe["integrity_ok_count"],
        "integrity_ok_rate_pct": (abe["integrity_ok_count"] / abe["expected_allowed"] * 100.0) if abe["expected_allowed"] else 0.0,
    }


def write_json_report(out_dir: Path, report: Dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "validation_results.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return path


def write_csv_summary(out_dir: Path, report: Dict[str, Any]) -> Path:
    path = out_dir / "validation_summary.csv"
    rows: List[Dict[str, Any]] = []

    overall = report["overall"]
    for key in [
        "total_attempts",
        "expected_allowed",
        "expected_denied",
        "correct_decryptions",
        "correct_denials",
        "false_positives",
        "false_negatives",
        "decryption_correct_rate_pct",
        "denial_correct_rate_pct",
        "integrity_ok_count",
        "integrity_ok_rate_pct",
    ]:
        rows.append({"section": "overall", "mode": "", "scenario": "", "operation": "", "statistic": key, "value": overall[key], "unit": "%" if key.endswith("_pct") else "count"})

    for scenario, data in report["insider"].items():
        for key in ["k_tentativa", "n_bloqueio", "n_exposicao", "rho_bloqueio", "rho_exposicao"]:
            rows.append({
                "section": "insider",
                "mode": "",
                "scenario": scenario,
                "operation": "",
                "statistic": key,
                "value": data.get(key),
                "unit": "%" if key.startswith("rho_") else "count",
            })

    for mode, data in report["quantitative"].items():
        for operation in ["login_ms", "create_ms", "search_ms", "cipher_ms", "decrypt_ms", "payload_bytes", "cipher_response_bytes", "decrypt_response_bytes"]:
            for stat_name, stat_value in data[operation].items():
                rows.append({
                    "section": "quantitative",
                    "mode": mode,
                    "scenario": "",
                    "operation": operation,
                    "statistic": stat_name,
                    "value": stat_value,
                    "unit": "ms" if operation.endswith("_ms") else "bytes",
                })

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["section", "mode", "scenario", "operation", "statistic", "value", "unit"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def _fmt_float(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _markdown_table(headers: List[str], rows: List[List[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def write_markdown_report(out_dir: Path, report: Dict[str, Any]) -> Path:
    if STATE is None:
        raise RuntimeError("validation state not initialized")
    path = out_dir / "validation_report.md"
    users_lines = []
    for user in STATE.users.values():
        users_lines.append(f"- {user.username} ({'available' if user.available else 'unavailable'}): {', '.join(user.attributes)}")

    config_rows = [
        ["Base URL", STATE.config.base_url],
        ["Modo", STATE.config.mode],
        ["Iterações", str(STATE.config.iterations)],
        ["Seed", str(STATE.config.seed)],
        ["Gerado em", STATE.generated_at],
        ["Revogação experimental", "habilitada" if STATE.revocation_enabled else "desabilitada"],
        ["Epoch atual", STATE.current_epoch],
        ["Usuários testados", str(len([u for u in STATE.users.values() if u.available]))],
    ]

    abe = report["overall"]
    abe_rows = [[
        str(abe["total_attempts"]),
        str(abe["expected_allowed"]),
        str(abe["expected_denied"]),
        str(abe["correct_decryptions"]),
        str(abe["correct_denials"]),
        str(abe["false_positives"]),
        str(abe["false_negatives"]),
        f"{abe['decryption_correct_rate_pct']:.2f}%",
        f"{abe['denial_correct_rate_pct']:.2f}%",
        str(abe["integrity_ok_count"]),
        f"{abe['integrity_ok_rate_pct']:.2f}%",
    ]]
    abe_table = _markdown_table(
        [
            "Tentativas",
            "Esperados permitidos",
            "Esperados negados",
            "Descriptografias corretas",
            "Negações corretas",
            "Falsos positivos",
            "Falsos negativos",
            "Taxa correção decrypt",
            "Taxa correção negação",
            "Integridade ok",
            "Integridade ok rate",
        ],
        abe_rows,
    )

    insider_rows = []
    for scenario, data in report["insider"].items():
        if data.get("unavailable"):
            insider_rows.append([scenario, "-", "-", "-", "-", "-", data.get("unavailable_reason", "")])
            continue
        insider_rows.append([
            scenario,
            str(data.get("k_tentativa", 0)),
            str(data.get("n_bloqueio", 0)),
            str(data.get("n_exposicao", 0)),
            f"{data.get('rho_bloqueio', 0.0):.2f}%",
            f"{data.get('rho_exposicao', 0.0):.2f}%",
            "",
        ])

    q_rows: List[List[str]] = []
    for mode, data in report["quantitative"].items():
        for operation in ["login_ms", "create_ms", "search_ms", "cipher_ms", "decrypt_ms", "payload_bytes", "cipher_response_bytes", "decrypt_response_bytes"]:
            stats = data[operation]
            q_rows.append([
                mode,
                operation,
                _fmt_float(stats["mean"]),
                _fmt_float(stats["median"]),
                _fmt_float(stats["minimum"]),
                _fmt_float(stats["maximum"]),
                _fmt_float(stats["stdev"]),
            ])

    final_status = "PASS" if report["final_pass"] else "FAIL"
    reason = report["final_reason"]

    content = [
        "# Relatório de Validação MACHS2",
        "",
        "## 1. Configuração Experimental",
        _markdown_table(["Campo", "Valor"], config_rows),
        "",
        "### Usuários",
        "\n".join(users_lines),
        "",
        "## 2. Validação Funcional da ABE",
        abe_table,
        "",
        "## 3. Avaliação ABAC contra Insider Attacks",
        _markdown_table(["Cenário", "Tentativas", "Bloqueios corretos", "Exposições indevidas", "rho_bloqueio", "rho_exposicao", "Observação"], insider_rows),
        "",
        "## 4. Análise Quantitativa",
        _markdown_table(["Modo", "Operação", "Média", "Mediana", "Mínimo", "Máximo", "Desvio padrão"], q_rows),
        "",
        "## 5. Resultado Final",
        f"{final_status}: {reason}",
    ]
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(content).strip() + "\n")
    return path


def _finalize_result(abe: Dict[str, Any], insider: Dict[str, Any]) -> Tuple[bool, str]:
    critical_failure = abe["false_positives"] > 0
    exposed = any((not data.get("unavailable", False)) and data.get("n_exposicao", 0) > 0 for data in insider.values())
    integrity_ok = abe["false_negatives"] == 0 and abe["false_positives"] == 0 and abe["integrity_ok_count"] == abe["expected_allowed"]
    denials_ok = abe["correct_denials"] == abe["expected_denied"]
    if critical_failure:
        return False, "falha crítica: falsos positivos detectados"
    if exposed:
        return False, "falha crítica: exposição indevida em cenário insider"
    if not integrity_ok:
        return False, "falha crítica: integridade SHA-256 ou corretude de descriptografia insuficiente"
    if not denials_ok:
        return False, "falha crítica: negações esperadas não foram totalmente bloqueadas"
    return True, "critério de segurança atendido"


def _build_report(abe: Dict[str, Any], insider: Dict[str, Any], quantitative: Dict[str, Any]) -> Dict[str, Any]:
    overall = _build_overall_result(abe)
    final_pass, final_reason = _finalize_result(abe, insider)
    assert STATE is not None
    config_dict = dataclasses.asdict(STATE.config)
    config_dict["out_dir"] = str(config_dict["out_dir"])
    smoke_dict = json.loads(json.dumps(STATE.smoke, ensure_ascii=False))
    if isinstance(smoke_dict.get("login"), dict):
        smoke_dict["login"].pop("access_token", None)
    users = []
    for user in STATE.users.values():
        user_dict = dataclasses.asdict(user)
        user_dict["password"] = None
        users.append(user_dict)
    return {
        "generated_at": STATE.generated_at,
        "config": config_dict,
        "smoke": smoke_dict,
        "users": users,
        "policies": [dataclasses.asdict(policy) for policy in STATE.policies],
        "resources": {key: [dataclasses.asdict(item) for item in value] for key, value in STATE.resources_by_type.items()},
        "attempts": [dataclasses.asdict(attempt) for attempt in STATE.attempts],
        "insider": insider,
        "quantitative": quantitative,
        "overall": overall,
        "final_pass": final_pass,
        "final_reason": final_reason,
        "runtime": {
            "base_url": STATE.config.base_url,
            "mode": STATE.config.mode,
            "iterations": STATE.config.iterations,
            "seed": STATE.config.seed,
        },
    }


def _load_db_dsn_from_env() -> Optional[str]:
    return os.getenv("DATABASE_DSN") or os.getenv("POSTGRES_DSN") or os.getenv("VALIDATION_DB_DSN")


def parse_args(argv: Optional[List[str]] = None) -> ValidationConfig:
    parser = argparse.ArgumentParser(description="Run MACHS2 validation workflow")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--mode", default="fabeo", choices=["fabeo"], help="fabeo")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--db-dsn", default=None)
    args = parser.parse_args(argv)
    return ValidationConfig(
        base_url=args.base_url,
        iterations=args.iterations,
        mode=args.mode,
        out_dir=Path(args.out_dir),
        seed=args.seed,
        db_dsn=args.db_dsn or _load_db_dsn_from_env(),
    )


def main(argv: Optional[List[str]] = None) -> int:
    global STATE
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    config = parse_args(argv)
    rng = random.Random(config.seed)
    users = load_seed_users(DEFAULT_USERS_PATH)
    resources_by_type = build_resources(rng)
    policies = build_policies()
    STATE = ValidationState(
        config=config,
        rng=rng,
        users=users,
        resources_by_type=resources_by_type,
        policies=policies,
    )

    try:
        STATE.smoke = run_smoke_test(config)
        STATE.revocation_enabled = bool(STATE.smoke.get("health", {}).get("revocation_enabled", False))
        STATE.current_epoch = str(STATE.smoke.get("health", {}).get("current_epoch", ""))
    except Exception as exc:  # noqa: BLE001
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        return 1

    abe = run_abe_functional_validation()
    insider = run_insider_validation()
    quantitative = run_quantitative_analysis()
    report = _build_report(abe, insider, quantitative)

    out_dir = config.out_dir
    json_path = write_json_report(out_dir, report)
    csv_path = write_csv_summary(out_dir, report)
    md_path = write_markdown_report(out_dir, report)

    report["artifacts"] = {"json": str(json_path), "csv": str(csv_path), "markdown": str(md_path)}
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print(json.dumps({"final_pass": report["final_pass"], "final_reason": report["final_reason"], "artifacts": report["artifacts"]}, ensure_ascii=False, indent=2))
    return 0 if report["final_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())