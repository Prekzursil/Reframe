.PHONY: help api-install worker-install web-install api-dev worker-dev web-dev web-build compose-up compose-down python-compile python-test web-test verify

help:
	@echo "Targets: api-install, worker-install, web-install, api-dev, worker-dev, web-dev, web-build, compose-up, compose-down, verify"

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
	python -m compileall apps/api services/worker packages/media-core

python-test:
	PYTHONPATH=.:apps/api:packages/media-core/src python -m pytest apps/api/tests services/worker packages/media-core/tests

web-test:
	cd apps/web && npm test

verify: python-compile python-test web-test web-build

compose-up:
	cd infra && docker compose up --build

compose-down:
	cd infra && docker compose down
