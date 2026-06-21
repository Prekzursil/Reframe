# WIRING-T3 — Tiered translation (TranslateGemma stack)

T3 lane files (already written, nothing below edits them):

- `docs/research/MT-MODELS-2026.md` (survey + routing decision)
- `sidecar/media_studio/models/translation.py` (TieredTranslator + U4 manifest entries)
- `sidecar/media_studio/models/runner.py` (owner: now model-identity-aware)
- `sidecar/tests/test_translation.py` · `sidecar/tests/test_runner.py` (extended)

**No new RPC methods** (A2 names are frozen; `subtitles.translate` already
exists) — so there is no `register()` to call for T3. The snippets below are the
ONLY changes T3 needs in shared files. Apply exactly.

---

## 1. `sidecar/media_studio/handlers.py` — route subtitles.translate through the tiers

### 1a. `Services.__init__` — one shared ModelRunner slot

After the existing seam assignments (next to `self._provider = provider`), add:

```python
        # T3: the shared llama.cpp ModelRunner (built lazily; model-identity-aware,
        # so the tiered translator can swap MT GGUFs on the one server lane).
        self._model_runner: Optional[Any] = None
```

### 1b. New private helpers (place beside `_get_provider`)

```python
    def _get_model_runner(self) -> Any:
        """The shared ModelRunner (lazily built from settings; T3)."""
        if self._model_runner is None:
            from .models import runner as _runner_mod  # local import: heavy seam

            self._model_runner = _runner_mod.ModelRunner(self.settings.get())
        return self._model_runner

    def _get_translator(self) -> Optional[Any]:
        """TieredTranslator for subtitles.translate (T3).

        Returns ``None`` when a legacy ``provider`` seam was injected (tests):
        the caller then keeps the original single-provider path, so every
        existing handler test stays green.
        """
        if self._provider is not None:
            return None
        from .models import translation as _translation_mod  # local import

        return _translation_mod.get_translator(
            self.settings.get(), runner=self._get_model_runner()
        )
```

### 1c. `subtitles_translate` — replace the provider acquisition + job body

Replace:

```python
        provider = self._get_provider()
        save_path = project.manifest_path

        def job_body(job_ctx: Any) -> Dict[str, Any]:
            translated = _subtitles.translate(
                track,
                target_lang,
                provider=provider,
                progress=lambda pct, msg: job_ctx.progress(pct, msg),
                cancelled=lambda: job_ctx.cancelled,
            )
```

with:

```python
        translator = self._get_translator()  # None -> legacy injected provider
        provider = self._provider if translator is None else None
        save_path = project.manifest_path

        def job_body(job_ctx: Any) -> Dict[str, Any]:
            if translator is not None:
                # T3 tiered path: language-aware tier routing + fallback chain;
                # tier failures surface via job.done error payload (A6.3).
                translated = translator.translate_track(
                    track,
                    target_lang,
                    progress=lambda pct, msg: job_ctx.progress(pct, msg),
                    cancelled=lambda: job_ctx.cancelled,
                )
            else:
                translated = _subtitles.translate(
                    track,
                    target_lang,
                    provider=provider,
                    progress=lambda pct, msg: job_ctx.progress(pct, msg),
                    cancelled=lambda: job_ctx.cancelled,
                )
```

(The rest of the job body — persisting the track + `{"track": translated}` —
is unchanged.)

Notes:
- `_get_provider()` stays for the short-maker select path; do NOT remove it.
- If a Services shutdown hook exists (or U5 adds one), also call
  `self._model_runner.shutdown()` there when `self._model_runner is not None`
  (it terminates the llama-server child gracefully). Optional but tidy.

## 2. T2 dub pipeline — the `translate(cues, targetLang)` callable

The dub job's batched MT step (A4: translate ALL cues -> free MT -> synth ALL)
consumes the same translator:

```python
        translator = svc._get_translator()          # or translation.get_translator(settings, runner=...)
        translated_cues = translator.translate(cues, target_lang)   # List[Cue] in, List[Cue] out
```

`translate(cues, targetLang, *, source_lang=None, progress=None, cancelled=None)`
preserves cue timings/indices and only rewrites `text`. After it returns, the
runner can be switched/freed before TTS (the ModelRunner's lane semantics
already enforce one-heavy-model).

## 3. `sidecar/media_studio/__main__.py` — pre-import natives (A6 lesson 1)

**No change needed for T3.** `models/translation.py` uses only stdlib +
`urllib` (via the provider seam) — no native C-extension enters any job body.

## 4. `sidecar/pyproject.toml`

**No new dependency.** (Manifest entries are data-only; downloads ride U4's
existing httpx machinery.)

## 5. Settings keys T3 reads (all optional, §2-compatible)

| key | use |
|---|---|
| `modelsDir` | locate `translategemma-4b-it.Q4_K_M.gguf` / `translategemma-12b-it.Q4_K_M.gguf` (matches the U4 asset dests) |
| `translateGgufPath` / `translateTier2GgufPath` | explicit per-tier GGUF overrides |
| `cloudApiKey` (+ `cloudBaseUrl`, `cloudModel`) | tier3 hosted provider |
| `localBaseUrl` | non-default llama.cpp server URL for the local tiers |

## 6. Assets panel (FYI, no action)

Two new entries appear automatically in `assets.list` once
`models/translation.py` is imported (the handlers patch above imports it
lazily inside `_get_translator`; if you want the entries visible BEFORE the
first translate, add `from .models import translation as _  # noqa: F401`
near the assets registration in `register_all`):

- `translategemma-4b-gguf` (2550 MB, tier 1)
- `translategemma-12b-gguf` (7580 MB, tier 2 — SLOW)
