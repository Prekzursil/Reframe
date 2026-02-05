.PHONY: help api-install worker-install web-install api-dev worker-dev web-dev web-build compose-up compose-down tools-ffmpeg sample-media

help:
	@echo "Targets: api-install, worker-install, web-install, api-dev, worker-dev, web-dev, web-build, compose-up, compose-down"

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

compose-up:
	cd infra && docker compose up --build

compose-down:
	cd infra && docker compose down

tools-ffmpeg:
	bash scripts/install_ffmpeg_local.sh

sample-media:
	bash scripts/generate_sample_media.sh
