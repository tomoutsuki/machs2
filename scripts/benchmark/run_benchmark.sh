#!/bin/sh
set -eu

BASE_URL=${BASE_URL:-http://localhost:8000}
ITERATIONS=${BENCHMARK_ITERATIONS:-15}
OUT_DIR=scripts/benchmark/output
mkdir -p "$OUT_DIR"

python scripts/benchmark/run_benchmark.py --base-url "$BASE_URL" --iterations "$ITERATIONS" --out "$OUT_DIR/results.json"
python scripts/benchmark/summarize.py --in "$OUT_DIR/results.json" --out "$OUT_DIR/summary.md"

echo "benchmark complete: $OUT_DIR/summary.md"
