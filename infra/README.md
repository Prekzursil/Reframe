# infra

Infrastructure and deployment configuration.

## Quickstart

1. Copy one of the example env files to the repo root:
   - `cp infra/examples/env.local-dev.example .env` (local dev)
   - `cp infra/examples/env.small-server.example .env` (server-ish defaults)
2. Start services:
   - `make compose-up` (Docker Compose)
   - or run locally: `make api-dev`, `make worker-dev`, `make web-dev`
