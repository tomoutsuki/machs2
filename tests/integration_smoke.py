import requests

BASE = "http://localhost:8000"


def main() -> None:
    s = requests.Session()
    r = s.post(BASE + "/auth/login", json={"username": "doctor_general_clinic", "password": "DocGeral2026!"}, timeout=15)
    r.raise_for_status()

    create = s.post(
        BASE + "/entries",
        json={
            "mode": "aes_gcm",
            "resource": {
                "resourceType": "Patient",
                "id": "integration-smoke",
                "name": [{"family": "Test", "given": ["Integracao"]}],
                "identifier": [{"system": "https://saude.gov.br/fhir/sid/cpf", "value": "10203040506"}],
                "birthDate": "1999-09-09",
            },
        },
        timeout=15,
    )
    create.raise_for_status()
    entry_id = create.json()["entry_id"]

    search = s.get(BASE + "/entries/search", params={"mode": "aes_gcm", "cpf": "10203040506"}, timeout=15)
    search.raise_for_status()

    decrypt = s.post(BASE + "/entries/{0}/decrypt-package".format(entry_id), params={"mode": "aes_gcm"}, timeout=15)
    decrypt.raise_for_status()
    print("integration smoke ok")


if __name__ == "__main__":
    main()
