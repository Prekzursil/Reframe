# Reframe — "Reconcile, Don't Rebuild" Gap Dossier

> **Status:** ARCHIVED 2026-08-08

**Scope:** four read-only audits (WS-C readiness, WS-D keys, WS-D usage, WS-E Director) folded into one build-ready plan.
**Governing principle:** almost everything asked for already exists and ships. The work is to RECONCILE new capability requirements onto existing wire types / RPCs / components — NOT to rebuild. The single true build-out is the WS-D *storage* side (OS secret store) plus three small key-management RPCs and the Director current-video wiring.

---

## Executive summary — the one key gap

**KEY GAP:** API keys are stored and transmitted in **PLAINTEXT** (raw JSON in `%APPDATA%/media-studio/settings.json` + raw over the IPC/stdin pipe); `docs/_archive/2026-06/DESIGN-GATE-1.md` R2(c) mandates an OS secret store (DPAPI/Keychain/libsecret) and **that half is not implemented**. Everything else (add, validate, remove, usage bars, spend cap, readiness roll-up, reframe degrade-notices) already exists and only needs reconciliation, not a rebuild.

---

## Area 1 — WS-D: API-Key UI (reveal / edit / re-validate)

### Exists today
- **Add key + validate:** `AddKeyRow.tsx` (paste `<input type=password>` → `onAdd`) → `ProvidersKeys.addKey` (`ProvidersKeys.tsx:320-360`) validates via `providers.testKey({baseUrl, apiKey, model, capabilities})` then **always** stores via `providers.upsert({id, apiKeys:[...existingKeys, key]})` — note it **appends**.
- **Validate RPC:** `providers.testKey` (`providers_ops.py:96-127`) — one `chat(max_tokens=1)`; returns `{ok, capabilities?}` or scrubbed `{ok:false,error}`; never echoes the key.
- **Remove key / remove provider / consent toggles / usage bars:** all present. `ProviderKeyRow.tsx:20-41` renders only `redactedKey` (last-4) + **Remove**.

### Precise gap (three missing, all structural)
1. **No reveal.** No `providers.revealKey` RPC in `providers_ops.py`; the renderer *structurally cannot* reveal because the full key never crosses RPC (`redact_keys` at `settings_store.py:178-185`, `providers_ops.py:42-50`, `secrets.py:75-97`). **Fix:** new guarded RPC `providers.revealKey({id,index})` reading `get_raw()` (`settings_store.py:187`).
2. **No edit-in-place.** `ProviderKeyRow` offers only Remove; `AddKeyRow` only appends (`[...existingKeys, key]`, `ProvidersKeys.tsx:349`). `providers.upsert` merges whole entries by `id`, not per-key-index (`providers_ops.py:53-80`). **Fix:** index-targeted replace — extend `upsert` or add `providers.editKey({id,index,apiKey})`.
3. **No re-validate of a stored key.** `providers.testKey` requires a raw `apiKey` the renderer can't supply for a stored entry (`providers_ops.py:105-108`); the `tested` map only reflects the last in-session add and `removeKey` resets it to `false` (`ProvidersKeys.tsx:376`). **Fix:** server variant `providers.testKey({id,index})` that reads `get_raw()`.

### Storage & transit (the real build-out)
- **At rest — PLAINTEXT:** `SettingsStore._write` writes raw `providers[].apiKeys` (`settings_store.py:158-163`) to `%APPDATA%/media-studio/settings.json`. Good: outside any shareable/project folder. Bad: no encryption.
- **In transit — PLAINTEXT over stdio:** raw key travels renderer → `window.api.rpc` → `ipcMain.handle('rpc')` (`ipc.ts:58-61`) → `Sidecar.request` → `child.stdin.write(JSON.stringify(...))` (`sidecar.ts:354-377`). Local-only (stdio, not network) but still cleartext. Redaction is read-path-only; the write path carries raw.
- **Design intent vs reality:** `docs/_archive/2026-06/DESIGN-GATE-1.md` R2(c) mandates *"API keys in OS secret store (DPAPI/Keychain/libsecret), excluded from the shareable project folder."* The "excluded from project folder" half is met; the **DPAPI/secret-store half is NOT** — this is WS-D's storage gap.

### Recommended build (surgical seams)
- **A) Main-side keystore (recommended over sidecar crypto):** new `app/main/keystore.ts` owning `safeStorage.encryptString/decryptString` (currently **zero** `safeStorage` usage in repo). Keys never persist in `settings.json`; sidecar stores an opaque placeholder, main holds the DPAPI-encrypted vault. Single choke point that yields raw keys today = `settings_store.py:187 get_raw()` → provider factory (`providers_ops.py:417-439`).
- **B) Per-request key handoff:** inject at `sidecar.ts request()` (`:354-377`) or `ipc.ts` RPC handler (`:58-61`): before writing stdin, main decrypts and substitutes the real key for key-consuming methods; re-redacts on reads. Ultimate consumer = `provider.py _OpenAICompatProvider._headers` (`:293-298`, `Authorization: Bearer <key>`); rotation entry = `_cloud_specs_from_settings` (`:753-776`). The existing `get`/`get_raw` + `redact`/`scrub` split is the clean foundation — only *where raw comes from* changes.
- **C) Three new key-management RPCs** (none exist): `providers.revealKey({id,index})`, index-targeted edit, `providers.testKey({id,index})` — all read via `get_raw()` because the renderer cannot supply a raw key for a stored entry.

---

## Area 2 — WS-D: Usage-tracking UI

### Exists today (three surfaces, all in "Models & System" panel + Providers & Keys)
1. **`UsageBar.tsx` (`:180-248`)** — per-key request/token quota bars; groups by `unit`, never sums req+token; stale rows (>10 min) desaturate. Fed from `providers.usage` (`client.ts:514`, shape `UsageRow` `schemas.ts:681`).
2. **`OpenRouterUsage.tsx` (`:20-80`)** — per-key cost/credit rows, OpenRouter only. Fed from `providers.openrouterUsage` (`client.ts:520`, `OpenRouterUsageRow` `schemas.ts:576`).
3. **`SpendCap.tsx`** — monthly $ cap (soft/hard + MTD). Reads `providers.spend` (`client.ts:526`, `SpendInfo` `schemas.ts:736`).

### Data sources (all local; one real provider API)
- **(A) Request/token bars — local counters, NOT a provider API.** `providers_usage` (`providers_ops.py:153-195`) folds the in-process rotation pool `usage()` over `settings.usageCache`. `used` = optimistic +1 per success (`provider.py:660-667`); `max`/`remaining` only if provider echoes `X-RateLimit-*` headers (`provider.py:503-521`). Explicitly "NOT a poller."
- **(B) OpenRouter cost — the ONLY real usage-API call.** `providers_openrouter_usage` (`providers_ops.py:198-218`) → `GET https://openrouter.ai/api/v1/key` per raw key.
- **(C) Monthly spend — placeholder estimate.** `providers_spend` (`providers_ops.py:221-239`) reads `SpendLedger`; spend = `requests × PLACEHOLDER_CENTS_PER_REQUEST` where **`= 1`** (`spend_ledger.py:49`). Flagged in-code as a falsifiable stand-in.

### Precise gaps (for true "per-provider per-API usage")
1. **No native OpenAI usage API** (`/v1/organization/usage/*`, `/costs`, admin key). Not called — OpenAI usage only appears via `X-RateLimit-*` headers if OpenAI is a pool provider.
2. **No native Anthropic usage API** (Admin Usage & Cost API). Not called; no Anthropic-specific path exists — it would only appear as a generic OpenAI-compatible base URL (header counters only).
3. **No real cost for non-OpenRouter providers** — cost/credit USD is OpenRouter-exclusive.
4. **Spend is a 1¢/request placeholder**, unrelated to real billing.
5. **Header-dependent ceilings** — providers without `X-RateLimit-*` render `max=null` (unknown ceiling, `UsageBar.tsx:73-77`).
6. **No token telemetry from response bodies** — `usage.total_tokens` never parsed; token keys decremented by the same +1/request logic.

### Reconcile plan (don't rebuild the UI)
- Keep all three components + wire shapes. Add dedicated usage-API clients for OpenAI + Anthropic (admin-key reads) that emit the **existing** `UsageRow`/cost row shapes. Replace the 1¢ placeholder with catalog-driven per-model pricing (and/or provider cost APIs). Parse real `usage.total_tokens` from completion bodies to feed `unit:"token"` rows. No new panels required — the shapes already exist.

---

## Area 3 — WS-E: Director panel

**File:** `app/renderer/src/panels/DirectorPanel.tsx` (under `panels/`, not `features/`).

### (1) Current-video source — THERE IS NONE WIRED IN
`DirectorPanel` reads **no app-level video selection**. Only imports: React, CSS, `../lib/rpc`, `../lib/directorTypes` (`:20-51`). Props interface exposes only `rpcClient` + `jobEvents` for test injection (`:117-122`); `App.tsx:342` mounts a bare `<DirectorPanel />` with **no props**.

**The app DOES hold a selected video:** `App.tsx:176` `const [editVideo, setEditVideo] = useState<Video|null>(null)`, set by `openVideo` from Library (`App.tsx:255-256`, `Library onOpen={openVideo}` at `:350`), and passed to the Edit tab (`<Edit video={editVideo}>` at `:338`). **The Director tab is handed nothing.** The only "video" the panel can reference is `plan.videoId` from a *prior* plan (`DirectorEditPlan`, `schemas.ts:1115-1118`); on first run `plan` is `null`, so no real video identity exists.

**ANSWER (directorVideoSource):** The Director panel currently has **no** current-video source — it is mounted prop-less at `App.tsx:342`. The app's selected video lives in `App.tsx:176 editVideo` (set by `openVideo`, already passed to the Edit tab). The fix is to thread that same `editVideo` (its `videoId`) into `<DirectorPanel video={editVideo} />` and use `video.id` as arg1 of `director.plan`.

### (2) The ~line 226 fallback bug
`DirectorPanel.tsx:226` (inside `submit`):
```ts
const job = await api.director.plan(plan?.videoId ?? trimmed, trimmed);
```
Client signature: `plan(videoId: string, goal: string)` (`client.ts:649`). On a first action there is no prior `plan`, so `plan?.videoId` is `undefined` and `?? trimmed` passes the **goal text itself as the videoId** — `director.plan(<goal>, <goal>)`. The Director then resolves a video whose id is the literal sentence typed → mis-fires against a non-existent/garbage id. It only "works" on a *re-plan* (then `plan.videoId` is populated); `adjust` (`:293-295`) carries only the goal forward, not any video. **Root cause:** the panel has no wiring to `editVideo`, so it has no correct value for arg1.

**Fix:** thread the selected video in and replace the fallback:
```ts
// App.tsx: <DirectorPanel video={editVideo} ... />
const videoId = video?.id ?? plan?.videoId;
if (!videoId) { /* surface "open a video first" empty-state; do NOT submit */ return; }
const job = await api.director.plan(videoId, trimmed);
```
Never fall back to `trimmed` as the videoId. When no video is selected, show an empty-state prompt (mirror the Edit tab's `video`-gated behavior) instead of submitting.

### (3) Existing explainer / example UI
- `:340-343` intro paragraph (`.director-intro`): *"Describe the change you want in plain language. The Director plans a reviewable, reversible edit — nothing is applied until you confirm."*
- `:358` textarea placeholder example: *"e.g. make the scrolling smooth, or turn this into a Q&A showcase"*.
- No coach-mark/onboarding overlay (contrast: models panel has full 3-step `ModelsOnboarding`). Reuse static copy; add a modal only if a first-run coach-mark/apply-confirm is wanted.

### (4) Focus-trap pattern to reuse — `useFocusTrap`
`renderer/src/hooks/useFocusTrap.ts` (`:53-111`) does the WAI-ARIA trio: focus `initialFocus`→first focusable→container (`:75-77`); traps Tab/Shift+Tab (`:85-101`); Escape→`onEscape` (`:80-83`); restores focus to opener on unmount (`:106`). Options `{onEscape?, initialFocus?}`. `ModelsOnboarding.tsx:44` uses it: `const trapRef = useFocusTrap<HTMLDivElement>({onEscape: onDone})` on a `role="dialog" aria-modal="true"` container. Any Director modal (coach-mark / apply-confirm) should follow this exact pattern — reuse, don't rebuild.

---

## Area 4 — WS-C: Readiness infra + capability-per-profile reconcile

### Exists today (everything asked for ships)
- **RPC `readiness.summary()`** — single source of truth, read-only, ZERO network/provider calls, triggers no `assets.ensure`. Registered `composition.py:114`; handler `library_ops.py:306-338`; roll-up builders in `_wire.py` (`_tier_readiness_items` `:152-173`, `_function_readiness_items` `:176-214`, `_readiness_item` `:251-261`).
- **Two axes → one flat `items[]`:**
  - **Model tiers** (`_READINESS_TIERS`, `_wire.py:115-123`): `tier0-numeric` (always ready), `tier1-multimodal` (saliency/audio_saliency/scene_transnet/vlm_backbone/quality_gate), `tier2-vlm` (smolvlm2). Missing weight → `needsDownload` + `assets.ensure` action with exact asset names; Offline → `unavailable` (`_wire.py:166-172`). Component→asset map `_COMPONENT_ASSETS` (`:62-75`).
  - **AI functions** (`_READINESS_FUNCTIONS`, `_wire.py:128`: `select, subtitles, translation, vision, editPlan`): local→`ready`; cloud no key→`needsKey`(`openProviders`); key but no consent→`needsConsent`(`setConsent`; `vision`=FRAME, others=TEXT, `:202-206`).
- **Wire type** (`schemas.ts:644-672`): `ReadinessStatus = ready|needsDownload|needsKey|needsConsent|unavailable`; `ReadinessAction = {kind: assets.ensure|openProviders|setConsent; assets?; provider?}`; `ReadinessItem = {capability,label,status,blockedBy,action}`.
- **UI:** `ReadinessBadge.tsx` (status by text + `role="status"`, WCAG 1.4.1), `readinessMeta.ts` (label/class/hint + `readinessActionLabel()`), `ReadinessRollup.tsx` (calls `readiness.summary()`, forwards fix clicks to `onAction`). Mounted in **two** places titled "What works right now": Library home (`Library.tsx:394`) and Models & System (`ModelsSystemPanel.tsx:52,636-640`, whose `handleReadinessAction` routes `openProviders`/`setConsent`→Providers & Keys, `assets.ensure`→download).

### Precise gap for WS-C capability-per-profile matrix
Readiness is keyed at **tier** (tier0/1/2) + **AI-function** granularity — **NOT per end-user feature** (reframe, short-maker, subtitles…). **Reconcile plan:** add a thin **feature→(tiers + functions) mapping layer** that composes existing items; the `ReadinessItem` shape (`capability`, `label`, `status`, `action`) is already the correct primitive. No new wire type, no new RPC, no new badge — the matrix is a roll-up view over the existing `items[]`.

### Minimum-install behavior (does it silently center-crop? NO)
- **Always-on tracker = default `claudeshorts` engine** (`reframe.py:328-363`: `auto`/blank→`claudeshorts`, no WSL probe, no model download). Subject finder is a **degrade CHAIN** (`reframe_claudeshorts.py:768-794`): **face (MediaPipe→OpenCV haar) → HOG body → inter-frame MOTION saliency → centered crop**. MediaPipe/cv2 are pip deps; motion saliency is a pure diff → runs on a Minimum install with no downloaded models.
- **NOT silent.** NO-SILENT-FALLBACK contract (`reframe_claudeshorts.py:881-962`): a center crop from "no trackable subject"/detector failure still encodes but is surfaced loudly as a typed `REFRAME_DEGRADED_NOTICE` (`:149`, "speaker tracking unavailable ({reason}) — used center crop", + MediaPipe-missing hint `:156-158`). A true provisioning failure (no cv2/mediapipe) raises `ClaudeShortsBackendUnavailableError` and **fails the job loudly** (`:908-914`).
- **Flagship `reframe_multispeaker`** (explicit opt-in; `auto` never selects it) is what needs weights: **S3FD + LR-ASD** (`reframe_multispeaker.py:82-85`), gated by `default_models_present()` (`:833-856`); absent → `MultiSpeakerUnavailableError` or loud degrade to `claudeshorts`. Cold-start shot 1 → deterministic `select_dominant`, never blind center crop (`:44-47, 899-909`).
- **CORRECTION: there is NO "YuNet" anywhere in the repo** (zero matches). Face stack is MediaPipe/haar (claudeshorts) or S3FD (multispeaker).
- **ViNet-S saliency is a SEPARATE, on-demand, non-commercial tier-1 signal** (`saliency.py`): `vinet-s-saliency`, 36 MB, CC-BY-NC-SA 4.0. Feeds Phase-8 moment-finding/`select` scoring, NOT the reframe crop tracker. Missing+offline → `SignalTrack(present=False, signals=())` — never raises, never fabricates zeros; scorer drops the channel and re-normalizes. Gated behind `tier1-multimodal → needsDownload` in the roll-up.

**Bottom line:** a Minimum install does NOT silently center-crop — the default engine runs MediaPipe/haar→HOG→motion with no downloads, any collapse to center crop is a typed `reframe.degraded` notice (or a loud provisioning failure). ViNet-S is an independent on-demand signal that degrades to `present=False`.

---

## Consolidated build order (reconcile-first)

1. **WS-D storage (only true build-out):** `app/main/keystore.ts` with `safeStorage` DPAPI vault + per-request handoff at `sidecar.ts request()`/`ipc.ts`. Sidecar holds placeholders/ciphertext; raw enters only at `provider.py _headers`.
2. **WS-D three key RPCs:** `providers.revealKey({id,index})`, index-targeted edit, `providers.testKey({id,index})` — all via `get_raw()`. Add reveal/edit/re-check controls to `ProviderKeyRow`.
3. **WS-E Director:** thread `editVideo` into `<DirectorPanel video={editVideo}/>`; replace the `:226` `?? trimmed` fallback with `video?.id ?? plan?.videoId` + a "select a video first" empty-state guard.
4. **WS-C matrix:** add a feature→(tier+function) mapping layer composing existing `ReadinessItem`s; no new wire type/RPC/UI.
5. **WS-D usage (optional depth):** add OpenAI/Anthropic admin usage clients emitting existing row shapes; replace 1¢ placeholder with catalog pricing; parse real `total_tokens`.
