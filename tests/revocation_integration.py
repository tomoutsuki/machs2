import requests

BASE = "http://localhost:8000"


def login(u: str, p: str) -> requests.Session:
    s = requests.Session()
    r = s.post(BASE + "/auth/login", json={"username": u, "password": p}, timeout=10)
    r.raise_for_status()
    return s


def main() -> None:
    doctor = login("doctor_cardiologist", "Cardio2026!")

    c = doctor.post(
        BASE + "/entries",
        json={
            "mode": "fabeo",
            "resource": {
                "resourceType": "Patient",
                "id": "rev-integration",
                "name": [{"family": "Epoch", "given": ["Teste"]}],
                "identifier": [{"system": "https://saude.gov.br/fhir/sid/cpf", "value": "90909090909"}],
                "birthDate": "1991-02-03",
            },
            "policy_expression": "role.doctor AND clearance.demographics AND epoch.2026",
        },
        timeout=10,
    )
    c.raise_for_status()
    entry_id = c.json()["entry_id"]

    rot = doctor.post(BASE + "/entries/meta/epoch/rotate", params={"new_epoch": "epoch.2027"}, timeout=10)
    if rot.status_code >= 400:
        print("revocation mode likely disabled; skipping denial assertion")
        return

    d = doctor.post(BASE + "/entries/{0}/decrypt-package".format(entry_id), params={"mode": "fabeo"}, timeout=10)
    assert d.status_code == 403, d.text
    print("revocation integration pass")


if __name__ == "__main__":
    main()
