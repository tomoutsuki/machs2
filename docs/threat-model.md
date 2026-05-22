# Threat Model (Insider-Oriented Local MVP)

## 1. Scope

This threat model focuses on authenticated insider misuse and privilege abuse in a local research environment.

Primary security objective in scope:

- confidentiality of EHR plaintext against unauthorized authenticated users and database-only observers

Out of scope:

- internet perimeter attacks
- cloud multi-tenant hardening
- nation-state adversary model

## 2. Assets and Security Properties

### 2.1 Sensitive assets

- encrypted FHIR payloads (`<mode>.entries.encrypted_payload`)
- decrypted plaintext in decrypt-package responses
- session USK references (`public.session_usk`)
- KMS secrets (MSK, MQK)
- blind-index outputs used for lookup

### 2.2 Security properties expected

- only authorized attributes can pass policy checks for decrypt
- no plaintext payload stored in encrypted tables
- search should not require decrypting all records
- KMS secret keys should not be exposed through API contracts

## 3. Actors

- authorized users with different roles/attributes
- malicious insider user (valid account, insufficient privileges)
- DB observer/admin without application-level keys
- trusted service operators (MVP assumption)

## 4. Trust Boundaries

### 4.1 Trusted components (MVP assumption)

- Main API: auth validation, policy evaluation, orchestration
- KMS: secret custody and deterministic derivations

### 4.2 Partially trusted or exposed components

- Browser client: receives server-decrypted plaintext for authorized sessions
- FABEO bridge: policy-bound operation, simulation mode in local MVP

### 4.3 Untrusted for plaintext confidentiality

- PostgreSQL storage at rest (considered plaintext-untrusted)

## 5. Data-Flow Security Controls

### 5.1 Authentication controls

- JWT in HTTP-only cookie
- bcrypt password verification
- session validity additionally tied to `session_usk` existence and expiration

### 5.2 Authorization controls

- policy expression normalized and evaluated against authenticated user attributes
- decrypt-package denied on mismatch (`403`)
- optional epoch consistency check for experimental revocation

### 5.3 Search controls

- search uses blind indexes derived via KMS HMAC endpoint
- plaintext lookup values are normalized before derivation

### 5.4 KMS boundary controls

- internal KMS endpoints require `x-internal-token`
- MSK/MQK not exposed by KMS API

## 6. Insider Threat Scenarios

### 6.1 Policy mismatch decrypt attempt

Scenario:

- user can authenticate and even locate records by blind-index search
- user lacks required policy attributes

Expected result:

- `POST /entries/{entry_id}/decrypt-package` returns `403 policy mismatch: decrypt denied`

Validation references:

- `scripts/demo/insider_tests.py`

### 6.2 Search allowed, decrypt denied

Scenario:

- role can discover matching metadata by search
- same role cannot satisfy decrypt policy

Expected result:

- search returns metadata
- decrypt-package denied with `403`

### 6.3 Stale epoch decryption (revocation simulation)

Scenario:

- entry encrypted with old epoch label
- current epoch rotated

Expected result:

- decrypt-package denied with stale epoch message

Validation references:

- `scripts/demo/revocation_demo.py`
- `tests/revocation_integration.py`

### 6.4 DB observer access

Scenario:

- actor reads database directly

Expected result:

- actor sees ciphertext and metadata, not plaintext payload

## 7. Known Weaknesses and Residual Risks

- Decrypt-package returns plaintext from server-side FABEO flow; avoid exposing this outside trusted clients.
- Policy evaluator is simplified and does not implement full boolean precedence semantics.
- FABEO bridge currently runs simulation envelope for reproducibility.
- Internal token model is static and environment-based.
- No hardware-backed key protection or secure enclave assumptions.

## 8. Defensive Recommendations for Future Iterations

1. replace client-exposed data key flow with server-side decrypt or hardware-backed key wrapping per client identity
2. implement full policy parser with explicit precedence/AST evaluation
3. move KMS secrets to hardened custody (HSM/KMS product)
4. add audit trail for decrypt-package requests and denials
5. enforce short session TTL with rotation and logout invalidation list
6. add transport hardening and mTLS for inter-service calls in non-local environments

## 9. Non-Goals (Current MVP)

- production-grade key custody and governance
- side-channel resistance claims
- formal verification of policy language
- full healthcare compliance certification controls
