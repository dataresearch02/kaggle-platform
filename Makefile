.PHONY: up down test build format format-check storage-plan storage-init storage-migrate backup check deploy deploy-plan deploy-releases deploy-rollback

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

# OpenShift (ocp4.lab.local): build changed images offline, push, roll out. See deploy/README.md.
check:
	python3 deploy/pipeline.py check $(ARGS)

deploy-plan:
	python3 deploy/pipeline.py plan

deploy:
	python3 deploy/pipeline.py run $(ARGS)

deploy-releases:
	python3 deploy/pipeline.py releases

deploy-rollback:
	python3 deploy/pipeline.py rollback $(ARGS)
