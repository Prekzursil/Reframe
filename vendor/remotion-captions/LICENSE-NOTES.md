# vendor/remotion-captions — license + provenance notes

## Provenance (T4a vendoring)

Ported from **claude-shorts** (`D:/tools/reframe/claude-shorts`, MIT — see `LICENSE`,
Copyright (c) 2026 Daniel Agrici). Files ported, with modifications:

| This file | Upstream source | Modifications |
|---|---|---|
| `src/components/BoldCaptions.tsx` | `remotion/src/components/BoldCaptions.tsx` | unchanged logic |
| `src/components/BounceCaptions.tsx` | `remotion/src/components/BounceCaptions.tsx` | unchanged logic |
| `src/components/CleanCaptions.tsx` | `remotion/src/components/CleanCaptions.tsx` | unchanged logic |
| `src/components/Captions.tsx` | `remotion/src/components/Captions.tsx` | + `karaoke` branch |
| `src/components/KaraokeCaptions.tsx` | — (new for media-studio) | new style, same page pattern |
| `src/hooks/useCaptionPages.ts` | `remotion/src/hooks/useCaptionPages.ts` | unchanged |
| `src/styles/theme.ts` | `remotion/src/styles/theme.ts` | + `KARAOKE_THEME` |
| `src/styles/fonts.ts` | `remotion/src/styles/fonts.ts` | unchanged |
| `src/types.ts` | `remotion/src/types.ts` (subset) | CONTRACTS.md Cue schema + `CaptionedClipProps` replace `ShortVideoProps` |
| `src/Root.tsx`, `src/CaptionedClip.tsx`, `src/index.ts` | inspired by `remotion/src/Root.tsx` / `ShortVideo.tsx` | clean `CaptionedClip` composition driven entirely by inputProps |
| `remotion.config.ts` | `remotion/remotion.config.ts` | unchanged |

Upstream's `ShortVideo` composition (reframe crop, hook overlay, progress bar) was
deliberately NOT ported — reframing happens in the sidecar BEFORE captions (pipeline:
cut -> reframe -> captions), so this composition only burns animated captions onto an
already-reframed 1080x1920 clip.

## Remotion license (IMPORTANT — not MIT)

The `remotion` / `@remotion/*` npm packages consumed by `app/render-cli` are licensed
under the **Remotion License** (https://remotion.dev/license), NOT MIT/OSS:

- **Free** for individuals and for companies/organizations of up to 3 people.
- Larger companies need a paid **Company License**.

media-studio is a local personal video-manager (CONTRACTS.md §0 — "local personal
desktop app", no hosting/multi-tenancy), which falls within the free tier. If this
project is ever redistributed commercially or developed by a company of 4+ people,
obtain a Remotion Company License first.

## Chrome Headless Shell

Rendering uses **Chrome Headless Shell** (a "Chrome for Testing" build), registered as
a pinned asset in the U4 manifest (`sidecar/media_studio/features/caption_remotion.py`).
Chrome for Testing binaries are distributed by Google under the Google Chrome terms of
service; they are downloaded at first use, never redistributed inside this repo.

## Fonts (not vendored)

The caption styles reference Montserrat Bold, Bangers, and Inter Bold (all Google
Fonts, **OFL** — free to bundle). The `.ttf` binaries are NOT committed; place them in
`public/fonts/` (see `public/fonts/README.md`) before bundling. Missing fonts degrade
gracefully to system sans-serif fallbacks.
