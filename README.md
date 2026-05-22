# MACHS2

Modular Architecture for Cryptographic Control in Healthcare Systems (local MVP).

This repository implements a local research environment to validate FABEO-based ABAC for HL7 FHIR R5 JSON resources.

## Implemented Services

- `machs_main_api` (Python 3 / FastAPI)
- `machs_fabeo_service` (direct git submodule of FABEO, built with FABEO's own Dockerfile)
- `machs_minimal_kms` (minimal KMS holding MSK/MQK)
- `machs_postgresql` (PostgreSQL)

## Encryption Mode

MACHS2 supports a single encryption mode for the TCC2 scope:

- `fabeo` (FABEO CP-ABE bridge)

## FHIR Support

Supported resource types:

- Patient
- Observation
- Condition
- Encounter
- MedicationRequest

Validation baseline:

- payload is JSON object
- `resourceType` exists
- `resourceType` is in supported set

Original UTF-8 FHIR JSON is preserved as encryption input and never stored as plaintext payload in encrypted modes.

## FABEO Policy Syntax Rules

Allowed attribute syntax:

- `role.doctor`
- `specialty.cardiology`
- `department.laboratory`

Allowed operators: `AND`, `OR`

Forbidden syntax:

- `role=doctor`
- `department:laboratory`

## KMS Rules in This MVP

- KMS stores MSK and MQK only
- MSK/MQK never leave KMS
- USK is issued per login session and stored only as session reference (never in EHR tables)
- MPK is public endpoint output

## Predefined Users (No Registration)

Exactly six predefined users are seeded from `resources/users_seed.yaml`:

1. receptionist
2. nurse
3. doctor_general_clinic
4. doctor_cardiologist
5. medical_laboratory_technician
6. medical_laboratory_scientist

Passwords are bcrypt-hashed at seed load time. No self-registration endpoint is implemented.

## Experimental Revocation Mode

- default: OFF (`MAIN_API_ENABLE_EXPERIMENTAL_REVOCATION=false`)
- epoch-style attributes (example `epoch.2026`)
- epoch rotation can deny old-key decrypt attempts and simulate re-encryption requirement

This is explicitly experimental in this MVP.

## Required Seed Path

Seed reference file is copied to:

- `resources/seeds/patient_example_brazilian_HL7.json`

Source used in this repository:

- `.baseMaterial/patient_example_brazilian_HL7.json`

## Quick Start

1. Copy env template:

```bash
cp .env.example .env
```

2. Initialize FABEO submodule at service root:

```bash
git submodule update --init --recursive
```

3. Start all services:

```bash
docker compose up --build
```

4. Open UI:

- http://localhost:8000/ui/

## Single Command Sequence (Makefile)

```bash
make setup
make up
```

## API Smoke Checks

Health:

```bash
curl http://localhost:8000/health
```

Login:

```bash
curl -X POST http://localhost:8000/auth/login \
	-H "Content-Type: application/json" \
	-d '{"username":"doctor_general_clinic","password":"DocGeral2026!"}' \
	-c cookies.txt
```

Create encrypted entry:

```bash
curl -X POST http://localhost:8000/entries \
	-H "Content-Type: application/json" \
	-b cookies.txt \
	-d '{"mode":"fabeo","resource":{"resourceType":"Patient","id":"demo-1","name":[{"family":"Silva","given":["Ana"]}],"identifier":[{"system":"https://saude.gov.br/fhir/sid/cpf","value":"12345678901"}],"birthDate":"1990-01-01"}}'
```

Search via blind index input:

```bash
curl "http://localhost:8000/entries/search?mode=fabeo&cpf=12345678901" -b cookies.txt
```

## Benchmarks

Run benchmark:

```bash
BENCHMARK_ITERATIONS=15 ./scripts/benchmark/run_benchmark.sh
```

Outputs:

- `scripts/benchmark/output/results.json`
- `scripts/benchmark/output/summary.md`

## Tests

Insider attack tests:

```bash
python scripts/demo/insider_tests.py
```

Integration smoke:

```bash
python tests/integration_smoke.py
```

## Documentation

- `docs/architecture.md`
- `docs/threat-model.md`
- `docs/api.md`
- `docs/benchmarking.md`

## Known Limitations

- FABEO container is built from the upstream FABEO Dockerfile (Ubuntu 16.04 / Python 2.7 / Charm 0.43 compatibility assumptions).
- A thin local HTTP bridge script is mounted into the FABEO container at runtime to expose `/encrypt`, `/decrypt`, and `/validate-policy` endpoints expected by `machs_main_api`.
- Bridge mode keeps deterministic policy-bound ciphertext behavior for local reproducibility tests.
- Full FHIR profile validation beyond required checks is not implemented.
- Local path names containing `#` may break Vite projects; this repository uses plain static UI to avoid that issue.
