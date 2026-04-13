# Threat Model (Insider-Oriented, Local MVP)

## Scope
This model focuses on authenticated insider misuse scenarios in local research workflows.

## Assets
- FHIR JSON encrypted payloads
- Session USKs
- MSK and MQK
- Blind-index search values

## Trust Boundaries
- KMS is trusted to hold MSK/MQK and never expose them.
- Main API is trusted for auth and policy enforcement.
- Database is untrusted for plaintext confidentiality.
- UI/browser is local test client.

## Threats Tested
1. Unauthorized authenticated user attempts decrypt on restricted entry.
2. Search allowed but decrypt denied by policy mismatch.
3. Decrypt denied due missing attributes.
4. Decrypt denied after epoch rotation when revocation mode is enabled.

## Non-goals
- Production-grade key custody.
- Hardware-backed trust roots.
- Full side-channel hardening.
