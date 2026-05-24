# Referência da API Principal

## Objetivo

Documentar os endpoints HTTP públicos expostos por `machs_main_api`, com base nos routers `auth.py`, `entries.py` e nos handlers de `main.py`.

## Convenções gerais

- Base URL padrão: `http://localhost:8000`
- Autenticação: cookie HTTP-only com JWT no nome configurado por `MAIN_API_COOKIE_NAME`
- Modos aceitos: apenas `fabeo` ou ausência do parâmetro `mode`
- Tipos FHIR suportados: `Patient`, `Observation`, `Condition`, `Encounter`, `MedicationRequest`

## Endpoints de infraestrutura

### `GET /health`

**Autenticação:** não requer

**Parâmetros:** nenhum

**Exemplo de request**

```http
GET /health HTTP/1.1
Host: localhost:8000
```

**Exemplo de response**

```json
{
  "status": "ok",
  "service": "machs_main_api",
  "revocation_enabled": false,
  "current_epoch": "epoch.2026"
}
```

**Possíveis erros**

- não há tratamento específico; falhas de processo impedem a resposta

**Processamento interno**

- devolve um snapshot simples da configuração carregada pela Main API;
- `current_epoch` aqui vem de `settings.current_epoch`, não de consulta ativa ao KMS.

### `GET /`

**Autenticação:** não requer

**Parâmetros:** nenhum

**Exemplo de response**

```json
{
  "message": "MACHS2 main api",
  "ui": "/ui/"
}
```

**Processamento interno**

- endpoint informativo que aponta para a UI estática.

## Endpoints de autenticação

### `POST /auth/login`

**Autenticação:** não requer

**Body JSON**

| Campo | Tipo | Obrigatório | Observação |
| --- | --- | --- | --- |
| `username` | `string` | sim | username sem espaços vazios |
| `password` | `string` | sim | senha do usuário pré-semeado |

**Exemplo de request**

```http
POST /auth/login HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "username": "<usuario>",
  "password": "<senha>"
}
```

**Exemplo de response**

```json
{
  "access_token": "<jwt>",
  "session_id": "8a9b7f93-0b7b-42a6-a490-bf1d7db197ab",
  "username": "<usuario>",
  "full_name": "<nome completo>",
  "role": "<papel>",
  "attributes": [
    "role.doctor",
    "department.clinic",
    "clearance.demographics",
    "epoch.2026"
  ],
  "current_epoch": "epoch.2026"
}
```

**Efeitos colaterais**

- seta cookie HTTP-only com o JWT;
- gera um `session_id`;
- solicita `session-usk` ao KMS;
- persiste `session_id -> usk_ref` em `public.session_usk`.

**Possíveis erros**

- `401 invalid credentials`
- `5xx` se KMS/FABEO falharem na emissão da sessão

**Processamento interno**

1. Busca usuário em `public.users`.
2. Valida `password_hash` com bcrypt.
3. Gera `session_id`.
4. Solicita USK de sessão ao KMS com os atributos do usuário.
5. Salva `usk_ref` e expiração em `public.session_usk`.
6. Emite JWT contendo `sub` e `sid`.

### `POST /auth/logout`

**Autenticação:** não exige `Depends(get_current_user)`, mas só é útil se houver cookie

**Exemplo de response**

```json
{
  "status": "ok"
}
```

**Possíveis erros**

- não há erro específico; sempre tenta apagar o cookie

**Processamento interno**

- remove o cookie no cliente;
- não remove a linha correspondente em `public.session_usk`;
- não mantém blacklist de JWT.

### `GET /auth/me`

**Autenticação:** requer cookie JWT válido e `session_usk` ativo

**Exemplo de response**

```json
{
  "username": "<usuario>",
  "full_name": "<nome completo>",
  "role": "<papel>",
  "attributes": [
    "role.doctor",
    "department.clinic",
    "clearance.demographics",
    "epoch.2026"
  ],
  "session_id": "8a9b7f93-0b7b-42a6-a490-bf1d7db197ab"
}
```

**Possíveis erros**

- `401 not authenticated`
- `401 invalid token`
- `401 invalid token payload`
- `401 invalid user`
- `401 session usk missing`
- `401 session expired`

**Processamento interno**

- lê o cookie;
- decodifica o JWT;
- busca o usuário no banco;
- busca a `session_usk` e valida expiração;
- injeta `session_id` e `usk_ref` no contexto do usuário autenticado.

## Endpoints de entradas cifradas

### `POST /entries`

**Autenticação:** requer usuário autenticado

**Body JSON**

| Campo | Tipo | Obrigatório | Observação |
| --- | --- | --- | --- |
| `mode` | `string \| null` | não | somente `fabeo` ou omitido |
| `resource` | `object` | sim | payload FHIR JSON |
| `policy_expression` | `string \| null` | não | se ausente, usa política padrão por `resourceType` |

**Exemplo de request**

```http
POST /entries HTTP/1.1
Host: localhost:8000
Content-Type: application/json
Cookie: machs2_session=<jwt>

{
  "mode": "fabeo",
  "resource": {
    "resourceType": "Patient",
    "id": "demo-patient-01",
    "name": [
      {
        "family": "Silva",
        "given": ["Ana"]
      }
    ],
    "identifier": [
      {
        "system": "https://saude.gov.br/fhir/sid/cpf",
        "value": "12345678901"
      }
    ],
    "birthDate": "1990-01-01"
  }
}
```

**Exemplo de response**

```json
{
  "entry_id": "57fa1c4d-0f9f-4702-bc8e-55f0604d194a",
  "mode": "fabeo",
  "resource_type": "Patient",
  "policy_expression": "(role.receptionist OR role.nurse OR role.doctor) AND clearance.demographics AND epoch.2026"
}
```

**Possíveis erros**

- `400 invalid mode`
- `400` por falha de validação FHIR mínima
- `400` por política inválida
- `422` por body fora do schema
- `503` por falha em encapsulamento/cifra

**Processamento interno**

1. Aceita apenas `fabeo`.
2. Valida superficialmente o FHIR.
3. Determina política explícita ou padrão.
4. Normaliza e valida a política no FABEO Bridge.
5. Extrai campos pesquisáveis.
6. Solicita blind indexes ao KMS.
7. Encapsula a DEK via FABEO.
8. Cifra o JSON com `AES-GCM`.
9. Persiste em `fabeo.entries`.

### `GET /entries/search`

**Autenticação:** requer usuário autenticado

**Query params**

| Parâmetro | Tipo | Obrigatório | Observação |
| --- | --- | --- | --- |
| `mode` | `string \| null` | não | somente `fabeo` ou omitido |
| `name` | `string \| null` | não | normalizado para lowercase e espaços colapsados |
| `cpf` | `string \| null` | não | normalizado para apenas dígitos |
| `birthdate` | `string \| null` | não | apenas `strip()` |

**Exemplo de request**

```http
GET /entries/search?mode=fabeo&cpf=12345678901 HTTP/1.1
Host: localhost:8000
Cookie: machs2_session=<jwt>
```

**Exemplo de response**

```json
{
  "count": 1,
  "items": [
    {
      "entry_id": "57fa1c4d-0f9f-4702-bc8e-55f0604d194a",
      "resource_type": "Patient",
      "policy_expression": "(role.receptionist OR role.nurse OR role.doctor) AND clearance.demographics AND epoch.2026",
      "epoch_label": "epoch.2026",
      "owner_username": "doctor_general_clinic",
      "mode_meta": {
        "fabeo_mode": "fabeo22cp",
        "flow": "cp_abe_fabeo_hybrid"
      },
      "created_at": "2026-05-24T00:00:00+00:00"
    }
  ]
}
```

**Possíveis erros**

- `400 invalid mode`

**Processamento interno**

- normaliza os filtros informados;
- deriva blind indexes no KMS;
- consulta `fabeo.entries`;
- combina múltiplos filtros com `OR`, não com `AND`;
- se nenhum filtro for enviado, retorna lista vazia.

### `GET /entries/meta/policies`

**Autenticação:** requer usuário autenticado

**Exemplo de response**

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

**Processamento interno**

- consulta `public.policy_examples`;
- não executa autorização fina além do requisito de autenticação.

### `POST /entries/meta/epoch/rotate`

**Autenticação:** requer usuário autenticado

**Parâmetro**

| Local | Nome | Tipo | Obrigatório | Observação |
| --- | --- | --- | --- | --- |
| query | `new_epoch` | `string` | sim | deve começar com `epoch.` no KMS |

**Exemplo de request**

```http
POST /entries/meta/epoch/rotate?new_epoch=epoch.2027 HTTP/1.1
Host: localhost:8000
Cookie: machs2_session=<jwt>
```

**Exemplo de response**

```json
{
  "status": "ok",
  "kms": {
    "current_epoch": "epoch.2027"
  }
}
```

**Possíveis erros**

- `403 only predefined doctors can rotate epoch in MVP`
- `400 experimental revocation mode disabled`
- erros propagados do KMS para epoch inválido

**Processamento interno**

- permite apenas os papéis `doctor_cardiologist` e `doctor_general_clinic`;
- encaminha a solicitação ao KMS;
- não executa recriptografia em lote nem atualização do `settings.current_epoch` da Main API.

### `GET /entries/{entry_id}/cipher`

**Autenticação:** requer usuário autenticado

**Path params**

| Nome | Tipo |
| --- | --- |
| `entry_id` | `UUID` |

**Query params**

| Nome | Tipo | Observação |
| --- | --- | --- |
| `mode` | `string \| null` | somente `fabeo` ou omitido |

**Exemplo de response**

```json
{
  "entry_id": "57fa1c4d-0f9f-4702-bc8e-55f0604d194a",
  "mode": "fabeo",
  "resource_type": "Patient",
  "policy_expression": "(role.receptionist OR role.nurse OR role.doctor) AND clearance.demographics AND epoch.2026",
  "epoch_label": "epoch.2026",
  "mode_meta": {
    "fabeo_mode": "fabeo22cp",
    "flow": "cp_abe_fabeo_hybrid"
  }
}
```

**Possíveis erros**

- `400 invalid mode`
- `404 entry not found`

**Processamento interno**

- busca a linha no banco;
- devolve somente metadados;
- não devolve `encrypted_payload`, `iv`, `auth_tag` ou `wrapped_key`.

### `POST /entries/{entry_id}/decrypt-package`

**Autenticação:** requer usuário autenticado

**Path params**

| Nome | Tipo |
| --- | --- |
| `entry_id` | `UUID` |

**Query params**

| Nome | Tipo | Observação |
| --- | --- | --- |
| `mode` | `string \| null` | somente `fabeo` ou omitido |

**Exemplo de response**

```json
{
  "entry_id": "57fa1c4d-0f9f-4702-bc8e-55f0604d194a",
  "mode": "fabeo",
  "policy_expression": "(role.receptionist OR role.nurse OR role.doctor) AND clearance.demographics AND epoch.2026",
  "result": {
    "flow": "cp_abe_fabeo_decrypt",
    "resource_json": {
      "resourceType": "Patient",
      "id": "demo-patient-01"
    },
    "client_decrypt_required": false
  }
}
```

**Possíveis erros**

- `400 invalid mode`
- `404 entry not found`
- `403` por negação CP-ABE, `usk_ref` ausente ou unwrap falho
- `503` por indisponibilidade do KMS/FABEO ou falha de descriptografia

**Processamento interno**

1. Busca a linha em `fabeo.entries`.
2. Converte `wrapped_key` para base64.
3. Chama o KMS com `usk_ref` da sessão.
4. O KMS pede unwrap ao bridge FABEO.
5. Se autorizado, a Main API decifra o payload `AES-GCM`.
6. Tenta desserializar o JSON e responde com o recurso.

## Considerações de segurança da API pública

- `search` e `cipher` exigem autenticação, mas não exigem que o usuário satisfaça a política da entrada.
- A autorização forte é aplicada apenas em `decrypt-package`.
- `logout` remove o cookie no cliente, mas não invalida a sessão no lado servidor.
- O JWT também é retornado no corpo da resposta de login, além do cookie.
