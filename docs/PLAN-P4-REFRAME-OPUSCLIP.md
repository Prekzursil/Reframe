# P4 — "Reframe" OpusClip-parity wave

Status: PLANNED (grill-approved 2026-06-13). Builds on P3 (HEAD `309fd42`).
This doc is the **frozen mini-contract** for the P4 build — every agent reads it
and must NOT invent method/field names outside it. Extends CONTRACTS.md + the P2
ADDENDUM. Times in **seconds** unless suffixed `Ms`. Wire field names are FROZEN.

## 0. Decisions (grill 2026-06-13)

- **Rename**: app productName → `Reframe - Media Studio` (brand string + window
  title + electron-builder productName). Internal package `name` stays
  `media-studio` (avoid breaking imports/paths). appId may stay.
- **Captions**: 12+ OpusClip-style templates (data-driven registry; per-template
  colors/font/position), not 4.
- **Preview**: fix candidate playback AND add a LIVE HTML/CSS caption overlay
  that mirrors the selected template + hook title (export still uses
  Remotion/libass — the overlay is a fast approximation, NOT a Remotion render).
- **Shorts**: a global "Shorts" view (gallery across all videos) + a per-video
  list; actions play / open-folder / re-export / delete.
- **Scoring**: surface the existing virality-v2 (% + 4 factors) more prominently
  (headline badge, sort, shown in the gallery). No new scoring math.
- **Polishes (all 4)**: (a) caption emoji + keyword highlight; (b) auto punch-in
  zoom on emphasis; (c) platform presets + batch "make N"; (d) brand kit
  (logo watermark + default palette/font).
- **Repo**: integrate into `Prekzursil/Reframe` monorepo as the Electron
  `apps/desktop` (supersede the stale Tauri one) on a NEW branch → PR. Nothing on
  `main` destroyed. (LAST step; reversible.)

## 1. Hard constraints (carry the P1–P3 lessons)

- **GREEN MOCKED TESTS ≠ WORKS.** The GUI cannot be run in the build harness;
  the USER does final live verification. Every WU still ships real unit tests +
  typecheck + (where touched) a real render-cli build. Wiring claims must be
  backed by a grep showing the call site, not just the helper's existence.
- Keep the **three caption-style lists in sync** (see §4) — a conformance test
  enforces it. Adding a style without updating all three is a known bug class.
- Sidecar: argv lists only (never `shell=True`); drain BOTH subprocess pipes on a
  joined thread (the 29-min-freeze pattern); failures raise → job.done error.
- Renderer cannot import sidecar/vendor packages — mirror constants + a
  conformance test (existing pattern in ShortMaker.tsx / Player.tsx).
- Immutability; files <800 lines; functions <50; explicit error handling.
- Coverage gate: `.coverage-thresholds.json` is the source of truth — run its
  enforcement before "done".

## 2. New RPC methods (sidecar registry — FROZEN names)

All follow the existing `{result}` envelope + job pattern. Add to the method
registry + `__init__` wiring exactly like existing methods.

- `shorts.list` `{videoId?}` → `{shorts: ShortInfo[]}`
  Scan the export output dir(s) for produced clips. `videoId` filters to one
  source video; omitted = all. Sorted by `createdAt` desc.
- `shorts.thumbnail` `{path}` → `{thumbnailPath}`
  ffmpeg-extract a poster frame (cached next to the clip as `<clip>.thumb.jpg`);
  idempotent. Drained pipes; raises on failure.
- `shorts.delete` `{path}` → `{ok: true}`
  Delete the exported clip (and its `.thumb.jpg`). Path MUST be inside the app's
  output root (reject otherwise — path-traversal guard). UI confirms first.
- `shorts.reexport` `{path}` → `{jobId}` OR a structured "reopen in short-maker"
  hint. (Simplest acceptable impl: return the clip's source `videoId` +
  candidate so the UI re-opens Short-maker primed; document whichever is built.)
- `captions.cues` `{videoId}` → `{cues: Cue[]}`
  Word/segment cues (seconds, source-absolute) for the live preview overlay.
  REUSE the existing transcript store if one exists — check `features/` first;
  only add a thin method if none returns cues.

Settings keys (settings.get/set already exist — no new RPC):
`brandLogoPath` (str|""), `brandCaptionTemplate` (template id|""),
`brandFontFamily` (str|""), `outputDir` (already may exist — reuse).

## 3. New/extended schemas (FROZEN field names)

```
ShortInfo {
  id: str            # stable hash of path
  path: str          # absolute path to the exported mp4
  videoId: str       # source library video id ("" if unknown)
  sourceTitle: str   # source video title ("" if unknown)
  template: str      # caption template id used ("" if none)
  viralityPct: int|null   # the clip's score if known
  durationSec: float
  width: int
  height: int
  createdAt: float   # mtime epoch seconds
  thumbnailPath: str|""   # "" until generated
  hook: str          # hook/title text ("")
}
```

Export must WRITE a sidecar metadata file per clip (`<clip>.json`) carrying
`{videoId, sourceTitle, template, viralityPct, durationSec, hook, createdAt}` so
`shorts.list` reconstructs `ShortInfo` without re-probing. Back-compat:
`shorts.list` still lists clips with no `.json` (fields default/blank, dims via
one ffprobe).

## 4. Caption template registry (the keystone)

Single source of truth = `vendor/remotion-captions/src/templates.ts`:

```ts
type Family = 'bold' | 'bounce' | 'clean' | 'karaoke';
interface TemplateDef {
  id: string; label: string; family: Family;
  theme: {            // overrides merged onto the family's base theme
    textColor?: string; activeColor?: string; spokenColor?: string;
    shadowColor?: string; backgroundColor?: string; activeBackground?: string;
    rotatingColors?: string[];
  };
  fontFamily?: string;
  position?: 'bottom' | 'center' | 'top';
  uppercase?: boolean;
  box?: boolean;       // solid caption card behind the line
  outline?: boolean;   // thick text outline (impact look)
}
export const TEMPLATES: Record<string, TemplateDef>;        // ≥12 entries
export const CAPTION_STYLES = Object.keys(TEMPLATES);        // replaces the old const
```

Refactor `BoldCaptions/BounceCaptions/CleanCaptions/KaraokeCaptions` to accept a
`theme` (and `opts`: position/uppercase/box/outline/fontFamily) prop instead of
importing a fixed theme. `Captions.tsx` dispatches `TEMPLATES[style].family` →
component, passing `TEMPLATES[style].theme/opts`. Backward compat: the four old
ids (`bold/bounce/clean/karaoke`) MUST remain valid template ids.

Target ≥12 ids (concrete set — tune palettes for quality, keep ids stable):
`bold, karaoke, clean, bounce` (existing) + `hormozi, neon, tiktok, gradient,
impact, mrbeast, pop, serif, subtitle, fire`.

**Three mirrors kept in sync (conformance-tested):**
1. `vendor/remotion-captions/src/templates.ts` `TEMPLATES` (source of truth)
2. `sidecar/media_studio/features/caption_remotion.py` `STYLES` (the id list)
3. `app/renderer/src/features/ShortMaker.tsx` `CAPTION_STYLES` (id+label+engine)
   — plus `app/renderer/src/lib/captionTemplates.ts` (NEW): the visual params
   (palette/font/position) the live HTML overlay needs, mirroring `TEMPLATES`.
Add a test that asserts the id sets in (2) and (3)+(4) equal the keys in (1)
(read the files / a generated JSON). `caption_remotion.build_job` already
validates `style in STYLES` — keep that gate.

## 5. Live caption overlay (renderer, HTML/CSS approximation)

- `app/renderer/src/components/CaptionOverlay.tsx` (NEW): props
  `{cues: Cue[], templateId: string, currentTime: number, hookTitle?: string,
  window: PlayerWindow}`. Renders the active caption line(s) for `currentTime`
  (cues re-based to the window: subtract `window.start`) styled per
  `captionTemplates.ts[templateId]` (color/font/position/highlight/box/outline),
  + the hook title slot when provided. Pure render given props; word-highlight
  uses cue timing. Unit-tested (which line shows at t, palette applied).
- ShortMaker preview: drive `currentTime` from the Player's `onTimeUpdate`,
  fetch cues via `captions.cues`, overlay `CaptionOverlay` inside `.sm-phone`
  over the `<Player>`. Show it for any non-`none` template; update live when the
  caption-style select changes (this is the "see how they'd look" requirement).
- Preview playback fix: ensure the ShortMaker preview Player participates in the
  proxy-build remount (Workspace builds the proxy + remounts via `playerEpoch`;
  the ShortMaker Player is a separate instance that today does NOT remount on
  `media.proxy` job.done → diagnose & fix; likely a shared remount key or a
  `media.playable`/`media.proxy.start` check in ShortMaker mirroring Workspace).
  Verify window seeking to `sourceStart`. Document the root cause found.

## 6. Shorts gallery (renderer + main)

- App shell: add a top-level `Shorts` route (App.tsx `Route` union + a header
  nav entry alongside the brand). `views/Shorts.tsx` (NEW): grid of `ShortCard`
  (thumbnail, source title, template, viralityPct badge, duration). Actions:
  Play (modal/inline `Player` over the exported file), Open folder, Re-export,
  Delete (with confirm). Empty state. Polls/loads `shorts.list` on mount.
- Per-video: after export in ShortMaker, the exported list already renders;
  enrich it with the same card actions + a `shorts.list {videoId}` reload.
- **Playing an exported file**: the `mstream://` resolver maps a library
  `videoId` → path. Exported clips are NOT library videos. Extend the resolver
  (main `getPathForVideoId` wiring) to ALSO resolve export paths — e.g. accept
  `mstream://media/short/<base64url(path)>` and resolve inside the output root
  (path-traversal guarded), OR add a sibling resolver. Keep the pure
  `mediaProtocol.ts` planners unchanged; only the wiring/resolver grows. Add a
  renderer helper `shortMediaUrl(path)`.
- Open folder is a MAIN-process action (`shell.showItemInFolder`) exposed via
  IPC + `window.api.openInFolder(path)` (NOT a sidecar RPC). preload + ipc.

## 7. Scoring surfacing (renderer only — data already exists)

- ShortMaker card: keep the virality % headline; make it a bolder badge; add a
  "sort by virality" toggle on the candidate list. Show factor bars (exist).
- Shorts gallery card: show `viralityPct` badge + sort by it.
No sidecar changes (select.py virality-v2 already attaches factors/viralityPct).

## 8. Polishes

- (a) **emoji + keyword highlight** — sidecar `features/emphasis.py` (NEW):
  `annotate(cues) -> cues` adding per-cue emphasis spans (deterministic: a
  keyword lexicon + ALLCAPS/number/long-word heuristic) and an optional trailing
  emoji from a small keyword→emoji map. Applied in BOTH caption paths (libass +
  remotion) when the template/flag enables it; the live overlay mirrors it. A new
  control `emphasis` (bool, default ON for OpusClip-style templates, OFF for
  clean/minimal). Pure + tested; NO network, NO LLM (keep deterministic).
- (b) **auto punch-in zoom** — sidecar `features/zoom.py` (NEW): build an ffmpeg
  `zoompan`/scale filter that does subtle slow zoom + a quick punch-in at
  emphasis beats (beats from sentence starts in the cues, optionally audio RMS
  peaks via an ffmpeg `astats`/`silencedetect` pass). New export control
  `autoZoom` (bool, default OFF). Filter-string builder is pure + tested; an
  export stage applies it. Must compose with reframe + captions (order:
  reframe → zoom → captions, or document the proven order).
- (c) **platform presets + batch** — ShortMaker UI: preset buttons
  `TikTok / Reels / Shorts` that set `{aspect:'9:16', maxSec, count}`
  (TikTok 60 / Reels 90 / Shorts 60) + a "Make N shorts" button: runs
  `shortmaker.select` → auto-approve the top N by viralityPct → `shortmaker.export`
  unattended, with progress. Pure preset map + tested; wiring reuses existing RPCs.
- (d) **brand kit** — settings UI (a small "Brand" section: logo file picker via
  an open-file IPC, default template select, font input) persisting
  `brandLogoPath/brandCaptionTemplate/brandFontFamily` via `settings.set`.
  Export applies the logo as an ffmpeg `overlay` (corner, padded) when set, and
  defaults the caption template/font when the user hasn't overridden. Logo
  overlay filter builder pure + tested.

## 9. Work units & order (dependency-sequenced)

1. **WU-FND** foundation: template registry refactor (§4) + sync 3 mirrors +
   `captionTemplates.ts` + conformance test + RENAME (§0). (renderer + vendor +
   sidecar STYLES.)
2. **WU-SIDE** sidecar features: `shorts.*` + export `.json` metadata + thumbnail
   + `captions.cues` + `emphasis.py` (8a) + `zoom.py` (8b) + brandkit export
   wiring (8d export side). TDD.
3. **WU-MAIN** main/IPC: `openInFolder` IPC, export-path mstream resolver (§6),
   open-file IPC for the logo picker. TDD (pure planners).
4. **WU-REND** renderer: `CaptionOverlay` + preview fix (§5), `Shorts` view +
   per-video cards (§6), scoring surfacing (§7), presets+batch (8c), brand-kit
   settings UI (8d UI). TDD.
5. **WU-VERIFY** integration: run sidecar pytest + app vitest + coverage gate +
   typecheck + render-cli build; adversarial review of the full diff;
   completeness critic (what's unwired / untested / claim-without-callsite).
6. **WU-REPO** (after user sees the result): integrate into Reframe monorepo as
   `apps/desktop` on a new branch + open PR. Reversible.

## 10. Acceptance (Definition of Done)

- ≥12 caption templates selectable; each renders distinctly (Remotion export) AND
  previews live in the overlay; 3 mirrors conformance test green.
- Candidate preview plays the correct window AND shows the live caption + hook
  overlay updating with the style select; preview-bug root cause documented.
- Shorts view lists exported clips with thumbnails + virality badge; play / open
  folder / re-export / delete all work; per-video list too.
- All 4 polishes wired with a grep-proven call site + tests.
- App brand reads "Reframe - Media Studio".
- Full test suite + coverage gate green; typecheck green; render-cli builds.
- GUI live-verification explicitly handed to the user (harness can't run it).

## 11. Plan-gate corrections (BINDING — these OVERRIDE §§2–10 on conflict)

3 adversarial reviewers verified the plan against the real code (2026-06-13).
Apply every item below; they fix verified blockers.

**C1 — zod enum is NOT buildable from `Object.keys` (BLOCKER).**
`types.ts:38 z.enum(CAPTION_STYLES)` needs a readonly tuple literal. KEEP
`CAPTION_STYLES` as an explicit `as const` tuple of the ≥12 ids (do NOT write
`CAPTION_STYLES = Object.keys(TEMPLATES)`). `TEMPLATES` stays the visual source
of truth; a conformance test asserts `new Set(CAPTION_STYLES)` ===
`new Set(Object.keys(TEMPLATES))`. `CaptionStyle`/`CaptionStyleType` stay derived
from the tuple and remain the dispatch key.

**C2 — the style list lives in FIVE places; Captions.tsx is a dispatcher rewrite.**
Mirrors to update + keep in sync: (1) `types.ts` `CAPTION_STYLES` tuple + the
`z.enum`; (2) `caption_remotion.py` `STYLES`; (3) `ShortMaker.tsx`
`CAPTION_STYLES`; (4) NEW `lib/captionTemplates.ts`; (5) `components/Captions.tsx`
dispatcher — rewrite its `switch(style)` to `switch(TEMPLATES[style].family)`
passing `theme`+`opts` (breaking prop-signature change to the 4 components).

**C3 — conformance is a SUPERSET relation, not full equality (BLOCKER).**
Renderer `CAPTION_STYLES` legitimately includes `libass` (the DEFAULT) and `none`
which are NOT remotion templates. The test MUST be:
`keys(TEMPLATES)` == sidecar `STYLES` == remotion-template keys of
`captionTemplates.ts`; AND renderer remotion-engine subset == `keys(TEMPLATES)`;
AND renderer full list == `keys(TEMPLATES) ∪ {libass, none}`. Do NOT drop
`libass`/`none`. `captionTemplates.ts` must also cover `libass`/`none` for the
overlay (overlay no-ops on `none`; `libass`→a sensible default look).

**C4 — existing tests pin the old 4-style list; WU-FND MUST update them.**
`sidecar/tests/test_caption_remotion.py:177` (`assert STYLES == [4]`);
`app/renderer/src/features/ShortMaker.test.tsx:265` (`toEqual([4])`) and `:1014`
(select options == CAPTION_STYLES). Update these assertions, plus any style-set
asserts in `test_caption.py`/`test_shortmaker.py`.

**C5 — export persistence is the PRIMARY path (BLOCKER: shorts.list is empty otherwise).**
Today `_export_one` (shortmaker.py ~744–760, `final_path = out_dir/f"{stem}.mp4"`)
returns `{candidate, path}` and NOTHING is persisted (`project.data["clips"]`
stays `[]`). Write the `<clip>.json` metadata IN `_export_one` where
hook/template/viralityPct/duration are still in scope. `shorts.list` scans the
export dir (`exports/shorts-<videoId>/` — `out_dir_for`, handlers.py ~540/542;
`Services.exports_dir = data_dir/"exports"`, handlers.py ~89) for `*.mp4` (+ its
`*.json`, ffprobe fallback when absent). Make the `.json` PRIMARY, not back-compat.

**C6 — register new RPCs explicitly in `handlers.py register_all`.** No
auto-discovery. Add `reg("shorts.list", svc.shorts_list)`,
`reg("shorts.thumbnail", …)`, `reg("shorts.delete", …)`, `reg("shorts.reexport", …)`,
`reg("captions.cues", svc.captions_cues)` (near handlers.py ~784–898). `shorts.*`
may be `Services` methods or a feature module with its own `register()` (mirror
`_feedback.register`/`_media_compat.register`) — pick one, document it.

**C7 — `captions.cues` is NET-NEW, WORD-level, built on existing data.** No
existing method returns cues. Transcript IS persisted with word timing
(`transcribe.py word_timestamps=True`; `Word/Segment/Transcript` in rpc.ts:19–36;
manifest `transcript` field, handlers.py ~519–527). Build `captions.cues` from
`_shortmaker_context(videoId)` + `_cues_for_clip`/`_words_of`
(shortmaker.py ~435–469), emitting WORD-level cues (needed for karaoke highlight).

**C8 — renderer RPC typing: extend `lib/rpc.ts`.** Add typed wrappers to the
`client` const (rpc.ts ~307–328) for `shorts.{list,thumbnail,delete,reexport}` +
`captions.cues`, a `ShortInfo` interface, and REUSE the existing `Cue` type
(rpc.ts:38) for cues. (Generic `rpc<T>()` works untyped, but follow the pattern.)

**C9 — IPC is FOUR layers (openInFolder + logo open-file picker).** Mirror the
proven `dialogIpc.ts` pattern: (a) handler module `ipcMain.handle('shell.showItemInFolder',…)`
+ a logo open-file handler (parallel to `dialog.openVideos`, dialogIpc.ts ~23/75);
(b) wire its disposer into `bootstrap()` (main.ts ~194–260) + teardown in
`will-quit` (main.ts ~299); (c) preload bridge `window.api.openInFolder` /
`window.api.pickLogoFile` (preload.ts ~42–100, channel-name consts like
preload.ts:24); (d) renderer types in `MediaApi` (rpc.ts ~193–202) AND the local
`Api` shapes that exist (ShortMaker.tsx:131; components/api.ts; features/_api.ts).
`shell` is already imported (main.ts:13). Open-folder is MAIN-process, NOT a
sidecar RPC.

**C10 — export-path playback uses the `short:` id-PREFIX (no pure-planner change).**
The resolver is the inline closure in `main.ts ~213–237` and already has a `dub:`
prefix branch (main.ts ~216–222) with a traversal guard. Add a sibling `short:`
branch resolving `base64url(path)` inside the exports root with the SAME guard.
Renderer helper `shortMediaUrl(path)` clones `Dub.tsx ~103–109`
(`mstream://media/${encodeURIComponent('short:'+path)}`). Do NOT use a
`media/short/<b64>` two-segment PATH (it breaks `videoIdFromUrl`). Pure
`mediaProtocol.ts` planners stay unchanged.

**C11 — App.tsx route add is a small refactor.** Add a 3rd `Route` variant
(`{name:'shorts'}`), a nav control in `app__bar` (none exists today — brand span +
QualityToggle + Jobs button), and convert the `route.name` ternary (App.tsx
~122–126) to a switch. Per-video enrichment edits the exported-clips `<ul>`
(ShortMaker.tsx ~1142–1156) to add card actions + a `shorts.list {videoId}` reload.

**C12 — settings keys are free-form; `outputDir` does NOT exist.** `settings.set`
blindly `current.update(values)` (settings_store.py ~100); `DEFAULT_SETTINGS` =
{useCloud, modelsDir, ffmpegPath} (~27–31). Add `brandLogoPath`,
`brandCaptionTemplate`, `brandFontFamily` to `DEFAULT_SETTINGS` (discoverability)
or have the UI tolerate absent keys. DELETE the §2 "outputDir (already may
exist)" claim — exports are hard-coded to `Services.exports_dir`; do not add
redirection unless asked.

**C13 — rename touches FOUR brand surfaces, ZERO path literals (MAJOR).** Update:
window title (main.ts ~167 `title:'media-studio'`), brand (App.tsx:109),
electron-builder `productName`, `nsis.shortcutName`. Do NOT touch the appData/path
literals: main.ts ~62/218 `'media-studio'`, settings_store.py:36
`_APP_DIR_NAME='media-studio'`, assets/manager.py `ENV_SENTINEL='.media-studio-env.json'`
(+ proxies/peaks/dubs/voices/feedback roots). Add a grep-guard test that these
path literals remain `media-studio`. `electron-builder.yml artifactName=${name}-…`
uses package `name` (kept) → artifacts unaffected.

**C14 — vendor sources are typechecked by NEITHER tsc.** `app/tsconfig.json`
includes only `main/**`+`renderer/src/**`; render-cli tsconfig only `src/**`. The
whole §4 caption refactor escapes `tsc` (webpack bundle is transpile-only). WU-VERIFY
MUST add a `vendor/remotion-captions/tsconfig.json` + `typecheck` script (or add
the vendor path to render-cli `include`) and RUN it — otherwise "typecheck green"
is false comfort for the keystone WU, and only a real Remotion render proves it.

**C15 — coverage gate: `.coverage-thresholds.json` does NOT exist in this repo.**
No vitest coverage config, no `vitest.config.*`, scripts are bare `vitest run` +
pytest. Do NOT claim a 100% gate the repo never had. WU-VERIFY gate =
ALL existing+new tests pass (`vitest run` in app/, `pytest` in sidecar/) +
typecheck (incl. C14) + render-cli build + NEW code has tests + no test regressions.
Optionally CREATE a realistic `.coverage-thresholds.json` + wire vitest/pytest
thresholds, but state honestly it is net-new, not pre-existing.

**C16 — zoom (8b): route through `ffmpeg.run` (proven, drains pipes).** Do NOT
re-implement a joined-drain. Insert the zoom stage between reframe and caption via
the injectable `Stages` seam (shortmaker.py ~370–387; current order cut→filler→
reframe→caption→export→mux). `autoZoom` default OFF. Audio-RMS beat source is
OPTIONAL/phase-2; the SHIPPABLE v1 beat source is sentence-starts from the cues.
Logo overlay (8d) follows the existing 2nd-input pattern (`build_audio_mux_argv`,
shortmaker.py ~297–339).

**C17 — scope all grep/conformance/callsite checks to `sidecar/` + `app/`,
EXCLUDING `dist/`** (stale bundled copies cause false hits).

**C18 — WU-REPO is ADDITIVE + PROPOSAL-only (BLOCKER: do not overwrite Tauri).**
`apps/desktop` ALREADY EXISTS as a committed Tauri scaffold, and `DESKTOP.md`
documents a DELIBERATE Tauri/thin-shell-over-Docker decision (opposite of
media-studio's fat-client + embedded sidecar). Therefore: land media-studio at a
NEW non-colliding path (`apps/studio` or `apps/desktop-electron`), leave the Tauri
`apps/desktop` UNTOUCHED. Open the PR as an RFC/proposal whose body surfaces the
Tauri-vs-Electron + thin-vs-fat conflict and updates `DESKTOP.md`/`ARCHITECTURE.md`
to state the supersession explicitly — leaving the merge + delete-Tauri decision
to the user. Reconcile (or scope-exempt) Reframe's CI (Sonar/Codacy/codecov/
pre-commit) for the new path. Precondition: the user's explicit "ship it" AFTER
live GUI verification — not merely "VERIFY passed."
