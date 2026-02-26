# Reframe API

FastAPI service for jobs/assets/project orchestration in Reframe.

## Run locally

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

OpenAPI docs:

- `http://localhost:8000/docs`
- `http://localhost:8000/openapi.json`

## Usage + Projects endpoints (examples)

Usage summary:

```bash
curl -sS "http://localhost:8000/api/v1/usage/summary"
```

Usage summary filtered by project + date range:

```bash
curl -sS "http://localhost:8000/api/v1/usage/summary?project_id=<PROJECT_ID>&from=2026-01-01T00:00:00Z&to=2026-12-31T23:59:59Z"
```

Create a project:

```bash
curl -sS -X POST "http://localhost:8000/api/v1/projects" \
  -H "Content-Type: application/json" \
  -d '{"name":"Campaign A","description":"Spring launch clips"}'
```

List project jobs:

```bash
curl -sS "http://localhost:8000/api/v1/projects/<PROJECT_ID>/jobs"
```

Generate signed share links for project assets:

```bash
curl -sS -X POST "http://localhost:8000/api/v1/projects/<PROJECT_ID>/share-links" \
  -H "Content-Type: application/json" \
  -d '{"asset_ids":["<ASSET_ID>"],"expires_in_hours":24}'
```

Resolve a signed share link:

```bash
curl -I "http://localhost:8000/api/v1/share/assets/<ASSET_ID>?token=<TOKEN>"
```
