.PHONY: help api-install worker-install web-install api-dev worker-dev web-dev web-build compose-up compose-down python-compile python-test web-test verify smoke-hosted smoke-local smoke-security smoke-workflows smoke-perf-cost

PYTHON ?= python

help:
	@echo "Targets: api-install, worker-install, web-install, api-dev, worker-dev, web-dev, web-build, compose-up, compose-down, verify, smoke-hosted, smoke-local, smoke-security, smoke-workflows, smoke-perf-cost"

api-install:
	pip install -r apps/api/requirements.txt

worker-install:
	pip install -r services/worker/requirements.txt

web-install:
	cd apps/web && npm install

api-dev:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --app-dir apps/api

worker-dev:
	cd services/worker && celery -A worker.celery_app worker --loglevel=info

web-dev:
	cd apps/web && npm run dev -- --host 0.0.0.0 --port 5173

web-build:
	cd apps/web && npm run build

python-compile:
	$(PYTHON) -m compileall apps/api services/worker packages/media-core

python-test:
	TMPDIR=/tmp PYTHONPATH=.:apps/api:packages/media-core/src $(PYTHON) -m pytest --rootdir=. apps/api/tests services/worker packages/media-core/tests

web-test:
	cd apps/web && npm test

verify: python-compile python-test web-test web-build

smoke-hosted:
	PYTHON=$(PYTHON) bash scripts/smoke_hosted.sh

smoke-local:
	PYTHON=$(PYTHON) bash scripts/smoke_local.sh

smoke-security:
	PYTHON=$(PYTHON) bash scripts/smoke_security.sh

smoke-workflows:
	PYTHON=$(PYTHON) bash scripts/smoke_workflows.sh

smoke-perf-cost:
	PYTHON=$(PYTHON) bash scripts/smoke_perf_cost.sh

compose-up:
	cd infra && docker compose up --build

compose-down:
	cd infra && docker compose down
