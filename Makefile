.PHONY: up down test build format format-check storage-plan storage-init storage-migrate backup

up:
	python scripts/containers.py up --build

down:
	python scripts/containers.py down

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

storage-plan:
	python scripts/storage.py plan

storage-init:
	python scripts/configure_notebooks.py
	python scripts/storage.py init

storage-migrate:
	python scripts/configure_notebooks.py
	python scripts/storage.py migrate

backup:
	python scripts/storage.py backup
