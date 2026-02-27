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

## Hosted collaboration + billing (Stripe test mode)

The hosted collaboration/billing paths are feature-gated. Keep local mode free by default:

- `REFRAME_HOSTED_MODE=false`
- `REFRAME_ENABLE_BILLING=false`
- `REFRAME_ENABLE_OAUTH=false`

Enable hosted+billing in `.env` when you want to validate org seats + Stripe flows in test mode:

```bash
REFRAME_HOSTED_MODE=true
REFRAME_ENABLE_BILLING=true
REFRAME_APP_BASE_URL=http://localhost:5173
REFRAME_STRIPE_SECRET_KEY=sk_test_...
REFRAME_STRIPE_WEBHOOK_SECRET=whsec_...
REFRAME_STRIPE_PRICE_PRO=price_...
REFRAME_STRIPE_PRICE_ENTERPRISE=price_...
```

### Invite-link collaboration flow (link-first)

Create invite (owner/admin):

```bash
curl -sS -X POST "http://localhost:8000/api/v1/orgs/invites" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"email":"editor@example.com","role":"editor","expires_in_days":7}'
```

List/revoke invites:

```bash
curl -sS "http://localhost:8000/api/v1/orgs/invites" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"

curl -sS -X POST "http://localhost:8000/api/v1/orgs/invites/<INVITE_ID>/revoke" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

Resolve/accept invite token:

```bash
curl -sS "http://localhost:8000/api/v1/orgs/invites/resolve?token=<INVITE_TOKEN>"

curl -sS -X POST "http://localhost:8000/api/v1/orgs/invites/accept" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"token":"<INVITE_TOKEN>"}'
```

### Seat enforcement endpoints

Read seat usage:

```bash
curl -sS "http://localhost:8000/api/v1/billing/seat-usage" \
  -H "Authorization: Bearer <ACCESS_TOKEN>"
```

Update seat limit (billing enabled + Stripe subscription required):

```bash
curl -sS -X PATCH "http://localhost:8000/api/v1/billing/seat-limit" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"seat_limit":8}'
```

Checkout session with seat quantity:

```bash
curl -sS -X POST "http://localhost:8000/api/v1/billing/checkout-session" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"plan_code":"pro","seat_limit":8}'
```

### Stripe webhook events consumed

The API syncs subscription/seat state from these events:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid`
- `invoice.payment_failed`
- `invoice.finalized`
