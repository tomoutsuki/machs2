import json
from pathlib import Path
from typing import Any, Dict, List

import psycopg2
import requests

from app.core.settings import settings

BASE_URL = "http://127.0.0.1:{0}".format(settings.api_port)

USERS = {
    "doctor_general_clinic": "DocGeral2026!",
    "doctor_cardiologist": "Cardio2026!",
    "receptionist_frontdesk": "Recep2026!",
    "nurse_clinic": "Nurse2026!",
}

ITERATIONS: List[Dict[str, Any]] = [
    {
        "policy": "role.doctor AND department.clinic",
        "authorized_user": "doctor_general_clinic",
        "unauthorized_user": "receptionist_frontdesk",
        "resource": {
            "resourceType": "Patient",
            "id": "cpabe-iteration-1",
            "name": [{"family": "IterationOne", "given": ["Alice"]}],
            "identifier": [{"system": "https://saude.gov.br/fhir/sid/cpf", "value": "11111111111"}],
            "birthDate": "1990-01-01",
        },
    },
    {
        "policy": "role.doctor AND specialty.cardiology",
        "authorized_user": "doctor_cardiologist",
        "unauthorized_user": "doctor_general_clinic",
        "resource": {
            "resourceType": "Observation",
            "id": "cpabe-iteration-2",
            "status": "final",
            "code": {"text": "Heart rate"},
            "subject": {"display": "Patient Iteration Two"},
            "valueString": "72 bpm",
        },
    },
    {
        "policy": "role.receptionist AND clearance.demographics",
        "authorized_user": "receptionist_frontdesk",
        "unauthorized_user": "nurse_clinic",
        "resource": {
            "resourceType": "Patient",
            "id": "cpabe-iteration-3",
            "name": [{"family": "IterationThree", "given": ["Carla"]}],
            "identifier": [{"system": "https://saude.gov.br/fhir/sid/cpf", "value": "33333333333"}],
            "birthDate": "1985-03-03",
        },
    },
    {
        "policy": "role.nurse AND department.clinic",
        "authorized_user": "nurse_clinic",
        "unauthorized_user": "receptionist_frontdesk",
        "resource": {
            "resourceType": "Observation",
            "id": "cpabe-iteration-4",
            "status": "final",
            "code": {"text": "Clinic triage note"},
            "subject": {"display": "Patient Iteration Four"},
            "valueString": "BP 120/80",
        },
    },
    {
        "policy": "role.doctor AND clearance.sensitive",
        "authorized_user": "doctor_cardiologist",
        "unauthorized_user": "receptionist_frontdesk",
        "resource": {
            "resourceType": "Patient",
            "id": "cpabe-iteration-5",
            "name": [{"family": "IterationFive", "given": ["Eva"]}],
            "identifier": [{"system": "https://saude.gov.br/fhir/sid/cpf", "value": "55555555555"}],
            "birthDate": "1979-05-05",
        },
    },
]


def _normalize_resource(value: Any) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _db_connection():
    return psycopg2.connect(settings.database_dsn)


def _reset_state() -> None:
    with _db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM fabeo.entries")
            cur.execute("DELETE FROM public.session_usk")
        conn.commit()


def _load_row(entry_id: str) -> Dict[str, Any]:
    with _db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT encrypted_payload, iv, auth_tag, wrapped_key, wrapped_key_meta::text, mode_meta::text
                FROM fabeo.entries
                WHERE entry_id = %s
                """,
                (entry_id,),
            )
            row = cur.fetchone()
    if row is None:
        raise RuntimeError("entry missing from database")
    return {
        "encrypted_payload": row[0],
        "iv": row[1],
        "auth_tag": row[2],
        "wrapped_key": row[3],
        "wrapped_key_meta": row[4] or "",
        "mode_meta": row[5] or "",
    }


def _login(username: str) -> requests.Session:
    session = requests.Session()
    response = session.post(
        BASE_URL + "/auth/login",
        json={"username": username, "password": USERS[username]},
        timeout=15,
    )
    response.raise_for_status()
    return session


def _create_entry(session: requests.Session, resource: Dict[str, Any], policy: str) -> str:
    response = session.post(
        BASE_URL + "/entries",
        json={"resource": resource, "policy_expression": policy},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["entry_id"]


def _decrypt(session: requests.Session, entry_id: str) -> requests.Response:
    return session.post(BASE_URL + "/entries/{0}/decrypt-package".format(entry_id), timeout=20)


def _plaintext_not_in_db(entry_id: str, resource: Dict[str, Any]) -> bool:
    original = json.dumps(resource, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    row = _load_row(entry_id)
    blobs = [
        bytes(row["encrypted_payload"]),
        bytes(row["iv"]),
        bytes(row["auth_tag"]),
        bytes(row["wrapped_key"]),
        row["wrapped_key_meta"].encode("utf-8"),
        row["mode_meta"].encode("utf-8"),
    ]
    return all(original not in blob for blob in blobs)


def _cpabe_only_check(unauthorized_response: requests.Response) -> bool:
    detail = unauthorized_response.json().get("detail", "")
    entries_source = (
        Path(__file__).resolve().parents[1] / "routers" / "entries.py"
    ).read_text(encoding="utf-8")
    return (
        unauthorized_response.status_code == 403
        and "policy mismatch" not in detail.lower()
        and "evaluate_policy(" not in entries_source
        and "normalize_policy_expression(" not in entries_source
    )


def main() -> int:
    all_passed = True
    for index, item in enumerate(ITERATIONS, start=1):
        _reset_state()

        authorized_session = _login(item["authorized_user"])
        entry_id = _create_entry(authorized_session, item["resource"], item["policy"])

        authorized_response = _decrypt(authorized_session, entry_id)
        authorized_payload = authorized_response.json()
        authorized_decrypt = (
            authorized_response.status_code == 200
            and _normalize_resource(authorized_payload["result"]["resource_json"])
            == _normalize_resource(item["resource"])
            and authorized_payload["result"]["flow"] == "cp_abe_fabeo_decrypt"
        )

        unauthorized_session = _login(item["unauthorized_user"])
        unauthorized_response = _decrypt(unauthorized_session, entry_id)
        unauthorized_decrypt = unauthorized_response.status_code == 403

        plaintext_not_in_db = _plaintext_not_in_db(entry_id, item["resource"])
        cpabe_only = _cpabe_only_check(unauthorized_response)

        iteration_pass = authorized_decrypt and unauthorized_decrypt and plaintext_not_in_db and cpabe_only
        all_passed = all_passed and iteration_pass

        print(
            "ITERATION {0}: authorized_decrypt={1} unauthorized_decrypt={2} plaintext_not_in_db={3} cpabe_only={4}".format(
                index,
                "PASS" if authorized_decrypt else "FAIL",
                "PASS" if unauthorized_decrypt else "FAIL",
                "PASS" if plaintext_not_in_db else "FAIL",
                "PASS" if cpabe_only else "FAIL",
            )
        )

    print("FINAL RESULT: {0}".format("PASS" if all_passed else "FAIL"))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
