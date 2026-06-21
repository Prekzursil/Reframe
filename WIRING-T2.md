# WIRING-T2 — TTS voiceover/dub + audio tracks

T2 lane files (already written, nothing below edits them):

- `sidecar/media_studio/features/tts/` — `__init__.py` (register), `engine.py`,
  `kokoro.py`, `edgetts.py`, `chatterbox.py`, `chatterbox_runner.py`,
  `align.py`, `dub.py`, `voices.py`
- `sidecar/media_studio/features/tracks_audio.py`
- `sidecar/tests/test_tts_align.py`, `test_tts_engines.py`, `test_tts_voices.py`,
  `test_tts_dub.py`, `test_tracks_audio.py`
- `app/renderer/src/features/Dub.tsx` (+ `Dub.test.tsx`)

The snippets below are the ONLY changes T2 needs in shared files. Apply exactly.

---

## 1. `sidecar/media_studio/handlers.py` — register tracks.audio.* + tts.*

At the end of `register_all(...)` (after the existing `reg(...)` calls, before
the final `log.info`), add:

```python
    # tracks.audio.* + tts.* (A2): registered via the modules' own register()
    # so they bind to the services' library/projects/settings (T2).
    from .features import tracks_audio as _tracks_audio  # local: import-light
    from .features import tts as _tts

    def _load_project_data(video_id: str) -> Dict[str, Any]:
        return svc._load_or_create_project(video_id).data

    def _save_project_data(video_id: str, data: Dict[str, Any]) -> None:
        _library.Project(
            dict(data), manifest_path=svc._project_path(video_id)
        ).save()

    def _load_subtitle_track(video_id: str, track_id: str) -> Dict[str, Any]:
        project = svc._load_or_create_project(video_id)
        try:
            return _tracks.find_track(project.data, track_id)
        except _tracks.TrackError as exc:
            raise _invalid(str(exc)) from exc

    audio_tracks_svc = _tracks_audio.register(
        resolver=svc._resolve_video_path,
        load_project=_load_project_data,
        save_project=_save_project_data,
        settings_provider=svc.settings.get,
        run=svc._ffmpeg_run,        # None -> the real drained ffmpeg.run
        duration=svc._ffprobe_duration,
        register_fn=reg,
    )
    _tts.register(
        resolver=svc._resolve_video_path,
        load_track=_load_subtitle_track,
        audio_tracks=audio_tracks_svc,
        settings_provider=svc.settings.get,
        translator_factory=None,    # see §2 below — wire T3's seam here
        media_duration=(svc._ffprobe_duration or _self_ffprobe()),
        out_dir=str(svc.data_dir / "dubs"),
        register_fn=reg,
    )
```

Methods registered: `tracks.audio.list` / `tracks.audio.mux` /
`tracks.audio.replace` / `tracks.audio.strip` / `tts.voices` /
`tts.sample.add` / `tts.dub.start` (all frozen A2 names).

## 2. The translator seam (T3 `models/translation.py`)

`tts.dub.start` with a `targetLang` needs the **models.translation seam**
(`dub.Translator` protocol: `translate(texts, target_lang, source_lang) ->
texts` + `free()`). When T3's module has landed, replace
`translator_factory=None` above with an adapter, e.g. if T3 exposes
`get_translator(settings)` duck-compatible with the protocol:

```python
        translator_factory=lambda: __import__(
            "media_studio.models.translation", fromlist=["get_translator"]
        ).get_translator(svc.settings.get()),
```

(or an explicit adapter class if T3's surface differs — the protocol is small
on purpose). Until wired, dubbing WITHOUT `targetLang` works fully; a
`targetLang` request fails with a clear job error.

## 3. `sidecar/media_studio/__main__.py` — pre-import natives (A6 lesson 1)

Extend the tuple in `_preimport_native_modules` (guarded import; absence is
fine):

```python
    for mod in ("numpy", "ctranslate2", "cv2", "onnxruntime", "kokoro_onnx", "aiohttp"):
```

- `onnxruntime` — kokoro's native backend (lazy-imported inside a job).
- `kokoro_onnx` — pulls espeak-ng / phonemizer native bits at first import.
- `aiohttp` — edge-tts transitive dep; its http parser is a C-extension.
- **No `soundfile`** — T2 deliberately uses stdlib `wave` only.
- chatterbox/torch never load in the sidecar process (isolated env, A6.5).

## 4. `sidecar/pyproject.toml` — packages + pinned deps

`[tool.setuptools] packages` must gain the new subpackage:

```toml
packages = [..., "media_studio.features.tts"]
```

Dependencies (PINNED; ⚠ human: verify these are the current releases at
install time — chosen from 2025 release lines):

```toml
"kokoro-onnx==0.4.9",   # the onnx build — NEVER the torch `kokoro` package (A4)
"onnxruntime==1.20.1",  # kokoro-onnx backend (or onnxruntime-gpu, same pin)
"edge-tts==7.0.0",      # hosted engine (network only at runtime)
```

`chatterbox-tts` / `torch` must NOT be added here — they live exclusively in
the isolated env asset (A6 lesson 5).

## 5. Chatterbox env install — PIP_EXTRA_INDEX_URL

The `chatterbox-env` manifest entry pins `torch==2.6.0+cu124` /
`torchaudio==2.6.0+cu124` (CUDA12 wheels). pip can only resolve `+cu124`
local versions with the PyTorch index visible. The assets manager's runner
inherits `os.environ`, so the sidecar process (or T5's runtime_setup) must
export, before `assets.ensure(["chatterbox-env"])` runs:

```
PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cu124
```

The exact value is pinned as `chatterbox.TORCH_EXTRA_INDEX_URL`. Simplest
placement: set it in the supervisor's sidecar spawn env (main/sidecar.ts) or
in `runtime_setup`. ⚠ human: verify `chatterbox-tts==0.1.2` is compatible
with torch 2.6.0 at install time (resemble-ai pins torch in its own setup).

## 6. `app/main/main.ts` — `dub:` ids on the mstream resolver (audition the WAV)

Dub.tsx plays the finished WAV via `mstream://media/<encodeURIComponent("dub:" + path)>`.
In the `GetPathForVideoId` implementation passed to
`registerMediaProtocol(...)` (WIRING-U1), add a branch BEFORE the sidecar
lookup:

```ts
import { resolve as resolvePath, sep } from 'node:path';

// inside getPathForVideoId(videoId): serve dub WAVs from the sidecar's dub
// output dir ONLY (no arbitrary-disk streaming through the media scheme).
if (videoId.startsWith('dub:')) {
  const requested = resolvePath(videoId.slice(4));
  const dubsRoot = resolvePath(app.getPath('appData'), 'media-studio', 'dubs');
  return requested === dubsRoot || requested.startsWith(dubsRoot + sep)
    ? requested
    : null;
}
```

(`%APPDATA%/media-studio/dubs` is where `tts.dub.start` writes — handlers §1
passes `out_dir=str(svc.data_dir / "dubs")`, and `svc.data_dir` defaults to
the same config dir.) Until applied, the panel still works; only the inline
audition player cannot stream.

## 7. `app/renderer/src/views/Workspace.tsx` — Dub tab

Follow the existing `lazyPanel` pattern (the panel needs the active videoId,
same as Tracks):

```tsx
const Dub = lazyPanel<{ videoId: string }>('../features/Dub', 'Dub');

// in WORKSPACE_TABS:
  { id: 'dub', label: 'Dub' },

// in the tab-body switch:
  {active === 'dub' && <Dub videoId={videoId} />}
```

`<Dub />` consumes the frozen bridge surface (`window.api.rpc`,
`window.api.onProgress`, `window.api.onJobDone`) — **no preload/ipc changes
needed**.

## 8. `app/renderer/src/lib/rpc.ts` — optional typed client additions

If the canonical client is being extended this round, the T2 methods are:

```ts
tts: {
  voices: (): Promise<{ voices: { id: string; engine: string; lang: string; name: string }[] }> =>
    rpc('tts.voices'),
  sampleAdd: (path: string): Promise<{ sample: { id: string; name: string; path: string; durationSec: number } }> =>
    rpc('tts.sample.add', { path }),
  dubStart: (p: { videoId: string; trackId: string; engine: string; voice?: string; sampleId?: string; targetLang?: string }):
    Promise<{ jobId: string }> => rpc('tts.dub.start', { ...p }),
},
tracksAudio: {
  list: (videoId: string) => rpc('tracks.audio.list', { videoId }),
  mux: (p: { videoId: string; path: string; lang: string; name: string; kind: string }) =>
    rpc('tracks.audio.mux', { ...p }),
  replace: (p: { videoId: string; audioTrackId: string; path: string }) =>
    rpc('tracks.audio.replace', { ...p }),
  strip: (p: { videoId: string; audioTrackId: string }) => rpc('tracks.audio.strip', { ...p }),
},
```

(Dub.tsx does not depend on this — it uses the `_api.ts` helpers like its
siblings.)

## 9. `sidecar/media_studio/library.py` — carry `Project.audioTracks` (A3)

A3 adds `Project.audioTracks:[AudioTrack]`, but `library.Project.open()`
rebuilds its data dict from a fixed key list and would silently DROP the
field on the next open. One-line addition in `Project.open` (and the schema
comment):

```python
        data: Project = {
            ...
            "clips": raw.get("clips") or [],
            "audioTracks": raw.get("audioTracks") or [],   # A3 (T2)
            "settings": raw.get("settings") or {},
        }
```

Optionally mirror tracks/clips in `_ref_paths()`/`consolidate()` so dub AACs
consolidate with the project (`for t in self.data.get("audioTracks") or []:`
same copy-in pattern). T2's own persistence goes through the injected
load/save seam, so this is conformance, not a functional blocker for the
tracks_audio tests.

## 10. Job-system contact points (U5 awareness)

- `tts.dub.start` is a standard long job: handler calls `ctx.jobs.start(body)`
  and returns `{jobId}`; the body raises on failure (-> `job.done`
  `{error:{message,type}}`, verified in test_tts_dub.py) and honors
  cooperative cancel via `raise_if_cancelled` between stages.
- Natural JobInfo metadata: `feature="tts"`, `label="tts.dub.start"` — the
  dispatch layer backfills these from the request, nothing to wire.
- The dub job is CPU/GPU heavy; if U5 wants it gpu-tagged, pass `gpu=True`
  at the `ctx.jobs.start` call in `dub.py::DubService.dub_start` (left
  untagged because kokoro/edgetts are CPU-light; chatterbox runs out of
  process).
