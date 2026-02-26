# Security Policy

## Supported Versions

| Version | Supported |
| --- | --- |
| `main` | Yes |
| Tagged releases older than latest minor | No |
| Archived snapshot branches (for example `archive/*`) | No |

## Scope

This policy applies to production code and automation in:

- `apps/`
- `services/`
- `packages/`
- `.github/workflows/`

Legacy snapshot code kept only for reference is out of support and must not be deployed.

## Reporting a Vulnerability

Please use GitHub Security Advisories for private disclosure:

1. Go to the repository **Security** tab.
2. Click **Report a vulnerability**.
3. Include reproduction steps, impact, and affected commit/tag.

If GitHub private reporting is unavailable, open a private security contact through repository maintainers and include the same detail.

## Response Targets

- Initial acknowledgement: within 3 business days.
- Triage and severity classification: within 7 business days.
- Fix target:
  - Critical/High: as soon as possible, target 14 days.
  - Medium: target 30 days.
  - Low: best effort in scheduled maintenance.

## Disclosure Process

We follow coordinated disclosure:

1. Confirm and triage.
2. Prepare and validate fix.
3. Publish patch/release notes.
4. Publicly disclose advisory details after a fix is available.

## Severity Guidance

Severity is assessed by exploitability + impact:

- Critical: remote compromise, data exfiltration, privilege escalation.
- High: significant integrity/confidentiality risk requiring urgent patching.
- Medium: bounded impact or mitigated by environment constraints.
- Low: low-impact or defense-in-depth findings.

## Dependency and Supply Chain Policy

- Dependency updates are managed through Dependabot.
- High and critical advisories are prioritized.
- Unsupported archived code is isolated from `main` and excluded from active maintenance.
