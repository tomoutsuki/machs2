# MACHS2 QA Execution Report

Date: 2026-04-14
Environment: Local Docker stack on Windows
Scope: Checklist execution based on docs/qa-checklist.md

## Overall Status

- Passed checks: 32
- Partial or blocked checks: 8
- Failed checks: 0

## Executed Checks

### Environment and Startup

- PASS: Docker compose stack started with build.
- PASS: All services healthy in docker compose ps.
- PASS: Main API health endpoint returns status ok.
- PASS: KMS health endpoint returns status ok.
- PASS: FABEO service health endpoint returns status ok.

### Authentication and Session

- PASS: Login works for all 6 seeded users.
- PASS: Invalid password login returns 401.
- PASS: Unknown username login returns 401.
- PASS: /auth/me without cookie returns 401.

### Core Automated Tests

- PASS: tests/integration_smoke.py
- PASS: scripts/demo/insider_tests.py
- PASS: tests/revocation_integration.py (revocation disabled path acknowledged by script)
- PASS: pytest tests/test_policy_and_normalization.py (2 passed)

### FHIR and Validation

- PASS: Missing resourceType returns 400.
- PASS: Unsupported resourceType returns 400.
- PASS: Non-object resource rejected at request validation layer (422).

### Encryption Mode Coverage

For each mode fabeo, aes_gcm, tde, column_level, app_level:

- PASS: Create entry returned 200.
- PASS: Search by CPF returned 200 with count 1.
- PASS: Decrypt package returned 200 for authorized doctor.

### Authorization and Insider Policy

- PASS: Search allowed while decrypt denied scenario validated.
- PASS: Nurse decrypt attempt on doctor policy entry returned 403.

### Revocation Endpoint Behavior (Current Config)

- PASS: Doctor epoch rotate returns 400 with revocation disabled.
- PASS: Receptionist epoch rotate returns 403 (role blocked).

### Database and Seed Validation

- PASS: Required schemas exist: fabeo, aes_gcm, tde, column_level, app_level.
- PASS: policy_examples seeded count = 7.
- PASS: users seeded count = 6.
- PASS: Binary-safe plaintext marker spot-check found 0 matches in aes_gcm and fabeo payloads.

### Benchmark and Non-Functional

- PASS: Benchmark executed for 15 iterations across all 5 modes.
- PASS: Benchmark artifacts generated:
  - scripts/benchmark/output/results.json
  - scripts/benchmark/output/summary.md
- PASS: docker stats snapshot captured.

Benchmark summary values:

- fabeo: write 583.92 ms, read 78.75 ms, decrypt 89.01 ms, 273 bytes
- aes_gcm: write 549.57 ms, read 90.21 ms, decrypt 89.32 ms, 291 bytes
- tde: write 581.44 ms, read 83.20 ms, decrypt 59.05 ms, 287 bytes
- column_level: write 531.31 ms, read 70.61 ms, decrypt 70.73 ms, 296 bytes
- app_level: write 565.82 ms, read 68.31 ms, decrypt 61.39 ms, 293 bytes

## Partial or Blocked Items

- BLOCKED (tooling on this host): scripts/demo/smoke_test.sh via sh command (sh not installed on current PowerShell environment).
- BLOCKED (tooling on this host): make test (make not installed on current PowerShell environment).
- PARTIAL: UI manual flow checks were not executed in browser automation in this run.
- PARTIAL: Cookie attribute hardening checks were not explicitly inspected from browser developer tools in this run.
- PARTIAL: CORS restrictive origin checks were not explicitly tested with cross-origin requests in this run.
- PARTIAL: End-to-end revocation denial after epoch rotation in enabled mode was not run because revocation is currently disabled.
- PARTIAL: Full SQL-level no-plaintext proof across all rows and all schemas was sampled with marker checks, not cryptographic audit.
- PARTIAL: docker stats captured as snapshot; continuous monitoring during benchmark loop was not recorded.

## Notes and Recommendations

- For complete parity with Linux-script checklist steps on Windows, run inside WSL or install make and sh.
- To complete revocation branch coverage, run one dedicated pass with MAIN_API_ENABLE_EXPERIMENTAL_REVOCATION=true.
- To close UI checklist items, execute manual browser workflow at /ui and capture screenshots and response payloads.
