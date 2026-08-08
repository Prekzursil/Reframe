# Reframe Distribution Posture Audit — installer · updater · code-signing · backward compatibility

> **Status:** ACTIVE

- **Date of audit:** 2026-08-08. Every external price / CA rule below was looked up on **2026-08-08**;
  prices and CA requirements change, so re-check before purchase.
- **Scope:** AUDIT + DESIGN only. This lane does **not** edit `electron-builder.yml`; the installer
  implementation is owned by a separate lane.
- **Honesty contract:** `UNVERIFIED` is attached INLINE to the sentence it qualifies and names the
  settling experiment. Forward-looking claims carry a Sherman-Kent band
  (*almost certain* ≈ 90-99% · *likely* ≈ 55-80% · *roughly even* ≈ 40-60% · *unlikely* ≈ 20-45%).
  External facts carry a URL; repo facts carry `file:line`.

## COVERAGE

| § | Section | State |
|---|---------|-------|
| 0 | Measured baseline + 3 live defects in the existing pipeline | MEASURED |
| 1 | Code-signing options, 2026 prices, recommendation | MEASURED (external, URL-cited) |
| 2 | NSIS component-page design | DESIGNED — hooks + inclusion path measured in the pinned tool; the `.nsh` is **not compiled** (§2.9) |
| 3 | Backward-compatibility test plan | DESIGNED — every path measured to `file:line`; **no sequence executed** |
| 4 | Gap register, ranked by value/effort | MEASURED + ranked |

One claim in an earlier draft of this document was **REFUTED** during self-review and is corrected
in place, with the refutation left visible rather than deleted — see the boxed correction in §0.3/D3.

## ⚠ RECONCILIATION WITH EXISTING v1.5 DOCS — read this before acting on §0.3 or §4

An earlier draft of this audit was written **without first enumerating `docs/plans/v1.5/`**. That was
a process failure on my part and it produced one actively harmful recommendation. Two sibling
documents, both dated 2026-08-08 07:13, already cover part of this ground:

- **`docs/plans/v1.5/signed-release-ci.md`** (36 KB) — a complete two-phase release-signing runbook:
  CI builds → SLSA `actions/attest-build-provenance` → publish to a **DRAFT** release → human
  downloads the exact CI bytes, `gh attestation verify`s them, signs offline with
  `build/sign-release.mjs`, uploads the `.sig`, **then** un-drafts (`:15-16`, `:61-74`, `:267-290`).
- **`docs/plans/v1.5/signed-release-trust-options.md`** (24 KB) — the trust-model options analysis.
- **`docs/plans/v1.5/GRILL-DECISION-QUEUE.md`** — the owner's open decision queue.

### RETRACTED: "un-draft a release" (was G3)

**Do not do this.** `signed-release-ci.md:249` states: *"Draft is the safety interlock. Draft assets
are not served at the public `/releases/download` URL. `updateVerify.ts` fetches the `.sig` from that
public URL, which only resolves after un-draft — so **no client can auto-update to an unsigned
draft.**"* v1.4.1's draft state is therefore **deliberate**, not an oversight. Un-drafting it without
first uploading a `.sig` would ship an unsigned release and defeat the interlock the sibling lane
designed. My original G3 had this as a top-three "~0 d, DO FIRST" action. It was wrong. Retracted.

### D1 and D3 re-framed — the measurements stand, the framing did not

What I verified independently and still stands: no release carries a `.sig`; `dist/` holds 8
installers and zero `*.sig`; `/releases/latest` resolves to v1.4.0; `updateVerify.ts` is absent from
the `v1.4.0` and `v1.4.1` tags. Those are measured facts.

What was overclaimed: the heading "found by this audit" and the framing as undiscovered defects.
`signed-release-ci.md:89` already names the exact failure mode — *"Fail-closed on a missing
signature… **Auto-update stays dark until a real `.sig` is published** — which is why the
draft-then-sign-then-publish ordering is mandatory, not stylistic"* — and `:345` already records the
PoC-key blocker. So **D1/D2 are known and have a designed remediation; D3 is intentional.** The
residual value of §0.3 is the *state* evidence (the runbook has never been executed end-to-end, and
the dry-run at `signed-release-ci.md:325` has not been run), not the diagnosis.

My audit also **omitted SLSA build provenance** entirely, which the sibling design treats as a
first-class complementary layer. Defer to `signed-release-ci.md` on that.

### The Authenticode conflict — surfaced, not silently resolved

`signed-release-ci.md:32` and `§8` put Authenticode explicitly **out of scope** ("stays unsigned",
"no action needed"), and `GRILL-DECISION-QUEUE.md:146` records *"**Signing** stays NONE (already by
design). No SmartScreen concern to solve."*

Per AGENTS.md §10 I surface this rather than pick a side — but the record needs two corrections:

1. **The queue item is OPEN, not decided.** `GRILL-DECISION-QUEUE.md:63` reads
   `[ ] **B-2** Unsigned installer — confirm (memory says signing = NONE by design)` — an unchecked
   box awaiting owner confirmation. §1 is therefore *input to an open decision*, not an override of a
   closed one.
2. **The stated rationale is factually outdated.** "No SmartScreen concern to solve" does not
   address **Smart App Control**, which on Windows 11 *"will block execution of unsigned files unless
   the file has a positive reputation"* and *"applies to all executable files, not just those
   downloaded from the Internet"* ([Microsoft, SmartScreen reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation),
   read 2026-08-08). That is a **block**, not a warning. Nor does it address the compounding cost for
   an auto-updating app: *"Unsigned files must build reputation anew with every update."*
   The Ed25519 gate and Authenticode answer **different questions** — feed authenticity vs. OS
   execution trust — exactly as `signed-release-ci.md:106-108` argues provenance and the `.sig` are
   orthogonal and must coexist. The same reasoning applies one layer out.

So §1 stands as a real gap, re-scoped to: *evidence for owner decision B-2*, not a unilateral "DO".

---

## 0. Measured baseline

### 0.1 What ships today

| Fact | Evidence |
|---|---|
| Targets: NSIS installer + portable zip, **x64 only** | `electron-builder.yml:132-136` |
| `productName: Reframe`, `appId: local.media-studio`, package name `media-studio` | `electron-builder.yml:24-25`, `app/package.json:2-4` |
| Current version **1.4.2** | `app/package.json:4` |
| Installer size **223.3 MB**, zip **295.7 MB** (measured on disk, `dist/`, built 2026-08-08 07:22) | `dist/media-studio-1.4.2-win-x64.exe` |
| electron-builder **^26.15.3**, electron-updater **^6.8.9**, electron **^43.3.0** | `app/package.json` devDependencies/dependencies |
| Publish provider: GitHub Releases, `Prekzursil/Reframe` | `electron-builder.yml:39-42` |
| Repo is **PUBLIC** but has **no LICENSE file** and `"license": "UNLICENSED"` | `gh repo view` → `{"isPrivate":false,"licenseInfo":null}`; `app/package.json:10` |
| NSIS config is 6 keys only — no component page, no custom `include`/`script` | `electron-builder.yml:139-150` |

NSIS block verbatim (`electron-builder.yml:139-150`): `oneClick: false`, `perMachine: false`,
`allowToChangeInstallationDirectory: true`, `installerIcon`, `uninstallerIcon`,
`deleteAppDataOnUninstall: false`, `shortcutName: Reframe`. There is **no** `build/installer.nsh`
in the tree (measured: `build/` contains only `check-python.ps1`, `make-portable.ps1`,
`python-embed-setup.ps1`, `sign-release.mjs`, two `wsl-verthor-bootstrap.*`, and the
`ffmpeg`/`icon`/`icons`/`python-embed`/`python-embed-314` directories).

### 0.2 The updater — already built, and better than most

This is genuinely good work and should not be rebuilt. Measured:

- `electron-updater` wired to the GitHub feed; `latest.yml` + NSIS `.blockmap` (delta downloads)
  emitted by the `publish` block — `electron-builder.yml:26-38`.
- Launch check deferred until the renderer has loaded so it can observe the status stream —
  `app/main/main.ts:845-852`.
- `autoDownload = false` and `autoInstallOnAppQuit = false`: the user confirms every download and
  nothing installs outside the gate — `app/main/updater.ts:163-164`.
- **Ed25519 authenticity gate** over `reframe:update:v1 ‖ version ‖ sha512(installer)`, verified
  against embedded public keys with a two-key rotation window — `app/main/updateVerify.ts:36`,
  `:52-61`, `:98-100`, `:119-136`.
- **Downgrade-replay guard** (a validly-signed *older* release is refused) —
  `app/main/updateVerify.ts:185-187`, called at `:223-225`.
- Signature URL is a fixed `github.com` release path with both segments percent-encoded, so a
  hostile feed value cannot redirect the host — `app/main/updateVerify.ts:103-111`.
- Re-verification immediately before `quitAndInstall()`, closing the TOCTOU window —
  `app/main/updater.ts:14-16`, `:245-262`.
- Fail-closed by construction: the verifier never throws, every failure is a typed
  `{ok:false, reason}` — `app/main/updateVerify.ts:66-67`, `:195-198`.

### 0.3 THREE live defects in the release pipeline (found by this audit)

**D1 — the Ed25519 gate has never been exercised, and no release carries a `.sig`.** The gate will
reject 100% of updates the moment it ships, unless `.sig` publication is added to the release
runbook.

Two mechanically independent signals:
1. `gh release view --repo Prekzursil/Reframe` on the **Latest** release (`v1.4.0`) returns exactly
   three assets: `latest.yml`, `media-studio-1.4.0-win-x64.exe`, `…exe.blockmap`. **No `.sig`.**
2. `dist/` on disk holds 8 built installers (1.0.0 → 1.4.2) and **zero** `*.sig` files —
   `build/sign-release.mjs` has never been run.

Failure path if shipped as-is: `fetchUpdateSignature` (`app/main/main.ts:797-805`) gets HTTP 404 →
throws → `verifyDownloadedUpdate` rejects with `cannot fetch update signature`
(`app/main/updateVerify.ts:238-241`) **after the full 223 MB download completes**. Confidence
*almost certain* (the code path is unconditional and fail-closed).

Mitigating detail that changes the severity — **the gate is not in any shipped build yet.** Measured:
`git ls-tree v1.4.0:app/main/` and `v1.4.1:app/main/` list `updater.ts` but **not**
`updateVerify.ts`; `git ls-tree v1.4.0:build/` does **not** list `sign-release.mjs`. So the gate
lives only on `main` and will ship first in the next release. Consequence: the v1.4.0 → next-release
upgrade is performed by **v1.4.0's un-gated updater**, so the gate protects N+1 → N+2, not
N → N+1. That is normal for a first-signed release, but it must be stated rather than assumed away.

**D2 — the embedded update keypair is a proof-of-concept key and is a hard release blocker.**
`app/main/updateVerify.ts:46-51` says so in its own words: *"these two keys were generated for this
proof-of-concept PR. Before the first PRODUCTION signed release, regenerate a fresh keypair on an
offline machine … whose private half has NEVER touched a shared/agent environment."* Both embedded
keys (`:54-60`) are therefore untrusted. Shipping them would mean the authenticity claim is
cosmetic. Settling action (not a check — a task): generate offline, replace both entries, re-run the
`updateVerify.test.ts` pins.

**Third, mechanically independent signal that no signed release has ever been possible:** the
production keypair **does not exist yet**. `signed-release-ci.md:278` documents reading it from
`C:\offline\reframe-ed25519.pem`; measured 2026-08-08, `C:\offline\reframe-ed25519.pem` is absent,
as are `C:\offline` and `%USERPROFILE%\offline`. So the D1/D2 cluster now rests on three independent
probes — release assets (`gh release view`), built artifacts (`dist/` has zero `*.sig`), and the
signing key's own absence on disk.

**Minor hygiene finding while verifying the above (low severity, cheap fix).**
`docs/plans/v1.5/signed-release-ci.md` is **committed** (`git log` → `6ae972c1`, clean working-tree
status) in a **public** repo, and line 278 names the intended on-disk location of the offline
update-signing private key. That key is the highest-authority secret in the entire distribution
chain — it authorizes *silent* auto-updates on every installed copy. Right now the disclosure is
inert (the file does not exist), so this is **not** an exposure and there is nothing to rotate. But it
is a pre-committed instruction telling any future local foothold exactly where to look. When G2
generates the real key: (a) do not place it at the documented path, (b) genericise that line to
`<offline-key-path>` or an env-var reference, and (c) prefer a removable/encrypted volume over a
plain `C:\` directory. Confidence *high* that this is worth doing and *high* that it is not urgent.

**D3 — v1.4.0 users currently have no update path at all.** `gh release list` shows `v1.4.1` in
state **Draft** and `v1.4.2` built (`dist/`, 2026-08-08) but never released.

Mechanism, measured in the pinned provider — not inferred. `allowPrerelease` is not set anywhere in
this repo, so `GitHubProvider.getLatestVersion()` takes the `else` branch at
`app/node_modules/electron-updater/out/providers/GitHubProvider.js:92-93` and resolves the tag via
`getLatestTagName()`, which for `github.com` hits `<repo>/releases/latest`
(`GitHubProvider.js:158-163`). The Atom feed is fetched only to locate the matching entry for release
notes (`:94-104`) — it does **not** select the tag on this path.

Second independent signal: `https://github.com/Prekzursil/Reframe/releases/latest` measurably
resolves to **v1.4.0** (read 2026-08-08). So every installed copy reports "no update available".
Confidence *almost certain*.

> **Correction to an earlier draft of this document.** An earlier version asserted the mechanism was
> "the Atom feed excludes drafts". That is **REFUTED**: fetching
> `https://github.com/Prekzursil/Reframe/releases.atom` lists `v1.4.1` as its newest entry, because
> that feed enumerates **tags** (the tag `v1.4.1` exists — `git tag --list "v1.4*"` → `v1.4.0`,
> `v1.4.1`) regardless of whether a release is published. The conclusion survives; the reasoning did
> not. Worth keeping visible because it also flags a latent hazard: **if `allowPrerelease: true` is
> ever set for a beta channel (§4, G7), the code path switches to the Atom feed and can select a tag
> whose release is a draft or has no assets** (`GitHubProvider.js:51-58` takes the first entry
> outright when the current version is stable and no channel is set). Any G7 work must test that
> case explicitly.

Asset-count reconciliation, so the D1 evidence is not misread: the v1.4.0 release *page* reports
"Assets 5" while `gh release view` returns 3. The difference is GitHub's two auto-generated source
archives, which `gh` does not list. There are still **no `.sig` assets**.

### 0.4 Where user state lives (the backward-compatibility surface)

Two roots, and the distinction is the whole ballgame:

- **`$INSTDIR`** (`%LOCALAPPDATA%\Programs\Reframe` by default at `perMachine:false`) — **replaced
  wholesale by electron-updater's in-place NSIS upgrade.** Anything here is destroyed on update.
- **`<userData>`** = `app.getPath('userData')` — survives.
- **`<dataRoot>`** = `%APPDATA%/media-studio` by default — survives. Relocatable.

| Artifact | Path | Evidence | Survives update? |
|---|---|---|---|
| Encrypted provider keys (DPAPI) | `<userData>/secure-keys.json` | `app/main/keystore.ts:37`, `:905` | YES |
| Settings — incl. `savePresets`, `routing`, `firstRunChoiceMade` | `<dataRoot>/settings.json` | `sidecar/media_studio/handlers/_services.py:75`, `settings_store.py:159`, `:163` | YES |
| Library database | `<dataRoot>/library.db` | `sidecar/media_studio/library.py:131`, `handlers/library_ops.py:395` | YES |
| Project manifests | `<dataRoot>/projects/<videoId>.json` | `_services.py:73`, `library_ops.py:60` | YES |
| Exports | `<dataRoot>/exports` | `_services.py:74` | YES |
| Export-preset catalog | `<dataRoot>/export-presets.json` | `handlers/composition.py:436-441` | YES |
| Thumbnails / posters | `<dataRoot>/thumbnails/<id>.jpg` | `library_ops.py:144` | YES |
| Keep-a-copy managed store | `<dataRoot>/managed-copies` (cap 20 GiB) | `sidecar/media_studio/keepcopy.py:54-59` | YES |
| Models / tools / pip envs | `<dataRoot>/{models,tools,envs}` | `electron-builder.yml:147-148`; `bootstrap.py` | YES |
| First-run markers | `<dataRoot>/.first-run-complete.json`, `.first-run-requirements.json`, `.first-run-profile.json` | `bootstrap.py:618`; `firstRunGate.ts:41`; `installProfiles.ts:242` | YES |
| Data-root pointer (stable) | `<userData>/data-dir.txt` | `dataRootIo.ts:59-65`, `dataRoot.ts:19` | YES |
| Data-root pointer (legacy) | `<exeDir>/data-dir.txt` | `dataRootIo.ts:43-54` | **NO** — but forward-migrated into the stable copy on read (`dataRootIo.ts:131-141`) |
| Embeddable-python activation | `<resources>/python/python3XX._pth` | `main.ts:692-719` | **NO** — destroyed by design, rewritten every packaged launch by `ensurePthActivated()` |

`deleteAppDataOnUninstall: false` (`electron-builder.yml:149`) means an **uninstall** also keeps
`<dataRoot>`, so a reinstall needs no re-download. That is deliberate and correct.

The two mechanisms that make an upgrade non-destructive already exist and were built for exactly
this: `dataRootPlan.ts:1-24` documents the historical `<exeDir>/data` regression (a default install's
`library.db` + multi-GB envs *were* wiped by the very auto-update v1.4 relies on) and the
migrate-out-of-`$INSTDIR` fix; `dataRootIo.ts:114-141` documents the legacy-marker forward write.

### 0.5 Install profiles today (the input to §2)

The Default/Full/Custom concept **already exists in the app**, with a single source of truth:

- Four profile ids — `minimum` · `default` · `full` · `custom` — `app/main/installProfiles.ts:24`.
- A **core floor** present in every profile including Minimum: `yunet-face-detection` +
  `lightasd-asd` (`installProfiles.ts:44`). Skipping it is the trap the completion marker guards:
  without those weights the engine silently centre-crops (`installProfiles.ts:16-21`).
- Exactly **two** optional bundles — `transcription` (Whisper large-v3-turbo) and `ai-director`
  (Qwen3-4B GGUF + three llama-server builds) — `installProfiles.ts:60`, `:72-85`.
- Fixed mapping: minimum `[]` · default `[transcription]` · full `[transcription, ai-director]` —
  `installProfiles.ts:92-98`.
- Sizes for the picker come from the same map (`ASSET_SIZES_MB`, `installProfiles.ts:47-55`), so the
  number shown can never drift from what is installed.
- Choice → `installProfile.choose` IPC → validate → persist → spawn `bootstrap.py --assets …` —
  `app/main/installProfileIpc.ts:17`, `:60-81`.
- Persisted as `{profile, bundles}` at `<dataRoot>/.first-run-profile.json` —
  `installProfiles.ts:242-248`, written by `main.ts:654-665`, replayed by `main.ts:675-689`.
- The picker is shown **only** on a first-ever run (`firstRunKind === 'first-ever'`), never on a
  silent re-bootstrap — `app/main/main.ts:1206-1216`.

**Everything else is on-demand, at point of use, not an install-time pack.** Measured asset universe
beyond the two bundles: `all-minilm-l6-v2-onnx`, `hsemotion-onnx`, `rapidocr-onnx`,
`edgetam-video-tracker`, `kokoro-v1.0-onnx`, `sherpa-onnx-punct-en`, `speechbrain-vad-crdnn`,
`speechbrain-ecapa-voxceleb`, `ctc-forced-aligner-wav2vec2`, `ctc-forced-aligner-romanian`,
`dover-mobile-quality`, `pyannote-speaker-diarization-31`, `pyannote-segmentation-30`, `qwen3vl-4b`,
`qwen3vl-8b`, `siglip2-so400m` (grep of `*_ASSET_NAME` across `sidecar/media_studio`).

`ModelsSystemPanel.tsx` is **not** a static pack list — it renders whatever `assets.list` returns
from the sidecar at runtime and downloads via `assets.ensure`
(`app/renderer/src/panels/ModelsSystemPanel.tsx:446`, `:629`, `:678-685`). So the installer's pack
list must be derived from `installProfiles.ts`, not from that panel. Trying to mirror the panel into
NSIS would create a second, drifting source of truth.

---

## 1. Code signing

### 1.1 Two market changes that invalidate most advice you will find

**(a) EV certificates no longer bypass SmartScreen.** Microsoft's own docs, twice:

> "EV certificates no longer bypass SmartScreen. Years ago, signing files with an Extended
> Validation (EV) code signing certificate would result in positive SmartScreen reputation by
> default, but this behavior no longer exists. … Paying a premium for EV solely to avoid SmartScreen
> warnings is no longer justified."
> — [SmartScreen reputation for Windows app developers](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation) (page `ms.date` 2026-05-04; read 2026-08-08)

The comparison table on the sibling page marks EV as *"Same as OV since 2024 — no longer instant
bypass"* and *"No longer recommended specifically for SmartScreen bypass"* —
[Code signing options for Windows app developers](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options)
(page `ms.date` 2026-04-20; read 2026-08-08). **Any recommendation to buy EV for SmartScreen is
obsolete.** This is the single most consequential finding in this section.

**(b) Certificate lifetimes just collapsed.** CA/Browser Forum **Ballot CSC-31** passed 2025-10-13
and cuts the maximum validity of publicly-trusted code-signing certificates **from 39 months to 460
days, effective 2026-03-01** —
[cabforum.org/2025/11/17/ballot-csc-31-maximum-validity-reduction](https://cabforum.org/2025/11/17/ballot-csc-31-maximum-validity-reduction/)
(read 2026-08-08). Practical effect: multi-year OV orders are now re-issued inside the term, and the
"buy 3 years to amortise the token" strategy is dead. Budget as an annual cost.

**(c) HSM/token has been mandatory since June 2023.** *"As of June 2023, the CA/Browser Forum
requires private keys for OV certificates to be stored on a hardware security module (HSM) or
hardware token."* — Microsoft, code-signing-options page (above). Cloud-HSM services (DigiCert
KeyLocker, Sectigo cloud signing, SSL.com eSigner) satisfy this without a shipped USB stick, which
is what makes CI signing possible at all.

### 1.2 Options, with 2026 prices

| Option | Cost | Availability | SmartScreen | Token/HSM | Source |
|---|---|---|---|---|---|
| **Azure Artifact Signing** (formerly Trusted Signing) | **~$9.99/mo** Basic (5,000 signatures/mo), $99.99/mo Premium (100,000) | Orgs: US, CA, EU, UK (+AU, NZ, JP, KR, SG, CH, NO, IL for Public Trust). **Individuals: US and Canada only** | Reputation builds over time. Explicitly **not** instant trust | **None required**; native GitHub Actions / Azure DevOps integration | [code-signing-options](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options); [Artifact Signing quickstart](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart) |
| **OV cert, Sectigo/Comodo via reseller** | **$219/yr** | Worldwide. **Individual Validation (IV) offered to solo devs with no registered company** | Same as Artifact Signing | USB token or HSM | [SSL Dragon code signing](https://www.ssldragon.com/ssl-certificates/code-signing/) |
| OV cert, GoGetSSL | $289/yr | Worldwide, IV available | Same | Token or HSM | same |
| OV cert, DigiCert | $400/yr | Worldwide, **no IV** | Same | Token, HSM, or **KeyLocker cloud** | same |
| EV cert | $287 (Sectigo) – $685 (DigiCert)/yr | Worldwide, **no IV** | **Same as OV** | Token or HSM | same + Microsoft docs |
| Microsoft Store (MSIX) | Free | Worldwide | **No warnings at all** — Microsoft re-signs | n/a | [code-signing-options](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options) |
| SignPath Foundation (OSS) | Free | OSS only | OV-level | managed | [signpath.org/terms](https://signpath.org/terms) |
| Self-signed / unsigned | Free | — | Blocks / strong warning | — | Microsoft docs |

The $9.99/$99.99 figures are **UNVERIFIED against a Microsoft-hosted price page** — the official
[Artifact Signing pricing page](https://azure.microsoft.com/en-us/pricing/details/artifact-signing/)
renders its price cells empty to unauthenticated fetches (measured 2026-08-08: it returned `$-` for
both tiers while still showing the 5,000 / 100,000 quotas and "1 of each Certificate Profile type" /
"10 of each"). Microsoft's own docs pages independently corroborate the magnitude
("Approximately $9.99/month", "Approximately $10/month"), which is why the number is stated at all.
**Settling experiment:** sign in to the Azure pricing calculator (or `az` a test account) and read
the Basic SKU rate for the target region. Do this before committing a budget line.

### 1.3 Eligibility analysis for *this* developer

Microsoft's geographic restriction is unambiguous and it is the deciding constraint. Verbatim from
the Artifact Signing quickstart prerequisites (read 2026-08-08):

> "Public Trust certificates are available to organizations in the United States, Canada, the
> European Union, the United Kingdom, Australia, New Zealand, Japan, South Korea, Singapore,
> Switzerland, Norway, and Israel. **Individual developers must be located in the United States or
> Canada.** These geographic restrictions do not apply to Private Trust certificates."

The owner is in **Romania (EU)**. Therefore:

- **As an individual / sole developer → NOT eligible** for Azure Artifact Signing. Confidence *almost
  certain* (primary-source restriction, stated twice across two Microsoft pages).
- **As a registered EU legal entity (SRL / PFA with a business identifier and a matching website
  domain) → eligible**, at ~$9.99/mo. The organization path requires: legal business entity name,
  a website URL belonging to that entity, a business identifier, the business address, and an
  individual representative who completes government-ID verification — quickstart, Organization tab.
  Processing time is stated as **"from 1 to 20 business days"**.
- Additional constraint for the individual path that also bites the org path: identity details are
  **auto-sourced from the Azure billing account**, and *"the billing account type must match the
  identity validation type"* — an Individual billing account cannot validate an Organization
  identity or vice versa. So an existing personal Azure subscription cannot be reused to validate a
  company.

**SignPath Foundation free OSS signing: NO-GO.** It requires *"an OSI-approved Open Source license"*
with *"no commercial dual-licensing"* and the project *"may not contain any proprietary, non
open-source component"* ([signpath.org/terms](https://signpath.org/terms), read 2026-08-08).
Reframe is public-source but carries **no LICENSE file** and `"license": "UNLICENSED"`
(`app/package.json:10`) — i.e. all-rights-reserved, not open source — and it bundles ViNet-S under
**CC-BY-NC-SA 4.0** (`NOTICE`, "NON-COMMERCIAL NOTICE"), which is not an OSI license. Two
independent disqualifiers. Confidence *almost certain*.

### 1.4 Recommendation

**Buy a Sectigo (or Comodo) OV code-signing certificate with Individual Validation, ~$219/year,
with a cloud-HSM signing option rather than a shipped USB token.**

- **Cost:** ~$219/yr (+ any cloud-signing fee the reseller charges separately — **UNVERIFIED**: the
  `signmycode.com` OV page returned HTTP 403 to automated fetch on 2026-08-08, so the cloud-HSM
  line-item price was not read. Settling experiment: open the chosen reseller's OV product page in a
  browser and read the eSigner / cloud-signing add-on price before ordering).
- **Lead time:** *"1–7 days"* issuance per the reseller, on top of your own document-gathering.
  Plan **two weeks** wall-clock. Confidence *likely*.
- **Why not Azure Artifact Signing**, despite being 2.2× cheaper and CI-native: the owner is an
  individual in Romania and individuals are restricted to US/Canada. It becomes the better choice
  **the moment a Romanian legal entity exists** — at which point migrating is a config change, but
  note Microsoft's own warning that *"changing your signing certificate affects the publisher trust
  signal"*, so any accumulated reputation resets.
- **Why not EV** at any price: §1.1(a). It buys enterprise-procurement optics, nothing for
  SmartScreen.
- **Why not the Microsoft Store**, which would eliminate warnings entirely: Reframe ships an
  NSIS/EXE installer that spawns an embeddable CPython, writes to `%APPDATA%`, and downloads
  multi-GB models on demand. An MSIX repackage is a large, separate programme, and the Store's
  MSI/EXE path still requires you to sign the installer yourself (*"Microsoft does not re-sign your
  installer"*). Worth a v2 evaluation, not a v1.5 decision.

### 1.5 What signing actually buys — set expectations honestly

Signing does **not** remove the first-download warning. *"newly created binary could still show a
SmartScreen warning until its hash or publisher certificate accumulates sufficient evidence of
positive reputation"* and *"There is no exact threshold, but it can take several weeks and hundreds
of clean installs from a wide audience"* (SmartScreen page). There is also *"no need (or mechanism)
to manually submit a file for SmartScreen reputation review for consumer endpoints."*

What it does buy, concretely:

1. **The publisher name is displayed** in the warning instead of "Unknown publisher" — the single
   biggest trust delta for a user deciding whether to click through.
2. **Reputation carries across versions.** *"Signing files using a trusted certificate can allow
   certificate reputation to build, potentially avoiding warnings on new files signed by the same
   trusted certificate. Unsigned files must build reputation anew with every update."* For an app
   that auto-updates, this compounds — every unsigned release restarts at zero.
3. **Smart App Control.** *"On Windows 11 devices, the Smart App Control feature may supersede
   SmartScreen Application Reputation. Smart App Control will block execution of unsigned files
   unless the file has a positive reputation."* This is a **block**, not a warning, and it applies to
   all executables, not just downloaded ones. For a Windows-11-targeted app this is the strongest
   argument for signing.
4. **Enterprise deployability** — unsigned installers are commonly blocked outright by policy.

Two operational rules from the same page that interact with Reframe's build: *"Avoid modifying files
after signing as doing so can break the signature"* — the Ed25519 `.sig` step (`build/sign-release.mjs`)
computes a detached signature over the file and does **not** modify it, so the ordering
Authenticode-sign → then Ed25519-sign is safe. Confidence *high* (detached signature by construction,
`updateVerify.ts:88-100`). And *"Use a consistent signing identity"* — do not rotate CAs casually.

### 1.6 Wiring it in (design only — this lane does not edit the config)

`electron-builder.yml:31-38` currently documents the absence of signing. The change is confined to
the `win` block plus CI secrets:

- Cloud-HSM path (recommended): set `win.signtoolOptions.sign` to a custom script, or use the CA's
  signing CLI as electron-builder's `sign` hook. Do **not** put a `.pfx` + password in CI — the
  CA/B HSM rule makes an exportable `.pfx` non-compliant for a publicly-trusted OV cert anyway.
- Add `win.signtoolOptions.rfc3161TimeStampServer` (the CA's timestamp URL). **Timestamping is
  what keeps already-shipped binaries valid after the 460-day certificate expiry** (§1.1(b)) — with
  the new short lifetimes this is no longer optional hygiene.
- **Sign order — CORRECTED.** An earlier draft of this section said "build → Authenticode-sign →
  regenerate `latest.yml`/`.blockmap` from the signed bytes → `sign-release.mjs`". For the Ed25519
  step that is **wrong**, and `signed-release-ci.md:136` explains why: *"a local rebuild would produce
  different bytes (electron-builder/NSIS Windows builds embed timestamps and are not bit-reproducible),
  breaking both the provenance digest match and the users' download."* The owner must sign **the exact
  CI-built bytes downloaded from the draft release**, never a local rebuild.

  Authenticode therefore has to happen **inside the CI build**, before `--publish always` computes
  `latest.yml` + `.blockmap` — so that the bytes CI attests, the bytes the human downloads and
  Ed25519-signs, and the bytes users receive are all one and the same signed artifact. Concretely the
  Phase A step in `signed-release-ci.md:61` gains the signing credential and drops
  `CSC_IDENTITY_AUTO_DISCOVERY: "false"`; Phase B is unchanged. Getting this wrong is the classic
  self-inflicted wound — Authenticode-signing *after* the blockmap is computed invalidates every
  sha512 in `latest.yml`.

  **UNVERIFIED** that electron-builder orders its internal sign → blockmap correctly for this
  config; settling experiment: build once with signing enabled, then assert `sha512` in
  `dist/latest.yml` equals `sha512` of the signed `dist/*.exe` on disk.

  Note the trade-off this forces, which the sibling lane deliberately avoided: putting a signing
  credential in CI reintroduces a long-lived secret, the very thing `signed-release-ci.md:104` argues
  against for the *Ed25519* key. A cloud-HSM OV credential is narrower in blast radius than the
  update-signing key (it cannot forge a silent auto-update, only an installer signature), but it is
  not zero. This is a real cost of G4 and belongs in decision B-2.

---

## 2. NSIS component page design

### 2.1 The constraint that shapes the entire design

electron-builder's NSIS installer extracts **one 7z app package in one `Section`**
(`app/node_modules/app-builder-lib/templates/nsis/installSection.nsh:66` `installApplicationFiles`,
with `setSpaceRequired` targeting a single section id in `common.nsh:19-45`). There is **no**
`MUI_PAGE_COMPONENTS` anywhere in the template set (measured: 24 files under
`app-builder-lib/templates/nsis/`; the assisted page order is `assistedInstaller.nsh:9-64` and
contains welcome → license → install-mode → directory → `customPageAfterChangeDir` → instfiles →
finish).

Therefore: **a real NSIS components page that selects payload subsets is not achievable without
restructuring the whole build.** And it is not wanted — the owner's decision is that models keep
downloading on demand (`electron-builder.yml:3-7` documents the slim-artifact contract and the NSIS
~2 GB ceiling; bundling `transcription` alone would add ~1.6 GB per `ASSET_SIZES_MB`).

So the correct design is a **choice-recording page**: an `nsDialogs` page that captures
Default/Full/Custom/Minimum and writes it into the existing `.first-run-profile.json` contract. The
installer decides *what the app will fetch on first launch*; it does not change what the installer
extracts. This is exactly what the owner already decided, and it is also the only thing the platform
allows cheaply.

### 2.2 The pack list (derived, not invented)

Straight from `app/main/installProfiles.ts` — no new names:

| Radio option | id | Bundles added on top of the core floor | Approx first-run download |
|---|---|---|---|
| Minimum | `minimum` | — | ~4 MB |
| **Default (pre-selected)** | `default` | `transcription` | ~1.6 GB |
| Full | `full` | `transcription`, `ai-director` | ~4.9 GB |
| Custom | `custom` | user-checked subset | computed |

Custom checkboxes (exactly the two that exist — `installProfiles.ts:72-85`):

- **Transcription & subtitles** — *"Whisper speech-to-text for captions, subtitles and search."*
  (`whisper-large-v3-turbo`)
- **AI Director** — *"The local LLM (plus its llama-server builds) that powers prompt-driven
  editing."* (`qwen3-4b-gguf`, `llama-server-cuda`, `llama-server-cuda-cudart`, `llama-server-cpu`)

Labels, descriptions and the `recommended` flag on Default are already authored in
`installProfiles.ts:111-140` and `:72-85`; **copy those strings verbatim** so the installer and the
in-app picker read identically. Size labels must come from the same map (`formatSize`,
`installProfiles.ts:220-225`) — hardcoding "~1.6 GB" in the `.nsh` creates the drift the TS module
exists to prevent. Recommendation: have the build emit a tiny generated `.nsh` fragment of
`!define`s from `installProfiles.ts` rather than hand-typing numbers.

The core floor (`yunet-face-detection`, `lightasd-asd`) must **not** be a checkbox. It is the
no-silent-centre-crop invariant (`installProfiles.ts:16-21`, `firstRunGate.ts:43-50`); making it
optional re-opens the exact bug the completion marker was built to catch.

### 2.3 Where the page goes (measured hook)

`assistedInstaller.nsh:41-44`:

```nsis
  # after change installation directory and before install start, you can show custom page here.
  !ifmacrodef customPageAfterChangeDir
    !insertmacro customPageAfterChangeDir
  !endif
```

That is the hook — after the directory page, before `MUI_PAGE_INSTFILES`. Two adjacent measured
facts that the design must respect:

- The license and directory pages are wrapped in `skipPageIfUpdated` (`assistedInstaller.nsh:14`,
  `:25`), which `Abort`s the page when `${isUpdated}` (`common.nsh:110-121`). **The component page
  must do the same**, or electron-updater's silent in-place upgrade becomes an interactive prompt and
  auto-update breaks. This is the highest-risk detail in §2.
- `${Silent}` is already handled throughout (`installSection.nsh:5-7`, `:106-109`), and
  `/allusers` + `/currentuser` are parsed at `assistedInstaller.nsh:122-133`. A silent install must
  skip the page and take the profile from the command line (§4, G6).

### 2.4 The `.nsh`

`build/installer.nsh` (new file; electron-builder auto-detects this exact path — see §2.5):

```nsis
; build/installer.nsh — Reframe installer customisation.
; Included by electron-builder into BOTH the installer and the uninstaller build,
; so every Function is defined INSIDE a macro that is only inserted on the
; installer side. Never define a bare top-level Function here.

; Sizes/labels are generated from app/main/installProfiles.ts at build time into
; build/installProfiles.generated.nsh (single source of truth -- see §2.2).
!include /NONFATAL "installProfiles.generated.nsh"
!ifndef REFRAME_SIZE_DEFAULT
  ; Fallback keeps a hand build compiling, but the generator is the contract.
  !define REFRAME_SIZE_MINIMUM "~4 MB"
  !define REFRAME_SIZE_DEFAULT "~1.6 GB"
  !define REFRAME_SIZE_FULL    "~4.9 GB"
!endif

!macro customPageAfterChangeDir
  Var /GLOBAL ReframeProfile        ; minimum | default | full | custom
  Var /GLOBAL ReframeWantWhisper    ; "1" | "0"
  Var /GLOBAL ReframeWantDirector   ; "1" | "0"
  Var /GLOBAL RfDialog
  Var /GLOBAL RfRbMinimum
  Var /GLOBAL RfRbDefault
  Var /GLOBAL RfRbFull
  Var /GLOBAL RfRbCustom
  Var /GLOBAL RfCbWhisper
  Var /GLOBAL RfCbDirector
  Var /GLOBAL RfState

  Page custom RfComponentsCreate RfComponentsLeave

  Function RfComponentsCreate
    ; 1. An in-place auto-update MUST NOT prompt. Mirrors skipPageIfUpdated
    ;    (common.nsh:110-121) -- the same guard the license/directory pages use.
    ${If} ${isUpdated}
      Abort
    ${EndIf}
    ; 2. Unattended install: take /PROFILE= + /PACKS= and never draw a dialog.
    ${If} ${Silent}
      Abort
    ${EndIf}

    !insertmacro MUI_HEADER_TEXT "Choose what to set up" \
      "Reframe downloads its AI models on first launch. Pick how much to fetch now -- you can add the rest later in Models & System."

    nsDialogs::Create 1018
    Pop $RfDialog
    ${If} $RfDialog == error
      Abort
    ${EndIf}

    ${NSD_CreateRadioButton} 0 0u 100% 12u "Minimum -- app plus subject tracking (${REFRAME_SIZE_MINIMUM})"
    Pop $RfRbMinimum
    ${NSD_CreateLabel} 12u 13u 96% 18u "Everything else downloads the first time you use it. Smallest first-run download."
    Pop $RfState

    ${NSD_CreateRadioButton} 0 34u 100% 12u "Default (recommended) -- adds offline transcription (${REFRAME_SIZE_DEFAULT})"
    Pop $RfRbDefault
    ${NSD_CreateLabel} 12u 47u 96% 18u "Captions, subtitles and search work out of the box. The balanced choice for most people."
    Pop $RfState

    ${NSD_CreateRadioButton} 0 68u 100% 12u "Full -- everything up front (${REFRAME_SIZE_FULL})"
    Pop $RfRbFull
    ${NSD_CreateLabel} 12u 81u 96% 18u "Also installs the local AI Director model so nothing downloads later. Best for offline use."
    Pop $RfState

    ${NSD_CreateRadioButton} 0 102u 100% 12u "Custom -- choose feature packs"
    Pop $RfRbCustom
    ${NSD_OnClick} $RfRbCustom RfSyncCustom
    ${NSD_OnClick} $RfRbMinimum RfSyncCustom
    ${NSD_OnClick} $RfRbDefault RfSyncCustom
    ${NSD_OnClick} $RfRbFull RfSyncCustom

    ${NSD_CreateCheckBox} 12u 116u 96% 12u "Transcription && subtitles -- Whisper speech-to-text"
    Pop $RfCbWhisper
    ${NSD_CreateCheckBox} 12u 130u 96% 12u "AI Director -- local LLM for prompt-driven editing"
    Pop $RfCbDirector

    ; Default is the pre-selected recommendation (installProfiles.ts:111-140).
    ${NSD_Check} $RfRbDefault
    Call RfSyncCustom
    nsDialogs::Show
  FunctionEnd

  ; Custom checkboxes are only live when Custom is selected.
  Function RfSyncCustom
    ${NSD_GetState} $RfRbCustom $RfState
    ${If} $RfState == ${BST_CHECKED}
      EnableWindow $RfCbWhisper 1
      EnableWindow $RfCbDirector 1
    ${Else}
      EnableWindow $RfCbWhisper 0
      EnableWindow $RfCbDirector 0
    ${EndIf}
  FunctionEnd

  Function RfComponentsLeave
    StrCpy $ReframeWantWhisper "0"
    StrCpy $ReframeWantDirector "0"
    ${NSD_GetState} $RfRbMinimum $RfState
    ${If} $RfState == ${BST_CHECKED}
      StrCpy $ReframeProfile "minimum"
      Return
    ${EndIf}
    ${NSD_GetState} $RfRbFull $RfState
    ${If} $RfState == ${BST_CHECKED}
      StrCpy $ReframeProfile "full"
      StrCpy $ReframeWantWhisper "1"
      StrCpy $ReframeWantDirector "1"
      Return
    ${EndIf}
    ${NSD_GetState} $RfRbCustom $RfState
    ${If} $RfState == ${BST_CHECKED}
      StrCpy $ReframeProfile "custom"
      ${NSD_GetState} $RfCbWhisper $RfState
      ${If} $RfState == ${BST_CHECKED}
        StrCpy $ReframeWantWhisper "1"
      ${EndIf}
      ${NSD_GetState} $RfCbDirector $RfState
      ${If} $RfState == ${BST_CHECKED}
        StrCpy $ReframeWantDirector "1"
      ${EndIf}
      Return
    ${EndIf}
    StrCpy $ReframeProfile "default"
    StrCpy $ReframeWantWhisper "1"
  FunctionEnd
!macroend

; Runs inside the install Section, AFTER installApplicationFiles +
; registryAddInstallInfo + shortcuts (installSection.nsh:66-83).
!macro customInstall
  ; An in-place update must not touch the user's recorded choice.
  ${If} ${isUpdated}
    Goto rfSkipProfile
  ${EndIf}

  ; Unattended default resolution: /PROFILE=<id> [/PACKS=transcription,ai-director]
  ${If} ${Silent}
    ${GetParameters} $R0
    ${GetOptions} $R0 "/PROFILE=" $R1
    ${IfNot} ${Errors}
      StrCpy $ReframeProfile $R1
    ${EndIf}
    ${If} $ReframeProfile == ""
      StrCpy $ReframeProfile "default"
      StrCpy $ReframeWantWhisper "1"
    ${EndIf}
    ${GetOptions} $R0 "/PACKS=" $R1
    ${IfNot} ${Errors}
      ${StrContains} $0 "transcription" $R1
      ${If} $0 != ""
        StrCpy $ReframeWantWhisper "1"
      ${EndIf}
      ${StrContains} $0 "ai-director" $R1
      ${If} $0 != ""
        StrCpy $ReframeWantDirector "1"
      ${EndIf}
    ${EndIf}
  ${EndIf}

  ; Build the bundles array in the EXACT shape parsePersistedInstallProfile reads
  ; (installProfiles.ts:257-267): {"profile": "...", "bundles": [...]}.
  StrCpy $R2 ""
  ${If} $ReframeWantWhisper == "1"
    StrCpy $R2 '"transcription"'
  ${EndIf}
  ${If} $ReframeWantDirector == "1"
    ${If} $R2 != ""
      StrCpy $R2 '$R2, '
    ${EndIf}
    StrCpy $R2 '$R2"ai-director"'
  ${EndIf}

  ; STAGING handoff -- see §2.6 for why this is NOT written to %APPDATA% directly.
  ClearErrors
  FileOpen $R3 "$INSTDIR\.install-profile.json" w
  ${IfNot} ${Errors}
    FileWrite $R3 '{$\n'
    FileWrite $R3 '  "profile": "$ReframeProfile",$\n'
    FileWrite $R3 '  "bundles": [$R2]$\n'
    FileWrite $R3 '}$\n'
    FileClose $R3
  ${EndIf}
  rfSkipProfile:
!macroend
```

Notes on correctness: `${StrContains}` is available because `assistedInstaller.nsh:23` includes
`StrContains.nsh` when `allowToChangeInstallationDirectory` is defined — which it is
(`electron-builder.yml:142`). `&&` in the checkbox label is the NSIS escape for a literal ampersand.
`$\n` is the NSIS newline escape. `${isUpdated}`, `${Silent}`, `${GetParameters}`, `${GetOptions}`
are all already in scope in the generated script.

### 2.5 How electron-builder picks it up

Zero config needed, and this is measured from the pinned build tool rather than from docs:
`app/node_modules/app-builder-lib/out/targets/nsis/NsisTarget.js:600-603` reads
`await packager.getResource(this.options.include, "installer.nsh")` and, when non-null, does
`addIncludeDir(packager.info.buildResourcesDir)` + `include(customInclude)`. With
`directories.buildResources: ../build` (`electron-builder.yml:46`), dropping the file at
`build/installer.nsh` is therefore sufficient. Making it explicit is still preferable for
grep-ability:

```yaml
nsis:
  # ... existing keys unchanged ...
  include: installer.nsh          # relative to buildResources (= ../build)
  warningsAsErrors: true          # a typo'd macro name otherwise compiles silently
```

`warningsAsErrors: true` is the important one — an `!ifmacrodef` hook whose macro name is misspelled
is simply never inserted, and the page silently does not appear. That failure mode is invisible
without it. **UNVERIFIED** that `warningsAsErrors` catches *that specific* class (a never-inserted
`!ifmacrodef` may not emit a makensis warning at all); settling experiment: rename the macro to
`customPageAfterChangeDirXX`, build, and confirm the build fails rather than producing an installer
with no component page. This is precisely the both-states test — do not trust the page's appearance
in the good state as proof the guard works.

### 2.6 Writing the choice into the existing `.first-run-profile.json` contract

Three candidate designs. The recommendation is (C).

**(A) Installer writes `%APPDATA%\media-studio\.first-run-profile.json` directly.** Rejected. Three
defects: (1) it duplicates the data-root precedence logic — `MEDIA_STUDIO_CONFIG_DIR` env >
`<userData>/data-dir.txt` > legacy `<exeDir>/data-dir.txt` > `%APPDATA%` (`dataRootPlan.ts:67-84`,
`dataRootIo.ts:114-141`) — inside NSIS, creating a second source of truth that will drift; (2) it
cannot see a data root the user relocated to `D:/Reframe/data`; (3) if `perMachine` is ever enabled
(§4, G4), the elevated inner UAC instance's `$APPDATA` is the **administrator's** profile, not the
installing user's, so the file lands in the wrong place — silently. Confidence *likely* for (3)
(standard NSIS/UAC behaviour; **settling experiment:** add `perMachine: true` in a scratch build and
`MessageBox` `$APPDATA` from the elevated section).

**(B) Registry handoff** (`HKCU\Software\Reframe\InstallProfile`). Works, and dodges (1)/(2). But it
adds a new persistence mechanism and a new uninstall-cleanup obligation for a value consumed exactly
once.

**(C) `$INSTDIR` staging file, consumed once on first launch — RECOMMENDED.** The installer writes
`$INSTDIR\.install-profile.json`; the app adopts it on the first-ever launch and writes the real
`.first-run-profile.json` through the code that already owns that file.

Why the `$INSTDIR` wipe-on-update is a *feature* here: the staging file must **not** survive an
update (an update must never re-offer or re-apply a profile), and it *should* be re-created by a
fresh re-install. The lifetime matches exactly.

App-side change (one function, ~20 lines, in the file that already does this work):

1. In `main.ts`, beside `readPersistedInstallAssets()` (`app/main/main.ts:675-689`), add
   `adoptStagedInstallProfile(): ResolvedInstallChoice | null` — if `<dataRoot>/.first-run-profile.json`
   is **absent** and `<exeDir>/.install-profile.json` exists, parse it with the *existing*
   `parsePersistedInstallProfile` (`installProfiles.ts:257-267`), resolve with the *existing*
   `resolveInstallChoice`, and return it. Never overwrite an existing data-root profile — a returning
   user's choice always wins.
2. At the gate (`main.ts:1206-1216`), when `firstRunKind === 'first-ever'` **and** a staged profile
   was adopted: `persistInstallProfile(choice)` (`main.ts:654-665`), set `awaitingProfile = false`,
   and go straight to `beginBootstrap(choice.assets)`. The user picked in the installer; do not ask
   twice.
3. Delete the staging file after a successful adopt (best-effort, fail-open — same posture as
   `persistInstallProfile`'s logged-not-fatal write).
4. Fall through to today's behaviour on any parse failure: no staged file, or a corrupt one, ⇒ show
   the ProfilePicker. `parsePersistedInstallProfile` already returns `null` on garbage and drops
   unknown bundle ids defensively (`installProfiles.ts:250-267`), so a hostile/garbled staging file
   degrades to a prompt, never to a wrong install.

This keeps **one** writer of `.first-run-profile.json` and **one** validator, adds no new schema, and
reuses the module whose entire reason for existing is that there is exactly one map
(`installProfiles.ts:1-14`).

### 2.7 Test obligations this design creates

`installProfiles.test.ts` already pins the TS↔Python conformance and "Default is the sole recommended
profile" (`installProfiles.ts:27-31`). Add:

- A cross-file test asserting the `.nsh` (or the generated `installProfiles.generated.nsh`) contains
  exactly the ids in `INSTALL_PROFILE_IDS` and exactly the bundle ids in `BUNDLE_IDS` — the same
  read-the-other-file pattern `firstRunGate.test.ts` uses against `bootstrap.py`.
- A unit test for `adoptStagedInstallProfile` covering: absent staging file · valid staging file ·
  corrupt JSON · unknown bundle id · **staging file present but data-root profile already exists**
  (must be ignored). That last case is the data-loss-adjacent one.
- The both-states test from §2.5 for the `!ifmacrodef` hook.

### 2.8 What this design deliberately does *not* do

Bundle models into the installer. `electron-builder.yml:3-7` sets the slim contract and notes NSIS's
~2 GB ceiling; `transcription` alone is ~1.6 GB and `full` ~4.9 GB (`ASSET_SIZES_MB`,
`installProfiles.ts:47-55`). A "Full" *installer* is not physically available at NSIS; a "Full"
*profile* is. The page therefore chooses download policy, not payload — and the UI copy must say so
("Reframe downloads its AI models on first launch"), or the size labels will read as a lie.

### 2.9 Honest status of §2

This is a **design**, not a verified implementation. The `.nsh` above has **not been compiled by
makensis** and has not been run. Expect at least one iteration on nsDialogs coordinates and on
`Var /GLOBAL` placement inside a macro. **Settling experiment:** `npx electron-builder --win` with the
file in place, then (a) confirm the page appears on a fresh install, (b) confirm it is skipped on an
electron-updater-driven upgrade, (c) confirm `$INSTDIR\.install-profile.json` matches the selection,
(d) confirm `/S /PROFILE=full` produces `{"profile":"full","bundles":["transcription","ai-director"]}`.

---

## 3. Backward compatibility — as a test plan, not a promise

### 3.1 What "backward compatible" has to mean here

Four distinct upgrade shapes, and they fail differently:

1. **In-place auto-update** (electron-updater → NSIS `/S`): `$INSTDIR` replaced, `<userData>` and
   `<dataRoot>` retained.
2. **Manual re-install over an existing install** (user double-clicks the new `.exe`): same, plus the
   interactive pages appear (and must not re-prompt for a profile if one already exists).
3. **Uninstall → install** (`deleteAppDataOnUninstall: false`, `electron-builder.yml:149`):
   `<dataRoot>` retained, so the app must open already-provisioned.
4. **Sidecar-requirements change across versions**: handled by the fingerprint file — a silent
   re-bootstrap, no picker (`firstRunGate.ts:23-41`, `main.ts:1196-1209`).

Shape 4 is the one most likely to regress silently, because a "successful" upgrade that quietly
re-downloads 1.6 GB looks identical to one that does not, unless you measure.

### 3.2 The matrix

**Two baselines are required, not one.**

- **Baseline A — the published old build:** v1.4.0 from
  `https://github.com/Prekzursil/Reframe/releases/download/v1.4.0/media-studio-1.4.0-win-x64.exe`
  (the current `/releases/latest`). This is what a real user upgrades *from*.
- **Baseline B — the owner's actual installed state:** **v1.4.1 at `D:\Program Files\Reframe`, with
  an `/allusers` uninstaller requiring elevation** (`GRILL-DECISION-QUEUE.md:24`). This is a
  per-machine-shaped, non-default install path, so it exercises the elevated-`$APPDATA` hazard
  (§2.6 defect 3), a non-`%LOCALAPPDATA%` `$INSTDIR`, and a version that never shipped publicly.
  An earlier draft of this matrix used Baseline A alone; that would have tested a configuration the
  owner is not running.

Then install the candidate over it. Every row is *install-old → mutate → install-new → assert*, and
rows B10/B12/B13/B15 must be run against **both** baselines.

| # | Artifact | Mutate on old build | Assert on new build |
|---|---|---|---|
| B1 | Provider keys | Add an OpenRouter key via Models & System; record `sha256` of `<userData>/secure-keys.json` | File present, `sha256` unchanged, key still listed in the UI, a `providers.testKey` ping still succeeds (proves DPAPI still decrypts — file bytes alone do not) |
| B2 | Settings | Set a non-default in Models & System; note `firstRunChoiceMade: true` and one `savePresets` entry in `<dataRoot>/settings.json` | Both values byte-identical; the first-run local-vs-cloud chooser (`FirstRunChooser.tsx`) does **not** reappear |
| B3 | Library DB | Import 3 videos; record row count + `sha256` of `<dataRoot>/library.db` | Same row count; all 3 visible in Library; no migration error in the sidecar log |
| B4 | Projects | Edit one project (creates `<dataRoot>/projects/<id>.json`); record its `sha256` | File unchanged; project opens with the same edits |
| B5 | Export presets | Save a named export preset → `<dataRoot>/export-presets.json` | Preset present and applies |
| B6 | Thumbnails | Note `<dataRoot>/thumbnails/*.jpg` count | Same count; no black posters in Library |
| B7 | Keep-a-copy store | Enable keep-a-copy on one video → `<dataRoot>/managed-copies/`; record byte total | Byte total unchanged; `managed store status` reports the same used/cap |
| B8 | **Models — the expensive one** | Record `<dataRoot>/models` byte total + mtimes | Byte total unchanged **and no `assets.ensure` job runs on first launch**. A re-download is the silent failure: assert on *no download*, not just on final presence |
| B9 | pip env | Record `<dataRoot>/envs/sidecar` byte total + `.media-studio-env.json` | Unchanged if `requirements-sidecar.lock.txt` is unchanged between the two versions; if it *did* change, assert exactly one silent re-bootstrap and **no ProfilePicker** |
| B10 | Install profile | Note `<dataRoot>/.first-run-profile.json` | Unchanged. With §2 shipped: also assert `$INSTDIR\.install-profile.json` was **not** written by the update (the `${isUpdated}` guard) |
| B11 | First-run markers | Note `.first-run-complete.json` + `.first-run-requirements.json` | Present; app opens straight to the shell with **no** provisioning screen |
| B12 | **Relocated data root** | On old build, use Change… to move the data root to `D:\ReframeData`; confirm `<userData>/data-dir.txt` | New build resolves to `D:\ReframeData`, not `%APPDATA%`. This is the scenario `dataRootIo.ts:114-141` exists for — test the *legacy-marker-only* variant too by deleting the `<userData>` copy and leaving `<exeDir>/data-dir.txt`, then asserting it is forward-migrated |
| B13 | Legacy `<exeDir>/data` | Simulate a pre-fix install: create `<exeDir>\data` with a sentinel file and no markers | Migrated to `%APPDATA%/media-studio` with the sentinel intact, **or** left untouched with a loud warning if `%APPDATA%` is occupied — never a partial move (`dataRootPlan.ts:15-19`) |
| B14 | Python `._pth` | Note `<resources>/python/python3*._pth` contents | Recreated by `ensurePthActivated()` (`main.ts:708-719`); sidecar starts; `import media_studio` succeeds. This one is *expected* to be destroyed — the test proves the repair, not the survival |
| B15 | Shortcuts | Rename the desktop shortcut, then update | Not duplicated (`installSection.nsh:40-50` `KeepShortcuts` path) |
| B16 | Downgrade refusal | Point a test feed at an older version | Update rejected with `refusing downgrade` (`updateVerify.ts:223-225`) |
| B17 | **Signature gate** | Publish a candidate **without** a `.sig` | Update rejected with `cannot fetch update signature` — i.e. prove D1 fires, then publish the `.sig` and prove it passes. Both states, per §2.5 |

### 3.3 Make it a harness, not a ritual

Rows B1-B14 are all "hash/count a known path before and after", which is an exact algorithm — write
it as a script, do not eyeball it. Concretely: a PowerShell probe that emits a JSON snapshot
(`{path, exists, sha256|byteTotal|rowCount}`) for every path in §0.4, run before and after, then a
diff with an expected-change allowlist (only `$INSTDIR` contents and `._pth` may differ). Anything
else that differs is a finding. `packaged-artifact-smoke` and the existing e2e Electron harness are
the natural hosts; the postcondition style matches what already runs in this repo.

Rows B8/B9 need a *negative* assertion (no download happened), which a snapshot diff cannot express.
Get it from the sidecar log or by blocking egress for the first launch after the upgrade — the
hermetic-probe pattern used in `docs/validation/tools/hermetic_probe.py` is the right instrument.

Honest limits of this plan: it is **not executed**. It is a design over measured paths. Rows B12/B13
in particular depend on `dataRootPlan.ts` behaviour I read but did not run.

---

## 4. Gap register — everything else professional installers do

Ranked by value ÷ effort. "Value" is user-visible or risk-reducing; "effort" is engineering days,
*roughly even* confidence on each estimate.

| # | Gap | Value | Effort | Verdict |
|---|---|---|---|---|
| **G1** | **Publish the `.sig` asset in the release runbook** (D1). Without it the shipped Ed25519 gate rejects every update after a full 223 MB download | Critical — the difference between a working and a dead updater | ~0.5 d (runbook + a CI step; `electron-builder.yml:14-19` already documents the command) | **DO FIRST.** Add a release-gate check that asserts a `.sig` exists for every `.exe` before the release leaves draft |
| **G2** | **Regenerate the update keypair offline** (D2) | Critical — the authenticity claim is otherwise cosmetic | ~0.5 d, mostly process | **DO FIRST**, blocks the first signed release |
| ~~**G3**~~ | ~~Un-draft a release~~ | — | — | **RETRACTED — do not do this.** Draft state is a deliberate safety interlock (`signed-release-ci.md:249`); un-drafting without a `.sig` ships an unsigned release. See the Reconciliation section. The real action is *execute the runbook* (G1), which ends in un-drafting |
| **G4** | **Authenticode signing** (§1) | High — publisher name in the warning, reputation carries across versions, and Smart App Control *blocks* unsigned binaries on Win 11 | ~1-2 d + ~$219/yr + ~2 wk lead + a CI signing credential (§1.6) | **OWNER DECISION B-2** — `GRILL-DECISION-QUEUE.md:63` is an open, unchecked item. §1 is the evidence for it, and it rebuts the recorded "No SmartScreen concern to solve" rationale (`:146`). Not a unilateral DO |
| **G5** | **RFC-3161 timestamping** alongside G4 | High — with the 460-day cap (§1.1b) untimestamped binaries stop validating fast | ~0 d (one config key, with G4) | **DO with G4** |
| **G6** | **Silent/unattended flags documented** — `/S`, `/D=`, `/allusers`, `/currentuser` already work (`assistedInstaller.nsh:122-133`, `installSection.nsh:5-7`); add `/PROFILE=` + `/PACKS=` (§2.4) and *document* them | Medium-high — the entry ticket for any IT deployment, and it is nearly free | ~0.5 d | **DO** with §2 |
| **G7** | **Release channels (stable/beta)** — `allowPrerelease` + `channel` are already supported by the pinned provider (`GitHubProvider.js:51-89`, `:132-138`); needs a UI toggle and a settings key. **Carries the D3 hazard**: setting `allowPrerelease: true` switches tag resolution from `/releases/latest` to the Atom feed, which enumerates *tags* — so a stale tag with a draft or asset-less release can be selected (`GitHubProvider.js:51-58`). Must be tested against a feed that contains exactly that (this repo currently does) | Medium-high — lets you test an installer change on volunteers before it reaches everyone | ~1-2 d | **DO**, with that specific test — cheapest risk reduction available for installer work specifically |
| **G8** | **Rollback on failed update.** Today `quitAndInstall()` replaces `$INSTDIR` with no retained previous version. A bad release is only recoverable by manually installing an older `.exe` | Medium-high | ~3-5 d (keep N-1 payload, or a repair-from-last-good path) | **CONSIDER** — cost is real; G7 plus a canary mitigates most of the exposure for less |
| **G9** | **Portable mode is built but undocumented.** `zip` target ships (`electron-builder.yml:135-136`) and `build/make-portable.ps1` exists, but there is no user-facing portable story and no statement about where a portable copy stores data | Medium | ~1 d (docs + assert the data root lands beside the exe or in `%APPDATA%`, deliberately) | **DO** — mostly writing down what exists |
| **G10** | **Uninstall cleanup choice.** `deleteAppDataOnUninstall: false` keeps multi-GB models forever with no way to reclaim them from the uninstaller | Medium — a user who uninstalls and does not know about `%APPDATA%/media-studio` silently loses GBs of disk | ~1 d (a `customUnInstall` checkbox; the hook exists in the template set) | **DO** — small, visible, and a genuine disk-space courtesy |
| **G11** | **winget manifest.** Reaches `winget install` users; the manifest is YAML pointing at the GitHub release; requires a stable installer URL + sha256 | Medium | ~1-2 d, and it **wants G4 first** (winget's validation and user trust both favour signed installers) | **DO after G4** |
| **G12** | **Staged rollout.** electron-builder supports a `stagingPercentage` in `latest.yml` | Low-medium — meaningful at thousands of users, not at tens | ~0.5 d | **DEFER** until install base justifies it |
| **G13** | **`perMachine` / elevated install — ALREADY LIVE IN THE FIELD, not hypothetical.** `GRILL-DECISION-QUEUE.md:24` records the owner's installed app as *"Reframe **1.4.1**, `D:\Program Files\Reframe`, uninstaller `/allusers` (needs elevation)"* — i.e. a per-machine-shaped install exists despite `perMachine: false` (`electron-builder.yml:141`), presumably via `/D=` into Program Files and/or `/allusers` (`assistedInstaller.nsh:122-133`) | Medium — this makes §2.6 defect 3 (elevated `$APPDATA` = the **admin's** profile) a live hazard for the component page, not a future one | ~1 d to test; ~2-3 d to support properly | **TEST BEFORE §2 SHIPS.** The staging-file design (§2.6C) is what makes this safe — it writes to `$INSTDIR`, which is correct under elevation. Re-confirm on an elevated Program Files install |
| **G14** | **MSI / Chocolatey.** MSI needs a different toolchain (WiX) and loses electron-updater's delta path; Chocolatey is a community-maintained wrapper around the same `.exe` | Low for a consumer video tool | MSI ~5+ d | **DECLINE** MSI. Chocolatey only if a user asks |
| **G15** | **Uninstall survey.** Opens a URL on uninstall | Low, and it conflicts with the local-first/privacy posture the app leads with (`FirstRunChooser.tsx:63-65`) | ~0.5 d | **DECLINE** |
| **G16** | **ARM64 build.** `target.arch: [x64]` only (`electron-builder.yml:134`) | Low today, rising | High — the embeddable CPython, ffmpeg, and the Remotion native compositor all need ARM64 variants | **DEFER**, revisit when a user asks |

### 4.1 The ordering that matters

**G1 + G2 first** — execute the `signed-release-ci.md` runbook end-to-end, including its own
unexercised dry-run (`signed-release-ci.md:325`), and replace the PoC keypair. These are the
difference between an updater that works and one that does not. Shipping a component page onto a
release pipeline that has never completed a signed release would be the classic inversion: the
visible work lands, the load-bearing work does not.

**Then G13's test** — before the §2 component page ships, confirm the staging-file handoff behaves on
an elevated `D:\Program Files` install, because that is what the owner actually runs.

**Then G6/G7** (cheap; G7 de-risks everything after it, but must be tested against the
`allowPrerelease` Atom-feed hazard), then G9/G10.

**G4/G5 (Authenticode) is not in this sequence — it is owner decision B-2.** It is the gap the owner
asked about and §1 is the evidence, but it carries a cost the sibling lane deliberately avoided (a
signing credential in CI, §1.6) and it contradicts a recorded — though unconfirmed — scope decision.
That belongs to the owner, not to this lane.

---

## Residual uncertainties (consolidated)

| Claim | Status | Settling experiment |
|---|---|---|
| Azure Artifact Signing is $9.99/mo Basic | Corroborated by two Microsoft doc pages; **not** read off a Microsoft price page (that page renders `$-` unauthenticated) | Azure pricing calculator, signed in, Basic SKU, target region |
| Reseller cloud-HSM add-on price | **UNVERIFIED** — `signmycode.com` returned HTTP 403 to automated fetch | Open the chosen reseller's OV page in a browser before ordering |
| `warningsAsErrors` catches a misspelled `!ifmacrodef` hook | **UNVERIFIED** | Rename the macro, build, expect failure (both-states test) |
| electron-builder recomputes `latest.yml` sha512 from the *signed* exe | **UNVERIFIED** for this repo's two-stage signing | Build with signing on; assert `dist/latest.yml` sha512 == sha512 of the signed `dist/*.exe` |
| Elevated `$APPDATA` is the admin's profile under `perMachine` | *likely* (standard NSIS/UAC) | `MessageBox $APPDATA` from an elevated scratch build |
| The `.nsh` in §2.4 compiles | **UNVERIFIED — not compiled** | `npx electron-builder --win` with the file in place |
| §3 matrix outcomes | **UNVERIFIED — designed, not executed** | Run the matrix against v1.4.0 → candidate |
| ~~GitHub's Atom feed excludes drafts~~ | **REFUTED and retired** — the feed lists tags, and `v1.4.1` is present. D3's conclusion now rests on `/releases/latest`, measured directly | done: `releases.atom` shows v1.4.1; `/releases/latest` shows v1.4.0 |
| `nsis.include` defaults to `<buildResources>/installer.nsh` | **MEASURED** in the pinned tool (`NsisTarget.js:600-603`) | done |
| With `allowPrerelease: true`, the Atom-feed path can select a draft/asset-less tag | *likely* — inferred from `GitHubProvider.js:51-58` taking the first entry outright; not executed | Set `allowPrerelease: true` in a scratch build against this repo's feed and observe which tag is chosen |
