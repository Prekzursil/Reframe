# Reframe Trust-Wave Plan — Auto-Updater Authenticity + Electron 39→43

> **Status:** DRAFT

**Date:** 2026-07-11
**Repo:** `Prekzursil/Reframe` (local `C:/Users/Prekzursil/Documents/GitHub/Reframe`)
**Audit P0:** the electron-updater feed is UNSIGNED — integrity (SHA512 in `latest.yml`) but NOT authenticity. A party controlling the feed serves a matching malicious `(latest.yml, installer)` pair → silent RCE via auto-update.
**Constraints:** no paid cert; security always-on; TDD; 100% branch coverage; never `--no-verify`; never force-push.

---

## 0. Decision (TL;DR)

1. **Authenticity — implement NOW:** **Option 1 — Ed25519 detached signatures, verified in-app against an embedded public key** (the minisign / Doyensec-SafeUpdater design), using **Node's built-in `crypto`** (Ed25519 verify + SHA-512) — **zero new runtime dependency**. Signing is a human/CI release step with an offline private key; verification runs fully offline inside the shipping app. It gates BOTH the `update-downloaded → ready` transition AND `quitAndInstall()` (with a TOCTOU re-verify), and forces `autoInstallOnAppQuit = false` to close a confirmed silent-install bypass.
2. **Electron 39→43 — DEFER to its own PR; ship authenticity FIRST.** The two changes are orthogonal (release/verify path vs runtime/build), have no dependency between them, and must stay independently green/revertible. Doing authenticity first also means the Electron-bump release is itself signed, exercising the new signed path during the bump.

Both research streams (authenticity + Electron-43) converged on exactly this, independently, at **high confidence**. Direct code inspection of the current repo confirms the seams and sharpens the exact edits below.

---

## 1. Authenticity options — graded (no paid cert)

| # | Option | Free? | No CI-migration? | In-app verify complexity | Provenance | Fits repo TDD/100%-branch | Verdict |
|---|--------|:----:|:----:|--------|--------|--------|--------|
| **1** | **Ed25519 / minisign detached sig, embedded pubkey, verify in-app** | ✅ | ✅ (works with today's manual release) | **Low** (~pure fn, built-in crypto) | Same-signer (no build provenance) | **✅ trivial — pure function** | **CHOSEN — implement now** |
| 2 | GitHub build-provenance attestations (SLSA, `actions/attest-build-provenance`, keyless Sigstore) | ✅ | ❌ (**requires** moving the manual build into Actions) | High (bundle Sigstore verifier + pin identity + TUF trusted-root rotation) | **Strong** (ties artifact→commit+workflow) + Rekor transparency | Hard (heavy branch logic, trusted-root maintenance) | **LATER hardening** — layer on top once/if build lives in CI |
| 3 | cosign / Sigstore sign-blob (keyless-in-CI or static key) | ✅ | ❌ keyless / ⚠️ static-key | High (Sigstore verifier, or ship a large cosign binary — can't bundle into app) | keyless=strong; static-key=none | Hard | **Dominated** — keyless = Option 2 minus SLSA; static-key = Option 1 + heavier deps |
| 4 | electron-updater built-in Authenticode / Squirrel.Mac verify | ❌ | — | Zero (if you have a cert) | Cert identity | n/a | **INFEASIBLE** — needs a paid Authenticode/EV cert; owner rejects |
| — | Status quo: SHA512-in-`latest.yml` only | ✅ | ✅ | none | none | n/a | **REJECTED baseline** — this IS the P0 (integrity ≠ authenticity) |

### Why Option 1 wins (decisive)
- **The only option that needs no certificate AND no CI-build migration.** Reframe's installer is a **manual, human-run local build** (embeddable CPython staging, ffmpeg, Remotion bundle — confirmed: `.github/workflows` has only `quality`/`mutation`/`e2e`, **no release workflow**). Options 2/3 keyless *require* the release build to run inside GitHub Actions (the OIDC identity *is* the workflow) — a separate, substantial project.
- **Fully offline verification, essentially zero new runtime dependency.** Node/Electron built-in `crypto` does Ed25519 verify (`crypto.verify(null, msg, pubkey, sig)` — `null` algorithm is the Ed25519 form) and SHA-512. No `@noble/ed25519`, no Sigstore, no TUF trusted-root, no transparency-log fetch. (`@noble/hashes@2.2.0` is already transitively in the app tree, but we don't even need it.)
- **The verifier is a PURE FUNCTION** (bytes + sig + pubkey + version → bool), trivially unit-testable to the repo's mandatory 100% branch bar with good/bad/missing/tampered/wrong-version/malformed/wrong-key fixtures — no network, no cert, no packaged app. It mirrors the exact injected-seam style already in `keystore.ts` and `updater.test.ts`.
- **Closes the exact P0:** a compromised feed can serve any `latest.yml` + installer + `.sig` bytes, but cannot forge a valid Ed25519 signature over `version‖sha512(file)` without the offline private key. Version-binding also blocks downgrade/rollback.
- **Matches the Feb-2026 Doyensec SafeUpdater reference** for this precise unsigned-electron-updater threat model, and is **purely additive** — it does not weaken existing hardening.

**Residual (accepted):** long-lived private key to protect (passphrase + offline / Actions secret; compromise is game-over, no revocation); no build provenance / transparency log; key rotation needs an app update (mitigated by embedding a **current + next** public key). These are exactly the gaps Option 2 later fills without replacing the Ed25519 gate.

---

## 2. Chosen design — precise mechanics

**Signed message (version-bound, one canonical digest):**
```
message = `${version}\n${sha512_base64}`
```
where `sha512_base64` is the installer's SHA-512 — the **same digest electron-builder already emits into `latest.yml`**, so we introduce no second hash. The app **recomputes** SHA-512 from the actually-downloaded bytes on disk and requires it to equal the value inside the signed message → the signature is bound to exactly what will be installed, not to a feed-supplied claim.

**Two-point verification (defense-in-depth), gate at the APP layer — NOT the built-in hook:**
1. On `update-downloaded` (which carries `downloadedFile: string` — confirmed via electron-builder `UpdateDownloadedEvent`): recompute `sha512(downloadedFile)`, fetch the detached `.sig` release asset, rebuild `message`, `crypto.verify(null, message, EMBEDDED_PUBKEY[current|next], sig)`, and assert `version` is not a downgrade. **Only on success** broadcast `{state:'downloaded'}` (the renderer's "Restart to update" affordance); on failure broadcast `{state:'error', message:'update signature verification failed'}` and latch `verified=false`.
2. On `UPDATE_INSTALL_CHANNEL`: **refuse `quitAndInstall()` unless `verified===true`**, and **re-verify immediately before** calling it (shrinks the TOCTOU window between download-verify and install).

**Why NOT electron-updater's `verifyUpdateCodeSignature(publisherName, path)` hook:** issue **#4701** ("Update is installed even though signature verification fails") shows that seam **fail-opens** — a rejected verification can still install. So we gate at our own app layer where a failed verify provably prevents install.

**CRITICAL latent bypass to fix in the same change — `autoInstallOnAppQuit`:** electron-updater's `BaseUpdater` registers `addQuitHandler()` right after `update-downloaded`; with `autoInstallOnAppQuit` defaulting **TRUE**, a downloaded update **auto-installs via `install(true,false)` on app quit (exit 0) WITHOUT ever crossing our `UPDATE_INSTALL_CHANNEL`** — i.e. it would install an **unverified** update behind the gate. Today's `updater.ts` never sets it. We force **`autoInstallOnAppQuit = false`** (next to the existing `autoDownload = false`) so the ONLY install path is our explicit, verified `quitAndInstall`. This is a real, confirmed hole, not hygiene.

**Key custody:** private key NEVER in repo or app — passphrase-protected, held offline on the release machine (and/or a GitHub Actions secret if/when release moves to CI). App embeds `CURRENT` + `NEXT` public keys (rotation bootstrap). `.sig` uploaded as a GitHub release asset beside the installer.

---

## 3. Exact FILE changes (authenticity PR)

Anchored to the current code (`app/main/updater.ts` 191 lines, `main.ts:763-779` `wireAutoUpdater`, `keystore.ts` house style).

1. **`app/main/updateVerify.ts` — NEW (pure, no Electron import; only `node:crypto` + `node:fs`).** Mirrors `keystore.ts` idioms (injected deps, exported pure fns, CodeQL `safeFilePath` path-injection barrier, typed result union). Exports:
   - `EMBEDDED_UPDATE_PUBLIC_KEYS` — `readonly [current, next]` base64 Ed25519 SPKI constants (placeholder until real keys are generated at release-key-ceremony time).
   - `buildSignedMessage(version: string, sha512B64: string): string` — canonical `` `${version}\n${sha512B64}` `` (single source of truth, imported by the signing script so sign/verify can never drift).
   - `sha512Base64(bytes: Buffer): string`.
   - `verifyEd25519(message: string, sigB64: string, pubKeysB64: readonly string[]): boolean` — accepts current OR next key; `crypto.verify(null, Buffer.from(message), keyObject, Buffer.from(sigB64,'base64'))`; catches malformed-key/sig → `false` (never throws).
   - `isNotDowngrade(candidate: string, current: string): boolean` — semver-ish monotonic guard.
   - `verifyDownloadedUpdate(deps): Promise<VerifyResult>` (`{ok:true} | {ok:false, reason}`) — orchestrates recompute-hash → fetch `.sig` (injected `fetchSig`) → `buildSignedMessage` → `verifyEd25519` → downgrade check; NEVER throws (fetch/parse errors → `{ok:false, reason}`).
2. **`app/main/updateVerify.test.ts` — NEW.** Exhaustive branch fixtures: valid sig; tampered file (hash mismatch); wrong version; downgrade; missing/404 `.sig`; malformed sig (bad base64 / wrong length); wrong key; `next`-key acceptance; `fetchSig` throws; `verifyEd25519` malformed-key path. Target 100% branch.
3. **`app/main/updater.ts` — EDIT.**
   - Add `autoInstallOnAppQuit: boolean` to `AutoUpdaterLike`; set `autoUpdater.autoInstallOnAppQuit = false` in `registerUpdater` (beside `autoDownload = false`, ~line 129).
   - Add `downloadedFile?: string` to `UpdateInfoLike`.
   - Extend `UpdaterDeps` with an injected `verify: (info) => Promise<VerifyResult>` (default `verifyDownloadedUpdate`) and the `fetchSig` transport.
   - `update-downloaded` handler (~line 139): capture `{version, downloadedFile}` as `pendingUpdate`; run `verify`; success → latch `verified=true` + broadcast `{state:'downloaded', version}`; failure → latch `verified=false` + broadcast `{state:'error', message}` (do NOT surface a ready state).
   - `UPDATE_INSTALL_CHANNEL` handler (~line 176): refuse unless `verified===true`; **re-verify (TOCTOU)** before `quitAndInstall()`; on refusal return `{ok:false, reason}` + broadcast `{state:'error'}`; never call `quitAndInstall` on an unverified/failed update.
   - Rewrite the header comment (remove "we deliberately do NOT add signing"; document the Ed25519 authenticity gate — OS-level Authenticode stays off, app-level authenticity is now ON).
4. **`app/main/updater.test.ts` — EDIT.** Add `autoInstallOnAppQuit` to the fake `AutoUpdaterLike`; assert it's forced `false`; add cases: verified → install allowed; unverified/failed-verify → install refused (`quitAndInstall` NOT called); TOCTOU re-verify path; `update-downloaded` gates the `downloaded` broadcast on verify success/failure. Keep the suite at 100%.
5. **`app/main/main.ts` — EDIT (`wireAutoUpdater`, lines 763-779 + the WU-U comment ~746-761).** Provide the `fetchSig` transport (Electron `net`/`https` GET of the `.sig` release asset derived from the feed base + installer name) and inject `verifyDownloadedUpdate`; the cast at line 765 now also carries `autoInstallOnAppQuit`. Update the comment block to state the Ed25519 gate + `autoInstallOnAppQuit=false`.
6. **`app/main/preload.ts` — NO CHANGE (deliberate).** Verify-failure reuses the existing `{state:'error'}` variant, so the mirrored `UpdateStatus` union + 4 channels (lines 40-43, 134) are untouched — smallest possible renderer surface, protecting the renderer's 100% bar. *(Optional future: a dedicated `{state:'rejected'}` variant for a clearer "possible tampering" message would touch `preload.ts` + `UpdateBanner` + the `updater.ts` union — deferred.)*
7. **`build/sign-release.mjs` — NEW (human/CI release step, not shipped in the app).** Reads the private key from env `REFRAME_UPDATE_PRIVATE_KEY` (passphrase-protected PKCS8 / raw seed — NEVER in repo; validated-present at start per security floor); globs `dist/*-win-x64.exe`, reads `version`, computes SHA-512, **imports `buildSignedMessage` from `updateVerify.ts`** (no format drift), Ed25519-signs, writes `dist/<installer>.sig` (base64). Optional companion unit test for its pure path.
8. **`electron-builder.yml` — EDIT (comment/docs only).** Extend the build-steps header (lines 9-14) with step **4b: `node build/sign-release.mjs`** (after electron-builder, before publish) and reconcile the "Signing stays OFF" narrative (OS Authenticode still off; app-level Ed25519 authenticity now ON). No packaging-field change.

---

## 4. Exact CI / release-process changes (authenticity PR)

- **`app/vitest.config.ts` — EDIT (genuine CI-enforced change).** Today `coverage.include` is `['renderer/src/**/*.{ts,tsx}']` → `main/**` tests **run but are not threshold-gated**. Because this is a P0 security gate, add the new/critical main modules to the **enforced 100%** include:
  `include: ['renderer/src/**/*.{ts,tsx}', 'main/updateVerify.ts', 'main/updater.ts']`.
  This makes the authenticity verifier CI-gated at 100% branch, not merely conventionally tested. **Caveat (verified by reading the code):** promoting `updater.ts` into the enforced set surfaces one pre-existing blind spot — `errText()`'s non-empty-**string** branch is not exercised by any current test (all throws are `Error`/`undefined`). Add a one-line test for it in the same PR so the gate stays green. (If preferred, enforce only `updateVerify.ts` now and add `updater.ts` once that test lands — but folding it in is the honest, security-first call.)
- **`.github/workflows/quality.yml` — NO EDIT NEEDED.** The new `*.test.ts` files auto-run under the existing `gate-tests-coverage vitest app` step (they match `main/**/*.test.ts` in `test.include`). The new coverage assertions ride the same step.
- **`osv-scanner` / lockfiles — NO new CVE surface.** Verification uses **built-in `crypto`** → **zero new runtime dependency** added to `app/package.json`, so `gate-deps osv-scanner` and the lockfiles are unchanged. (Explicit design win.)
- **Signing is a documented human/CI RELEASE step, not a `quality.yml` job.** It runs `build/sign-release.mjs` after electron-builder; the `.sig` assets publish alongside the installer (`electron-builder --publish` for the artifacts, then `gh release upload dist/*.sig`, or include them in the publish step). This matches the current **manual, no-release-workflow** reality and needs no new workflow file.
- **Later (Option 2, out of scope here):** if/when the installer build moves into Actions, add a release workflow with `permissions: id-token: write, attestations: write, contents: read` running `actions/attest-build-provenance` — layered *on top of* the Ed25519 gate, not replacing it.

---

## 5. TDD / coverage plan

- **RED→GREEN, house style:** write `updateVerify.test.ts` fixtures first (they fail), then implement `updateVerify.ts`; extend `updater.test.ts` for the gate + `autoInstallOnAppQuit`, then edit `updater.ts`. Mirror the injected-fake pattern already in `updater.test.ts` (fake `AutoUpdaterLike`, mocked `ipcMain`) and `keystore.test.ts` (fake `SafeStorageLike`, tmp dirs).
- **Branch matrix (100%):** valid / tampered-file / wrong-version / downgrade / missing-sig / malformed-sig / wrong-key / next-key-accepted / fetch-throws / verify-throws / verified-install-allowed / unverified-install-refused / TOCTOU-re-verify.
- **Run the full 9-step quality gate locally** before PR (pre-commit, tsc ×2, basedpyright, pytest `--cov-branch --cov-fail-under=100`, `vitest run --coverage`, opengrep, osv-scanner, charter) per `.coverage-thresholds.json` (the single source of truth: renderer + sidecar at 100/100).
- Purely additive; no existing hardening weakened.

---

## 6. Electron 39→43 — VERDICT: separate PR, ship AFTER authenticity

**Ship as its own PR. Reasons:** (1) orthogonal surfaces — authenticity touches release/verify, the bump touches runtime/build (Chromium 142→150, Node 22→24, NSIS); (2) risk isolation/revertibility — a combined PR can't tell an auto-update break from the Electron bump vs the signature gate; (3) priority — authenticity is a P0 security fix, fully unit-testable and fast; the bump is broad maintenance whose real risk (packaged-app behavior) CI can't see and needs a manual smoke matrix; (4) no dependency — Ed25519 works with the current local release, so it doesn't wait on any CI change, and doing it first means the Electron-bump release is itself signed.

**Still worth doing soon:** Electron 39 is **already EOL (2026-05-05)** — no more Chromium security patches. E43 (Chromium **150.0.7871.46** / Node **24.17.0** / V8 **15.0**) is current stable, supported to 2027-01-05. So the bump is security-maintenance, just decoupled.

### Migration checklist (the Electron-bump PR)
1. Branch `chore/electron-43`. `app/package.json`: `electron ^39.0.0 → ^43.0.0` (consider pinning a specific 43.x) and `@types/node ^20 → ^24` (match the Node 24 runtime). Keep `electron-builder ^26.15.3`, `electron-updater ^6.8.9`, `electron-vite ^3.1.0`, `esbuild` override `^0.28` — all E43/Node-24 compatible.
2. `npm install` in `app/` and `npm --prefix render-cli install`; re-run `render-cli:bundle`.
3. `npm run typecheck` (tsc) — fix any Node24/E43 type deltas; `vitest run --coverage` must stay 100% (source unchanged; updater/security tests use injected fakes → Electron-version-agnostic). Then the full 9-step gate.
4. **E43 behavioral change to handle:** `dialog.showOpenDialog`/`showSaveDialog` now default `defaultPath` to the **Downloads** folder AND the OS no longer restores the last-used dir. Audit `app/main/dialogIpc.ts` (`showOpenDialog`, currently **no** `defaultPath`) and any `showSaveDialog`; pass an explicit `defaultPath` (or accept Downloads as intended UX). Everything else in 40→43 is macOS/Linux/PDF/offscreen/clipboard-in-renderer — **N/A** for this Windows-x64, sandboxed, `contextIsolation:true` app.
5. **Native/ABI is LOW-risk (key de-risking finding):** the `app/` package has **no in-process native `.node` addons** (deps are `electron-updater`/`react`/`react-dom`, all pure JS; `npmRebuild:false`/`nodeGypRebuild:false`). The Python sidecar is a **separate process** (embeddable CPython, decoupled from Electron's Node ABI); render-cli's Remotion compositor is a **separate binary**; the only `.node` (`@rspack/binding-win32-x64-msvc`) is **N-API (ABI-stable) and build-time only**. No native rebuild required for Node 22→24 — but reinstall render-cli `node_modules` + re-bundle as cheap insurance.
6. **electron-builder/electron-updater:** both compatible with E43; `electron-builder.yml` needs no change for the bump. Revalidate only the slim-size budget (`build/make-portable.ps1` assertions) — E43 binaries are larger than E39; the <~700 MB slim target could shift.
7. **HUMAN packaged smoke test (CI does not build the installer):** build NSIS+zip, install, launch, verify sidecar boot; **video/proxy playback under Chromium 150 codecs** (`mstream` scheme + `PLAYABLE_EXTENSIONS`); export/save dialogs (new Downloads default); DPAPI keystore; a real Remotion render under `ELECTRON_RUN_AS_NODE`; and **CRITICALLY the auto-update round-trip** (a prior version detects → downloads → **verifies, if the authenticity PR landed** → `quitAndInstall` upgrades in place preserving userData). Re-check `make-portable.ps1` size assertions.

### Top E43 risks (ranked)
R1 packaged in-place auto-update round-trip regression (CI-invisible — the highest-value manual test). R2 Chromium 142→150 renderer/video-playback regressions. R3 Node 22→24 behavior in main + render-cli under `ELECTRON_RUN_AS_NODE`. R4 E43 `dialog.defaultPath`→Downloads. R5 electron-builder NSIS/`latest.yml`/blockmap + slim-size budget shift. R6 `@types/node` 20 vs runtime 24 mismatch. R7 (minor) rspack N-API binding (ABI-stable → low). R8 32-bit ending after 43.x — N/A (x64).

---

## 7. Residual risks / follow-ups
- **Private-key custody & rotation** — offline/passphrase; embed current+next pubkeys; a lost/compromised key needs an out-of-band new pubkey via an app update (no revocation). Document a key-ceremony runbook.
- **TOCTOU** — narrowed (re-verify before `quitAndInstall`), not eliminated; acceptable for a same-user desktop threat model.
- **No provenance/transparency** — the acknowledged Ed25519 gap; **Option 2 (GitHub attestations)** is the right *later* hardening once the build lives in Actions — it strengthens, never replaces, the Ed25519 gate.
- **SmartScreen** — unchanged (needs Authenticode); out of scope for the no-paid-cert P0 fix.

---

## 8. Sources & confidence

**Confidence: HIGH** (both research streams converged independently; every load-bearing external claim re-verified against primary sources + direct repo inspection). The one inherent unknown is packaged-app runtime regressions on the Electron bump — discoverable only via the manual smoke matrix (step 7 of the checklist), which is why that PR is decoupled.

- Doyensec, *Building a Secure Electron Auto-Updater* (2026-02-16) — embedded-Ed25519 + SHA512 + signed-manifest design for unsigned apps; TOCTOU caveat. https://blog.doyensec.com/2026/02/16/electron-safe-updater.html
- `doyensec/ElectronSafeUpdater` — reference impl (embedded pubkey, `.sig` assets, version-bound message). https://github.com/doyensec/ElectronSafeUpdater
- electron-updater **#4701** — "Update installed even though signature verification fails" (the built-in `verifyUpdateCodeSignature` fail-open → gate at app layer). https://github.com/electron-userland/electron-builder/issues/4701
- electron-builder `UpdateDownloadedEvent` — carries `downloadedFile: string`; `verifyUpdateCodeSignature(publisherName: string[], path) => Promise<string|null>`. https://www.electron.build/electron-updater.Interface.UpdateDownloadedEvent.html · https://www.electron.build/docs/api/electron-updater/
- electron-updater `BaseUpdater` `addQuitHandler()` / `autoInstallOnAppQuit` default TRUE → auto-`install()` on quit (the confirmed bypass). (electron-builder `packages/electron-updater/src/BaseUpdater.ts`, via Context7 `/electron-userland/electron-builder`)
- Node.js `crypto.verify(null, data, publicKey, signature)` — Ed25519 verify (`null` algorithm) with built-in crypto, KeyObject or raw key. https://nodejs.org/api/crypto.html · https://github.com/nodejs/help/issues/2203
- `actions/attest-build-provenance` (SLSA, keyless Sigstore) — the Option-2 later-hardening path. https://github.com/actions/attest-build-provenance · offline verify needs bundle + `trusted_root.jsonl`: https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline
- Minisign (Frank Denis) — Ed25519 detached sigs, prehashed mode for large files. https://jedisct1.github.io/minisign/
- Electron 43 stack + breaking changes — Chromium 150.0.7871.46 / Node 24.17.0 / V8 15.0; `dialog.defaultPath`→Downloads; `showHiddenFiles` removed on Linux. https://www.electronjs.org/blog/electron-43-0 · https://www.electronjs.org/docs/latest/breaking-changes · https://github.com/electron/electron/releases/tag/v43.0.0
- Electron EOL calendar (E39 EOL 2026-05-05; E43 → 2027-01-05). https://endoflife.date/electron
- **Reframe repo inspection:** `app/main/updater.ts` (unconditional `quitAndInstall`; no verify; `autoInstallOnAppQuit` unset), `app/main/updater.test.ts` (injected-fake seam), `electron-builder.yml` (github publish, signing OFF, `npmRebuild:false`), `app/package.json` (`electron ^39`, `electron-updater ^6.8.9`, `electron-builder ^26.15.3`, `@types/node ^20`), `app/vitest.config.ts` (renderer-only 100% include), `.github/workflows/{quality,mutation,e2e}.yml` (no release workflow), `app/main/keystore.ts` (the injected-seam / CodeQL-barrier house style to mirror), `app/main/dialogIpc.ts` (`showOpenDialog`, no `defaultPath`), `app/main/preload.ts` (mirrored `UpdateStatus` union).
