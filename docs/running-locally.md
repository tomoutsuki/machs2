# Execução Local

## Objetivo

Explicar como subir o MACHS2 localmente, quais variáveis são relevantes, como verificar a saúde da stack e quais problemas práticos tendem a aparecer.

## Pré-requisitos

- Docker Engine
- Docker Compose v2
- Git
- Ambiente capaz de executar scripts POSIX se você quiser usar `Makefile` ou `.sh`

Observação para Windows:

- os scripts `.sh` e o `Makefile` são mais naturais em WSL, Git Bash ou ambiente Linux;
- a API em si roda normalmente via Docker Desktop.

## 1. Preparação

### Arquivo de ambiente

Crie o `.env` a partir do modelo raiz:

```bash
cp .env.example .env
```

Se estiver em PowerShell, faça o equivalente manual.

### Variáveis de ambiente relevantes

#### Banco

- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`

#### Main API

- `MAIN_API_HOST`
- `MAIN_API_PORT`
- `MAIN_API_LOG_LEVEL`
- `MAIN_API_JWT_SECRET`
- `MAIN_API_JWT_ALGORITHM`
- `MAIN_API_JWT_EXP_MINUTES`
- `MAIN_API_COOKIE_NAME`
- `MAIN_API_COOKIE_SECURE`
- `MAIN_API_COOKIE_SAMESITE`
- `MAIN_API_RESET_ON_START`
- `MAIN_API_ALLOW_ORIGINS`
- `MAIN_API_ENABLE_EXPERIMENTAL_REVOCATION`
- `MAIN_API_CURRENT_EPOCH`
- `MAIN_API_POLICY_STRICT`

#### KMS

- `KMS_HOST`
- `KMS_PORT`
- `KMS_INTERNAL_TOKEN`
- `KMS_MQK_B64`

#### FABEO

- `FABEO_HOST`
- `FABEO_PORT`
- `FABEO_MODE`

#### Benchmark

- `BENCHMARK_ITERATIONS`

## 2. Subida da stack

### Forma direta

```bash
docker compose up --build
```

### Em background

```bash
docker compose up --build -d
```

### Atalhos via `Makefile`

```bash
make setup
make up
```

Observação:

- `make setup` também tenta executar `git submodule update --init --recursive`, embora o repositório atual já traga o diretório `services/machs_fabeo_service/`.

## 3. O que acontece no startup

1. O PostgreSQL executa `db/init/*.sql` no primeiro bootstrap do volume.
2. O bridge FABEO precisa inicializar o runtime CP-ABE.
3. O KMS verifica a saúde do bridge.
4. A Main API:
   - verifica KMS e bridge;
   - se `MAIN_API_RESET_ON_START=true`, executa reset determinístico e recarga seeds cifrados.

## 4. Como verificar saúde dos serviços

### Docker Compose

```bash
docker compose ps
```

### Main API

```bash
curl http://localhost:8000/health
```

### KMS

```bash
curl http://localhost:8100/health
```

### FABEO Bridge

```bash
curl http://localhost:8200/health
```

## 5. Endereços úteis

| Recurso | URL padrão |
| --- | --- |
| Main API | `http://localhost:8000` |
| Health da Main API | `http://localhost:8000/health` |
| UI estática | `http://localhost:8000/ui/` |
| Minimal KMS | `http://localhost:8100` |
| FABEO Bridge | `http://localhost:8200` |
| PostgreSQL | `localhost:5432` |

## 6. Como acessar a API

Fluxo mínimo:

1. fazer login em `POST /auth/login`;
2. reutilizar o cookie de sessão;
3. chamar `POST /entries`, `GET /entries/search` e `POST /entries/{id}/decrypt-package`.

Observação:

- os usuários são semeados automaticamente a partir de `resources/users_seed.yaml`;
- a documentação não reproduz as credenciais locais.

## 7. Reset e reseed

### Reset total

```bash
./scripts/reset/reset_all.sh
```

Esse script:

1. executa `docker compose down -v`;
2. sobe a stack novamente com build;
3. força reexecução do bootstrap SQL e do seed determinístico.

### Seed

`./scripts/seed/seed_all.sh` não realiza inserts diretamente; ele apenas lembra que o seed ocorre no startup da Main API.

## 8. Logs

### Todos os serviços

```bash
docker compose logs -f --tail=200
```

### Problemas específicos

- se a Main API não sobe, verifique primeiro o health do KMS e do bridge;
- se o KMS não sobe, verifique o health do bridge;
- se o bridge falha, a causa tende a estar na inicialização do runtime Charm/FABEO.

## 9. Troubleshooting

### `machs_main_api` em loop de falha no startup

Possíveis causas:

- KMS indisponível;
- bridge FABEO indisponível;
- falha no reset determinístico;
- erro de conexão com PostgreSQL.

### `machs_minimal_kms` saudável, mas `bridge_real_cpabe=false`

Significado:

- o bridge respondeu, mas não conseguiu inicializar o runtime CP-ABE;
- a Main API deve falhar no startup porque exige CP-ABE real.

### Health do FABEO retorna `503`

Possíveis causas:

- imagem FABEO não inicializou Charm corretamente;
- falha na montagem do bridge;
- incompatibilidade do ambiente legado do container.

### Login funciona, mas decrypt falha com `403 session usk missing`

Possível causa importante:

- reinício do bridge FABEO após o login pode ter eliminado a USK em memória;
- a linha em `public.session_usk` continua existindo, mas o material efetivo da chave não.

### Rotação de epoch não produz o efeito esperado

Possíveis causas estruturais:

- `MAIN_API_ENABLE_EXPERIMENTAL_REVOCATION` desabilitado;
- Main API e KMS podem divergir no epoch atual em runtime;
- não existe recriptografia automática.

### Scripts `.sh` não executam em PowerShell puro

Alternativas:

- usar WSL;
- usar Git Bash;
- executar os comandos equivalentes manualmente.

## 10. Recomendações práticas para ambiente acadêmico

- manter `MAIN_API_RESET_ON_START=true` durante experimentação local reprodutível;
- usar `docker compose down -v` entre mudanças estruturais do banco;
- preservar o `.env` apenas para ambiente local de pesquisa;
- tratar o container FABEO como dependência legada sensível a ambiente.
