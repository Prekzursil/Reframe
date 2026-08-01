# Reframe — Technical Best-Practice Dossier

Build-ready synthesis of four research streams (FFmpeg bundling · llama-server lifecycle · Electron secret handling · on-demand model-download UX). Each section states the concrete recommendation Reframe should adopt, then the licensing/robustness gotchas that must not be forgotten. Dated 2026-07-04.

---

## WS-A · Bundling static ffmpeg + ffprobe into the closed-source Electron Windows app

### Recommendation
Vendor **BtbN `win64-lgpl` static `ffmpeg.exe` + `ffprobe.exe`** into `build/ffmpeg/win/` and ship them via electron-builder **`extraResources`**, invoked as a child process (directly via `execFile`, or through fluent-ffmpeg with `setFfmpegPath`/`setFfprobePath`). Resolve the path in the **main process**:

```js
const ffmpegDir = app.isPackaged
  ? path.join(process.resourcesPath, 'ffmpeg')                 // packaged
  : path.join(__dirname, '..', 'build', 'ffmpeg', 'win');     // dev
const ffmpegPath  = path.join(ffmpegDir, 'ffmpeg.exe');
const ffprobePath = path.join(ffmpegDir, 'ffprobe.exe');
```

```jsonc
"build": { "extraResources": [ { "from": "build/ffmpeg/win", "to": "ffmpeg", "filter": ["**/*"] } ] }
```

### Why this over the alternatives
- BtbN is the **only mainstream source with a redistribution-safe LGPL static Windows build**. gyan.dev main builds are all `--enable-gpl` (GPL v2+).
- `extraResources` lands the exes in `process.resourcesPath` — **outside `app.asar`** — so no `asarUnpack` gymnastics and no "can't exec from inside asar" failure. (If instead you use `ffmpeg-static`/`@ffmpeg-installer`, you MUST add `asarUnpack` and rewrite `app.asar` → `app.asar.unpacked` in the returned path.)

### Licensing / gotcha notes (load-bearing)
- **LGPL vs GPL is the whole game.** FFmpeg is LGPL 2.1+ by default; `--enable-gpl` (needed for libx264/libx265/libxvid) flips the entire binary to GPL v2+. Invoking an **unmodified LGPL exe as a separate child process** is redistribution-safe in a proprietary app.
- **Never use `ffmpeg-static` (eugeneware)** — its package and binaries are GPL-3.0. `@ffmpeg-installer/ffmpeg` (LGPL-2.1) is cleaner but you lose control of the exact build/flags.
- **LGPL obligations to satisfy:** (a) ship the `LICENSE`/`COPYING` file next to the binaries, (b) don't modify the binaries, (c) record the **exact BtbN release tag** so you can honor the source-availability obligation (a link to that tag suffices in practice).
- **Functional cost of LGPL:** no software `libx264`/`libx265` encoders. Decoding H.264/H.265 still works. For encoding you get **OpenH264** and hardware encoders (`h264_nvenc`/`hevc_nvenc`/`h264_qsv`/`h264_amf`). If Reframe ever needs software x265, that path is GPL-only — use `hevc_nvenc`/hardware instead rather than shipping GPL.
- **Patents are orthogonal.** H.264/H.265 carry MPEG-LA royalties independent of GPL/LGPL — confirm separately for commercial distribution.
- **Size:** budget **~150 MB** for both full static exes; drop to an essentials/reduced LGPL build if the installer is too heavy. Prefer **static over shared** (single self-contained exe, no DLL path juggling).

---

## WS-B · llama-server lifecycle & readiness for the desktop app

### Recommendation
Gate readiness on **`GET /health` HTTP status code** (200 = ready, 503 = still loading), never on the body text. After green, optionally do one `GET /v1/models` to assert the expected model/alias loaded. Use a **bounded poll** that treats both connection-refused and HTTP 503 as "keep waiting", only 200 as ready, with a hard wall-clock deadline and a separate per-request timeout, and that fails fast if the child process already exited:

```python
def wait_until_ready(base_url, timeout_s=90.0, interval_s=0.5, proc=None):
    url = base_url.rstrip("/") + "/health"
    deadline = time.monotonic() + timeout_s
    while True:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"llama-server exited early, code={proc.returncode}")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=3) as r:
                if r.status == 200: return
        except urllib.error.HTTPError as e:
            if e.code != 503: raise           # 503 = still loading, tolerate
        except (urllib.error.URLError, ConnectionError, socket.timeout, OSError):
            pass                               # not listening yet
        if time.monotonic() >= deadline:
            raise TimeoutError(f"llama-server not ready after {timeout_s:.0f}s at {url}")
        time.sleep(interval_s)
```

Recommend `timeout_s` ≈ **90–120 s** for a 4B on desktop hardware (covers cold disk + CUDA init), `interval_s` 0.25–0.5 s. Watch child stdout in parallel for `main: server is listening ... - starting the main loop`.

### Reuse a running instance (avoid re-paying cold load)
Probe first, spawn only if needed. Bind the port deterministically (`--host 127.0.0.1 --port <fixed>`):
- **200** → instance up & ready → reuse (optionally check `/v1/models` id/alias matches).
- **503** → instance up but loading → reuse, run `wait_until_ready`.
- **Connection refused** → nothing there → spawn, then `wait_until_ready`.
- Guard the "probe → spawn" critical section with a **local lock file / named mutex** so two app windows don't start two servers on the same port. A spawn that fails because the port is bound is itself a signal an instance exists — re-probe rather than erroring.

### Graceful shutdown
- **No HTTP shutdown endpoint** — process signals only. `llama-server` handles SIGINT/SIGTERM cleanly.
- **Windows:** no real SIGTERM. Spawn in its own process group and send `CTRL_BREAK_EVENT`, or simplest/reliable call `proc.terminate()`/`TerminateProcess`. If launched via a wrapper, kill the whole tree (`taskkill /T /PID`) so the actual `llama-server.exe` dies.
- **POSIX:** SIGTERM then `wait()` with timeout, escalate to SIGKILL only if it doesn't exit in a few seconds.
- Keep the `Popen` handle for app lifetime; register atexit cleanup that terminates the tree — never orphan.

### Gotchas (load-bearing)
- **`/health` is served on the same request queue as everything else.** Under heavy load / long prompt processing it can be slow or transiently 503 (upstream #20684). → Give the *readiness* probe a generous timeout; do **NOT** run an aggressive *liveness* probe that kills the server for a briefly-slow `/health` during a big generation.
- **503 means "still coming up," not "failed."** Large models / RPC tensor upload can hold 503 a long time (#19745). Only a hard wall-clock timeout should declare failure.
- Don't use `/v1/models` as a readiness signal (weaker loading-window semantics; `id` defaults to the GGUF path unless `--alias`). Don't rely on `/health` for slot availability — use `/slots` (`--slots`) for concurrency.
- `--timeout N` (default 3600 s) is the inflight-request socket timeout, **not** a lifecycle/idle-exit control.
- **Cold-load reality for a ~4B GGUF** (Q4_K_M ≈ 2.3–2.8 GB): warm cache ~1–4 s; cold disk ~5–15 s; larger quants or GPU/CUDA init 20–40 s+. **Do not hardcode a fixed sleep** — poll and size the timeout conservatively.

---

## WS-D · Secure API-key handling in Electron + handoff to the Python sidecar

### Recommendation
1. **Store at rest with `safeStorage.encryptStringAsync`** (OS-keyring backed), persisted as base64 in `app.getPath('userData')`. Gate everything on `isEncryptionAvailable()`.
2. **Decrypt with `decryptStringAsync` in the MAIN process only**, and honour the returned `shouldReEncrypt` flag (master-key rotation) by re-encrypting and rewriting the file.
3. **Spawn the Python sidecar with a scrubbed, allowlisted env** — never spread `process.env` wholesale, and the key is **NOT in env or argv**.
4. **Deliver the key over stdin / an existing framed stdio channel, per request** — a private parent↔child pipe invisible to process listings. Bound the plaintext lifetime in the child to the request.
5. **Renderer never sees plaintext:** `contextIsolation:true`, `nodeIntegration:false`, `sandbox:true`; expose only narrow **intent-based** IPC via `contextBridge` (`api.transcribe(payload)`, `api.saveKey(plaintextOnce)`) — **never `api.getKey()`**. Disable DevTools in production.
6. **Migrate legacy plaintext:** read → `encryptStringAsync` → write ciphertext → delete plaintext → **rotate the key at the provider** (the only honest remediation).

### Why NOT env vars or argv
Both leak plaintext to anything that can enumerate processes:
- **argv:** `/proc/<pid>/cmdline`, and on Windows `tasklist` / `Get-CimInstance Win32_Process`.CommandLine / Process Explorer.
- **env:** `ps -wwwE`, `/proc/<pid>/environ`, **inherited by every grandchild by default**, and routinely exfiltrated by crash reporters / error trackers (Sentry) / "dump the environment" debug logs.
- Both also end up in crash dumps and shell history.

### Gotchas (load-bearing)
- **`safeStorage` is main-process only** and only ready after the `app` `ready` event (Win/Linux) / Keychain reachable (mac) — calling too early throws.
- **Windows DPAPI protects against *other users* and disk theft — NOT same-user processes/malware/debuggers.** Any code running as the same user can call `CryptUnprotectData()`. The cipher is **unauthenticated AES-128-CBC with a fixed 16-space IV** — identical plaintext → identical ciphertext. Treat it as "raise the bar against casual/offline theft," not a vault against a local same-user attacker.
- **Linux silent-plaintext fallback:** without libsecret/kwallet, safeStorage falls back to `basic_text` (PBKDF2-HMAC-SHA1, hardcoded `"saltysalt"`, **1 iteration**, hardcoded password) — effectively plaintext while *appearing* encrypted. **Call `getSelectedStorageBackend()` at startup and refuse/loudly-warn on `basic_text`.** Never call `setUsePlainTextEncryption(true)` in production.
- Prefer the **async** `encrypt/decryptStringAsync` variants (non-blocking, support key rotation, tolerate temporary keyring unavailability; sync API may be deprecated).
- Ciphertext is **not portable** across users/machines (DPAPI is per-user) — don't sync the blob and expect it to decrypt.
- **"Secure delete" is largely a myth** on SSD/CoW/journaling storage — after distributing a plaintext key, **rotate at the provider**; overwrite-then-unlink is only defense-in-depth. Also scrub renderer stores (`localStorage.removeItem`) and logs.
- JS strings can't be zeroed — keep plaintext lifetime minimal; prefer a `Buffer` you can `.fill(0)` where you own it.

---

## WS-C · On-demand model-download UX + install profiles

### Where Reframe already stands (do NOT rebuild the core)
`sidecar/media_studio/assets/manager.py` + `manifest.py` already **meet or exceed** Ollama/LM Studio/A1111/HF on the fundamentals: resumable HTTP Range (206/200/**416-past-EOF-as-complete**), atomic `.part` + `os.replace`, cancellation keeps `.part` for resume, **mandatory SHA256 on-complete** (rejects `download` assets with no `sha256`; requires HF **commit hash, not branch**; deletes `.part` on mismatch), whole-batch disk preflight (+256 MB), installed-detection that agrees with real layout (size-plausibility `MIN_SIZE_FRACTION 0.5`, HF snapshot presence, env sentinel, settings `detect` probe), size-weighted aggregate progress, offline gate, and verify-before-execute for `get-pip.py`. The adoptable value is in the **surface layer**, not the plumbing.

### Recommendations to adopt, in priority order
1. **ETA + speed in the progress payload (high value, low cost).** Today `on_frac` emits only `"{done}/{total} MB"`. Add a rolling-window rate (bytes over the last ~3–5 s, Ollama-style time-bucket) and emit `{ pct, mbDone, mbTotal, mbps, etaSec }` so the UI shows "1.2 GB / 2.5 GB · 42 MB/s · ~31 s". Pure addition to `_download_file`'s loop.
2. **Automatic retry with exponential backoff + jitter (robustness gap).** Reframe currently raises on the first network error. Wrap the `client.stream` body in a retry loop: on conn-reset/timeout/5xx, back off `min(n²·10ms, 10s)` × 0.5–1.5 jitter, up to ~5 attempts, **re-reading `resume_offset` each attempt** so it resumes rather than restarts (reuses existing Range machinery). Matches the global "never self-throttle, but DO survive transient failures" note.
3. **Install profiles — Minimum / Recommended / Full (fills a genuine gap).** Nothing groups assets today. Add a `tier`/`group` tag per `AssetEntry` and expose named bundles: **Minimum** (core reframe path — LR-ASD + S3FD), **Recommended** (+ Whisper transcription + captions), **Full** (+ emotion/OCR/local LLM/embedder). `assets.ensure(profile)` resolves tag → union of missing entries, reusing batch-preflight + weighted-progress. Gives first-run one meaningful choice instead of a checklist of cryptic names.
4. **Per-asset what/why/size explainer + hardware-fit badge.** Add optional `description` + `unlocks`/`feature` strings to `AssetEntry` and surface `size_mb`/`dest` so the panel shows "you're about to download 2.5 GB because you enabled X" instead of an opaque name (counters the ComfyUI "why is this here?" confusion). Feed `system_advisor.py`'s verdict into `AssetInfo` as `fit: ok|slow|unsupported` (LM Studio's green-rocket idea, honestly scoped: "local LLM will run CPU-only — slow", "needs WSL2 GPU — not detected").
5. **Finer HF progress + post-snapshot verify.** `_install_hf` reports only start/end. Pass a `tqdm_class`/per-file hook to forward real fraction; and given HF #3643 (Xet reported success despite checksum mismatch), add a **post-snapshot size/etag sanity check** rather than trusting the "success" return.
6. **Parallel chunked download for large blobs (largest lift, only if speed is a real complaint).** Ollama's 16-part / 100 MB-min / 1000 MB-max Range scheme ~2–4× throughput on fast links. Gate behind a size threshold (only split blobs > ~256 MB), keep single-stream as default/fallback; `.part` model would need per-part JSON sidecars (Ollama `-partial-<N>`) to stay resumable.

### Gotchas (load-bearing, from the reference apps)
- **Download path and installed-detection path MUST agree** or you get ComfyUI's "downloaded but still reads as missing" bug (#11758). Reframe already avoids this via its `detect` probe — keep it.
- **Every button must give visible feedback — never a silent no-op** (ComfyUI #13464/#13876). Extend Reframe's contract: every asset action emits a terminal state (`installed` / `failed:<reason>` / `cancelled-resumable`) so the panel never shows a dead button.
- **Verify checksum once at download-completion and cache it** — don't re-hash on every load (A1111 #12826), and hash the exact artifact bytes (A1111 #13752). Reframe already does on-complete SHA256 — keep it.
- **HF delegation is fine but don't assume byte-verification** (Xet #3643) — hence the post-snapshot sanity check above.
- **Graceful failure = keep the partial, never brick.** Reframe already keeps `.part` on cancel and deletes on mismatch (better than most) — preserve this.

Key implementation files: `C:\Users\Prekzursil\Documents\GitHub\Reframe\sidecar\media_studio\assets\manager.py` (download loop `_download_file`/`_finalize`, `ensure` weighted progress) and `...\assets\manifest.py` (`AssetEntry` — where `description`/`unlocks`/`tier` fields and profile grouping land).

---

## One-line adopt summary per stream
- **FFmpeg:** vendor BtbN `win64-lgpl` static exes via `extraResources`, ship LICENSE + record the tag, invoke as child process; avoid GPL builds.
- **llama-server:** bounded `/health`-status poll (503/refused = wait, 200 = ready), reuse-if-running with a mutex, signal-based tree shutdown; 90–120 s timeout.
- **safeStorage:** `encryptStringAsync` in main, key over stdin/framed stdio per request (never env/argv), renderer never sees plaintext, refuse Linux `basic_text`.
- **Download UX:** keep the strong plumbing; add ETA/speed, retry-with-backoff, and Minimum/Recommended/Full profiles + what/why/size + hardware-fit badges.
