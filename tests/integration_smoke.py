import requests

BASE = "http://localhost:8000"


def main() -> None:
    s = requests.Session()
    r = s.post(BASE + "/auth/login", json={"username": "doctor_general_clinic", "password": "DocGeral2026!"}, timeout=15)
    r.raise_for_status()

    resource = {
        "resourceType": "Patient",
        "id": "integration-smoke",
        "name": [{"family": "Test", "given": ["Integracao"]}],
        "identifier": [{"system": "https://saude.gov.br/fhir/sid/cpf", "value": "10203040506"}],
        "birthDate": "1999-09-09",
    }

    create = s.post(
        BASE + "/entries",
        json={
            "mode": "fabeo",
            "resource": resource,
        },
        timeout=15,
    )
    create.raise_for_status()
    entry_id = create.json()["entry_id"]
    invalid_modes = ["aes_gcm", "tde", "column_level", "app_level"]
    for mode in invalid_modes:
        bad_create = s.post(
            BASE + "/entries",
            json={
                "mode": mode,
                "resource": resource,
            },
            timeout=15,
        )
        assert bad_create.status_code in {400, 422}, bad_create.text

    search = s.get(BASE + "/entries/search", params={"mode": "fabeo", "cpf": "10203040506"}, timeout=15)
    search.raise_for_status()

    search_default = s.get(BASE + "/entries/search", params={"cpf": "10203040506"}, timeout=15)
    search_default.raise_for_status()

    for mode in invalid_modes:
        bad_search = s.get(BASE + "/entries/search", params={"mode": mode, "cpf": "10203040506"}, timeout=15)
        assert bad_search.status_code in {400, 422}, bad_search.text

    decrypt = s.post(BASE + "/entries/{0}/decrypt-package".format(entry_id), params={"mode": "fabeo"}, timeout=15)
    decrypt.raise_for_status()

    for mode in invalid_modes:
        bad_decrypt = s.post(BASE + "/entries/{0}/decrypt-package".format(entry_id), params={"mode": mode}, timeout=15)
        assert bad_decrypt.status_code in {400, 422}, bad_decrypt.text
    print("integration smoke ok")


if __name__ == "__main__":
    main()
