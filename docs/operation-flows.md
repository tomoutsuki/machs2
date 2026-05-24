# Fluxos Operacionais

## Objetivo

Documentar os principais fluxos ponta a ponta do MACHS2 como operações completas entre cliente, Main API, KMS, FABEO Bridge e PostgreSQL.

## 1. Login

### Descrição

O login conecta autenticação tradicional a uma sessão criptográfica CP-ABE.

### Diagrama

```mermaid
sequenceDiagram
    actor U as Usuário
    participant API as Main API
    participant DB as PostgreSQL
    participant KMS as Minimal KMS
    participant FAB as FABEO Bridge

    U->>API: POST /auth/login {username, password}
    API->>DB: SELECT public.users WHERE username=?
    DB-->>API: user + password_hash + attributes
    API->>KMS: POST /session-usk
    KMS->>FAB: POST /session-keygen
    FAB-->>KMS: usk_ref
    KMS-->>API: usk_ref + expires_at + issued_epoch
    API->>DB: UPSERT public.session_usk
    API-->>U: access_token + cookie HTTP-only
```

## 2. Criação de entrada

### Descrição

Fluxo usado por `POST /entries` para cifrar e persistir um recurso FHIR.

### Diagrama

```mermaid
sequenceDiagram
    actor U as Usuário autenticado
    participant API as Main API
    participant KMS as Minimal KMS
    participant FAB as FABEO Bridge
    participant DB as PostgreSQL

    U->>API: POST /entries
    API->>FAB: POST /validate-policy
    FAB-->>API: policy normalizada
    API->>KMS: POST /blind-index (name/cpf/birthdate)
    KMS-->>API: blind indexes
    API->>FAB: POST /encapsulate-dek
    FAB-->>API: dek_b64 + wrapped_key_b64
    API->>API: AES-GCM encrypt(payload_json)
    API->>DB: INSERT INTO fabeo.entries
    DB-->>API: ok
    API-->>U: entry_id + policy_expression
```

## 3. Busca

### Descrição

Fluxo usado por `GET /entries/search`.

### Observações

- a busca é por blind index;
- a combinação de múltiplos filtros é `OR`;
- a resposta contém metadados, não plaintext.

### Diagrama

```mermaid
sequenceDiagram
    actor U as Usuário autenticado
    participant API as Main API
    participant KMS as Minimal KMS
    participant DB as PostgreSQL

    U->>API: GET /entries/search?cpf=...&name=...
    API->>API: normalização dos filtros
    API->>KMS: POST /blind-index
    KMS-->>API: blind indexes hex
    API->>DB: SELECT ... FROM fabeo.entries WHERE bidx_* = ? OR ...
    DB-->>API: linhas e metadados
    API-->>U: count + items
```

## 4. Consulta de metadados/cipher

### Descrição

Fluxo usado por `GET /entries/{entry_id}/cipher`.

### Observação importante

Apesar do nome do endpoint, ele não entrega o ciphertext binário.

### Diagrama

```mermaid
sequenceDiagram
    actor U as Usuário autenticado
    participant API as Main API
    participant DB as PostgreSQL

    U->>API: GET /entries/{entry_id}/cipher
    API->>DB: SELECT * FROM fabeo.entries WHERE entry_id=?
    DB-->>API: linha da entrada
    API-->>U: policy_expression + epoch_label + mode_meta
```

## 5. Decrypt-package

### Descrição

Fluxo usado por `POST /entries/{entry_id}/decrypt-package`.

### Diagrama

```mermaid
sequenceDiagram
    actor U as Usuário autenticado
    participant API as Main API
    participant DB as PostgreSQL
    participant KMS as Minimal KMS
    participant FAB as FABEO Bridge

    U->>API: POST /entries/{entry_id}/decrypt-package
    API->>DB: SELECT * FROM fabeo.entries WHERE entry_id=?
    DB-->>API: encrypted_payload + iv + auth_tag + wrapped_key
    API->>KMS: POST /unwrap-dek {usk_ref, wrapped_key_b64}
    KMS->>FAB: POST /unwrap-dek
    alt atributos satisfazem a política
        FAB-->>KMS: dek_b64
        KMS-->>API: dek_b64
        API->>API: AES-GCM decrypt(...)
        API-->>U: resource_json plaintext
    else atributos insuficientes
        FAB-->>KMS: erro 403
        KMS-->>API: detalhe do erro
        API-->>U: 403
    end
```

## 6. Verificação de política ABAC

### Descrição

A política ABAC não é verificada por um motor booleano próprio da Main API no fluxo de `decrypt-package`. O enforcement ocorre quando a USK da sessão tenta abrir o `wrapped_key` CP-ABE.

### Diagrama

```mermaid
flowchart TD
    A["policy_expression salva na entrada"] --> B["Bridge normaliza política no create"]
    C["Atributos do usuário no login"] --> D["Bridge gera USK da sessão"]
    B --> E["wrapped_key CP-ABE"]
    D --> F["usk_ref -> USK em memória"]
    E --> G["/unwrap-dek"]
    F --> G
    G --> H{"satisfaz policy?"}
    H -- sim --> I["DEK liberada"]
    H -- não --> J["403 decrypt denied"]
```

## 7. Rotação de epoch experimental

### Descrição

Há um fluxo experimental exposto por `POST /entries/meta/epoch/rotate`.

### O que o código faz hoje

1. exige usuário autenticado com papel médico específico;
2. verifica o flag `MAIN_API_ENABLE_EXPERIMENTAL_REVOCATION`;
3. chama `POST /rotate-epoch` no KMS;
4. o KMS troca o seu `CURRENT_EPOCH` em memória.

### O que o código não faz automaticamente

- não recriptografa entradas já existentes;
- não atualiza `settings.current_epoch` da Main API em runtime;
- não persiste histórico de epochs;
- não invalida explicitamente todas as `session_usk`.

### Diagrama

```mermaid
sequenceDiagram
    actor U as Médico autorizado
    participant API as Main API
    participant KMS as Minimal KMS

    U->>API: POST /entries/meta/epoch/rotate?new_epoch=epoch.2027
    API->>API: valida role e flag experimental
    API->>KMS: POST /rotate-epoch
    KMS->>KMS: atualiza CURRENT_EPOCH em memória
    KMS-->>API: current_epoch atualizado
    API-->>U: status ok
```

## 8. Fluxo de seed no startup

### Descrição

Se `MAIN_API_RESET_ON_START=true`, a Main API reseta e repovoa o ambiente no startup.

### Diagrama

```mermaid
sequenceDiagram
    participant API as Main API
    participant KMS as Minimal KMS
    participant FAB as FABEO Bridge
    participant DB as PostgreSQL
    participant RES as resources/seeds

    API->>KMS: health
    API->>FAB: health
    API->>DB: DELETE FROM fabeo.entries
    API->>DB: DELETE FROM public.session_usk
    API->>RES: lê users_seed.yaml
    API->>DB: UPSERT public.users
    API->>RES: lê FHIR seeds
    API->>KMS: blind indexes
    API->>FAB: validate-policy + encapsulate-dek
    API->>DB: INSERT fabeo.entries
```

## Observações finais

- O fluxo operacional dominante do sistema é `login -> create/search -> decrypt-package`.
- O fluxo de busca foi desenhado para permitir descoberta controlada por blind index, sem implicar autorização de leitura do payload.
- A trilha de revogação por epoch deve ser tratada como experimental e incompleta no estado atual do código.
