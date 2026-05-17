# Benchmarking Guide

## 1. Goal

The benchmark compares end-to-end API behavior across encryption modes in a reproducible local setup.

Compared modes:

- `fabeo`
- `aes_gcm`
- `tde`
- `column_level`
- `app_level`

## 2. Scripts and Responsibilities

- `scripts/benchmark/run_benchmark.sh`
	- wrapper script
	- reads `BASE_URL` and `BENCHMARK_ITERATIONS`
	- executes benchmark and summary generation
- `scripts/benchmark/run_benchmark.py`
	- performs timed API operations
	- writes raw JSON metrics
- `scripts/benchmark/summarize.py`
	- converts raw JSON to markdown table

Output files:

- `scripts/benchmark/output/results.json`
- `scripts/benchmark/output/summary.md`

## 3. What Is Measured

For each mode, each iteration runs this sequence:

1. `POST /entries` (write path)
2. `GET /entries/{entry_id}/cipher` (metadata read path)
3. `POST /entries/{entry_id}/decrypt-package` (authorization + decrypt material path)

Recorded metrics per mode:

- `write_latency_ms_avg`
- `read_latency_ms_avg`
- `decrypt_latency_ms_avg`
- `storage_overhead_bytes_avg`

Metric details:

- latencies are arithmetic means over iterations, measured with `time.perf_counter()`
- storage overhead uses response byte length from `/entries/{entry_id}/cipher` as local proxy

## 4. Workload Characteristics

- Each iteration creates a synthetic `Patient` resource with distinct id/CPF.
- Benchmark user is `doctor_general_clinic`.
- New login session is created for each mode run.
- Default iterations: `15` (configurable).

## 5. Execution

From repository root:

```bash
BENCHMARK_ITERATIONS=15 ./scripts/benchmark/run_benchmark.sh
```

Optional variables:

- `BASE_URL` (default `http://localhost:8000`)
- `BENCHMARK_ITERATIONS` (default `15`)

Equivalent direct command:

```bash
python scripts/benchmark/run_benchmark.py \
	--base-url http://localhost:8000 \
	--iterations 15 \
	--out scripts/benchmark/output/results.json
```

Then summarize:

```bash
python scripts/benchmark/summarize.py \
	--in scripts/benchmark/output/results.json \
	--out scripts/benchmark/output/summary.md
```

## 6. Environment Controls and Reproducibility

To improve comparability across runs:

- run with stable host load
- keep same Docker resource limits
- avoid concurrent traffic
- keep seed/reset settings consistent between runs

Recommended preparation:

1. start all services and wait for healthy state
2. run one smoke test to warm caches/paths
3. execute benchmark at least 3 times and compare medians externally

## 7. Interpreting Results Correctly

Important MVP interpretation constraints:

- `tde`, `column_level`, and `app_level` currently share the same AES envelope implementation path in application code for local comparability.
- `fabeo` mode uses bridge simulation behavior when `FABEO_ALLOW_SIMULATION=true`.
- Therefore, benchmark output is most useful for architectural overhead comparisons within this MVP, not as production cryptographic performance claims.

## 8. Optional Manual Observability

The scripts do not capture CPU/RAM directly. Use manual observation during benchmark:

```bash
docker stats
```

Correlate spikes with mode currently being executed.

## 9. Failure Modes and Troubleshooting

- `401/403` errors during run:
	- verify credentials and session cookie behavior
	- ensure seeded users are present
- connection errors:
	- verify all services healthy (`docker compose ps`)
- mode-specific `403` on decrypt-package:
	- review policy and epoch settings
- inconsistent numbers:
	- check host load and rerun with fixed environment
