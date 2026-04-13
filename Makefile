SHELL := /bin/sh

.PHONY: setup up down logs reset seed test bench

setup:
	cp -n .env.example .env || true
	git submodule update --init --recursive

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

reset:
	./scripts/reset/reset_all.sh

seed:
	./scripts/seed/seed_all.sh

test:
	./scripts/demo/smoke_test.sh

bench:
	./scripts/benchmark/run_benchmark.sh
