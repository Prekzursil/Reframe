# Reframe — Signed Release CI Pipeline Design

**Repo:** `Prekzursil/Reframe` · **Verified against:** `origin/main @ 7502e3a` (fetched 2026-07-12)
**Scope:** READ-ONLY design. No repo files changed. The owner decides local-vs-CI builds.
**Drivers:** Issue **#283** (MERGED — offline Ed25519 auto-update auth) · Issue **#285** (OPEN — private key stays OFFLINE-only) · the #283 review's "add GitHub build-provenance once/if the build moves into Actions".

---

## 0. TL;DR (headline)

**Move the build into GitHub Actions, but split signing off it.** Add a new `windows-latest` `release.yml` that fires on a `v*.*.*` tag and runs a **strict TWO-PHASE release**:

- **Phase A (CI, automated):** build the real electron-builder installers → run `actions/attest-build-provenance` (keyless SLSA provenance) → publish installer + `latest.yml` + `.blockmap` + portable `.zip` to a **DRAFT** GitHub release. **No private key touches CI.**
- **Phase B (human, offline/airgapped):** download the exact CI-built `.exe`, `gh attestation verify` it is the CI bytes, sign `version‖sha512` with the offline Ed25519 key (`build/sign-release.mjs`), upload the `.sig`, then **un-draft** to go live.

This is the **only** option that simultaneously satisfies: CI builds ✔, working silent auto-update ✔, offline key per #285 ✔, and SLSA provenance ✔. It is **forced, not preferred** — see §3.

**Confidence: HIGH.** Every load-bearing fact below was read directly from source at `origin/main`; the electron-builder-in-Actions recipe is already proven working by the repo's own `e2e.yml` Windows leg.

---

## 1. Recommendation: CI build vs keep local

### Recommendation: **Build in CI (GitHub Actions). Sign locally.**

| Question | Verdict |
|---|---|
| Where does the **build** run? | **GitHub Actions `windows-latest`** (new `release.yml`) |
| Where does the **signature** get produced? | **Offline / airgapped human box** (unchanged from today; honors #285) |
| Is the app **code-signed** (Authenticode)? | **No** — stays unsigned, orthogonal to #285 (see §8) |

### Why CI-build wins over keep-local

1. **Provenance is only meaningful for a CI build.** `actions/attest-build-provenance` attests artifacts *the runner built*. You **cannot** attach GitHub SLSA provenance to a hand-built local binary. The #283 review's "add attestations" recommendation is *unlockable only by moving the build into Actions.* Keeping the build local forecloses the entire provenance layer.
2. **The provenance attestation is the bridge that makes offline signing safe** (§5). It gives the offline signer a cryptographic guarantee that the `.exe` they are about to sign is byte-identical to what the repo's CI produced and what users will download — so the offline `.sig` lands on trustworthy bytes.
3. **A CI Windows build is already proven low-risk here.** `.github/workflows/e2e.yml`'s `e2e-gui` job **already runs `npx electron-builder --config ../electron-builder.yml --win` on `windows-latest`** and drives the shipped `.exe` (`packaged.spec.ts` asserts `app.isPackaged === true`). `release.yml` is net-new but reuses a recipe CI has been exercising nightly. Confidence that "the build works in Actions" is empirical, not hopeful.
4. **Reproducible, auditable, tag-triggered releases** replace an ad-hoc local ceremony. Any consumer can independently `gh attestation verify` the installer.

### Why NOT fully local, and why NOT fully CI

- **Fully local (status quo):** no provenance, no third-party-verifiable build origin, release depends on one machine's toolchain state. Rejected.
- **Fully CI (build *and* sign in Actions):** would require the Ed25519 **private key in Actions secrets** — a direct violation of #285 and a nullification of the exact threat model `updateVerify.ts` exists to defend (§3). Rejected.
- **Two-phase (build+attest in CI, sign offline):** the only design that keeps all four properties. **Recommended.**

**Cost accepted:** the release is a **2-actor flow** (CI does Phase A; a human does the ~5-command Phase B offline), not a single push-button. That is the price of an offline root of trust for silent auto-update, and it is the price #285 explicitly chooses to pay.

---

## 2. The pipeline at a glance

```
 TAG PUSH  v1.4.1
     │
     ▼
┌─────────────────────────── PHASE A · GitHub Actions (windows-latest) ───────────────────────────┐
│  checkout → setup-node@20(+npm cache) → setup-python@3.12 → cache electron dl                    │
│  → app: npm ci → app/render-cli: npm ci → app: npm run build (electron-vite + Remotion bundle)   │
│  → pwsh build/python-embed-setup.ps1 -WithFfmpeg   (stages py3.12 + py3.14 embeds + ffmpeg)      │
│  → npx electron-builder --win --publish always  (GH_TOKEN, EP_DRAFT=true, NO CSC)                │
│       └─ uploads .exe + .exe.blockmap + .zip + latest.yml  to a  DRAFT  release                  │
│  → pwsh build/make-portable.ps1 -SkipZip           (slim / staged-resource GATE)                 │
│  → actions/attest-build-provenance  subject-path: dist/*-win-x64.exe , dist/*-win-x64.zip        │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
     │   (release is a DRAFT — its assets are NOT at the public /releases/download URL,
     │    so no client can auto-update to a still-unsigned build. updateVerify.ts fetches the
     │    .sig from that public URL, which only resolves AFTER un-draft.)
     ▼
┌────────────────────── PHASE B · Human, OFFLINE / airgapped (holds the Ed25519 key) ──────────────┐
│  gh release download v1.4.1  --pattern '*-win-x64.exe'        (the EXACT CI bytes)                │
│  gh attestation verify <exe> --repo Prekzursil/Reframe --signer-workflow …/release.yml           │
│  $env:REFRAME_UPDATE_PRIVATE_KEY = <offline pem>;  node build/sign-release.mjs --dist dist        │
│  gh release upload v1.4.1 dist/*.sig                                                              │
│  gh release edit  v1.4.1 --draft=false            ← auto-update goes LIVE for existing clients    │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. The CRITICAL signing-key decision (honoring #285)

### 3.1 The hard constraint, from source

`app/main/updateVerify.ts` is the shipped, dependency-free (`node:crypto` only) authenticity gate for **silent, in-place auto-update** — i.e. it authorizes what is effectively remote code execution on every client. Its own header states the threat: *"A compromised feed cannot forge a valid signature over `version‖sha512` without the offline private key."* Issue **#285** codifies the corollary: the Ed25519 **private key must NEVER touch the repo, the shipped app, or any shared/agent/CI environment.**

Two facts read directly from `updateVerify.ts` make "just sign in CI" unacceptable **and** make a naive "lower-trust CI key" ineffective:

1. **Fail-closed on a missing signature.** `verifyDownloadedUpdate` returns `{ ok:false, reason:'update signature is empty (no .sig published?)' }` when the `.sig` is empty/absent. **Auto-update stays dark until a real `.sig` is published** — which is *why* the draft-then-sign-then-publish ordering is mandatory, not stylistic.
2. **Any embedded key is full authority.** `verifyEd25519()` loops over `EMBEDDED_UPDATE_PUBLIC_KEYS = [current, next]` and accepts a signature valid under **any** of them. There is no channel/role scoping. So a *second* key held in CI could authorize a silent auto-update for **all** current clients exactly as fully as the offline key.

### 3.2 Options, graded (this is the decision to make)

| # | Option | Honors #285? | Automatable? | Verdict |
|---|---|---|---|---|
| **A** | Put the **raw Ed25519 key in Actions secrets**, sign in CI | ❌ No — violates #285 verbatim; a workflow-edit / malicious action / insider / platform compromise can exfiltrate it and forge a silent update | ✔ Fully | **REJECT** — nullifies the exact threat model `updateVerify.ts` was built to close |
| **A′** | A **separate "lower-trust" CI key**, added to `EMBEDDED_UPDATE_PUBLIC_KEYS` | ❌ Not as-is — `verifyEd25519` gives it **equal** auto-update authority; "lower trust" is a fiction without an app-code change | ✔ Fully | **REJECT** unless the owner *explicitly* accepts a CI secret as the auto-update root of trust. Would need a `updateVerify.ts` role-separation change (CI key ⇒ beta/prerelease channel only, or app *also* requires provenance) — out of this scope, and re-introduces the dependency/complexity #283 deliberately rejected |
| **B** | **Build + attest in CI; sign OFFLINE** (two-phase) | ✔ **Yes — key never in CI** | ◑ 2-actor | **✅ RECOMMENDED** — the only all-green option |
| **C** | **Keyless Sigstore/cosign** *for the in-app update signature* | ❌ Moves the trust anchor to GitHub's OIDC/Sigstore PKI — the **feed host could mint a valid installer signature**, defeating the feed-compromise model; also needs `sigstore-js` in the app (the CVE/lockfile surface #283 rejected) | ✔ Fully | **REJECT for the silent-apply gate.** Keyless is correct for *provenance* — which `attest-build-provenance` already gives you (§5) |
| **D** | **Cloud KMS/HSM signing in CI** (key never leaves the HSM; CI calls `sign`) | ❌ Still an **ONLINE** key — contradicts #285's offline letter & spirit | ✔ Fully | Note only as the path **if #285 is ever relaxed.** Industry-standard for "sign in CI without exposing raw material," but not what #285 asks for |

### 3.3 The decision

> **Keep the Ed25519 update-signing key OFFLINE (Option B). Do NOT put it — or any equal-authority sibling — in Actions secrets. Add `attest-build-provenance` in CI as a COMPLEMENTARY, keyless layer (zero long-lived secret), which is exactly the "Option 2 later hardening" #283 called for. Provenance and the Ed25519 `.sig` answer different questions and must coexist:**
> - **Provenance** = *"did THIS repo's CI build these exact bytes?"* — origin/integrity, for **humans/auditors** at download time (`gh attestation verify`).
> - **Ed25519 `.sig`** = *"should the shipping app APPLY this as a silent auto-update?"* — authenticity, feed-independent, for the **updater** (`node:crypto`, no network trust).

They are **orthogonal**. The attestation is a human tool that needs the `gh` CLI — it can **never** replace the in-app gate (an end user's app can't shell out to `gh`). Do not let anyone argue provenance lets you drop the `.sig`; it does not.

### 3.4 A #285 prerequisite that is independent of this CI work

`EMBEDDED_UPDATE_PUBLIC_KEYS` currently holds **proof-of-concept** keys (the file's own SECURITY NOTE: *"regenerate a fresh keypair on an offline machine before the first PRODUCTION signed release"*). That offline key-generation ceremony **is** #285. It is a Phase-B/offline prerequisite and must happen before the first real signed release, regardless of the pipeline. The pipeline design here assumes the production offline keypair exists and its public halves are embedded.

---

## 4. Repo facts that shaped the design (verified at `origin/main @ 7502e3a`)

| Fact | Evidence | Why it matters |
|---|---|---|
| Project is **npm, not pnpm**; two packages both under `app/` (`app`, `app/render-cli`) | `quality.yml` runs `npm ci`; `app/package.json` + `app/render-cli/package.json`; no `pnpm-lock.yaml` | CI uses `setup-node cache: npm` with `cache-dependency-path` listing **both** lockfiles |
| App is **`media-studio` v1.4.1** (`productName: Reframe`); installer name = `${name}-${version}-win-${arch}.${ext}` | `app/package.json`, `electron-builder.yml` `artifactName` | Artifacts are `media-studio-1.4.1-win-x64.exe` and `…-win-x64.zip`; matches `sign-release.mjs` `INSTALLER_SUFFIX = '-win-x64.exe'` |
| **Build must be `windows-latest`** | `electron-builder.yml` has only a `win:` target; embeds/ffmpeg staging is Windows PowerShell; `render-cli` ships a native Windows Remotion compositor | Cannot cross-build on the Linux runner `quality.yml` uses |
| `npm run build` (in `app/`) **already chains the Remotion bundle** — `build = tsc --noEmit && electron-vite build && npm run build:remotion`; `build:remotion = npm --prefix render-cli run bundle` | `app/package.json` scripts | **CI order is: `app npm ci` → `render-cli npm ci` → `app npm run build`.** render-cli deps MUST be installed *before* `npm run build` (else `build:remotion` fails). No separate `npm run bundle` step is needed. *(This reconciles the two research streams — see §11.)* Confirmed by `e2e.yml`, which uses exactly this order |
| **One** `python-embed-setup.ps1 -WithFfmpeg` stages **all three** extraResources: `build/python-embed` (3.12), `build/python-embed-314` (3.14 chatterbox), `build/ffmpeg/win` | `python-embed-setup.ps1` (reads: stages 3.12 embed, 3.14 embed, ffmpeg with `-WithFfmpeg`) | `python-embed-314` **and** `ffmpeg/win` are **NOT committed** (only `python-embed` 3.12 is). electron-builder errors if an `extraResources` `from` dir is missing, so **CI MUST run the staging script** |
| The staging script's SHA pins are **empty** (`-ExpectedPythonSha256`/`-ExpectedChatterboxPythonSha256`/`-ExpectedFfmpegSha256 = ''`) | `python-embed-setup.ps1` params | **Hardening TODO:** fill them (the script prints each sha256 on first run) so a mutated upstream python.org / BtbN asset fails the build. BtbN tag `autobuild-2026-07-03-13-21` is a dated durable third-party asset — SHA-pinning is the mitigation |
| **No code-signing / CSC** in config; electron-builder skips signing when no cert is discovered | `electron-builder.yml` (no `win.sign`, no CSC); `e2e.yml` sets `CSC_IDENTITY_AUTO_DISCOVERY: "false"` | Unsigned build by design (SmartScreen may warn). Set `CSC_IDENTITY_AUTO_DISCOVERY: "false"` in CI so electron-builder never tries to discover/download a signing identity (can hang; pulls `winCodeSign`). Authenticity is the app-layer Ed25519 gate, not Authenticode |
| `sign-release.mjs` signs **only `*-win-x64.exe`** (not the `.zip`), and **reads the full installer bytes** to compute `sha512` (`readFileSync(installerPath)`); reads version from `app/package.json`; message = `reframe:update:v1\n<version>\n<sha512-b64>` | `build/sign-release.mjs` | The `.sig` covers the **NSIS `.exe` only** (the auto-update target). Phase B **must download the full `.exe`** (the shipped script computes the digest from the file — a "digest-only" sign is not supported without editing the script). The offline box must be checked out at the release tag so `app/package.json` version matches |
| `make-portable.ps1 -SkipZip` = **CI gate mode**: slim assertions only, no zip. Reads `dist/win-unpacked` (repo-root `dist/`) | `build/make-portable.ps1` (params `-SkipZip`, `-MaxMB 800`; asserts: no `*.gguf/*.safetensors/*.pt/*.ckpt`, no `torch` pkg, no `resources/sidecar/envs`, required staged resources present, size ≤ 800 MB; terminal `SUCCESS:`/`FAILED:`) | Run it as a **gate** after electron-builder (electron-builder already emits a `.zip` target, so `-SkipZip`). Its separately-named `media-studio-portable-win-x64.zip` is NOT what electron-builder publishes — skip it unless you also `gh release upload` it |
| Existing workflows pin every action **by commit SHA** | `quality.yml`, `e2e.yml` (`checkout@df4cb1c…#v6.0.3`, `setup-python@ece7cb…#v6.3.0`, `setup-node@48b55a…#v6.4.0`, `upload-artifact@330a01c…#v5.0.0`) | `release.yml` must do the same — reuse those exact SHAs; pin `actions/cache` and `actions/attest-build-provenance` by SHA too |
| **No release workflow exists** | `.github/workflows/` = `{quality, e2e, mutation}.yml` | `release.yml` is net-new; leave `quality.yml` (Linux lint/test gate) untouched |

---

## 5. Provenance is the bridge that makes the split safe

`sign-release.mjs` signs `version‖sha512(installer_bytes)` — the `.sig` is valid **only** for the exact bytes signed, and `updateVerify.ts` recomputes `sha512` of the downloaded file to check it. Therefore the owner must sign **the same bytes CI built and released** — a *local rebuild would produce different bytes* (electron-builder/NSIS Windows builds embed timestamps and are not bit-reproducible), breaking both the provenance digest match and the users' download.

`actions/attest-build-provenance` gives the owner a cryptographic way to confirm, **before signing**, that the downloaded `.exe` is byte-identical to what the repo's CI produced:

- **Keyless (OIDC):** the runner's OIDC token → short-lived Sigstore/Fulcio cert → signs an in-toto SLSA provenance predicate → recorded in the Rekor transparency log. **No long-lived secret stored.** SLSA **Build Level 2** out of the box.
- **Verify (online):** `gh attestation verify <exe> --repo Prekzursil/Reframe [--signer-workflow …/release.yml]`.
- **Verify (offline/airgapped, supported):** pre-stage on an online box `gh attestation download <artifact> -R Prekzursil/Reframe` (writes a `.jsonl` bundle) + `gh attestation trusted-root > trusted_root.jsonl`; then on the airgapped box `gh attestation verify <artifact> -R Prekzursil/Reframe --bundle <file>.jsonl --custom-trusted-root trusted_root.jsonl` — **no network at verify time.** This matters because the signing box is airgapped.

So the flow is: CI is the **sole builder** → it attests the bytes → the human verifies those bytes are the CI bytes → the human applies the offline `.sig` to bytes now trusted by provenance. Provenance is what lets you trust a CI artifact enough to sign it offline.

---

## 6. Phase A — `release.yml` sketch (the deliverable)

> Pin the two currently-unpinned actions (`actions/cache`, `actions/attest-build-provenance`) by commit SHA at implementation, matching the repo convention. `attest-build-provenance` is at **v4** (v4.1.1, 2026-06-26); its README now says new setups may call **`actions/attest`** directly — either works; `attest-build-provenance@<sha>` is the most-documented. Reused SHAs below are copied verbatim from `quality.yml`/`e2e.yml`.

```yaml
name: release

on:
  push:
    tags:
      - 'v*.*.*'                     # release discipline: tag == v<app/package.json version>
  workflow_dispatch:                 # for a throwaway dry-run (see §10)
    inputs:
      ref:
        description: 'Existing tag to (re)build, e.g. v0.0.0-ci-test'
        required: true

permissions:
  contents: write                    # create the DRAFT release + upload installer/latest.yml/blockmap/zip (default GITHUB_TOKEN, same-repo)
  id-token: write                    # OIDC -> Sigstore/Fulcio cert for the provenance attestation
  attestations: write                # persist the SLSA provenance attestation

concurrency:
  group: release-${{ github.ref }}
  cancel-in-progress: false          # NEVER cancel a half-finished release upload

jobs:
  build-win:
    runs-on: windows-latest
    env:
      # electron-builder must NOT try to discover a code-signing identity in CI: this app is
      # deliberately unsigned (electron-builder.yml has no CSC). Discovery can hang and pulls
      # the winCodeSign toolset. Mirrors e2e.yml's Windows leg.
      CSC_IDENTITY_AUTO_DISCOVERY: "false"
    steps:
      - name: Checkout
        uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10   # v6.0.3 (repo-pinned)

      - name: Set up Node
        uses: actions/setup-node@48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e  # v6.4.0 (repo-pinned)
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: |                 # BOTH lockfiles — multi-package, no root lock
            app/package-lock.json
            app/render-cli/package-lock.json

      - name: Set up Python                          # the ps1 downloads the EMBED zips itself;
        uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1  # v6.3.0 (repo-pinned)
        with:
          python-version: "3.12"                     # parity with quality.yml / e2e.yml

      - name: Cache Electron + electron-builder binary downloads
        uses: actions/cache@<PIN-BY-SHA>             # actions/cache v4 — avoids re-downloading Electron each run
        with:
          path: |
            ~\AppData\Local\electron\Cache
            ~\AppData\Local\electron-builder\Cache
          key: win-electron-${{ hashFiles('app/package-lock.json') }}
          restore-keys: win-electron-

      - name: Install app deps
        working-directory: app
        run: npm ci

      - name: Install render-cli deps                # MUST precede `npm run build` (build:remotion --prefix render-cli)
        working-directory: app/render-cli
        run: npm ci

      - name: Build app (electron-vite + Remotion bundle)
        working-directory: app
        run: npm run build                           # tsc --noEmit && electron-vite build && npm run build:remotion

      - name: Stage packaged runtime (embeddable CPython 3.12 + 3.14 + ffmpeg)
        shell: pwsh
        run: ./build/python-embed-setup.ps1 -WithFfmpeg
        # HARDENING TODO: pass -ExpectedPythonSha256/-ExpectedChatterboxPythonSha256/-ExpectedFfmpegSha256
        # (currently empty in the script) so a mutated python.org / BtbN asset fails the build.

      - name: Package Windows installers -> DRAFT release
        working-directory: app
        run: npx electron-builder --config ../electron-builder.yml --win --publish always
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}      # default token; contents:write suffices (same-repo, no PAT)
          EP_DRAFT: "true"                           # keep it a DRAFT (default anyway) so nothing is public/updatable yet
          # NO CSC_LINK / WIN_CSC_LINK -> Authenticode stays OFF. NO REFRAME_UPDATE_PRIVATE_KEY here — signing is offline.

      - name: Slim + staged-resource GATE (no publish side-effects)
        shell: pwsh
        run: ./build/make-portable.ps1 -SkipZip      # asserts no-torch/no-weights/no-envs + required staged resources + size<=800MB

      - name: Attest SLSA build provenance for the CI-built installers
        uses: actions/attest-build-provenance@<PIN-BY-SHA>   # v4.1.1 (or actions/attest); keyless OIDC -> Fulcio -> Rekor
        with:
          subject-path: |
            dist/*-win-x64.exe                       # NSIS installer — the auto-update + Ed25519 target
            dist/*-win-x64.zip                       # portable — attested so users can verify its origin too
```

**Notes on the sketch**
- **electron-builder targets the release for `v${package.version}`, not the git tag directly.** The `on: push: tags` trigger fires the run; electron-builder then creates/updates the **draft** release for `v1.4.1` (from `app/package.json`). Hence the discipline: **tag `vX.Y.Z` == `app/package.json` version `X.Y.Z` == installer `media-studio-X.Y.Z-win-x64.exe`** must all agree (`sign-release.mjs` also warns if the installer name lacks the package version).
- **Draft is the safety interlock.** Draft assets are not served at the public `/releases/download` URL. `updateVerify.ts` fetches the `.sig` from that public URL, which only resolves after un-draft — so **no client can auto-update to an unsigned draft.**
- **`--publish always`** emits `latest.yml` (the electron-updater feed) + the NSIS `.blockmap` (delta updates) + `.exe` + `.zip` into the draft. `EP_PRE_RELEASE=true` would force a prerelease (useful for a `-ci-test` tag).
- **Attestation order** is immaterial relative to publish (attestations live in GitHub's attestation store keyed by digest, not as release assets), but placing it after the slim gate means only gate-passing artifacts get attested.

---

## 7. Phase B — offline sign + publish (human, on the airgapped signing box)

Exact commands (PowerShell). This is the **only** part that touches the private key, and it runs where #285 requires — offline.

```powershell
# Pre: this box holds the OFFLINE Ed25519 private key and has the repo checked out AT THE TAG
#      (sign-release.mjs reads the version from app/package.json).
git -C C:\src\Reframe fetch --tags
git -C C:\src\Reframe checkout v1.4.1

# 1. Pull the EXACT CI-built installer from the DRAFT release (token needs repo read).
gh release download v1.4.1 --repo Prekzursil/Reframe -D dist --pattern "*-win-x64.exe"
#    (latest.yml + .blockmap are already on the draft from CI; only the .exe is needed to sign)

# 2. PROVE it is the byte-identical CI artifact BEFORE signing it (SLSA provenance).
gh attestation verify dist/media-studio-1.4.1-win-x64.exe --repo Prekzursil/Reframe `
    --signer-workflow Prekzursil/Reframe/.github/workflows/release.yml
#    Fully-offline variant (pre-staged on an online box):
#      gh attestation download dist/media-studio-1.4.1-win-x64.exe -R Prekzursil/Reframe   # -> *.jsonl
#      gh attestation trusted-root > trusted_root.jsonl
#    then here:  gh attestation verify <exe> -R Prekzursil/Reframe --bundle <file>.jsonl --custom-trusted-root trusted_root.jsonl

# 3. Sign version‖sha512(installer) with the OFFLINE key (the ONE step needing the private key).
$env:REFRAME_UPDATE_PRIVATE_KEY = (Get-Content C:\offline\reframe-ed25519.pem -Raw)
# optional: $env:REFRAME_UPDATE_PRIVATE_KEY_PASSPHRASE = '...'
node build/sign-release.mjs --dist dist            # writes dist/media-studio-1.4.1-win-x64.exe.sig
Remove-Item Env:\REFRAME_UPDATE_PRIVATE_KEY        # scrub the key from the environment

# 4. Upload the detached signature(s) to the SAME draft release.
gh release upload v1.4.1 dist/*.sig --repo Prekzursil/Reframe

# 5. Publish (un-draft) — the moment auto-update goes live for existing clients.
gh release edit v1.4.1 --repo Prekzursil/Reframe --draft=false
```

After un-draft: `latest.yml` (electron-updater integrity), the installer, and its `.sig` all reference the **same CI bytes**, so **both** electron-updater's sha512 check **and** `updateVerify.ts`'s Ed25519 check pass. Digest stability holds because the owner signed the **downloaded release bytes**, not a fresh local build.

---

## 8. Code-signing (Authenticode) — out of scope, no action needed

`electron-builder.yml` sets no `win.sign` and no CSC; electron-builder skips signing when no certificate is discovered (and avoids downloading `winCodeSign`). The app ships unsigned by design; app-layer Ed25519 substitutes for OS publisher trust. **This is orthogonal to #285.** A future optional enhancement — real Windows code signing via `win.sign: { type: azure }` (Azure Trusted Signing) or an EV/OV cert in a cloud HSM — would reduce SmartScreen friction but introduces an **online** signing key with its own cost/threat tradeoffs and does **not** replace the offline Ed25519 update key. Do not conflate the two.

---

## 9. Tradeoffs for the owner to decide

**On the signing-key decision (the crux):**

1. **Two-phase (B, recommended) vs sign-in-CI (A/A′):** B keeps the auto-update root of trust offline (#285 honored) at the cost of a **2-actor, not push-button** release; A/A′ are fully automated but make **a CI secret the root of trust for silent RCE-equivalent updates** — a single exfiltration forges an update for every client. Choose automation-vs-trust deliberately.
2. **"Lower-trust CI key" (A′) is a fiction as-is:** because `verifyEd25519` accepts *any* embedded key equally, a CI key has **full** auto-update authority. It only becomes genuinely lower-trust with a `updateVerify.ts` **role-separation code change** (CI key ⇒ prerelease channel only, and/or app additionally requires provenance) — extra code + the complexity #283 rejected. Adopt only if you accept that scope.
3. **Key rotation only protects FUTURE releases:** a live CI-key compromise still forges an update for all *current* clients before you notice. Rotation is not a substitute for keeping the key offline.
4. **KMS/HSM (D) is the clean "sign in CI" path IF #285 is ever relaxed:** raw key never leaves the HSM, but it is still an **online** key — offered only as the future fallback, not now.
5. **Keyless Sigstore (C) is right for provenance, wrong for the silent-apply gate:** using it in-app would move the trust anchor to the feed host (GitHub) and add `sigstore-js` (CVE/lockfile surface). Keyless already lives where it belongs — the provenance attestation.

**On build location & pipeline:**

6. **CI build (recommended) vs keep-local:** CI unlocks provenance + reproducibility + `gh`-verifiable origin; local forecloses provenance entirely. CI adds a `windows-latest` minute cost and a network dependency on python.org/BtbN staging (mitigate: SHA-pin, or commit `python-embed-314`+`ffmpeg/win` ~+150 MB like `python-embed` already is, or cache the staged dirs).
7. **Staged binaries — 3 sub-options:** (a) run `python-embed-setup.ps1 -WithFfmpeg` in CI each run (simplest; a build-time network dep — **fill the empty SHA pins**); (b) commit `python-embed-314` + `ffmpeg/win` to the repo (consistent with `python-embed`, removes the network dep, +~150 MB); (c) `actions/cache` the staged dirs keyed on script+versions. Pick per your tolerance for repo size vs build-time network trust.
8. **SLSA Build L2 (default) vs L3:** L2 is out-of-the-box. L3 requires extracting the build into a **reusable workflow** (isolates signing material from user build steps) and consumers pinning `--signer-workflow`. Start L2; upgrade later.
9. **Public vs private repo changes the Sigstore instance:** if `Prekzursil/Reframe` is **public**, the attestation + Rekor entry are **public and immutable** (fine for OSS, but note the release history is transparency-logged); if **private**, it uses GitHub's private Sigstore instance (plan-gated). Confirm which you want.
10. **Attestation entrypoint:** `attest-build-provenance@v4` (most-documented) vs `actions/attest` (the forward-path wrapper) — both functional; **pick one and pin by SHA.**
11. **Offline signer ergonomics:** the shipped `sign-release.mjs` reads the full `.exe` to compute the digest, so Phase B downloads the full installer (fine — you want the real bytes to verify anyway). If you ever want a truly "digest-only" offline step (no full download), that is a small script change to accept a precomputed sha512 — optional, not needed.

---

## 10. Pre-flight / dry-run plan (do this before a real release)

1. Ensure the **production** offline Ed25519 keypair exists (the #285 ceremony) and its public halves replace the PoC keys in `EMBEDDED_UPDATE_PUBLIC_KEYS`.
2. **Fill the empty SHA pins** in `python-embed-setup.ps1` (run it once locally, copy the printed sha256s).
3. **Dry-run tag:** bump `app/package.json` to a throwaway prerelease (e.g. `1.4.2-ci.1`), tag `v1.4.2-ci.1`, push. (electron-builder targets `v${package.version}`, so the tag must equal it; `EP_PRE_RELEASE=true` keeps it a prerelease.) Confirm the loop: **draft created → assets uploaded → `attest-build-provenance` succeeds → `gh release download` → `gh attestation verify` passes → `node build/sign-release.mjs` → `.sig` uploaded → un-draft**.
4. Delete the throwaway release/tag; restore the version. Only then cut the real `vX.Y.Z`.

---

## 11. Reconciliation of the two research streams (where they differed, resolved by source)

- **Build ordering.** Stream 1: `app npm ci → render-cli npm ci → app npm run build` (build already chains Remotion). Stream 2: `npm run build` then `render-cli npm ci` then a separate `npm run bundle`. **Stream 1 is correct** — `app/package.json` shows `build:remotion = npm --prefix render-cli run bundle`, so render-cli deps must exist *before* `npm run build`, and no separate bundle step is needed. `e2e.yml` uses exactly Stream 1's order. Adopted.
- **Offline sign cost.** Stream 2: "signer only needs the digest, no full download — cheap." Stream 1: "download-and-sign the full installer." **Stream 1 matches the shipped tooling** — `sign-release.mjs` computes `sha512` from `readFileSync(installerPath)`, so the full `.exe` must be present. Stream 2's digest-only is a *possible future script tweak*, not current behavior. Adopted Stream 1; noted the tweak as optional (§9.11).
- **Everything else converged:** two-phase necessity, `windows-latest`, provenance-as-bridge, npm-not-pnpm, draft interlock, no-CSC, permissions, `gh attestation verify`. Both streams HIGH confidence; independently corroborated by direct source reads here.

---

## 12. Confidence & sources

**Confidence: HIGH** on: the #285 two-phase necessity (read `updateVerify.ts` fail-closed + accept-any-key + `sign-release.mjs`); repo build reality (files read at `origin/main @ 7502e3a`); electron-builder publish/draft/`GH_TOKEN`/CSC-skip semantics (official docs + the repo's own working `e2e.yml` Windows leg); attestation permissions + `gh attestation verify`/offline-verify syntax (GitHub docs); `attest-build-provenance` at v4/v4.1.1 recommending `actions/attest` (fetched from the action's README, 2026-07-12).
**Confidence: MEDIUM** on: exact behavior of the network staging script inside a `windows-latest` runner (not executed here — validate on the dry-run tag; expect to fill the empty SHA pins); which attestation entrypoint to pin (`@v4` vs `actions/attest` — both functional, pick+pin).

**Primary source reads (`origin/main @ 7502e3a`, 2026-07-12):**
- `build/sign-release.mjs` — offline Ed25519 signer; `$REFRAME_UPDATE_PRIVATE_KEY`; message `reframe:update:v1\n<version>\n<sha512-b64>`; `INSTALLER_SUFFIX '-win-x64.exe'`; reads full installer bytes; version from `app/package.json`.
- `app/main/updateVerify.ts` — pure `node:crypto` verifier; rejects empty `.sig`; `verifyEd25519` accepts ANY of `[current, next]`; downgrade guard; fixed public `/releases/download/v<ver>/<file>.sig` URL; PoC-keys-regenerate SECURITY NOTE.
- `electron-builder.yml` — github publish provider (`Prekzursil/Reframe`); `nsis`+`zip` win targets; `artifactName ${name}-${version}-win-${arch}.${ext}`; no CSC; `extraResources` require `python-embed`, `python-embed-314`, `ffmpeg/win`, `render-cli/*`; `directories.output ../dist`; the 6-step build header incl. `4b node build/sign-release.mjs`.
- `build/python-embed-setup.ps1` — stages 3.12 embed + 3.14 embed + BtbN ffmpeg (`-WithFfmpeg`); pinned URLs; **empty** `-Expected*Sha256`; "run manually, never from an agent session".
- `build/make-portable.ps1` — `-SkipZip` gate mode; slim assertions (no `*.gguf/*.safetensors/*.pt/*.ckpt`, no `torch`, no `resources/sidecar/envs`), required staged resources, `-MaxMB 800`; terminal `SUCCESS:`/`FAILED:`.
- `app/package.json` — `media-studio` 1.4.1; electron ^39, electron-builder ^26.15.3, electron-updater ^6.8.9, electron-vite ^3.1.0; `build` chains `build:remotion`.
- `.github/workflows/quality.yml` — Linux lint/test gate; `npm ci` app + render-cli; SHA-pinned actions; `permissions: contents: read`.
- `.github/workflows/e2e.yml` — `e2e-gui` **already builds the real electron-builder package on `windows-latest`** (`--publish never`), `CSC_IDENTITY_AUTO_DISCOVERY: "false"`, render-cli-ci-before-`npm run build`, `python-embed-setup.ps1 -WithFfmpeg`; SHA-pinned actions incl. `upload-artifact@330a01c…#v5.0.0`.
- `.github/workflows/` listing — only `{quality,e2e,mutation}.yml`; no release workflow.

**External docs (fetched/searched 2026-07-12):**
- `actions/attest-build-provenance` README — v4 current (v4.1.1, 2026-06-26); recommends `actions/attest` for new setups. (WebFetch)
- GitHub Actions artifact-attestations docs — permissions `id-token: write` / `attestations: write` / `contents: read|write`; `subject-path` multiline glob; keyless OIDC→Fulcio→Rekor; SLSA Build L2 default, L3 via reusable workflow; offline verify via `gh attestation download` + `trusted-root` + `--bundle`/`--custom-trusted-root`.
- `electron.build` publish docs + electron-builder GitHub-Actions guide — `--publish onTag|onTagOrDraft|always|never`; `GH_TOKEN`/`GITHUB_TOKEN` + `contents: write`; draft default; `EP_DRAFT`/`EP_PRE_RELEASE`; `setup-node cache: npm`; cache the Electron download dirs.
- `gh` CLI manual — `gh attestation verify <file> --repo owner/repo [--signer-workflow …]`.
- Issues **#283** (MERGED — provenance is the later hardening layered on top, rejects Sigstore/TUF app deps) and **#285** (OPEN — private key never in repo/app/shared/CI).
```
