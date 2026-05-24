# Serviços Internos

## Objetivo

Mapear os serviços internos utilizados pela Main API, seus endpoints, níveis de proteção e responsabilidades dentro do fluxo criptográfico.

## Panorama

O MACHS2 usa dois serviços internos principais:

1. `machs_minimal_kms`
2. `machs_fabeo_service` executando o bridge em `services/machs_fabeo_bridge/server.py`

Ambos se comunicam por HTTP dentro da rede Docker `machs_network`.

## Minimal KMS

### Papel no sistema

O KMS do MVP é mínimo e atua como:

- derivador de blind index por `HMAC-SHA256`;
- emissor de `usk_ref` por sessão de login;
- proxy da MPK pública;
- intermediário de unwrap da DEK;
- controlador de um `CURRENT_EPOCH` experimental.

### Configuração relevante

Variáveis consumidas:

- `KMS_INTERNAL_TOKEN`
- `KMS_MQK_B64`
- `MAIN_API_CURRENT_EPOCH`
- `MAIN_API_ENABLE_EXPERIMENTAL_REVOCATION`
- `FABEO_HOST`
- `FABEO_PORT`

### Endpoints do Minimal KMS

| Método | Caminho | Proteção | Uso principal |
| --- | --- | --- | --- |
| `GET` | `/health` | público | health do serviço e do bridge |
| `GET` | `/public-mpk` | público | expor MPK do bridge |
| `POST` | `/blind-index` | `x-internal-token` | derivar blind index |
| `POST` | `/session-usk` | `x-internal-token` | gerar `usk_ref` de sessão |
| `POST` | `/unwrap-dek` | `x-internal-token` | unwrap autorizado da DEK |
| `GET` | `/epoch` | `x-internal-token` | consultar epoch atual |
| `POST` | `/rotate-epoch` | `x-internal-token` | trocar epoch atual experimental |

### `GET /health`

Retorna:

- `status`
- `service`
- `bridge_mode`
- `bridge_real_cpabe`

Uso:

- healthcheck do Docker;
- verificação de startup da Main API.

### `GET /public-mpk`

Comportamento:

- chama internamente `GET /public-mpk` do bridge;
- devolve `mpk_b64` e `mode`.

Uso observado:

- o endpoint existe, mas não há consumo ativo pela Main API nos fluxos principais.

### `POST /blind-index`

Body:

```json
{
  "field": "cpf",
  "normalized_value": "12345678901"
}
```

Resposta:

```json
{
  "blind_index": "<hex hmac sha256>"
}
```

Implementação observada:

- concatena `field + "|" + normalized_value`;
- calcula `HMAC-SHA256` com a MQK;
- devolve o digest em hexadecimal.

Uso pela Main API:

- criação de entradas;
- busca por metadados.

### `POST /session-usk`

Body:

```json
{
  "username": "<usuario>",
  "attributes": ["role.doctor", "epoch.2026"],
  "session_id": "<uuid>",
  "epoch": "epoch.2026"
}
```

Resposta:

```json
{
  "usk_ref": "<uuid>",
  "expires_at_epoch_seconds": 1760000000,
  "issued_epoch": "epoch.2026"
}
```

Implementação observada:

- chama `POST /session-keygen` no bridge;
- fixa expiração em `time.time() + 3600`;
- não retorna a chave CP-ABE, apenas a referência.

Uso pela Main API:

- login.

### `POST /unwrap-dek`

Body:

```json
{
  "usk_ref": "<uuid>",
  "wrapped_key_b64": "<base64>"
}
```

Resposta:

```json
{
  "dek_b64": "<base64>",
  "policy": "role.doctor AND clearance.demographics AND epoch.2026",
  "mode": "fabeo22cp"
}
```

Uso pela Main API:

- `decrypt-package`.

### `GET /epoch` e `POST /rotate-epoch`

São endpoints estritamente internos no desenho atual.

Limitações observadas:

- a rotação depende de `MAIN_API_ENABLE_EXPERIMENTAL_REVOCATION=true`;
- altera apenas o `CURRENT_EPOCH` do KMS em memória;
- não recriptografa entradas;
- não sincroniza automaticamente a `Main API`, que continua usando `settings.current_epoch`.

## FABEO Bridge

### Papel no sistema

O bridge transforma o runtime CP-ABE do projeto FABEO em uma interface HTTP mínima compatível com o fluxo do MACHS2.

### Dependências técnicas

- Python 2.7
- `BaseHTTPServer`
- Charm-Crypto 0.43
- `PairingGroup('MNT224')`
- `FABEO22CPABE`

### Endpoints do bridge

| Método | Caminho | Proteção | Uso principal |
| --- | --- | --- | --- |
| `GET` | `/health` | público | health do runtime CP-ABE |
| `GET` | `/public-mpk` | público | MPK serializada |
| `POST` | `/validate-policy` | `x-internal-token` | normalização e validação de política |
| `POST` | `/session-keygen` | `x-internal-token` | geração da chave de sessão e `usk_ref` |
| `POST` | `/encapsulate-dek` | `x-internal-token` | encapsulamento da DEK |
| `POST` | `/unwrap-dek` | `x-internal-token` | unwrap autorizado da DEK |

### `GET /health`

Resposta típica:

```json
{
  "status": "ok",
  "service": "machs_fabeo_service",
  "mode": "fabeo22cp",
  "real_cpabe": true,
  "session_keys_loaded": 3
}
```

Comportamento:

- se a inicialização do runtime falhar, responde `503` e `real_cpabe: false`.

### `POST /validate-policy`

Body:

```json
{
  "policy": "(role.doctor OR role.nurse) AND clearance.clinical_notes AND epoch.2026"
}
```

Resposta:

```json
{
  "valid": true,
  "normalized": "( role.doctor or role.nurse ) and clearance.clinical_notes and epoch.2026",
  "mode": "fabeo22cp"
}
```

Observações de implementação:

- rejeita sintaxe com `=` ou `:`;
- aceita `AND`, `OR` e parênteses;
- normaliza atributos para lowercase;
- converte internamente a política para o formato esperado pelo FABEO.

### `POST /session-keygen`

Body:

```json
{
  "username": "<usuario>",
  "session_id": "<uuid>",
  "attributes": ["role.doctor", "clearance.demographics"],
  "epoch": "epoch.2026"
}
```

Resposta:

```json
{
  "usk_ref": "<uuid>",
  "attributes": [
    "CLEARANCE.DEMOGRAPHICS",
    "EPOCH.2026",
    "ROLE.DOCTOR"
  ],
  "mode": "fabeo22cp"
}
```

Observações:

- o bridge mescla `epoch` aos atributos;
- remove epoch antigo, se houver;
- guarda a chave de sessão em `SESSION_KEYS`, memória do processo.

### `POST /encapsulate-dek`

Body:

```json
{
  "policy": "role.doctor AND clearance.demographics AND epoch.2026"
}
```

Resposta:

```json
{
  "policy": "role.doctor AND clearance.demographics AND epoch.2026",
  "dek_b64": "<base64>",
  "wrapped_key_b64": "<base64>",
  "wrapped_key_meta": {
    "cpabe_scheme": "fabeo22cp",
    "kdf": "sha256(gt_secret)"
  },
  "mode": "fabeo22cp"
}
```

Uso pela Main API:

- criação de entrada.

### `POST /unwrap-dek`

Body:

```json
{
  "usk_ref": "<uuid>",
  "wrapped_key_b64": "<base64>"
}
```

Resposta:

```json
{
  "dek_b64": "<base64>",
  "policy": "role.doctor AND clearance.demographics AND epoch.2026",
  "mode": "fabeo22cp"
}
```

Erros relevantes:

- `403 invalid internal token`
- `403 session usk missing`
- `403 cp-abe key unwrap failed`
- `400` para exceções genéricas com trace

## Como a Main API usa esses serviços

| Fluxo | Main API -> KMS | KMS -> Bridge | Resultado |
| --- | --- | --- | --- |
| Login | `/session-usk` | `/session-keygen` | `usk_ref` salvo no banco |
| Create | `/blind-index` | nenhum | blind indexes hex |
| Create | nenhum | `/validate-policy`, `/encapsulate-dek` | política normalizada e DEK encapsulada |
| Decrypt | `/unwrap-dek` | `/unwrap-dek` | DEK liberada apenas se atributos satisfizerem a política |

## Limitações observadas

- O token interno é estático e depende de variável de ambiente.
- As chaves de sessão ficam apenas em memória no bridge; reinício do container pode invalidar sessões ainda presentes no banco.
- A MPK pública existe, mas não é usada na interface pública da Main API.
- A rotação de epoch não propaga automaticamente para todas as partes do sistema.
