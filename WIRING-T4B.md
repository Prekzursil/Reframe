# WIRING-T4B — claude-shorts reframe engine (T4b) wiring requests

Unit T4b shipped: `sidecar/media_studio/features/reframe_claudeshorts.py` (+tests),
the engine registry + automatic fallback in `sidecar/media_studio/features/reframe.py`
(owner), and the ShortMaker caption-style picker + reframe-engine override
(`app/renderer/src/features/ShortMaker.tsx` + tests).

**T4b registers NO new RPC methods** — everything flows through the existing
`shortmaker.select` / `shortmaker.export`. The renderer ALREADY sends the new
fields (safe: the current sidecar handler ignores unknown params), so the only
wiring needed is the consumption below.

---

## 1. `__main__.py` — pre-import mediapipe (A6 lesson 1, MANDATORY)

The claudeshorts engine uses **mediapipe** and **cv2** inside job threads
(`reframe_claudeshorts.NATIVE_MODULES_FOR_PREIMPORT == ("mediapipe", "cv2")`).
`cv2` is already in the pre-import tuple; **`mediapipe` is NEW**. In
`_preimport_native_modules`:

```python
# media_studio/__main__.py  — in _preimport_native_modules()
-    for mod in ("numpy", "ctranslate2", "cv2"):
+    for mod in ("numpy", "ctranslate2", "cv2", "mediapipe"):
```

(If other units add modules too, consolidate into one tuple — order doesn't
matter, absence is tolerated by the existing try/except.)

## 2. `features/shortmaker.py` — engine selection + typed fallback notice

`shortmaker.py` is not in the T4b lane; apply these three exact patches.

### 2a. `ShortMaker.export` handler — accept the optional T4b params

The renderer sends OPTIONAL top-level `reframeEngine` ("auto"|"verthor"|
"claudeshorts") and `captionStyle` (style id) on `shortmaker.export`. Merge
them into the per-job settings:

```python
    def export(self, params: Dict[str, Any], ctx: Any) -> Dict[str, Any]:
        """``shortmaker.export`` -> ``{jobId}`` (streams to ``{clips:[{path}]}``)."""
        video_id = params.get("videoId")
        candidate_ids = params.get("candidateIds") or []
        candidates = params.get("candidates") or []
        if not isinstance(video_id, str) or not video_id:
            raise _invalid_params("videoId (str) is required")
        settings = dict(self.settings_provider())
        # T4b: optional per-export overrides (renderer ShortMaker controls).
        for key in ("reframeEngine", "captionStyle"):
            value = params.get(key)
            if isinstance(value, str) and value:
                settings[key] = value
        out_dir = self.out_dir_for(video_id)
```

(Only the `settings = ...` line and the 4-line loop change; the rest of the
method body is untouched.)

### 2b. `run_export` — resolve the engine ONCE + surface the fallback notice

Insert right after the existing `aspect = str(...)` line in `run_export`:

```python
    aspect = str((settings.get("aspect") or DEFAULT_ASPECT))

    # T4b: resolve the reframe engine ONCE per export; an automatic
    # verthor->claudeshorts fallback surfaces as a typed notice via job.progress.
    from . import reframe as _reframe_mod  # lazy: keeps module import-light

    engine_name, notice = _reframe_mod.resolve_engine_name(
        str(settings.get("reframeEngine") or "auto"), settings
    )
    settings = {**settings, "reframeEngine": engine_name}
    if notice is not None:
        ctx.progress(3, notice["message"])
```

### 2c. `_lazy_reframe` — construct via the registry

Replace the existing `_lazy_reframe` body:

```python
def _lazy_reframe(in_path, out_path, aspect, *, settings=None) -> str:
    from . import reframe as _reframe

    # T4b: settings["reframeEngine"] is the CONCRETE name run_export resolved
    # ("verthor" | "claudeshorts"); "auto" (direct callers) re-resolves here.
    engine, _notice = _reframe.get_engine(
        (settings or {}).get("reframeEngine", "auto"), settings or {}
    )
    return engine.reframe(in_path, out_path, aspect)
```

Notes:
- `reframe.get_engine(name, settings) -> (engine, notice|None)`; the notice
  dict is `{type:"reframe.fallback", requested, engine, reason, message}`.
- `shortmaker.select` needs NO patch — `controls` (which now carry
  `captionStyle` + `reframeEngine`) already pass through to `run_select`.
- `settings["captionStyle"]` is consumed by the T4a caption-engine wiring (see
  WIRING-T4A.md); T4b only plumbs it (2a). Style id `"libass"` = the libass
  default; `"none"` = skip captions; `"bold"/"bounce"/"clean"/"karaoke"` =
  remotion (must match `caption_remotion.STYLES`).

## 3. CONTRACTS conformance checks (no code)

- **Style-id sync (3 mirrors):** renderer `ShortMaker.CAPTION_STYLES` remotion
  subset `["bold","bounce","clean","karaoke"]` == sidecar
  `caption_remotion.STYLES` == `vendor/remotion-captions/src/types.ts`
  `CAPTION_STYLES`. Verified identical as of this commit; re-check at wiring.
- **Controls:** T4b extends the §2 controls with `reframeEngine` (CONTRACT-NOTE
  in ShortMaker.tsx); `shortmaker.export` gains OPTIONAL `captionStyle` +
  `reframeEngine` params (alongside A2's optional `audioTrackId`).
- `reframe.ENGINES` is exactly `{verthor, claudeshorts}` (A4).

## 4. Runtime/deps note (for T5 / assets manifest)

The claudeshorts engine degrades gracefully: **mediapipe** → **opencv haar** →
**center crop**, so no hard new dependency. For subject tracking to work, the
sidecar env (or `%APPDATA%/media-studio/envs/` per A7) should pin:
`mediapipe==0.10.21`, `opencv-python==4.11.0.86`, `numpy<2.0` (mediapipe
constraint). cv2-only installs still get haar face tracking.
