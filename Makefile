.PHONY: up down test build format format-check

up:
	docker compose up --build -d

down:
	docker compose down

test:
	cd apps/api && ../../.venv/bin/python -m pytest -q

build:
	cd apps/web && npm run build

format:
	npm run format
	.venv/bin/python -m black apps/api infra scripts

format-check:
	npm run format:check
	.venv/bin/python -m black --check apps/api infra scripts
