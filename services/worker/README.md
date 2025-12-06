# Reframe Worker

Celery worker skeleton using Redis for broker/result.

## Quick start

```
BROKER_URL=redis://redis:6379/0 \
RESULT_BACKEND=redis://redis:6379/0 \
celery -A worker.celery_app worker --loglevel=info
```

Tasks available:
- `tasks.ping`
- `tasks.echo`
