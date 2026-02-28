.PHONY: help api-install worker-install web-install api-dev worker-dev web-dev web-build compose-up compose-down python-compile python-test web-test verify smoke-hosted smoke-local release-readiness

PYTHON ?= python

help:
	@echo "Targets: api-install, worker-install, web-install, api-dev, worker-dev, web-dev, web-build, compose-up, compose-down, verify, smoke-hosted, smoke-local, release-readiness"

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

release-readiness:
	@set -eu; \
	STAMP="$$(date -u +%F)"; \
	mkdir -p docs/plans; \
	set +e; \
	PYTHON=$(PYTHON) $(MAKE) verify > "docs/plans/$$STAMP-make-verify.log" 2>&1; VERIFY_EXIT=$$?; \
	PYTHON=$(PYTHON) $(MAKE) smoke-hosted > "docs/plans/$$STAMP-smoke-hosted.log" 2>&1; HOSTED_EXIT=$$?; \
	PYTHON=$(PYTHON) $(MAKE) smoke-local > "docs/plans/$$STAMP-smoke-local.log" 2>&1; LOCAL_EXIT=$$?; \
	bash scripts/run_diarization_benchmarks.sh samples/sample.mp4 --stamp "$$STAMP" > "docs/plans/$$STAMP-diarization-orchestrator.log" 2>&1; DIAR_EXIT=$$?; \
	set -e; \
	$(PYTHON) scripts/release_readiness_report.py --stamp "$$STAMP" --verify-exit "$$VERIFY_EXIT" --smoke-hosted-exit "$$HOSTED_EXIT" --smoke-local-exit "$$LOCAL_EXIT" --diarization-exit "$$DIAR_EXIT"

compose-up:
	cd infra && docker compose up --build

compose-down:
	cd infra && docker compose down
