# Estrutura do Projeto

## Objetivo

Mapear os diretórios e arquivos relevantes do MACHS2 para facilitar navegação, manutenção e leitura orientada por responsabilidade.

## Visão de topo

```text
/
|-- docker-compose.yml
|-- .env.example
|-- README.md
|-- Makefile
|-- db/
|   |-- init/
|   `-- seeds/
|-- resources/
|   |-- users_seed.yaml
|   `-- seeds/
|-- services/
|   |-- machs_main_api/
|   |-- machs_minimal_kms/
|   |-- machs_fabeo_bridge/
|   `-- machs_fabeo_service/
|-- scripts/
|   |-- benchmark/
|   |-- demo/
|   |-- reset/
|   |-- seed/
|   `-- validation/
|-- tests/
|-- frontend/
`-- docs/
```

## Arquivos raiz

| Caminho | Função |
| --- | --- |
| `docker-compose.yml` | Orquestra os quatro containers principais, healthchecks, volumes e rede |
| `.env.example` | Modelo central das variáveis de ambiente usadas pelos serviços |
| `README.md` | Visão geral resumida do repositório |
| `Makefile` | Atalhos POSIX para `setup`, `up`, `down`, `reset`, `seed`, `test` e `bench` |
| `LICENSE` | Licença do repositório |

## Diretório `services/`

### `services/machs_main_api/`

Serviço principal em FastAPI.

Arquivos centrais:

| Caminho | Função |
| --- | --- |
| `services/machs_main_api/Dockerfile` | Imagem da Main API |
| `services/machs_main_api/requirements.txt` | Dependências Python da API |
| `services/machs_main_api/.env.example` | Indica reaproveitamento do `.env` raiz |
| `services/machs_main_api/app/main.py` | Inicialização do FastAPI, CORS, rotas, UI estática e startup |
| `services/machs_main_api/app/routers/auth.py` | Login, logout, `/me` e dependência `get_current_user` |
| `services/machs_main_api/app/routers/entries.py` | Criação, busca, metadados, rotação de epoch e decrypt-package |
| `services/machs_main_api/app/core/settings.py` | Leitura de configurações e composição das URLs internas |
| `services/machs_main_api/app/core/security.py` | JWT, bcrypt e geração de `session_id` |
| `services/machs_main_api/app/db/database.py` | Conexão e cursor PostgreSQL |
| `services/machs_main_api/app/db/repository.py` | Acesso ao banco para usuários, sessão e entradas |
| `services/machs_main_api/app/services/fhir.py` | Validação mínima e extração de campos pesquisáveis |
| `services/machs_main_api/app/services/normalization.py` | Normalização de nome, CPF e data |
| `services/machs_main_api/app/services/kms_client.py` | Cliente HTTP para o Minimal KMS |
| `services/machs_main_api/app/services/fabeo_client.py` | Cliente HTTP para o FABEO Bridge |
| `services/machs_main_api/app/services/crypto_modes.py` | Cifra `AES-GCM` + unwrap/decifra híbridos |
| `services/machs_main_api/app/services/seed_loader.py` | Reset determinístico e carga de seeds |
| `services/machs_main_api/app/static/` | UI estática HTML/CSS/JS servida em `/ui` |
| `services/machs_main_api/app/validation/cpabe_validation.py` | Script interno de validação da trilha CP-ABE |

### `services/machs_minimal_kms/`

KMS mínimo em FastAPI.

Arquivos centrais:

| Caminho | Função |
| --- | --- |
| `services/machs_minimal_kms/Dockerfile` | Imagem do KMS |
| `services/machs_minimal_kms/requirements.txt` | Dependências Python do KMS |
| `services/machs_minimal_kms/app/main.py` | Endpoints internos, derivação de blind index, unwrap e epoch |

### `services/machs_fabeo_bridge/`

Bridge HTTP fino que adapta o runtime FABEO ao fluxo do MACHS2.

| Caminho | Função |
| --- | --- |
| `services/machs_fabeo_bridge/server.py` | Servidor HTTP com validação de política, keygen, encapsulamento e unwrap |

### `services/machs_fabeo_service/`

Projeto upstream do FABEO e sua imagem de build.

Arquivos centrais:

| Caminho | Função |
| --- | --- |
| `services/machs_fabeo_service/Dockerfile` | Build legado com Ubuntu 16.04, Python 2.7 e Charm |
| `services/machs_fabeo_service/requirements.txt` | Dependência `charm-crypto` |
| `services/machs_fabeo_service/FABEO/` | Implementação upstream das famílias ABE |
| `services/machs_fabeo_service/samples/` | Scripts upstream de benchmark e demonstração do FABEO |
| `services/machs_fabeo_service/README.md` | Documentação do projeto FABEO original |

## Diretório `db/`

### `db/init/`

Scripts executados automaticamente pelo PostgreSQL no bootstrap inicial do volume:

| Caminho | Função |
| --- | --- |
| `db/init/01_schemas.sql` | Cria extensão UUID, tabelas públicas e `fabeo.entries` |
| `db/init/02_policy_examples.sql` | Carrega exemplos de políticas ABAC |
| `db/init/03_notes.sql` | Notas do MVP FABEO-only |

### `db/seeds/`

| Caminho | Função |
| --- | --- |
| `db/seeds/README.md` | Explica que o seed é carregado pela Main API, não por SQL |

## Diretório `resources/`

| Caminho | Função |
| --- | --- |
| `resources/users_seed.yaml` | Usuários pré-definidos, atributos e senhas de seed |
| `resources/seeds/patient_example_brazilian_HL7.json` | Exemplo principal de `Patient` |
| `resources/seeds/patients/` | Pacientes extras de seed |
| `resources/seeds/observations/` | Observações de seed |
| `resources/seeds/conditions/` | Condições clínicas de seed |
| `resources/seeds/encounters/` | Encontros clínicos de seed |
| `resources/seeds/medication_requests/` | Prescrições de seed |

Observação: a documentação não reproduz as senhas do arquivo de seed, embora o repositório as use localmente para demonstração.

## Diretório `scripts/`

### `scripts/benchmark/`

| Caminho | Função |
| --- | --- |
| `scripts/benchmark/run_benchmark.sh` | Wrapper POSIX do benchmark |
| `scripts/benchmark/run_benchmark.py` | Mede latência de escrita, leitura e decrypt |
| `scripts/benchmark/summarize.py` | Gera sumário Markdown a partir do JSON |
| `scripts/benchmark/output/` | Saída de benchmark já versionada no repositório |

### `scripts/demo/`

| Caminho | Função |
| --- | --- |
| `scripts/demo/smoke_test.sh` | Smoke muito simples do `/health` |
| `scripts/demo/revocation_demo.py` | Demonstração do endpoint de rotação de epoch |
| `scripts/demo/insider_tests.py` | Script legado de insider test; exige atenção aos usernames configurados |

### `scripts/reset/`

| Caminho | Função |
| --- | --- |
| `scripts/reset/reset_all.sh` | Derruba a stack, remove volume do banco e sobe novamente |

### `scripts/seed/`

| Caminho | Função |
| --- | --- |
| `scripts/seed/seed_all.sh` | Informa que o seed é feito no startup da Main API |

### `scripts/validation/`

| Caminho | Função |
| --- | --- |
| `scripts/validation/run_validation.py` | Suíte principal de validação funcional, ABAC insider e observador de banco |
| `scripts/validation/observer_validation.py` | Execução isolada da etapa de observador de banco |
| `scripts/validation/output/` | Resultados versionados de execuções anteriores |

## Diretório `tests/`

| Caminho | Função |
| --- | --- |
| `tests/integration_smoke.py` | Fluxo de login, criação, busca, decrypt e rejeição de modos inválidos |
| `tests/revocation_integration.py` | Exercita a rotação de epoch, com comportamento dependente do flag experimental |

Observação: há referência em material de QA a `tests/test_policy_and_normalization.py`, mas o arquivo-fonte não está presente no snapshot inspecionado; apenas um `.pyc` aparece no repositório.

## Diretório `frontend/`

| Caminho | Função |
| --- | --- |
| `frontend/README.md` | Declara que a UI real do MVP é a estática servida pela Main API |

## Diretório `docs/`

Contém esta documentação técnica e alguns documentos legados mais antigos.

## Organização lógica do código

Uma forma prática de navegar no repositório é:

1. `docker-compose.yml`
2. `services/machs_main_api/app/main.py`
3. `services/machs_main_api/app/routers/`
4. `services/machs_main_api/app/services/`
5. `services/machs_minimal_kms/app/main.py`
6. `services/machs_fabeo_bridge/server.py`
7. `db/init/01_schemas.sql`
8. `scripts/validation/run_validation.py`

## Pontos estruturais importantes

- O design sugere suporte a múltiplos modos, mas `repository.py` fixa `ENTRY_SCHEMA = "fabeo"`.
- O bridge HTTP local é externo ao diretório do serviço FABEO upstream e é montado por volume em tempo de execução.
- O seed não é carregado por SQL; ele é cifrado e inserido pela Main API no startup.
- A UI não é um frontend moderno separado; é uma página estática servida em `/ui`.
