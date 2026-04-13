import json
import time
from typing import Optional

import requests

BASE_URL = "http://localhost:8000"


def login(username: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(BASE_URL + "/auth/login", json={"username": username, "password": password}, timeout=10)
    r.raise_for_status()
    return s


def create_patient(session: requests.Session, mode: str) -> str:
    payload = {
        "mode": mode,
        "resource": {
            "resourceType": "Patient",
            "id": "test-insider-patient",
            "name": [{"family": "Moraes", "given": ["Felipe"]}],
            "identifier": [{"system": "https://saude.gov.br/fhir/sid/cpf", "value": "11122233344"}],
            "birthDate": "1992-08-09"
        },
        "policy_expression": "role.doctor AND clearance.demographics AND epoch.2026"
    }
    r = session.post(BASE_URL + "/entries", json=payload, timeout=15)
    r.raise_for_status()
    return r.json()["entry_id"]


def test_search_allowed_decrypt_denied() -> None:
    doctor = login("doctor_general_clinic", "DocGeral2026!")
    nurse = login("nurse", "Nurse2026!")

    entry_id = create_patient(doctor, "aes_gcm")
    sr = nurse.get(BASE_URL + "/entries/search", params={"mode": "aes_gcm", "cpf": "11122233344"}, timeout=10)
    assert sr.status_code == 200, sr.text

    dr = nurse.post(BASE_URL + "/entries/{0}/decrypt-package".format(entry_id), params={"mode": "aes_gcm"}, timeout=10)
    assert dr.status_code == 403, dr.text
    print("PASS: search allowed but decrypt denied")


def test_policy_mismatch_fabeo() -> None:
    doctor = login("doctor_general_clinic", "DocGeral2026!")
    recep = login("receptionist", "Recep2026!")

    entry_id = create_patient(doctor, "fabeo")
    dr = recep.post(BASE_URL + "/entries/{0}/decrypt-package".format(entry_id), params={"mode": "fabeo"}, timeout=10)
    assert dr.status_code == 403, dr.text
    print("PASS: FABEO policy mismatch denied")


if __name__ == "__main__":
    test_search_allowed_decrypt_denied()
    test_policy_mismatch_fabeo()
    print("insider tests completed")
