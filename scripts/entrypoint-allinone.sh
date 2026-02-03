#!/usr/bin/env bash
set -euo pipefail

uvicorn app.main:app --host 0.0.0.0 --port 8000 &
api_pid=$!

celery -A services.worker.worker.celery_app worker --loglevel=info &
worker_pid=$!

trap 'kill $api_pid $worker_pid' SIGINT SIGTERM

wait -n "$api_pid" "$worker_pid"
