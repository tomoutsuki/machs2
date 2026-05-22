# MACHS2 Architecture (Local MVP)

## 1. Purpose and Scope

MACHS2 is a local research MVP to validate FABEO-based ABAC while preserving HL7 FHIR R5 JSON payload semantics.

The project is intentionally modular:

- one API service for auth, policy checks, and orchestration
- one minimal KMS for key-related derivations
- one FABEO bridge service for CP-ABE related operations
- one PostgreSQL service for storage

The system favors reproducibility over production hardening.

## 2. Container Topology

Docker Compose defines four services connected on a single bridge network (`machs_network`).

### 2.1 `machs_main_api` (FastAPI, Python 3)

- External port: `8000`
- Responsibilities:
	- user authentication (pre-seeded users)
	- issue/validate session cookie (JWT)
	- create/search/read/decrypt-package endpoints
	- policy normalization/evaluation
	- FABEO encryption orchestration
- Dependencies: PostgreSQL, KMS, FABEO bridge (via `depends_on` health checks)
- Mounted volume: `./resources` (read-only) for deterministic startup seeding

### 2.2 `machs_minimal_kms` (FastAPI, Python 3)

- External port: `8100`
- Responsibilities:
	- derive blind indexes (`HMAC(MQK, field|normalized_value)`)
	- derive per-session USK references (`HMAC(MSK, username|session_id|attrs|epoch)`)
	- expose current epoch and optional epoch rotation
	- expose MPK as a public endpoint
- Access control for sensitive endpoints: `x-internal-token` header

### 2.3 `machs_fabeo_service` (FABEO image + mounted bridge)

- External port: `8200`
- Runtime command: Python 2 bridge script at `/opt/machs2/bridge/server.py`
- Responsibilities:
	- validate policy strings
	- encrypt/decrypt payloads for `fabeo` mode
- Current MVP behavior: deterministic simulation envelope when `FABEO_ALLOW_SIMULATION=true`

### 2.4 `machs_postgresql` (PostgreSQL 16)

- External port: `5432`
- Responsibilities:
	- users and session references
	- policy examples
	- encrypted entries stored in `fabeo.entries`
- Initialization scripts loaded from `db/init`

## 3. Inter-Module Communication

### 3.1 High-level communication matrix

- Browser/UI -> Main API: public HTTP endpoints (`/auth`, `/entries`, `/health`, `/ui`)
- Main API -> PostgreSQL: psycopg2 DSN connection
- Main API -> KMS: HTTP calls to `/blind-index`, `/session-usk`, `/epoch`, `/rotate-epoch` with internal token
- Main API -> FABEO bridge: HTTP calls to `/validate-policy`, `/encrypt`, `/decrypt`
- KMS/FABEO -> Main API: no callback path; strictly request/response

### 3.2 Startup and readiness chain

1. PostgreSQL becomes healthy (`pg_isready`).
2. KMS health endpoint responds (`/health`).
3. FABEO bridge health endpoint responds (`/health`).
4. Main API starts and, if enabled, runs deterministic reset+seed on startup.

## 4. End-to-End Data Flows

### 4.1 Login flow

1. Client posts credentials to `/auth/login`.
2. Main API verifies bcrypt password hash from `public.users`.
3. Main API requests session USK from KMS (`/session-usk`).
4. Main API stores USK reference in `public.session_usk` with expiration.
5. Main API issues JWT and writes HTTP-only cookie.

### 4.2 Create entry flow

1. Validate FHIR payload shape and supported `resourceType`.
2. Normalize and extract searchable fields (name, CPF, birthdate for Patient).
3. Request blind indexes from KMS for each available normalized field.
4. Encrypt payload using FABEO.
5. Insert encrypted row into `fabeo.entries`.

### 4.3 Search flow

1. Normalize search inputs.
2. Derive blind indexes via KMS.
3. Query `fabeo.entries` by blind index columns (`OR` combination).
4. Return metadata only (no plaintext payload).

### 4.4 Decrypt-package flow

1. Load row from `fabeo.entries`.
2. Check epoch staleness when experimental revocation is enabled.
3. Evaluate policy expression against authenticated user attributes.
4. If authorized, return plaintext JSON in `result.resource_json`.

## 5. Storage Model

## 5.1 Public schema

- `public.users`: predefined users, role, bcrypt hash, attributes JSONB
- `public.session_usk`: session-bound USK reference with expiration
- `public.policy_examples`: policy catalog exposed by API

## 5.2 FABEO schema

The `fabeo` schema contains a single `entries` table.

Common columns in `fabeo.entries`:

- `entry_id` (UUID, PK)
- `resource_type`
- `policy_expression`
- `epoch_label`
- `owner_username`
- `bidx_name`, `bidx_cpf`, `bidx_birthdate` (blind-index fields)
- `encrypted_payload` (BYTEA)
- `mode_meta` (JSONB)
- timestamps (`created_at`, `updated_at`)

Indexes exist for blind-index columns, resource type, and created-at.

## 6. Cryptographic Behavior in This MVP

- Encryption/decryption delegated to FABEO bridge service.
- Bridge validates policy syntax and enforces attribute checks on decrypt.
- In current local setup, payload is wrapped in deterministic simulation envelope for reproducibility.

## 7. Policy and Attribute Engine

Policy syntax accepts only token format:

- attribute token: `namespace.value` (for example `role.doctor`)
- operators: `AND`, `OR`
- parentheses are accepted in input but evaluation is linearized after normalization
- forbidden syntax: `=` and `:`

Decryption authorization always checks policy against user attributes in the authenticated session context.

## 8. Revocation Model (Experimental)

- Controlled by `MAIN_API_ENABLE_EXPERIMENTAL_REVOCATION`.
- Entries carry `epoch_label` at write time.
- If current epoch differs from row epoch, decrypt-package is denied (`403`) with stale-epoch message.
- Rotation endpoint is guarded by role and feature flag.

This is a research simulation of revocation semantics, not full production key-rotation infrastructure.

## 9. Deterministic Seeding and Reproducibility

When `MAIN_API_RESET_ON_START=true`:

1. all entries in `fabeo.entries` are cleared
2. all session references are cleared
3. users from `resources/users_seed.yaml` are upserted
4. resource seed files are encrypted and inserted in `fabeo` only

This ensures repeatable behavior for demos, benchmarks, and integration scripts.

## 10. Architectural Limitations

- FABEO service remains tied to Python 2 bridge/runtime compatibility constraints.
- Policy evaluator is intentionally simplified for MVP.
- Full FHIR profile validation is out of scope (baseline checks only).
- KMS is minimal and intentionally not HSM-backed.
