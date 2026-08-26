# Scrollshot Markdown wiring

Date: 19.08.2026

## What is wired

Reframe now has a job-based scrollshot Markdown flow:

- backend core: `sidecar/media_studio/features/scrollshot.py`
- RPC/job facade: `sidecar/media_studio/features/scrollshot_markdown.py`
- composition registration: `sidecar/media_studio/handlers/composition.py`
- renderer panel: `app/renderer/src/features/ScrollshotMarkdown.tsx`
- workspace tab mounting: `app/renderer/src/views/Workspace.tsx`

The RPC name is `scrollshot.exportMarkdown`.

Request:

```json
{
  "videoId": "optional-video-id",
  "path": "optional-direct-path",
  "title": "optional-title",
  "language": "eng",
  "assurance": "strict | balanced | best-effort"
}
```

Start response:

```json
{
  "jobId": "job-...",
  "kind": "scrollshot.exportMarkdown"
}
```

Terminal result currently includes canonical job metadata plus the bundle paths and hashes:

- `schemaVersion`
- `runId`
- `verdict`
- `reviewRequired`
- `warnings`
- `panoramaPaths`
- `manifestPath`
- `markdownPath`
- `imagePath`
- `observationsPath`
- `conflictsPath`
- `coverageVerdict`
- `sourceSha256`
- `markdownSha256`
- `imageSha256`

## Bundle contract

Each successful run publishes one immutable bundle under `exports/scrollshots/<bundle-id>/` with:

- `scrollshot.md`
- `long-screenshot.png`
- `observations.json`
- `conflicts.json`
- `manifest.json`

The exporter stages into a hidden temp directory, verifies source and artifact hashes, then atomically publishes the final directory.

## Current verification state

Verified:

- focused backend gate: `tests/test_scrollshot.py` + `tests/test_scrollshot_markdown.py`
- focused renderer gate: `renderer/src/features/ScrollshotMarkdown.test.tsx` + `renderer/src/views/Workspace.test.tsx`
- direct offline OCR path now uses the installed Tesseract executable instead of `pytesseract`

Not yet green:

- `tests/test_scrollshot_real_media_e2e.py`

The real-media suite is the remaining quality gate for the overlap solver and compositor.

## Recommended MCP + skill stack

Use this feature with a small, explicit control plane:

- `basic-memory`
  - persist failure modes, sample clips, and accepted parameter choices
- `agent-mail`
  - coordinate backend, renderer, and review passes without hidden context drift
- Playwright MCP
  - drive the Reframe UI and assert job progress, terminal payloads, and artifact reveal actions

Skills to keep attached to this flow:

- `deep-research`
  - refresh document/OCR stack choices when upstream releases move
- `agent-skills-toolchain:gem-hunt`
  - periodically re-scan for better OCR/document MCP candidates
- `python-testing`
  - keep the sidecar path pinned to explicit regression tests
- `playwright`
  - keep the renderer path pinned to deterministic UI verification

## Scope boundary

This repo change wires the feature into Reframe itself. It does not auto-edit shared global MCP registries under `.agents` or runtime profile files under `.codex`; those are broader machine-level changes and should be done deliberately after the real-media gate is green.
