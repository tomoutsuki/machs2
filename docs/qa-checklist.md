# MACHS2 QA Checklist

This checklist is designed for full QA of the local MVP.

## 1. Test Preparation

- [ ] Confirm Docker and Docker Compose are installed and running.
- [ ] Confirm Git submodule is initialized: `git submodule update --init --recursive`.
- [ ] Confirm `.env` exists (copied from `.env.example`).
- [ ] Confirm required ports are free: 5432, 8000, 8100, 8200.
- [ ] Confirm test scope includes all five modes: `fabeo`, `aes_gcm`, `tde`, `column_level`, `app_level`.
- [ ] Confirm the seeded users are available (6 predefined accounts).
- [ ] Confirm baseline test data exists under `resources/seeds/`.

## 2. Environment and Startup

- [ ] Run `make setup` successfully.
- [ ] Run `make up` successfully.
- [ ] Verify all containers are healthy in `docker compose ps`.
- [ ] Verify API health: `GET /health` returns `status=ok`.
- [ ] Verify KMS health endpoint is reachable.
- [ ] Verify FABEO bridge health endpoint is reachable.
- [ ] Verify startup seeding behavior matches `MAIN_API_RESET_ON_START` setting.

## 3. Database and Schema Validation

- [ ] Verify schemas exist: `fabeo`, `aes_gcm`, `tde`, `column_level`, `app_level`.
- [ ] Verify `public.users`, `public.session_usk`, and `public.policy_examples` tables exist.
- [ ] Verify each mode has an `entries` table.
- [ ] Verify indexes exist for blind indexes and common filters.
- [ ] Verify policy examples are inserted in `public.policy_examples`.
- [ ] Verify no plaintext FHIR JSON is stored in encrypted payload columns.

## 4. Authentication and Session Management

- [ ] `POST /auth/login` succeeds for each seeded user with valid credentials.
- [ ] `POST /auth/login` fails with invalid password.
- [ ] `POST /auth/login` fails with unknown username.
- [ ] Verify auth cookie is set with expected cookie name.
- [ ] Verify `GET /auth/me` returns current user details after login.
- [ ] Verify `GET /auth/me` returns 401 when no cookie is provided.
- [ ] Verify `POST /auth/logout` clears auth cookie.
- [ ] Verify requests with tampered or expired token are denied.
- [ ] Verify requests with missing/expired session USK are denied.

## 5. FHIR Input Validation

- [ ] Verify create entry fails when payload `resource` is not a JSON object.
- [ ] Verify create entry fails when `resourceType` is missing.
- [ ] Verify create entry fails for unsupported `resourceType`.
- [ ] Verify supported `resourceType` values succeed: `Patient`, `Observation`, `Condition`, `Encounter`, `MedicationRequest`.
- [ ] Verify UTF-8 characters in FHIR JSON are preserved during roundtrip.

## 6. Policy Syntax and Evaluation

- [ ] Verify valid policy syntax accepts dot notation attributes (example: `role.doctor`).
- [ ] Verify invalid policy syntax using `=` is rejected.
- [ ] Verify invalid policy syntax using `:` is rejected.
- [ ] Verify policy normalization handles extra spaces/casing.
- [ ] Verify `AND` and `OR` combinations evaluate as expected.
- [ ] Verify policy mismatch returns 403 on decrypt.

## 7. Entry Creation Coverage

- [ ] Create one entry per mode with explicit policy.
- [ ] Create one entry per mode without explicit policy and verify default policy assignment by resource type.
- [ ] Verify response includes `entry_id`, `mode`, `resource_type`, and `policy_expression`.
- [ ] Verify owner metadata is set to the authenticated username.
- [ ] Verify epoch metadata is set to current epoch.

## 8. Search and Blind Index Behavior

- [ ] Verify search by CPF finds expected entries in each mode.
- [ ] Verify search by name finds expected entries in each mode.
- [ ] Verify search by birthdate finds expected entries in each mode.
- [ ] Verify search normalization works (CPF punctuation, extra spaces, mixed case names).
- [ ] Verify search returns empty list when no match exists.
- [ ] Verify search requires authentication.
- [ ] Verify search response does not expose plaintext payload.

## 9. Cipher Metadata Endpoint

- [ ] Verify `GET /entries/{entry_id}/cipher` returns metadata for existing entries.
- [ ] Verify `GET /entries/{entry_id}/cipher` returns 404 for unknown IDs.
- [ ] Verify mode mismatch (query mode vs stored mode) does not leak data from other schemas.
- [ ] Verify response fields include `policy_expression`, `epoch_label`, `mode_meta`.

## 10. Decrypt Package and Authorization

- [ ] Verify decrypt succeeds for authorized user in each mode.
- [ ] Verify decrypt fails with 403 for unauthorized insider user.
- [ ] Verify decrypt fails with 404 for non-existent entry ID.
- [ ] Verify decrypt response for AES-family modes includes expected client package fields.
- [ ] Verify decrypt response for FABEO mode returns server-decrypted flow output.
- [ ] Verify decrypt response includes no secret key material that should remain server/KMS-only.

## 11. UI and Client-Side Decrypt Flow

- [ ] Open `http://localhost:8000/ui/` and verify page loads.
- [ ] Perform login from UI and verify user info appears.
- [ ] Create entry from UI for `aes_gcm` mode.
- [ ] Run UI search and verify expected result count.
- [ ] Fetch decrypt package from UI and verify output appears.
- [ ] Run client decrypt in browser and verify JSON plaintext reconstruction works.
- [ ] Verify error messages are shown for invalid JSON in resource editor.

## 12. Revocation (Experimental Mode)

- [ ] Run with `MAIN_API_ENABLE_EXPERIMENTAL_REVOCATION=false` and verify epoch rotation endpoint is rejected.
- [ ] Run with `MAIN_API_ENABLE_EXPERIMENTAL_REVOCATION=true` and verify epoch rotation succeeds for allowed doctor roles.
- [ ] Verify epoch rotation is denied for non-doctor roles.
- [ ] Create entry with old epoch, rotate epoch, then verify decrypt is denied as stale epoch.
- [ ] Verify behavior matches `tests/revocation_integration.py`.

## 13. Insider and Negative Security Scenarios

- [ ] Execute `python scripts/demo/insider_tests.py` and confirm pass conditions.
- [ ] Verify user can search matching records yet still be denied decrypt when policy mismatches.
- [ ] Verify receptionist cannot decrypt doctor-protected FABEO entry.
- [ ] Verify unauthorized calls without login are denied on protected endpoints.
- [ ] Verify internal token-protected KMS operations are not publicly exposed by main API.

## 14. Automated Tests and Scripted Checks

- [ ] Execute `python tests/integration_smoke.py` successfully.
- [ ] Execute `python tests/test_policy_and_normalization.py` successfully.
- [ ] Execute `python tests/revocation_integration.py` and confirm expected behavior for revocation-enabled or disabled mode.
- [ ] Execute `./scripts/demo/smoke_test.sh` successfully.
- [ ] Execute `make test` and confirm green status.

## 15. Benchmark and Non-Functional Validation

- [ ] Run `BENCHMARK_ITERATIONS=15 ./scripts/benchmark/run_benchmark.sh`.
- [ ] Confirm output files are generated: `results.json` and `summary.md`.
- [ ] Verify results include all five modes.
- [ ] Capture `docker stats` during benchmark and store CPU/memory observations.
- [ ] Compare average write/read/decrypt latencies for expected relative trends.
- [ ] Confirm no crashes, restarts, or healthcheck failures during benchmark.

## 16. Configuration and Hardening Checks

- [ ] Verify `MAIN_API_APP_ENVELOPE_KEY_B64` decodes to 32 bytes.
- [ ] Verify weak default secrets are replaced for non-local runs.
- [ ] Verify CORS origins are limited to expected test origin(s).
- [ ] Verify cookie settings (`secure`, `samesite`) match intended environment.
- [ ] Verify log level is appropriate and does not leak sensitive data.

## 17. Recovery, Reset, and Repeatability

- [ ] Run `./scripts/reset/reset_all.sh` and verify clean rebuild completes.
- [ ] Re-run smoke tests after reset and confirm deterministic pass.
- [ ] Verify reseeding produces expected predefined users and policies.
- [ ] Verify repeated test cycles do not accumulate inconsistent state.

## 18. Exit Criteria

- [ ] All critical auth/policy/decrypt checks pass.
- [ ] All scripted tests complete without unexpected failures.
- [ ] All modes pass create/search/decrypt baseline flows.
- [ ] Revocation behavior matches configuration and design.
- [ ] Benchmark artifacts are generated and reviewed.
- [ ] Open defects are triaged by severity and documented.
- [ ] Final QA report includes environment, commit hash, executed checklist, and evidence links.

## 19. Recommended Evidence to Collect

- [ ] API response captures for each major endpoint.
- [ ] Container health and logs snapshot.
- [ ] SQL evidence for schema/index/table checks.
- [ ] Test run outputs from integration and insider scripts.
- [ ] Benchmark result files and summary.
- [ ] Defect log with reproduction steps and expected vs actual behavior.
