# Reframe v1.3 — Settings (Providers & Keys) RECONCILE gap list

**WU:** D1 (WS-D · Settings — reconcile, don't rebuild) · **Branch:** `feat/reframe-v1.3` (base v1.2.0 + Wave-1).
**Status:** audit + characterization only — **no behaviour changed**. This document scopes D2–D4.
**Characterization lock:** `sidecar/tests/test_settings_provider_surface_characterization.py` (6 tests, all green on
the current tree). Every gap below is pinned there so a D2–D4 fix is diff-visible in review.

This is a **reconcile**, not a rebuild. The Settings key + usage surface already ships and works; the gaps are
security-of-storage and three missing key-management verbs. Do **not** re-create the components below — complete
and repair them.

---

## 1. What already ships (verified against the current code — keep it)

### Renderer (`app/renderer/src/`)
| Component | Path | Responsibility (current) |
|---|---|---|
| `ProvidersKeys` | `features/ProvidersKeys.tsx` | Composition root: loads `providers.list/catalog/usage` + `settings.get` consent; renders provider cards, the add-a-provider picker, usage, and `SpendCap`. Owns all provider RPC calls. |
| `ProviderKeyRow` | `components/ProviderKeyRow.tsx` | One **redacted** stored key (last-4) + **Remove**. Stateless, no RPC, no reveal, no edit. |
| `AddKeyRow` | `components/AddKeyRow.tsx` | Paste a **raw** key into a `type=password` input → hands the trimmed raw value to `onAdd`; clears the field after add. |
| `UsageBar` / `UsageBars` | `components/UsageBar.tsx` | Per-key req/token usage bars (REMAINING fill, WCAG glyph + numeric label, req/token never summed, superpowered state, stale desaturation). Pure presentation. |
| `OpenRouterUsage` | `components/OpenRouterUsage.tsx` | Per-key OpenRouter **cost** rows (USD spent / remaining / limit, free-tier + cooldown). Pure presentation. |
| `SpendCap` | `features/SpendCap.tsx` | Monthly soft/hard spend caps + enforce toggle + MTD meter; reads `providers.spend`, writes `settings.set`. |

### Sidecar (`sidecar/media_studio/`)
| Handler / module | Anchor | Responsibility (current) |
|---|---|---|
| `providers.upsert` | `handlers/providers_ops.py:providers_upsert` | Insert/merge a provider entry; stores **RAW** keys; returns the **redacted** list. |
| `providers.list` | `handlers/providers_ops.py:providers_list` | Configured pool with every key redacted to last-4. |
| `providers.remove` | `handlers/providers_ops.py:providers_remove` | Drop a provider entry by id (idempotent). |
| `providers.testKey` | `handlers/providers_ops.py:providers_test_key` | Validate a key via one minimal completion; returns `{ok, capabilities?}` or `{ok:False, error}` — the key is **scrubbed** from any error and never echoed. |
| `providers.usage` | `handlers/providers_ops.py:providers_usage` | Per-key req/token usage from the rotation pool + persisted `usageCache`; redacted, stale-flagged, no probe socket. |
| `providers.openrouterUsage` | `handlers/providers_ops.py:providers_openrouter_usage` | Best-effort per-key OpenRouter credit usage; the live key rides **only** the `Authorization` header; rows redacted. |
| `providers.spend` | `handlers/providers_ops.py:providers_spend` | Read-only MTD spend + configured caps. |
| `SettingsStore` | `settings_store.py` | JSON doc in the per-user config dir. `get()` redacts keys (RPC-facing); `get_raw()` returns live keys (factory path only, never registered over RPC); `set()` restores redacted round-trip placeholders back to RAW before persisting. |

**Security invariants that already hold (do not regress):** no `providers.*` RPC *response* ever contains a full
key (redacted to last-4 by `SettingsStore.get` / `redact_keys`); `providers.testKey` and `openrouterUsage` scrub /
header-only the key; the raw key lives only in the per-user config file (never a project folder) and is read back
raw solely via the unregistered `get_raw()`.

---

## 2. Confirmed gaps (scope for D2–D4)

### G-1 — Keys are PLAINTEXT AT REST  *(security · owner: D2)*
The raw key is written unencrypted into `settings.json` (`SettingsStore._write` → `json.dumps`, keys stored RAW per
`settings_store.py` docstring + `DEFAULT_SETTINGS["providers"]`). A read of the on-disk file yields the full key.
- **Lock:** `test_stored_provider_key_is_plaintext_at_rest_on_disk`.
- **D2 fix:** Electron `safeStorage` (DPAPI) encrypt-at-rest; one-time migration that re-encrypts legacy plaintext
  and **shreds** all prior copies (`settings.json` + `.tmp` + backups); if `isEncryptionAvailable()` is false →
  refuse to persist (session-only + loud banner), never a silent plaintext fallback.

### G-2 — Raw key crosses stdio INBOUND as a plain RPC param  *(security · owner: D2/D3)*
The plaintext key enters the sidecar as an ordinary JSON-RPC parameter: `providers.upsert({apiKeys:[RAW]})` and
`providers.testKey({apiKey:RAW})`. There is no encrypted or transient inbound channel; the key is in the RPC frame
(and therefore in any param-dumping debug log unless redacted).
- **Lock:** `test_add_validate_remove_key_flow_is_locked` (raw key inline on upsert/testKey) + the plaintext-at-rest lock.
- **D2 fix (R7):** decrypt in Electron main → hand the raw key over the existing stdio frame **per-request, in-memory
  only**; **redact the key from ALL sidecar JSON-RPC debug/param logging** (the outbound responses are already
  redacted — this closes the inbound/log leg).

### G-3 — No REVEAL of a stored key  *(owner: D3)*
There is no `providers.revealKey` handler; `ProviderKeyRow` shows only the last-4 and offers Remove. A user can never
see a stored key to verify/copy it.
- **Lock:** `test_provider_key_and_usage_rpc_surface_snapshot` (asserts `providers.revealKey` absent).
- **D3 fix:** a dedicated explicit-click `providers.revealKey` returning exactly ONE plaintext key, transient,
  masked-by-default, auto-re-mask on blur/timeout — held in a transient ref, **never** written to React
  state/store/telemetry/crash payloads.

### G-4 — No EDIT-IN-PLACE and no RE-VALIDATE of a stored key  *(owner: D3)*
`ProviderKeyRow` has no edit affordance; the only key verbs are add (`AddKeyRow`) and remove. `providers.testKey`
**always** requires the plaintext key + `baseUrl` inline — you cannot re-validate an already-stored key by id, and
there is no "Replace"/edit path. Changing a key today means Remove + re-Add.
- **Lock:** `test_no_revalidate_of_stored_key_by_id` (testKey rejects an id-only / baseUrl-only request) + the
  surface snapshot (no `providers.revalidateKey`).
- **D3 fix:** prefer **"Replace"** (re-runs `providers.testKey` validation on the new value) over free in-place edit,
  plus a per-key **"Re-validate"** action; wire both through the existing `providers.testKey`.

### G-5 (minor) — Usage is real where an API exists; keep it honest  *(owner: D4)*
Usage surfaces are genuine today (`providers.usage` from the rotation pool's parsed rate-limit headers + persisted
cache; `providers.openrouterUsage` from the OpenRouter `GET /key`). The D4 scope is **completion, not rebuild**:
guarantee local request/token counters always increment on real ops, provider-side numbers where an API exists, and
a graceful "usage API not available for `<provider>`" message — **no fabricated/zero-as-real numbers**.
- **Lock:** `test_usage_surface_is_redacted_and_key_free`, `test_openrouter_usage_surface_is_redacted_and_key_free`.

---

## 3. Non-gaps (explicitly NOT to be rebuilt)
- Redaction on every RPC read (already enforced end-to-end).
- Key scrubbing in `providers.testKey` errors and header-only key transport in `openrouterUsage`.
- The usage bar / OpenRouter cost / spend-cap presentation components.
- Consent (`providers.setConsent`), routing/presets, and the provider catalog picker.

## 4. WU → gap map
| WU | Gaps addressed |
|---|---|
| D2 | G-1 (encrypt at rest + migrate/shred), G-2 (transient in-memory key + no-log redaction) |
| D3 | G-2 (reveal channel), G-3 (reveal), G-4 (replace + re-validate), never-in-renderer-state |
| D4 | G-5 (real local + provider-where-available usage, honest unavailable message) |
