.PHONY: help api-install worker-install web-install api-dev worker-dev web-dev web-build compose-up compose-down python-compile python-test web-test verify smoke-hosted smoke-local smoke-security smoke-workflows smoke-perf-cost release-readiness

PYTHON ?= python

help:
	@echo "Targets: api-install, worker-install, web-install, api-dev, worker-dev, web-dev, web-build, compose-up, compose-down, verify, smoke-hosted, smoke-local, smoke-security, smoke-workflows, smoke-perf-cost, release-readiness"

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

release-readiness:
	@set -eu; \
	STAMP="$$(date -u +%F)"; \
	mkdir -p docs/plans; \
	$(PYTHON) scripts/generate_benchmark_sample.py --out samples/sample.wav --duration 12 >/dev/null; \
	set +e; \
	PYTHON=$(PYTHON) $(MAKE) verify > "docs/plans/$$STAMP-make-verify.log" 2>&1; VERIFY_EXIT=$$?; \
	PYTHON=$(PYTHON) $(MAKE) smoke-hosted > "docs/plans/$$STAMP-smoke-hosted.log" 2>&1; HOSTED_EXIT=$$?; \
	PYTHON=$(PYTHON) $(MAKE) smoke-local > "docs/plans/$$STAMP-smoke-local.log" 2>&1; LOCAL_EXIT=$$?; \
	PYTHON=$(PYTHON) $(MAKE) smoke-security > "docs/plans/$$STAMP-smoke-security.log" 2>&1; SECURITY_EXIT=$$?; \
	PYTHON=$(PYTHON) $(MAKE) smoke-workflows > "docs/plans/$$STAMP-smoke-workflows.log" 2>&1; WORKFLOWS_EXIT=$$?; \
	PYTHON=$(PYTHON) $(MAKE) smoke-perf-cost > "docs/plans/$$STAMP-smoke-perf-cost.log" 2>&1; PERF_COST_EXIT=$$?; \
	bash scripts/run_diarization_benchmarks.sh samples/sample.wav --stamp "$$STAMP" > "docs/plans/$$STAMP-diarization-orchestrator.log" 2>&1; DIAR_EXIT=$$?; \
	set -e; \
	$(PYTHON) scripts/release_readiness_report.py --stamp "$$STAMP" --verify-exit "$$VERIFY_EXIT" --smoke-hosted-exit "$$HOSTED_EXIT" --smoke-local-exit "$$LOCAL_EXIT" --smoke-security-exit "$$SECURITY_EXIT" --smoke-workflows-exit "$$WORKFLOWS_EXIT" --smoke-perf-cost-exit "$$PERF_COST_EXIT" --diarization-exit "$$DIAR_EXIT"

compose-up:
	cd infra && docker compose up --build

compose-down:
	cd infra && docker compose down
