# MACHS2 API Reference (MVP)

Base URL (local): `http://localhost:8000`

All endpoints return JSON.

## 1. Authentication Model

Authentication is session-cookie based.

- Login returns an access token in response body and also sets an HTTP-only cookie.
- Protected endpoints read the JWT from cookie name defined by `MAIN_API_COOKIE_NAME` (default `machs2_session`).
- Cookie settings come from environment (`secure`, `samesite`, expiration).
- A valid JWT alone is not enough: session USK reference must also exist and be unexpired in `public.session_usk`.

### 1.1 Predefined users

No registration endpoint exists. Users are loaded from `resources/users_seed.yaml`.

## 2. Common Enumerations and Constraints

### 2.1 Encryption mode

Accepted mode value:

- `fabeo`

Used by:

- `POST /entries` (body field)
- `GET /entries/search` (query)
- `GET /entries/{entry_id}/cipher` (query)
- `POST /entries/{entry_id}/decrypt-package` (query)

### 2.2 Supported FHIR resource types

- `Patient`
- `Observation`
- `Condition`
- `Encounter`
- `MedicationRequest`

## 3. Public Utility Endpoints

### 3.1 `GET /health`

Purpose: service health and selected runtime flags.

Response example:

```json
{
  "status": "ok",
  "service": "machs_main_api",
  "revocation_enabled": false,
  "current_epoch": "epoch.2026"
}
```

### 3.2 `GET /`

Purpose: root info and UI path hint.

Response example:

```json
{
  "message": "MACHS2 main api",
  "ui": "/ui/"
}
```

## 4. Auth Endpoints

### 4.1 `POST /auth/login`

Authenticate user and create session.

Request body:

```json
{
  "username": "doctor_general_clinic",
  "password": "DocGeral2026!"
}
```

Success response (`200`):

```json
{
  "access_token": "<jwt>",
  "session_id": "<uuid>",
  "username": "doctor_general_clinic",
  "full_name": "Dr. Ricardo Pereira Santos",
  "role": "doctor_general_clinic",
  "attributes": ["role.doctor", "clearance.demographics", "epoch.2026"],
  "current_epoch": "epoch.2026"
}
```

Errors:

- `401 invalid credentials`

Side effects:

- stores/upserts `session_usk` record
- sets HTTP-only auth cookie

### 4.2 `GET /auth/me`

Return authenticated user context.

Success response (`200`):

```json
{
  "username": "doctor_general_clinic",
  "full_name": "Dr. Ricardo Pereira Santos",
  "role": "doctor_general_clinic",
  "attributes": ["role.doctor", "clearance.demographics", "epoch.2026"],
  "session_id": "<uuid>"
}
```

Errors:

- `401 not authenticated` (missing cookie)
- `401 invalid token`
- `401 invalid user`
- `401 session usk missing`
- `401 session expired`

### 4.3 `POST /auth/logout`

Delete auth cookie.

Success response (`200`):

```json
{
  "status": "ok"
}
```

## 5. Entries Endpoints

All endpoints in this section require valid authenticated session.

### 5.1 `POST /entries`

Create encrypted entry.

Request body:

```json
{
  "mode": "fabeo",
  "resource": {
    "resourceType": "Patient",
    "id": "demo-1",
    "name": [{ "family": "Silva", "given": ["Ana"] }],
    "identifier": [{ "system": "https://saude.gov.br/fhir/sid/cpf", "value": "12345678901" }],
    "birthDate": "1990-01-01"
  },
  "policy_expression": "role.doctor AND clearance.demographics AND epoch.2026"
}
```

Fields:

- `mode` (optional, default `fabeo`): must be `fabeo`
- `resource` (required): FHIR JSON object
- `policy_expression` (optional): if omitted, API chooses resource-type default policy

Success response (`200`):

```json
{
  "entry_id": "<uuid>",
  "mode": "fabeo",
  "resource_type": "Patient",
  "policy_expression": "role.doctor AND clearance.demographics AND epoch.2026"
}
```

Errors:

- `400` invalid FHIR payload or unsupported `resourceType`
- `422` invalid mode pattern or malformed body

Internal processing summary:

1. validate FHIR baseline
2. derive normalized fields (name, CPF, birthdate when available)
3. request blind indexes from KMS
4. encrypt payload with FABEO
5. store metadata + ciphertext in `fabeo.entries`

### 5.2 `GET /entries/search`

Search metadata by blind indexes.

Query parameters:

- `mode` (optional, default `fabeo`)
- `name` (optional)
- `cpf` (optional)
- `birthdate` (optional)

At least one of `name`, `cpf`, `birthdate` should be provided. If none are provided, response is empty by design.

Response example (`200`):

```json
{
  "count": 1,
  "items": [
    {
      "entry_id": "<uuid>",
      "resource_type": "Patient",
      "policy_expression": "role.doctor AND clearance.demographics AND epoch.2026",
      "epoch_label": "epoch.2026",
      "owner_username": "doctor_general_clinic",
      "mode_meta": {
        "fabeo_mode": "fabeo22cp",
        "simulated": true
      },
      "created_at": "2026-04-24T..."
    }
  ]
}
```

Notes:

- query uses `OR` over provided blind-index fields
- payload plaintext is never returned by this endpoint

### 5.3 `GET /entries/{entry_id}/cipher`

Return non-sensitive cipher metadata for an entry.

Path parameters:

- `entry_id`: UUID

Query parameters:

- `mode` (optional, default `fabeo`)

Success response (`200`):

```json
{
  "entry_id": "<uuid>",
  "resource_type": "Patient",
  "policy_expression": "role.doctor AND clearance.demographics AND epoch.2026",
  "epoch_label": "epoch.2026",
  "mode_meta": {
    "fabeo_mode": "fabeo22cp",
    "simulated": true
  }
}
```

Errors:

- `404 entry not found`

### 5.4 `POST /entries/{entry_id}/decrypt-package`

Authorize and return decrypted payload.

Path parameters:

- `entry_id`: UUID

Query parameters:

- `mode` (optional, default `fabeo`)

Authorization checks:

1. row exists
2. if revocation enabled: row epoch must equal current epoch
3. user attributes must satisfy policy expression
4. FABEO decrypt package generation succeeds

#### Success response shape for `fabeo`

```json
{
  "entry_id": "<uuid>",
  "mode": "fabeo",
  "policy_expression": "role.doctor AND clearance.demographics AND epoch.2026",
  "result": {
    "flow": "server_decrypt_for_fabeo_bridge",
    "resource_json": "{...FHIR JSON string...}",
    "client_decrypt_required": false
  }
}
```

Errors:

- `403 policy mismatch: decrypt denied`
- `403 ciphertext stale epoch, re-encryption required`
- `403` FABEO decryption error
- `404 entry not found`

### 5.5 `GET /entries/meta/policies`

Return predefined policy catalog from `public.policy_examples`.

Response example (`200`):

```json
{
  "items": [
    {
      "policy_name": "patient_demographics_reception",
      "resource_type": "Patient",
      "policy_expression": "role.receptionist AND clearance.demographics AND epoch.2026",
      "description": "Reception can read patient demographics only"
    }
  ]
}
```

### 5.6 `POST /entries/meta/epoch/rotate`

Rotate active epoch (experimental revocation feature).

Query parameters:

- `new_epoch` (required, must start with `epoch.`)

Access restrictions:

- only roles `doctor_cardiologist` or `doctor_general_clinic`
- feature flag `MAIN_API_ENABLE_EXPERIMENTAL_REVOCATION` must be true

Success response (`200`):

```json
{
  "status": "ok",
  "kms": {
    "current_epoch": "epoch.2027"
  }
}
```

Errors:

- `403 only predefined doctors can rotate epoch in MVP`
- `400 experimental revocation mode disabled`
- upstream KMS validation errors (for example invalid epoch format)

## 6. Internal Service Contracts (Not Public API)

These endpoints are called by Main API containers and are useful for operations/debugging.

### 6.1 KMS (`http://machs_minimal_kms:8100`)

- `POST /blind-index` (requires `x-internal-token`)
- `POST /session-usk` (requires `x-internal-token`)
- `GET /epoch` (requires `x-internal-token`)
- `POST /rotate-epoch` (requires `x-internal-token`)
- `GET /public-mpk` (public)

### 6.2 FABEO bridge (`http://machs_fabeo_service:8200`)

- `POST /validate-policy`
- `POST /encrypt`
- `POST /decrypt`
- `GET /health`

## 7. Curl Workflow Example

### 7.1 Login

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"doctor_general_clinic","password":"DocGeral2026!"}' \
  -c cookies.txt
```

### 7.2 Create entry

```bash
curl -X POST http://localhost:8000/entries \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"mode":"fabeo","resource":{"resourceType":"Patient","id":"demo","name":[{"family":"Silva","given":["Ana"]}],"identifier":[{"system":"https://saude.gov.br/fhir/sid/cpf","value":"12345678901"}],"birthDate":"1990-01-01"}}'
```

### 7.3 Search

```bash
curl "http://localhost:8000/entries/search?mode=fabeo&cpf=12345678901" -b cookies.txt
```

### 7.4 Decrypt package

```bash
curl -X POST "http://localhost:8000/entries/<ENTRY_ID>/decrypt-package?mode=fabeo" -b cookies.txt
```
