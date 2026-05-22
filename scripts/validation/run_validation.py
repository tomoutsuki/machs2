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
except Exception:  # pragma: no cover - optional DB observer path
    psycopg2 = None

try:
    import psycopg
except Exception:  # pragma: no cover - optional DB observer path
    psycopg = None

DB_BACKEND = "psycopg2" if psycopg2 else ("psycopg" if psycopg else None)

MODES = ["fabeo"]
SUPPORTED_RESOURCE_TYPES = ["Patient", "Observation", "Condition", "Encounter", "MedicationRequest"]
DEFAULT_USERS_PATH = Path(__file__).resolve().parents[2] / "resources" / "users_seed.yaml"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "output"
STAGE_ABE = "abe_functional"
STAGE_ABAC = "abac_insider"
STAGE_DB = "db_observer"


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
class ScenarioDefinition:
    name: str
    user_key: str
    policy_name: str
    resource_type: str
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


def build_abac_scenarios() -> List[ScenarioDefinition]:
    return [
        ScenarioDefinition(
            name="insider_role_insufficient",
            user_key="receptionist",
            policy_name="medications_doctor",
            resource_type="MedicationRequest",
            description="insider com papel insuficiente",
        ),
        ScenarioDefinition(
            name="insider_other_department",
            user_key="doctor_general_clinic",
            policy_name="clinical_cardiology",
            resource_type="Encounter",
            description="insider de outro departamento",
        ),
        ScenarioDefinition(
            name="insider_partial_privilege",
            user_key="medical_laboratory_scientist",
            policy_name="clinical_notes",
            resource_type="Condition",
            description="insider com privilegio parcial",
        ),
        ScenarioDefinition(
            name="receptionist_clinical_access",
            user_key="receptionist",
            policy_name="clinical_notes",
            resource_type="Condition",
            description="recepcionista tentando acessar dado clinico",
        ),
        ScenarioDefinition(
            name="doctor_without_context",
            user_key="doctor_general_clinic",
            policy_name="labs_shared",
            resource_type="Observation",
            description="medico sem contexto/departamento adequado",
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


def _log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{stamp}] {message}", flush=True)


class ProgressBar:
    def __init__(self, total: int, prefix: str, width: int = 30) -> None:
        self.total = max(total, 0)
        self.prefix = prefix
        self.width = width
        self.current = 0
        self._render(0)

    def update(self, step: int = 1) -> None:
        if self.total <= 0:
            return
        self.current = min(self.total, self.current + step)
        self._render(self.current)
        if self.current >= self.total:
            print("", flush=True)

    def _render(self, current: int) -> None:
        if self.total <= 0:
            return
        filled = int(self.width * current / self.total)
        bar = "=" * filled + "-" * (self.width - filled)
        percent = int(current / self.total * 100)
        print(f"\r{self.prefix} [{bar}] {current}/{self.total} ({percent}%)", end="", flush=True)


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
    expected_rows: List[Dict[str, Any]] = []
    observed_rows: List[Dict[str, Any]] = []
    raw_metrics: List[Dict[str, Any]] = []

    _log(f"ABE validation start: iterations={config.iterations}")
    bar = ProgressBar(config.iterations, "ABE functional")
    for i in range(config.iterations):
        attempt_id = "abe-{0:05d}".format(i + 1)
        attempt_start = time.perf_counter()
        mode = selected_modes[0] if len(selected_modes) == 1 else rng.choice(selected_modes)
        user = rng.choice(users)
        resource_type = rng.choice(SUPPORTED_RESOURCE_TYPES)
        resource = rng.choice(STATE.resources_by_type[resource_type])
        policy = _make_policy_choice(resource.resource_type, STATE.policies, rng)
        user_attrs_str = ";".join(user.attributes)

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
            bar.update(1)
            total_attempt_latency_ms = (time.perf_counter() - attempt_start) * 1000.0
            false_positive = bool((expected_allowed is False) and record.observed_allowed)
            false_negative = bool(expected_allowed and (not record.observed_allowed))
            expected_rows.append({
                "attempt_id": attempt_id,
                "validation_stage": STAGE_ABE,
                "scenario": STAGE_ABE,
                "username": user.username,
                "user_attributes": user_attrs_str,
                "resource_type": resource.resource_type,
                "entry_id": record.entry_id or "",
                "policy_expression": policy.expression,
                "expected_allowed": expected_allowed,
                "expected_reason": record.expected_reason,
            })
            observed_rows.append({
                "attempt_id": attempt_id,
                "validation_stage": STAGE_ABE,
                "scenario": STAGE_ABE,
                "username": user.username,
                "resource_type": resource.resource_type,
                "entry_id": record.entry_id or "",
                "policy_expression": policy.expression,
                "expected_allowed": expected_allowed,
                "observed_allowed": record.observed_allowed,
                "http_status": record.observed_status,
                "decrypt_success": record.observed_status == 200,
                "integrity_ok": record.integrity_ok,
                "original_sha256": record.original_sha256,
                "recovered_sha256": record.recovered_sha256,
                "false_positive": false_positive,
                "false_negative": false_negative,
                "latency_login_ms": record.login_time_ms,
                "latency_create_ms": record.create_time_ms,
                "latency_search_ms": record.search_time_ms,
                "latency_decrypt_ms": record.decrypt_time_ms,
                "total_attempt_latency_ms": total_attempt_latency_ms,
                "error_message": record.error,
            })
            raw_metrics.append({
                "attempt_id": attempt_id,
                "validation_stage": STAGE_ABE,
                "scenario": STAGE_ABE,
                "latency_login_ms": record.login_time_ms,
                "latency_create_ms": record.create_time_ms,
                "latency_search_ms": record.search_time_ms,
                "latency_decrypt_ms": record.decrypt_time_ms,
                "latency_db_check_ms": None,
                "total_attempt_latency_ms": total_attempt_latency_ms,
                "original_payload_bytes": record.request_payload_bytes,
                "encrypted_payload_bytes": None,
                "cipher_metadata_response_bytes": record.cipher_response_bytes,
                "decrypt_response_bytes": record.decrypt_response_bytes,
            })

    correct_rate = (correct_decryptions / total_expected_allowed * 100.0) if total_expected_allowed else 0.0
    denial_rate = (correct_denials / total_expected_denied * 100.0) if total_expected_denied else 0.0

    attempt_artifacts = write_attempt_tables(STATE.config.out_dir, STAGE_ABE, None, expected_rows, observed_rows)
    quant_artifacts = write_quantitative_csv(STATE.config.out_dir, STAGE_ABE, None, raw_metrics)

    _log("ABE validation completed")

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
        "integrity_ok_rate_pct": (integrity_ok_count / total_expected_allowed * 100.0) if total_expected_allowed else 0.0,
        "attempted_count": attempted_count,
        "unavailable_count": unavailable_count,
        "artifacts": {
            **attempt_artifacts,
            **quant_artifacts,
        },
    }


def run_single_insider_scenario(scenario: ScenarioDefinition, iterations: int) -> Dict[str, Any]:
    if STATE is None:
        raise RuntimeError("validation state not initialized")

    user = STATE.users.get(scenario.user_key)
    policy = next((item for item in STATE.policies if item.name == scenario.policy_name), None)
    resources = STATE.resources_by_type.get(scenario.resource_type, [])
    expected_rows: List[Dict[str, Any]] = []
    observed_rows: List[Dict[str, Any]] = []
    raw_metrics: List[Dict[str, Any]] = []

    if not user or not user.available or not policy or not resources:
        attempt_artifacts = write_attempt_tables(STATE.config.out_dir, STAGE_ABAC, scenario.name, expected_rows, observed_rows)
        quant_artifacts = write_quantitative_csv(STATE.config.out_dir, STAGE_ABAC, scenario.name, raw_metrics)
        return {
            "scenario": scenario.name,
            "description": scenario.description,
            "total_attempts": 0,
            "n_bloqueio": 0,
            "n_exposicao": 0,
            "rho_bloqueio": 0.0,
            "rho_exposicao": 0.0,
            "false_positives": 0,
            "false_negatives": 0,
            "validation_passed": False,
            "error": "scenario inputs unavailable",
            "artifacts": {**attempt_artifacts, **quant_artifacts},
        }

    n_bloqueio = 0
    n_exposicao = 0
    false_positives = 0
    false_negatives = 0
    unexpected_errors = 0

    _log(f"ABAC scenario start: {scenario.name} iterations={iterations}")
    bar = ProgressBar(iterations, f"ABAC {scenario.name}")
    for i in range(iterations):
        attempt_id = "{0}-{1:05d}".format(scenario.name, i + 1)
        attempt_start = time.perf_counter()
        resource = STATE.rng.choice(resources)
        expected_allowed = evaluate_expected_access(user.attributes, policy.expression)
        record_error: Optional[str] = None
        observed_allowed = False
        observed_status = 0
        login_ms = None
        create_ms = None
        search_ms = None
        decrypt_ms = None
        entry_id = ""
        integrity_ok = None
        original_sha256 = None
        recovered_sha256 = None
        decrypt_success = False

        try:
            session, login_ms = _login_user(user)
            create_t0 = time.perf_counter()
            create_resp = create_entry(session, resource.resource, policy.expression, "fabeo")
            create_ms = (time.perf_counter() - create_t0) * 1000.0
            entry_id = create_resp.json()["entry_id"]

            decrypt_t0 = time.perf_counter()
            decrypt_resp = decrypt_package(session, entry_id, "fabeo")
            decrypt_ms = (time.perf_counter() - decrypt_t0) * 1000.0
            observed_status = decrypt_resp.status_code
            if decrypt_resp.status_code == 403:
                observed_allowed = False
            elif decrypt_resp.ok:
                observed_allowed = True
                decrypt_success = True
                payload = decrypt_resp.json()
                plaintext = _decrypt_observed_plaintext("fabeo", payload)
                original_sha256 = canonical_json_hash(resource.resource)
                recovered_sha256 = canonical_json_hash(json.loads(plaintext))
                integrity_ok = original_sha256 == recovered_sha256
            else:
                record_error = decrypt_resp.text[:500]
                unexpected_errors += 1

        except requests.HTTPError as exc:
            record_error = f"HTTPError: {exc.response.status_code} {exc.response.text[:500]}"
            unexpected_errors += 1
        except Exception as exc:  # noqa: BLE001
            record_error = str(exc)
            unexpected_errors += 1

        if expected_allowed:
            if observed_allowed:
                pass
            else:
                false_negatives += 1
        else:
            if observed_allowed:
                n_exposicao += 1
                false_positives += 1
            elif observed_status == 403:
                n_bloqueio += 1

        total_attempt_latency_ms = (time.perf_counter() - attempt_start) * 1000.0
        expected_rows.append({
            "attempt_id": attempt_id,
            "validation_stage": STAGE_ABAC,
            "scenario": scenario.name,
            "username": user.username,
            "user_attributes": ";".join(user.attributes),
            "resource_type": resource.resource_type,
            "entry_id": entry_id,
            "policy_expression": policy.expression,
            "expected_allowed": expected_allowed,
            "expected_reason": "user attributes satisfy policy" if expected_allowed else "user attributes do not satisfy policy",
        })
        observed_rows.append({
            "attempt_id": attempt_id,
            "validation_stage": STAGE_ABAC,
            "scenario": scenario.name,
            "username": user.username,
            "resource_type": resource.resource_type,
            "entry_id": entry_id,
            "policy_expression": policy.expression,
            "expected_allowed": expected_allowed,
            "observed_allowed": observed_allowed,
            "http_status": observed_status,
            "decrypt_success": decrypt_success,
            "integrity_ok": integrity_ok,
            "original_sha256": original_sha256,
            "recovered_sha256": recovered_sha256,
            "false_positive": (expected_allowed is False) and observed_allowed,
            "false_negative": expected_allowed and (not observed_allowed),
            "latency_login_ms": login_ms,
            "latency_create_ms": create_ms,
            "latency_search_ms": search_ms,
            "latency_decrypt_ms": decrypt_ms,
            "total_attempt_latency_ms": total_attempt_latency_ms,
            "error_message": record_error,
        })
        raw_metrics.append({
            "attempt_id": attempt_id,
            "validation_stage": STAGE_ABAC,
            "scenario": scenario.name,
            "latency_login_ms": login_ms,
            "latency_create_ms": create_ms,
            "latency_search_ms": search_ms,
            "latency_decrypt_ms": decrypt_ms,
            "latency_db_check_ms": None,
            "total_attempt_latency_ms": total_attempt_latency_ms,
            "original_payload_bytes": len(json.dumps(resource.resource, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
            "encrypted_payload_bytes": None,
            "cipher_metadata_response_bytes": None,
            "decrypt_response_bytes": None,
        })
        bar.update(1)

    k_tentativa = len(expected_rows)
    rho_bloqueio = (n_bloqueio / k_tentativa * 100.0) if k_tentativa else 0.0
    rho_exposicao = (n_exposicao / k_tentativa * 100.0) if k_tentativa else 0.0
    attempt_artifacts = write_attempt_tables(STATE.config.out_dir, STAGE_ABAC, scenario.name, expected_rows, observed_rows)
    quant_artifacts = write_quantitative_csv(STATE.config.out_dir, STAGE_ABAC, scenario.name, raw_metrics)
    validation_passed = (false_positives == 0 and false_negatives == 0 and n_exposicao == 0 and unexpected_errors == 0)
    _log(f"ABAC scenario completed: {scenario.name}")
    return {
        "scenario": scenario.name,
        "description": scenario.description,
        "total_attempts": k_tentativa,
        "n_bloqueio": n_bloqueio,
        "n_exposicao": n_exposicao,
        "rho_bloqueio": rho_bloqueio,
        "rho_exposicao": rho_exposicao,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "validation_passed": validation_passed,
        "unexpected_errors": unexpected_errors,
        "artifacts": {**attempt_artifacts, **quant_artifacts},
    }


def run_abac_insider_validation() -> Dict[str, Any]:
    if STATE is None:
        raise RuntimeError("validation state not initialized")

    _log("ABAC insider validation start")
    scenarios = build_abac_scenarios()
    results: Dict[str, Any] = {}
    for scenario in scenarios:
        results[scenario.name] = run_single_insider_scenario(scenario, STATE.config.iterations)
    _log("ABAC insider validation completed")
    return {
        "iterations": STATE.config.iterations,
        "scenarios": results,
    }


def _payload_to_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8", errors="ignore")
    return str(value).encode("utf-8", errors="ignore")


def detect_plaintext_json_in_encrypted_payload(payload_bytes: bytes) -> Dict[str, Any]:
    text = payload_bytes.decode("utf-8", errors="ignore").lstrip("\x00").lstrip()
    looks_like_json = text.startswith("{") or text.startswith("[")
    detected_markers = []
    fhir_markers = [
        "\"resourceType\"",
        "\"Patient\"",
        "\"Observation\"",
        "\"Condition\"",
        "\"Encounter\"",
        "\"MedicationRequest\"",
        "\"birthDate\"",
        "\"identifier\"",
        "\"name\"",
    ]
    for marker in fhir_markers:
        if marker in text:
            detected_markers.append(marker.strip("\""))
    contains_fhir_markers = bool(detected_markers)
    json_parse_success = False
    if looks_like_json:
        try:
            json.loads(text)
            json_parse_success = True
        except Exception:
            json_parse_success = False
    plaintext_detected = looks_like_json and (json_parse_success or contains_fhir_markers)
    return {
        "looks_like_json": looks_like_json,
        "json_parse_success": json_parse_success,
        "contains_fhir_markers": contains_fhir_markers,
        "plaintext_detected": plaintext_detected,
        "detected_markers": ",".join(detected_markers),
    }


def _resolve_entries_tables(cur) -> List[str]:
    cur.execute("SELECT to_regclass('fabeo.entries')")
    row = cur.fetchone()
    if row and row[0]:
        return ["fabeo.entries"]
    cur.execute(
        "SELECT table_schema, table_name FROM information_schema.tables WHERE table_name = 'entries' AND table_schema NOT IN ('pg_catalog', 'information_schema')"
    )
    rows = cur.fetchall()
    return [f"{r[0]}.{r[1]}" for r in rows]


def run_db_observer_validation() -> Dict[str, Any]:
    if STATE is None:
        raise RuntimeError("validation state not initialized")
    _log(f"DB observer validation start: iterations={STATE.config.iterations}")
    if DB_BACKEND is None:
        return {
            "total_rows_checked": 0,
            "plaintext_rows_detected": 0,
            "plaintext_detection_rate": 0.0,
            "validation_passed": False,
            "error": "database driver not available",
            "artifacts": {},
        }
    if not STATE.config.db_dsn:
        return {
            "total_rows_checked": 0,
            "plaintext_rows_detected": 0,
            "plaintext_detection_rate": 0.0,
            "validation_passed": False,
            "error": "db_dsn not provided",
            "artifacts": {},
        }

    raw_metrics: List[Dict[str, Any]] = []
    rows_out: List[Dict[str, Any]] = []
    created_entries: List[Tuple[str, str]] = []
    attempt_context: Dict[str, Dict[str, Any]] = {}
    error_count = 0

    create_bar = ProgressBar(STATE.config.iterations, "DB observer create")
    for i in range(STATE.config.iterations):
        attempt_id = "db_observer-{0:05d}".format(i + 1)
        attempt_start = time.perf_counter()
        resource = STATE.rng.choice(STATE.resources_by_type["Patient"])
        entry_id = ""
        login_ms = None
        create_ms = None
        db_check_ms = None
        payload_bytes_len = None

        try:
            session, login_ms = _login_user(STATE.users["doctor_general_clinic"])
            create_t0 = time.perf_counter()
            policy = next(item for item in STATE.policies if item.name == "patient_demographics")
            create_resp = create_entry(session, resource.resource, policy.expression, "fabeo")
            create_ms = (time.perf_counter() - create_t0) * 1000.0
            entry_id = create_resp.json()["entry_id"]
            created_entries.append((entry_id, resource.resource_type))
            attempt_context[entry_id] = {
                "attempt_id": attempt_id,
                "attempt_start": attempt_start,
                "login_ms": login_ms,
                "create_ms": create_ms,
                "original_payload_bytes": len(json.dumps(resource.resource, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
            }
        except Exception as exc:  # noqa: BLE001
            error_count += 1
            raw_metrics.append({
                "attempt_id": attempt_id,
                "validation_stage": STAGE_DB,
                "scenario": STAGE_DB,
                "latency_login_ms": login_ms,
                "latency_create_ms": create_ms,
                "latency_search_ms": None,
                "latency_decrypt_ms": None,
                "latency_db_check_ms": None,
                "total_attempt_latency_ms": (time.perf_counter() - attempt_start) * 1000.0,
                "original_payload_bytes": len(json.dumps(resource.resource, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
                "encrypted_payload_bytes": None,
                "cipher_metadata_response_bytes": None,
                "decrypt_response_bytes": None,
            })
            rows_out.append({
                "table_name": "",
                "entry_id": entry_id,
                "resource_type": resource.resource_type,
                "encrypted_payload_size_bytes": None,
                "looks_like_json": False,
                "json_parse_success": False,
                "contains_fhir_markers": False,
                "plaintext_detected": False,
                "detected_markers": "",
                "check_latency_ms": None,
                "error_message": str(exc),
            })
        finally:
            create_bar.update(1)

    try:
        if DB_BACKEND == "psycopg2":
            conn = psycopg2.connect(STATE.config.db_dsn)
        else:
            conn = psycopg.connect(STATE.config.db_dsn)
    except Exception as exc:  # noqa: BLE001
        return {
            "total_rows_checked": 0,
            "plaintext_rows_detected": 0,
            "plaintext_detection_rate": 0.0,
            "validation_passed": False,
            "error": f"db connection failed: {exc}",
            "artifacts": {},
        }
    try:
        with conn.cursor() as cur:
            tables = _resolve_entries_tables(cur)
        if not tables:
            error_count += 1
            validation_passed = False
            artifacts = {}
            return {
                "total_rows_checked": 0,
                "plaintext_rows_detected": 0,
                "plaintext_detection_rate": 0.0,
                "validation_passed": validation_passed,
                "error": "entries table not found",
                "artifacts": artifacts,
            }
        table_name = tables[0]
        check_bar = ProgressBar(len(created_entries), "DB observer check")
        with conn.cursor() as cur:
            for entry_id, resource_type in created_entries:
                context = attempt_context.get(entry_id, {})
                check_t0 = time.perf_counter()
                cur.execute(
                    f"SELECT entry_id, resource_type, encrypted_payload FROM {table_name} WHERE entry_id = %s",
                    (entry_id,),
                )
                row = cur.fetchone()
                db_check_ms = (time.perf_counter() - check_t0) * 1000.0
                if not row:
                    error_count += 1
                    rows_out.append({
                        "table_name": table_name,
                        "entry_id": entry_id,
                        "resource_type": resource_type,
                        "encrypted_payload_size_bytes": None,
                        "looks_like_json": False,
                        "json_parse_success": False,
                        "contains_fhir_markers": False,
                        "plaintext_detected": False,
                        "detected_markers": "",
                        "check_latency_ms": db_check_ms,
                        "error_message": "entry not found in table",
                    })
                    raw_metrics.append({
                        "attempt_id": context.get("attempt_id", "db_observer-missing"),
                        "validation_stage": STAGE_DB,
                        "scenario": STAGE_DB,
                        "latency_login_ms": context.get("login_ms"),
                        "latency_create_ms": context.get("create_ms"),
                        "latency_search_ms": None,
                        "latency_decrypt_ms": None,
                        "latency_db_check_ms": db_check_ms,
                        "total_attempt_latency_ms": (time.perf_counter() - context.get("attempt_start", check_t0)) * 1000.0,
                        "original_payload_bytes": context.get("original_payload_bytes"),
                        "encrypted_payload_bytes": None,
                        "cipher_metadata_response_bytes": None,
                        "decrypt_response_bytes": None,
                    })
                    check_bar.update(1)
                    continue
                row_entry_id = row[0]
                row_resource_type = row[1]
                encrypted_payload = row[2]
                payload_bytes = _payload_to_bytes(encrypted_payload)
                payload_bytes_len = len(payload_bytes)
                detect = detect_plaintext_json_in_encrypted_payload(payload_bytes)
                rows_out.append({
                    "table_name": table_name,
                    "entry_id": str(row_entry_id),
                    "resource_type": row_resource_type,
                    "encrypted_payload_size_bytes": payload_bytes_len,
                    "looks_like_json": detect["looks_like_json"],
                    "json_parse_success": detect["json_parse_success"],
                    "contains_fhir_markers": detect["contains_fhir_markers"],
                    "plaintext_detected": detect["plaintext_detected"],
                    "detected_markers": detect["detected_markers"],
                    "check_latency_ms": db_check_ms,
                    "error_message": "",
                })
                raw_metrics.append({
                    "attempt_id": context.get("attempt_id", "db_observer-{0}".format(entry_id)),
                    "validation_stage": STAGE_DB,
                    "scenario": STAGE_DB,
                    "latency_login_ms": context.get("login_ms"),
                    "latency_create_ms": context.get("create_ms"),
                    "latency_search_ms": None,
                    "latency_decrypt_ms": None,
                    "latency_db_check_ms": db_check_ms,
                    "total_attempt_latency_ms": (time.perf_counter() - context.get("attempt_start", check_t0)) * 1000.0,
                    "original_payload_bytes": context.get("original_payload_bytes"),
                    "encrypted_payload_bytes": payload_bytes_len,
                    "cipher_metadata_response_bytes": None,
                    "decrypt_response_bytes": None,
                })
                check_bar.update(1)
    finally:
        conn.close()

    total_rows_checked = len(rows_out)
    plaintext_rows_detected = sum(1 for row in rows_out if row.get("plaintext_detected"))
    detection_rate = (plaintext_rows_detected / total_rows_checked * 100.0) if total_rows_checked else 0.0
    validation_passed = (total_rows_checked > 0 and plaintext_rows_detected == 0 and error_count == 0)

    base_dir = STATE.config.out_dir / "db_observer"
    rows_path = base_dir / "db_observer_rows.csv"
    summary_path = base_dir / "db_observer_summary.csv"
    row_fields = [
        "table_name",
        "entry_id",
        "resource_type",
        "encrypted_payload_size_bytes",
        "looks_like_json",
        "json_parse_success",
        "contains_fhir_markers",
        "plaintext_detected",
        "detected_markers",
        "check_latency_ms",
        "error_message",
    ]
    _write_csv(rows_path, row_fields, rows_out)
    summary_rows = [{
        "total_rows_checked": total_rows_checked,
        "plaintext_rows_detected": plaintext_rows_detected,
        "plaintext_detection_rate": detection_rate,
        "validation_passed": validation_passed,
        "errors": error_count,
    }]
    _write_csv(summary_path, ["total_rows_checked", "plaintext_rows_detected", "plaintext_detection_rate", "validation_passed", "errors"], summary_rows)

    quant_artifacts = write_quantitative_csv(STATE.config.out_dir, STAGE_DB, None, raw_metrics)
    _log("DB observer validation completed")
    return {
        "total_rows_checked": total_rows_checked,
        "plaintext_rows_detected": plaintext_rows_detected,
        "plaintext_detection_rate": detection_rate,
        "validation_passed": validation_passed,
        "artifacts": {
            "rows_csv": str(rows_path),
            "summary_csv": str(summary_path),
            **quant_artifacts,
        },
    }


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


def _safe_csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            safe_row = {key: _safe_csv_value(row.get(key)) for key in fieldnames}
            writer.writerow(safe_row)
    return path


def calculate_quantitative_summary(raw_metrics: List[Dict[str, Any]], metric_fields: List[str]) -> List[Dict[str, Any]]:
    summary: List[Dict[str, Any]] = []
    for metric in metric_fields:
        values = [float(item[metric]) for item in raw_metrics if item.get(metric) is not None]
        if not values:
            summary.append({"metric": metric, "count": 0, "mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0, "stdev": 0.0})
            continue
        stats = _stats(values)
        summary.append({
            "metric": metric,
            "count": len(values),
            "mean": stats["mean"],
            "median": stats["median"],
            "min": stats["minimum"],
            "max": stats["maximum"],
            "stdev": stats["stdev"],
        })
    return summary


def write_quantitative_csv(out_dir: Path, stage: str, scenario: Optional[str], raw_metrics: List[Dict[str, Any]]) -> Dict[str, str]:
    metric_fields = [
        "latency_login_ms",
        "latency_create_ms",
        "latency_search_ms",
        "latency_decrypt_ms",
        "latency_db_check_ms",
        "total_attempt_latency_ms",
        "original_payload_bytes",
        "encrypted_payload_bytes",
        "cipher_metadata_response_bytes",
        "decrypt_response_bytes",
    ]
    base_dir = out_dir / "quantitative" / stage
    if scenario:
        base_dir = base_dir / scenario
    raw_path = base_dir / "raw_metrics.csv"
    summary_path = base_dir / "summary_metrics.csv"

    raw_fieldnames = ["attempt_id", "validation_stage", "scenario"] + metric_fields
    _write_csv(raw_path, raw_fieldnames, raw_metrics)

    summary_rows = calculate_quantitative_summary(raw_metrics, metric_fields)
    summary_fieldnames = ["metric", "count", "mean", "median", "min", "max", "stdev"]
    _write_csv(summary_path, summary_fieldnames, summary_rows)
    return {"raw_csv": str(raw_path), "summary_csv": str(summary_path)}


def write_attempt_tables(out_dir: Path, stage: str, scenario: Optional[str], expected_rows: List[Dict[str, Any]], observed_rows: List[Dict[str, Any]]) -> Dict[str, str]:
    base_dir = out_dir / "attempt_tables" / stage
    if scenario:
        base_dir = base_dir / scenario
    expected_path = base_dir / "expected.csv"
    observed_path = base_dir / "observed.csv"

    expected_fields = [
        "attempt_id",
        "validation_stage",
        "scenario",
        "username",
        "user_attributes",
        "resource_type",
        "entry_id",
        "policy_expression",
        "expected_allowed",
        "expected_reason",
    ]
    observed_fields = [
        "attempt_id",
        "validation_stage",
        "scenario",
        "username",
        "resource_type",
        "entry_id",
        "policy_expression",
        "expected_allowed",
        "observed_allowed",
        "http_status",
        "decrypt_success",
        "integrity_ok",
        "original_sha256",
        "recovered_sha256",
        "false_positive",
        "false_negative",
        "latency_login_ms",
        "latency_create_ms",
        "latency_search_ms",
        "latency_decrypt_ms",
        "total_attempt_latency_ms",
        "error_message",
    ]
    _write_csv(expected_path, expected_fields, expected_rows)
    _write_csv(observed_path, observed_fields, observed_rows)
    return {"expected_csv": str(expected_path), "observed_csv": str(observed_path)}


def _build_overall_result(abe: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "total_attempts": abe.get("attempted_count", 0),
        "expected_allowed": abe.get("expected_allowed", 0),
        "expected_denied": abe.get("expected_denied", 0),
        "correct_decryptions": abe.get("correct_decryptions", 0),
        "correct_denials": abe.get("correct_denials", 0),
        "false_positives": abe.get("false_positives", 0),
        "false_negatives": abe.get("false_negatives", 0),
        "decryption_correct_rate_pct": abe.get("decryption_correct_rate_pct", 0.0),
        "denial_correct_rate_pct": abe.get("denial_correct_rate_pct", 0.0),
        "integrity_ok_count": abe.get("integrity_ok_count", 0),
        "integrity_ok_rate_pct": abe.get("integrity_ok_rate_pct", 0.0),
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

    for scenario, data in report["abac_insider"]["scenarios"].items():
        for key in ["total_attempts", "n_bloqueio", "n_exposicao", "rho_bloqueio", "rho_exposicao", "false_positives", "false_negatives"]:
            rows.append({
                "section": "abac_insider",
                "mode": "",
                "scenario": scenario,
                "operation": "",
                "statistic": key,
                "value": data.get(key, 0.0),
                "unit": "%" if key.startswith("rho_") else "count",
            })

    db = report["db_observer"]
    for key in ["total_rows_checked", "plaintext_rows_detected", "plaintext_detection_rate", "validation_passed"]:
        rows.append({
            "section": "db_observer",
            "mode": "",
            "scenario": "",
            "operation": "",
            "statistic": key,
            "value": db.get(key, 0.0),
            "unit": "%" if key.endswith("_rate") else "count",
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

    abe = report["abe_functional"]
    config_rows = [
        ["Base URL", STATE.config.base_url],
        ["Modo", STATE.config.mode],
        ["Iterações por validação", str(STATE.config.iterations)],
        ["Seed", str(STATE.config.seed)],
        ["Gerado em", STATE.generated_at],
        ["Revogação experimental", "habilitada" if STATE.revocation_enabled else "desabilitada"],
        ["Epoch atual", STATE.current_epoch],
        ["Usuários testados", str(len([u for u in STATE.users.values() if u.available]))],
        ["Total tentativas ABE", str(abe.get("attempted_count", 0))],
        ["Tentativas por cenário ABAC", str(report["abac_insider"].get("iterations", 0))],
    ]

    abe_rows = [[
        str(abe.get("attempted_count", 0)),
        str(abe.get("expected_allowed", 0)),
        str(abe.get("expected_denied", 0)),
        str(abe.get("correct_decryptions", 0)),
        str(abe.get("correct_denials", 0)),
        str(abe.get("false_positives", 0)),
        str(abe.get("false_negatives", 0)),
        f"{abe.get('decryption_correct_rate_pct', 0.0):.2f}%",
        f"{abe.get('denial_correct_rate_pct', 0.0):.2f}%",
        str(abe.get("integrity_ok_count", 0)),
        f"{abe.get('integrity_ok_rate_pct', 0.0):.2f}%",
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
    for scenario, data in report["abac_insider"]["scenarios"].items():
        insider_rows.append([
            scenario,
            str(data.get("total_attempts", 0)),
            str(data.get("n_bloqueio", 0)),
            str(data.get("n_exposicao", 0)),
            f"{data.get('rho_bloqueio', 0.0):.2f}%",
            f"{data.get('rho_exposicao', 0.0):.2f}%",
            str(data.get("false_positives", 0)),
            str(data.get("false_negatives", 0)),
            "PASS" if data.get("validation_passed") else "FAIL",
            data.get("artifacts", {}).get("expected_csv", ""),
            data.get("artifacts", {}).get("observed_csv", ""),
        ])

    db = report["db_observer"]
    quantitative_rows = [
        [STAGE_ABE, "-", abe.get("artifacts", {}).get("summary_csv", "")],
    ]
    for scenario, data in report["abac_insider"]["scenarios"].items():
        quantitative_rows.append([
            STAGE_ABAC,
            scenario,
            data.get("artifacts", {}).get("summary_csv", ""),
        ])
    quantitative_rows.append([STAGE_DB, "-", db.get("artifacts", {}).get("summary_csv", "")])

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
        "Arquivos:",
        f"- expected.csv: {abe.get('artifacts', {}).get('expected_csv', '')}",
        f"- observed.csv: {abe.get('artifacts', {}).get('observed_csv', '')}",
        f"- quantitative summary: {abe.get('artifacts', {}).get('summary_csv', '')}",
        "",
        "## 3. Avaliação ABAC contra Insider Attacks",
        _markdown_table([
            "Cenário",
            "Total tentativas",
            "n_bloqueio",
            "n_exposicao",
            "rho_bloqueio",
            "rho_exposicao",
            "false_positive_count",
            "false_negative_count",
            "validation_passed",
            "expected.csv",
            "observed.csv",
        ], insider_rows),
        "",
        "## 4. Validação de Observador de Banco de Dados",
        _markdown_table([
            "total_rows_checked",
            "plaintext_rows_detected",
            "plaintext_detection_rate",
            "validation_passed",
            "db_observer_rows.csv",
            "db_observer_summary.csv",
        ], [[
            str(db.get("total_rows_checked", 0)),
            str(db.get("plaintext_rows_detected", 0)),
            f"{db.get('plaintext_detection_rate', 0.0):.2f}%",
            "PASS" if db.get("validation_passed") else "FAIL",
            db.get("artifacts", {}).get("rows_csv", ""),
            db.get("artifacts", {}).get("summary_csv", ""),
        ]]),
        "",
        "## 5. Análise Quantitativa Geral",
        _markdown_table(["Etapa", "Cenário", "summary_metrics.csv"], quantitative_rows),
        "",
        "## 6. Resultado Final",
        f"{final_status}: {reason}",
    ]
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(content).strip() + "\n")
    return path


def _finalize_result(abe: Dict[str, Any], abac: Dict[str, Any], db_observer: Dict[str, Any]) -> Tuple[bool, str]:
    if abe.get("false_positives", 0) > 0:
        return False, "falha crítica: falsos positivos detectados na ABE"
    if abe.get("false_negatives", 0) > 0:
        return False, "falha crítica: falsos negativos na ABE"
    if abe.get("integrity_ok_count", 0) != abe.get("expected_allowed", 0):
        return False, "falha crítica: integridade SHA-256 divergente"

    for scenario, data in abac.get("scenarios", {}).items():
        if data.get("n_exposicao", 0) > 0 or data.get("rho_exposicao", 0.0) > 0:
            return False, f"falha crítica: exposição indevida em cenário insider {scenario}"
        if not data.get("validation_passed", False):
            return False, f"falha crítica: cenário insider {scenario} com falha"

    if not db_observer.get("validation_passed", False):
        return False, "falha crítica: observador de banco detectou texto claro ou não executou"

    return True, "critério de segurança atendido"


def _build_report(abe: Dict[str, Any], abac: Dict[str, Any], db_observer: Dict[str, Any]) -> Dict[str, Any]:
    overall = _build_overall_result(abe)
    final_pass, final_reason = _finalize_result(abe, abac, db_observer)
    assert STATE is not None
    config_dict = dataclasses.asdict(STATE.config)
    config_dict["out_dir"] = str(config_dict["out_dir"])
    config_dict["db_dsn"] = None
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
        "abe_functional": abe,
        "abac_insider": abac,
        "db_observer": db_observer,
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
    _log(f"Validation start: base_url={config.base_url} iterations={config.iterations} mode={config.mode}")
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
        _log("Smoke test start")
        STATE.smoke = run_smoke_test(config)
        STATE.revocation_enabled = bool(STATE.smoke.get("health", {}).get("revocation_enabled", False))
        STATE.current_epoch = str(STATE.smoke.get("health", {}).get("current_epoch", ""))
        _log("Smoke test ok")
    except Exception as exc:  # noqa: BLE001
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        return 1

    abe = run_abe_functional_validation()
    abac = run_abac_insider_validation()
    db_observer = run_db_observer_validation()
    report = _build_report(abe, abac, db_observer)

    out_dir = config.out_dir
    json_path = write_json_report(out_dir, report)
    csv_path = write_csv_summary(out_dir, report)
    md_path = write_markdown_report(out_dir, report)

    report["artifacts"] = {"json": str(json_path), "csv": str(csv_path), "markdown": str(md_path)}
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print(json.dumps({"final_pass": report["final_pass"], "final_reason": report["final_reason"], "artifacts": report["artifacts"]}, ensure_ascii=False, indent=2))
    _log(f"Validation completed: status={'PASS' if report['final_pass'] else 'FAIL'}")
    return 0 if report["final_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())