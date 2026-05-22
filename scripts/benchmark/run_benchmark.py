import argparse
import json
import statistics
import time
from typing import Dict, List

import requests

USERS = {
    "doctor_general_clinic": "DocGeral2026!",
}

MODES = ["fabeo"]


def login(base_url: str) -> requests.Session:
    s = requests.Session()
    r = s.post(
        base_url + "/auth/login",
        json={"username": "doctor_general_clinic", "password": USERS["doctor_general_clinic"]},
        timeout=10,
    )
    r.raise_for_status()
    return s


def sample_patient(i: int) -> dict:
    return {
        "resourceType": "Patient",
        "id": "bench-patient-{0}".format(i),
        "name": [{"family": "Benchmark", "given": ["Paciente", str(i)]}],
        "identifier": [{"system": "https://saude.gov.br/fhir/sid/cpf", "value": "12345000{0:03d}".format(i)}],
        "birthDate": "1990-01-01",
    }


def run_mode(base_url: str, mode: str, iterations: int) -> Dict[str, float]:
    session = login(base_url)
    write_times: List[float] = []
    read_times: List[float] = []
    decrypt_times: List[float] = []
    sizes: List[int] = []

    for i in range(iterations):
        resource = sample_patient(i)
        payload = {"mode": mode, "resource": resource}

        t0 = time.perf_counter()
        create_resp = session.post(base_url + "/entries", json=payload, timeout=20)
        create_resp.raise_for_status()
        write_times.append(time.perf_counter() - t0)

        entry_id = create_resp.json()["entry_id"]

        t1 = time.perf_counter()
        read_resp = session.get(base_url + "/entries/{0}/cipher".format(entry_id), params={"mode": mode}, timeout=10)
        read_resp.raise_for_status()
        body = read_resp.content
        sizes.append(len(body))
        read_times.append(time.perf_counter() - t1)

        t2 = time.perf_counter()
        dec_resp = session.post(base_url + "/entries/{0}/decrypt-package".format(entry_id), params={"mode": mode}, timeout=20)
        dec_resp.raise_for_status()
        decrypt_times.append(time.perf_counter() - t2)

    return {
        "write_latency_ms_avg": statistics.mean(write_times) * 1000,
        "read_latency_ms_avg": statistics.mean(read_times) * 1000,
        "decrypt_latency_ms_avg": statistics.mean(decrypt_times) * 1000,
        "storage_overhead_bytes_avg": statistics.mean(sizes),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--iterations", type=int, default=15)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    output = {
        "base_url": args.base_url,
        "iterations": args.iterations,
        "modes": {},
        "notes": [
            "CPU/memory observations should be captured from docker stats during benchmark run.",
        ],
    }

    for mode in MODES:
        output["modes"][mode] = run_mode(args.base_url, mode, args.iterations)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)


if __name__ == "__main__":
    main()
