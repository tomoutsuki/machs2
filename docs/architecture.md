# MACHS2 Architecture (Local MVP)

## Overview
MACHS2 is a local research MVP for comparing encrypted EHR storage modes while preserving HL7 FHIR R5 JSON payload semantics.

Containers:
- machs_main_api (Python 3 FastAPI)
- machs_fabeo_service (FABEO git submodule image built from upstream FABEO Dockerfile)
- machs_minimal_kms (minimal KMS for MSK/MQK operations)
- machs_postgresql (PostgreSQL)

## Data Flow
1. User authenticates against main API using predefined credentials.
2. Main API issues JWT cookie and requests USK from KMS for session use.
3. On write, main API validates FHIR resourceType and supported resource set.
4. Main API derives blind indexes from normalized name/CPF/birthdate via KMS HMAC endpoint.
5. Main API encrypts payload per selected mode and stores encrypted bytes + metadata.
6. Search executes via blind indexes only; no full-table decrypt scanning.
7. Decrypt-package requires policy match against server-authoritative attributes.
8. AES modes: client receives decrypt package and performs browser-side AES-GCM decrypt.
9. FABEO mode: a thin mounted runtime bridge script exposes HTTP endpoints over the FABEO container runtime.

## Schemas
- fabeo
- aes_gcm
- tde
- column_level
- app_level

Each schema stores comparable entry metadata:
- entry_id UUID
- resource_type
- policy_expression
- epoch_label
- owner_username
- blind indexes (name/cpf/birthdate)
- encrypted_payload + mode metadata

## Revocation (Experimental)
When enabled, epoch-style attributes (example: epoch.2026) are enforced.
Epoch rotation simulates ABE revocation behavior by requiring re-encryption and denying stale epoch decrypt.

This mode is experimental and disabled by default.

## Legacy FABEO Constraint
FABEO remains Python 2.7 and is intentionally not ported to Python 3 in this MVP.

### Legacy Compatibility Notes
- FABEO integration in local environments may depend on legacy Charm/OpenSSL compatibility.
- The service is isolated in its own container built from the FABEO repository Dockerfile.
- A local mounted bridge keeps API compatibility for this MVP and can run in explicit simulation mode for API-level research tests.
