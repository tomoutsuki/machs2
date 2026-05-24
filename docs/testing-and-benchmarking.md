# Testes, Validação e Benchmarking

## Objetivo

Mapear os testes automatizados, scripts de demonstração, suíte de validação e benchmark existentes no repositório, além de explicar como interpretar os artefatos produzidos.

## Visão geral

O repositório possui quatro camadas distintas de verificação:

1. testes de integração simples em `tests/`
2. scripts de demonstração em `scripts/demo/`
3. benchmark em `scripts/benchmark/`
4. suíte de validação experimental em `scripts/validation/`

## 1. Testes em `tests/`

### `tests/integration_smoke.py`

Cobertura observada:

- login;
- criação de entrada `fabeo`;
- busca por CPF;
- busca sem `mode`;
- decrypt-package autorizado;
- rejeição explícita de `aes_gcm`, `tde`, `column_level` e `app_level`.

Execução:

```bash
python tests/integration_smoke.py
```

### `tests/revocation_integration.py`

Cobertura observada:

- cria uma entrada com política contendo `epoch.2026`;
- tenta rotacionar para `epoch.2027`;
- se a revogação estiver desabilitada, o script apenas informa e encerra;
- se a rotação passar, espera `403` no decrypt posterior.

Execução:

```bash
python tests/revocation_integration.py
```

Interpretação:

- este teste depende de um branch experimental do sistema;
- no estado padrão do `.env.example`, a revogação está desabilitada.

## 2. Scripts de demonstração

### `scripts/demo/smoke_test.sh`

Função:

- smoke mínimo do endpoint `/health`.

Execução:

```bash
./scripts/demo/smoke_test.sh
```

### `scripts/demo/revocation_demo.py`

Função:

- demonstra o endpoint `/entries/meta/epoch/rotate`;
- imprime o resultado do decrypt após a rotação.

Execução:

```bash
python scripts/demo/revocation_demo.py
```

### `scripts/demo/insider_tests.py`

Intenção:

- validar cenários em que o usuário consegue buscar metadados, mas não descriptografar;
- validar negação por política incompatível.

Observação importante:

- o snapshot inspecionado mostra usernames legados (`nurse`, `receptionist`) que não coincidem com o seed atual (`nurse_clinic`, `receptionist_frontdesk`);
- por isso, este script deve ser tratado como artefato de demonstração que pode exigir ajuste local antes da execução.

Execução:

```bash
python scripts/demo/insider_tests.py
```

## 3. Validação interna CP-ABE

### `services/machs_main_api/app/validation/cpabe_validation.py`

Função:

- executa iterações controladas com usuários autorizados e não autorizados;
- verifica:
  - decrypt autorizado;
  - decrypt negado;
  - ausência de plaintext em blobs do banco;
  - que a autorização está vindo do fluxo CP-ABE.

Execução típica dentro do container:

```bash
docker compose exec machs_main_api python -m app.validation.cpabe_validation
```

## 4. Benchmark simples

### Arquivos

- `scripts/benchmark/run_benchmark.sh`
- `scripts/benchmark/run_benchmark.py`
- `scripts/benchmark/summarize.py`

### Operações medidas por iteração

1. `POST /entries`
2. `GET /entries/{entry_id}/cipher`
3. `POST /entries/{entry_id}/decrypt-package`

### Métricas produzidas

| Métrica | Significado |
| --- | --- |
| `write_latency_ms_avg` | média do tempo de criação da entrada |
| `read_latency_ms_avg` | média do tempo de leitura do endpoint `cipher` |
| `decrypt_latency_ms_avg` | média do tempo do decrypt-package |
| `storage_overhead_bytes_avg` | média do tamanho da resposta do endpoint `cipher` |

### Execução

Wrapper POSIX:

```bash
BENCHMARK_ITERATIONS=15 ./scripts/benchmark/run_benchmark.sh
```

Execução direta:

```bash
python scripts/benchmark/run_benchmark.py \
  --base-url http://localhost:8000 \
  --iterations 15 \
  --out scripts/benchmark/output/results.json
```

Resumo:

```bash
python scripts/benchmark/summarize.py \
  --in scripts/benchmark/output/results.json \
  --out scripts/benchmark/output/summary.md
```

### Saídas

- `scripts/benchmark/output/results.json`
- `scripts/benchmark/output/summary.md`

### Limitações de interpretação

- mede somente `fabeo`;
- não mede CPU e memória automaticamente;
- `storage_overhead_bytes_avg` usa o tamanho da resposta do endpoint `cipher`, não o tamanho bruto de cada coluna do banco;
- serve para comparação arquitetural local, não para alegações de desempenho de produção.

## 5. Suíte de validação experimental

### Arquivos

- `scripts/validation/run_validation.py`
- `scripts/validation/observer_validation.py`

### Etapas executadas por `run_validation.py`

| Etapa | Objetivo |
| --- | --- |
| `abe_functional` | validar decrypt autorizado/negado e integridade do plaintext recuperado |
| `abac_insider` | validar cenários de insider com foco em bloqueio e não exposição |
| `db_observer` | validar ausência de plaintext observável no banco |

### Execução

```bash
python scripts/validation/run_validation.py --iterations 500 --out-dir scripts/validation/output/<nome>
```

Parâmetros relevantes:

- `--base-url`
- `--iterations`
- `--mode` (somente `fabeo`)
- `--out-dir`
- `--seed`
- `--db-dsn` opcional

### Artefatos gerados

Na raiz de saída:

- `validation_results.json`
- `validation_summary.csv`
- `validation_report.md`

Artefatos adicionais:

- tabelas `expected.csv` e `observed.csv` por etapa/cenário;
- diretórios `quantitative/.../summary_metrics.csv`;
- arquivos da etapa `db_observer`.

### Métricas e critérios da validação

#### `abe_functional`

Mede, entre outros:

- `expected_allowed`
- `expected_denied`
- `correct_decryptions`
- `correct_denials`
- `false_positives`
- `false_negatives`
- `integrity_ok_count`
- `integrity_ok_rate_pct`

#### `abac_insider`

Por cenário, produz:

- `total_attempts`
- `n_bloqueio`
- `n_exposicao`
- `rho_bloqueio`
- `rho_exposicao`
- `false_positives`
- `false_negatives`
- `validation_passed`

#### `db_observer`

Produz:

- `total_rows_checked`
- `plaintext_rows_detected`
- `plaintext_detection_rate`
- `validation_passed`

### Interpretação esperada

Uma execução ideal deve apresentar:

- `false_positives = 0`
- `false_negatives = 0`
- `integrity_ok_count = expected_allowed`
- `n_exposicao = 0` em todos os cenários insider
- `plaintext_rows_detected = 0`

Se qualquer um desses pontos falhar, o relatório final tende a marcar `final_pass = false`.

## 6. Observer validation isolado

### `scripts/validation/observer_validation.py`

Função:

- rodar apenas a etapa `db_observer`;
- gerar diagnósticos detalhados adicionais.

Execução:

```bash
python scripts/validation/observer_validation.py --iterations 1 --out-dir scripts/validation/output/<nome>
```

## 7. Dependências práticas e limitações

- `make` e `sh` podem não estar disponíveis em PowerShell puro.
- O benchmark simples e os scripts demo assumem stack já saudável.
- A validação de observador de banco usa acesso via `psql` no container PostgreSQL.
- O sucesso de cenários de revogação depende de um branch experimental ainda incompleto.
- A QA histórica do repositório menciona um `tests/test_policy_and_normalization.py`, mas o arquivo-fonte não está presente no snapshot inspecionado.

## 8. Como interpretar os resultados com rigor

- Trate benchmarks como medidas do MVP local, não como prova de desempenho universal.
- Trate `search` como vazamento controlado de metadados, não como autorização de leitura.
- Trate a etapa `db_observer` como verificação empírica de ausência de plaintext detectável, não como prova formal de segurança criptográfica.
- Trate a trilha de revogação como experimento arquitetural, não como mecanismo maduro de revogação operacional.
