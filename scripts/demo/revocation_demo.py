import requests

BASE = "http://localhost:8000"


def login(username: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(BASE + "/auth/login", json={"username": username, "password": password}, timeout=10)
    r.raise_for_status()
    return s


def main() -> None:
    doctor = login("doctor_cardiologist", "Cardio2026!")

    create = doctor.post(
        BASE + "/entries",
        json={
            "mode": "fabeo",
            "resource": {
                "resourceType": "Patient",
                "id": "revocation-demo",
                "name": [{"family": "Revogacao", "given": ["Teste"]}],
                "identifier": [{"system": "https://saude.gov.br/fhir/sid/cpf", "value": "55566677788"}],
                "birthDate": "2000-01-01",
            },
            "policy_expression": "role.doctor AND clearance.demographics AND epoch.2026",
        },
        timeout=10,
    )
    create.raise_for_status()
    entry_id = create.json()["entry_id"]

    rotate = doctor.post(BASE + "/entries/meta/epoch/rotate", params={"new_epoch": "epoch.2027"}, timeout=10)
    if rotate.status_code >= 400:
        print("rotation failed (expected if revocation disabled):", rotate.text)
        return

    decrypt = doctor.post(BASE + "/entries/{0}/decrypt-package".format(entry_id), params={"mode": "fabeo"}, timeout=10)
    print("decrypt status after rotation:", decrypt.status_code)
    print(decrypt.text)


if __name__ == "__main__":
    main()
