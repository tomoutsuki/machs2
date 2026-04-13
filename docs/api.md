# API Reference (MVP)

## Auth
- POST /auth/login
- GET /auth/me
- POST /auth/logout

## Entries
- POST /entries
- GET /entries/search
- GET /entries/{entry_id}/cipher
- POST /entries/{entry_id}/decrypt-package
- GET /entries/meta/policies
- POST /entries/meta/epoch/rotate

## Example curl
Login:

curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"doctor_general_clinic","password":"DocGeral2026!"}' \
  -c cookies.txt

Create entry:

curl -X POST http://localhost:8000/entries \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"mode":"aes_gcm","resource":{"resourceType":"Patient","id":"demo","name":[{"family":"Silva","given":["Ana"]}],"identifier":[{"system":"https://saude.gov.br/fhir/sid/cpf","value":"12345678901"}],"birthDate":"1990-01-01"}}'

Search by blind index input:

curl "http://localhost:8000/entries/search?mode=aes_gcm&cpf=12345678901" -b cookies.txt

Decrypt package:

curl -X POST "http://localhost:8000/entries/<ENTRY_ID>/decrypt-package?mode=aes_gcm" -b cookies.txt
