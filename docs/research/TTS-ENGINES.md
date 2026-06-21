# TTS Engines for Voiceover/Dub (research, 2026-06-11)

For a LOCAL, portable Electron+Python app generating multilingual voiceover/dub from subtitles, time-aligned to cues.
License is the first filter for a closed/portable app. Re-verify model availability before locking defaults.

## Recommended
- **Ship-local default: Kokoro-82M** (Apache-2.0) — tiny (~300MB, 1-2GB VRAM, CPU-OK), #1 TTS-Arena for its size,
  8 langs (en/zh/ja/es/fr/hi/it/pt-BR), fixed studio voices. No cloning, but ideal for subtitle-driven dub with selectable voices.
- **Premium / voice-clone tier: Chatterbox Multilingual 0.5B** (MIT) — 23 langs, zero-shot clone from a short ref,
  ships commercially, watermarked. ⚠️ 6GB is BORDERLINE: official 8-16GB VRAM → must run FP16/ONNX, batch=1; CPU slow.
  Validate on the real 4050 before committing as the default cloner.
- **Light cloning that fits comfortably: OpenVoice V2** (MIT) — tone-color transfer layered on Kokoro/MeloTTS.

## Cannot ship in a closed/commercial app
- **XTTS-v2 (Coqui)** — best cross-lingual cloner (17 langs) but **CPML = non-commercial**, and Coqui is defunct (no one to license from).
- **F5-TTS** — code MIT but **weights CC-BY-NC** (Emilia training data). Both re-open if the app is OSS/non-commercial or you self-train.

## Hosted fallback (pluggable-backend parity)
- **edge-tts** (rany2) — FREE, no API key, 100+ langs/400+ voices, native `--rate`/`--pitch`, SRT/VTT out. ⚠️ rides Edge's
  internal endpoint = technically outside MS ToS → fine for personal/hobby/free-tier, not a contractual SLA.
- **Paid/proper ToS:** Google Cloud TTS ($4-30/1M chars) or Deepgram Aura-2 ($0.030/1k, $200 free credit, on-prem option).

## Dub time-alignment recipe (translated text rarely matches source duration)
1. Per-cue target duration = `end - start` from SRT/VTT; synthesize each line separately.
2. **Two-pass speaking-rate (preferred, pitch-safe):** synth once, measure, re-synth at adjusted native rate (Kokoro/edge-tts `--rate`, Chatterbox pace).
3. **Time-stretch fallback (universal):** ffmpeg `atempo` (chain stages) or `rubberband` (formant-preserving); clamp ratio ±15% (0.85-1.15x).
4. **Pad, don't cram:** if shorter than the cue, pad trailing silence; preserve inter-line pauses.
5. **Duration-conditioned TTS (cleanest):** Azure TTS native; route alignment through it if added later (skip stretching).
6. Assemble each clip on a timeline at its SRT `start`, mix, mux with ffmpeg. Mirror **ThioJoe/Auto-Synced-Translated-Dubs**.

## Confidence
License facts HIGH (repo/HF source-verified). Chatterbox-on-6GB MED (official 8-16GB; "fits with FP16/ONNX" inferred — bench on the real 4050).
Quality/RTF MED (secondary articles, RTX 4070-class). Alignment recipe HIGH.
