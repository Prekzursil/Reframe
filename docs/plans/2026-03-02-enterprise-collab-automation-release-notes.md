# Release Notes Draft: Enterprise Identity + Collaboration + Publish Automation

Date: 2026-03-02
Branch: `feat/enterprise-collab-automation-2026-03-02`
PR: https://github.com/Prekzursil/Reframe/pull/96

## Highlights

- Added enterprise identity layer with Okta-first SSO + SCIM provisioning endpoints.
- Added advanced project collaboration APIs and UI controls (members, comments, approvals, activity).
- Added multi-platform publish automation flow for YouTube, TikTok, Instagram, and Facebook.
- Hardened strict policy + branch protection observability and ops digest quality metrics.
- Kept local-mode compatibility intact while extending hosted-mode capabilities.

## API Additions

### Identity and SCIM

- `GET /api/v1/orgs/{org_id}/sso/config`
- `PUT /api/v1/orgs/{org_id}/sso/config`
- `POST /api/v1/orgs/{org_id}/sso/scim-tokens`
- `DELETE /api/v1/orgs/{org_id}/sso/scim-tokens/{token_id}`
- `GET /api/v1/auth/sso/okta/start`
- `GET /api/v1/auth/sso/okta/callback`
- `GET/POST/PATCH/DELETE /api/v1/scim/v2/Users*`
- `GET/POST/PATCH/DELETE /api/v1/scim/v2/Groups*`

### Project collaboration

- `GET/POST/PATCH/DELETE /api/v1/projects/{project_id}/members*`
- `GET/POST/DELETE /api/v1/projects/{project_id}/comments*`
- `POST /api/v1/projects/{project_id}/approvals/request`
- `POST /api/v1/projects/{project_id}/approvals/{approval_id}/approve`
- `POST /api/v1/projects/{project_id}/approvals/{approval_id}/reject`
- `GET /api/v1/projects/{project_id}/activity`

### Publish automation

- `GET /api/v1/publish/providers`
- `GET /api/v1/publish/{provider}/connections`
- `GET /api/v1/publish/{provider}/connect/start`
- `GET /api/v1/publish/{provider}/connect/callback`
- `DELETE /api/v1/publish/{provider}/connections/{connection_id}`
- `POST /api/v1/publish/jobs`
- `GET /api/v1/publish/jobs`
- `GET /api/v1/publish/jobs/{job_id}`
- `POST /api/v1/publish/jobs/{job_id}/retry`

## Data Model Additions

- `SsoConnection`, `ScimToken`, `ScimIdentity`, `RoleMapping`
- `ProjectMembership`, `ProjectComment`, `ProjectApprovalRequest`, `ProjectActivityEvent`
- `PublishConnection`, `PublishJob`, `AutomationRunEvent`

Migration:
- `apps/api/alembic/versions/2026030202_enterprise_identity_collab_publish.py`

## Verification Snapshot

- Local gate pack: ✅ (verify + all smoke targets + release-readiness)
- Branch workflow matrix: ✅
  - CI: https://github.com/Prekzursil/Reframe/actions/runs/22596129521
  - Release Readiness: https://github.com/Prekzursil/Reframe/actions/runs/22599124528
  - strict-23 Preflight: https://github.com/Prekzursil/Reframe/actions/runs/22599125516
  - Branch Protection Audit: https://github.com/Prekzursil/Reframe/actions/runs/22599126733
  - Ops Weekly Digest: https://github.com/Prekzursil/Reframe/actions/runs/22599127735
- Readiness summary: `docs/plans/2026-03-02-release-readiness-summary.json` (`READY`)

## Known Follow-up

- Branch-protection API scope in Actions still returns `403 Resource not accessible by integration`; issue `#89` remains as the single active tracker for permission-scope closure.
- Post-merge action required: trigger `release-readiness.yml` on `main` and archive run/artifact link in this release train.
