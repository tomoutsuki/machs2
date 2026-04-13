#!/bin/sh
set -eu

BASE_URL=${BASE_URL:-http://localhost:8000}

python - <<'PY'
import json
import urllib.request
import urllib.error

base = "http://localhost:8000"

print("health:")
print(urllib.request.urlopen(base + "/health").read().decode())
PY
