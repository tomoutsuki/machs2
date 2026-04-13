#!/bin/sh
set -eu

echo "[reset] stopping stack and removing db volume"
docker compose down -v

echo "[reset] starting stack"
docker compose up --build -d

echo "[reset] done"
