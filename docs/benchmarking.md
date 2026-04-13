# Benchmarking

Scripts:
- scripts/benchmark/run_benchmark.sh
- scripts/benchmark/run_benchmark.py
- scripts/benchmark/summarize.py

Compared modes:
- fabeo
- aes_gcm
- tde
- column_level
- app_level

Measured metrics:
- write latency (ms avg)
- read latency (ms avg)
- decryption latency (ms avg)
- approximate storage overhead (response bytes as proxy)
- CPU/memory observation (manual docker stats during run)

Run:

BENCHMARK_ITERATIONS=15 ./scripts/benchmark/run_benchmark.sh

Output:
- scripts/benchmark/output/results.json
- scripts/benchmark/output/summary.md

Note:
In this local MVP, TDE is represented as a comparison mode with equivalent table shape and documented simulation assumptions.
