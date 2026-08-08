# Captions / Subtitles / Transcription / Translation — Audit + Design (v1.5)

> **Status:** ACTIVE

**Unit:** `captions` (audit + design only — NO implementation, NO file changes outside this doc)
**Date opened:** 2026-08-08 · **Last rewrite:** milestone 2 — ALL FIVE SECTIONS MEASURED

> **If a section reads "UNKNOWN - not yet measured", the unit died before measuring it and no
> verdict there may be cited.** No section currently reads that.

## COVERAGE

| § | Section | State |
|---|---|---|
| 1 | Per-engine supported-language set | MEASURED (one item NOT-CHECKED, named inline) |
| 2 | Language-selector design | MEASURED + DESIGNED |
| 3 | Translation quality | MEASURED + DESIGNED |
| 4 | Caption parity (karaoke / normal / Remotion) | MEASURED |
| 5 | Escape hatches (.SRT import, custom dictionary) | MEASURED |

## Owner ask (verbatim)

> "captions language list is very short ... it should feature everything and autodetect as well,
> should allow transcription and translation of transcription and it has to be very accurate and
> properly worded not bad translations, as well as properly captioned, for both shorts and/or
> karaoke captions and normal subtitles as well"

## Honesty contract in force

`UNVERIFIED` is INLINE next to the claim it qualifies and names the settling experiment.
Sherman-Kent bands on forward-looking claims (`almost certain` 90-99%, `likely` 55-80%,
`roughly even` 45-55%, `unlikely` 20-45%). Every factual claim carries `file:line` or a model-card
URL. `NOT-CHECKED` beats a guess.

## The three headline defects

1. **§3.1 — Translation is per-cue and context-free, on cues already split mid-sentence.** This is
   the mechanical cause of "bad translations", not model quality.
2. **§3.5 — An EN-only punctuation/casing model is applied to ALL languages with no language
   check.** Latent (behind two opt-ins) but it makes non-English captions worse, not better.
3. **§4.2 — One call site (`caption.py:640-648`) drops six styling parameters on the karaoke
   path.** Karaoke captions cannot be styled at all.

---

## 1. Real supported-language set per engine — MEASURED

### 1.1 Four language vocabularies that disagree

Counted by mechanical regex extraction, not by eye (a deliberate re-probe of the brief's hand
count, via a throwaway script):

| Vocabulary | Count | Source |
|---|---|---|
| **UI dropdown** (`LANGUAGES`) | **19** | `app/renderer/src/lib/languages.ts:25-45` |
| **UI dropdown #2** (duplicate, in `Transcribe`) | **9** + auto | `app/renderer/src/features/Transcribe.tsx:27-38` |
| MT local tier1 (TranslateGemma-4B) | 40 | `sidecar/media_studio/models/translation.py:104-147` |
| MT local tier2 (TranslateGemma-12B, `SLOW`) | 12 | `sidecar/media_studio/models/translation.py:148` |
| MT local total (tier1 ∪ tier2) | **52** | derived; `ROUTING_TABLE` at `translation.py:150-153` |
| MT hosted (tier3) | unbounded | `DEFAULT_TIER = TIER_HOSTED`, `translation.py:157` |

The 19 UI codes: `en es pt fr de it nl pl ru uk tr ar hi id vi th ja ko zh`.

**Every UI code is inside the local MT table**, so the UI is a strict SUBSET and **33
locally-supported languages are unreachable from the UI**: `bg bn ca cs da el et fa fi gu he hr hu
is kn lt lv ml mr ms nb no pa ro sk sl sr sv sw ta te ur zu`.

> Self-check on my own probe: it printed `local MT codes NOT offered in UI: 52`. That number is
> WRONG — an operator-precedence bug in my script (`set(t1)|set(t2) - ui` binds `-` first). The
> enumerated list is correct with **33** members (52 − 19 = 33, consistent). A self-contradicting
> output is a detector failure, not a finding: the list is the signal, the count was not.

**`ro` (Romanian) is absent from the UI's 19** — while Parakeet's docstring names Romanian
(`features/parakeet_asr.py:4-5`) and `ro` is a tier1 MT language (`translation.py:135`). A
Romanian user cannot select their own language even though both ASR and MT cover it.

**`languages.ts:6-9` claims to be "the SINGLE source of truth ... so every surface reads one
vocabulary". That claim is false as written** — `Transcribe.tsx:27-38` declares its own 9-language
array and never imports the module. It also uses a **different auto sentinel**: `code: ''`
(`Transcribe.tsx:28`) versus `AUTO_DETECT = 'auto'` (`languages.ts:18`).

### 1.2 ASR engines — what is actually wired

| Engine | Model | Language set | Citation |
|---|---|---|---|
| **whisper** (default) | `large-v3-turbo` GPU / `small` CPU | Whisper's full set | `features/transcribe.py:74`, `:82` |
| **parakeet** (opt-in) | `nvidia/parakeet-tdt-0.6b-v3` | **25 European**, CC-BY-4.0 | `features/parakeet_asr.py:4-5`, `:48` |

Engine choice: `settings["asrEngine"]` (`transcribe.py:385`); resolved by `selected_asr_engine`
(`:399-411`) — anything not `"parakeet"` → whisper. Live call path is
`transcribe_with_engine` at `handlers/media_ops.py:425`.

**Neither engine's language set exists in machine-readable form anywhere in the repo.** This is
the crux of the owner's complaint and it is structural:

- Parakeet's "25 European languages incl. Romanian" is a **docstring only** (`:4-5`). There is no
  `PARAKEET_LANGS` constant. Nothing in the app can warn that a chosen language is outside it.
  *NOT-CHECKED: the exact membership of the 25. Settling experiment: fetch
  `https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3` at the pinned revision
  `575de92b31b2f60855bca9b70968bde5afb069ba` (`parakeet_asr.py:420`) and read its language table.*
- Whisper's set is likewise not enumerated; `language=` is passed straight through
  (`transcribe.py:348-352`). *NOT-CHECKED: the exact count. I attempted a direct enumeration —
  `from faster_whisper.tokenizer import _LANGUAGE_CODES` — and it failed with
  `ModuleNotFoundError` (not installed in the ambient Python), so I am NOT asserting "99". The
  pin is `faster-whisper==1.2.1` (`sidecar/requirements.lock.txt:52`). Settling experiment: run
  that import inside the sidecar venv, or read `faster_whisper/tokenizer.py` at tag 1.2.1.*

**Consequence (measured, not inferred):** with `asrEngine="parakeet"` and an out-of-set language,
the only guard is the empty-transcript degrade at `transcribe.py:474-483`, which falls back to
whisper **only when `segments` is empty** — never when the output is wrong-language garbage.

### 1.3 Auto-detect: the engine supports it; the persistence layer forbids it

- Engine: `transcribe_file(language=None)` → faster-whisper auto-detects, detected code returned
  in `Transcript.language` (`transcribe.py:330-331`, `:355`, `:374-378`).
- Parakeet: `language` forwarded per chunk (`parakeet_asr.py:377`); detected code read from
  `info.language` (`:300`) with a fallback to the requested language (`:384-385`).
- `AUTO_DETECT = 'auto'` exported, documented "surfaces prepend it when they offer auto-detect"
  (`languages.ts:18`, `:20-24`).

The brief's screenshot claim is **CONFIRMED by an independent method** (reading source, not
pixels) — and the real mechanism is worse than a missing option. See §2.1.

---

## 2. Language-selector design — MEASURED + DESIGNED

### 2.1 Current state: five surfaces, three inconsistent

| Surface | Auto-detect? | Vocabulary | Citation |
|---|---|---|---|
| `components/LanguageSelect.tsx` (shared) | default **YES** | 19 | `:31`, `:49` |
| `features/ShortMakerControls.tsx` | YES (default) | 19 | `:145` |
| `components/OutputTray.tsx` (translation target) | **NO** — `includeAuto={false}` | 19 | `:124-126` |
| **`components/CaptionPreferences.tsx`** ("Default language") | **NO** — `includeAuto={false}` | 19 | `:162-168` |
| **`features/Transcribe.tsx`** | YES, but sentinel `''` | **9** (own array) | `:27-38`, `:167` |

`OutputTray`'s `includeAuto={false}` is **correct** — a translation *target* cannot be
auto-detected. `CaptionPreferences`' is not: a caption default language is a transcription
*source* hint, where auto-detect is exactly the meaningful choice.

**The deeper defect: auto-detect is not even representable in persisted state.**

```ts
// captionPreferences.ts:73-76
export function coerceLanguage(raw: unknown): string {
  const v = typeof raw === 'string' ? raw.trim() : '';
  return LANGUAGES.some((l) => l.code === v) ? v : DEFAULT_LANGUAGE;   // DEFAULT_LANGUAGE = 'en'
}
```

`LANGUAGES` deliberately excludes the auto sentinel (`languages.ts:20-24`), so
`coerceLanguage('auto')` returns `'en'`. **Even if the dropdown offered Auto-detect, saving it
would silently rewrite it to English.** Flipping `includeAuto` alone would produce a control that
appears to work and does not — fix both or neither.

### 2.2 Proposed design

**D1 — Two-level vocabulary: a full ISO set for display, a per-engine capability map for
warnings.** Replace the flat 19 with the complete set the engines actually cover, and keep the
current 19 as a "Common" ordering group at the top of the list (this preserves the V1-GRILL §h
intent — fast access to creator languages — while satisfying "should feature everything").

**D2 — Auto-detect first, always, on every SOURCE surface.** Target-language surfaces
(`OutputTray`) keep `includeAuto={false}`.

**D3 — Searchable, still not free-typed.** V1-GRILL §h banned free-typing to prevent invalid
codes (`languages.ts:3-5`). A filtering combobox over a fixed list satisfies both: you type to
filter, but can only commit a listed option. With ~100 entries a plain `<select>` is unusable, so
this is required, not cosmetic.

**D4 — Engine-capability signal.** When the chosen language is outside the chosen ASR engine's
set, show an inline warning and name the fix ("Parakeet does not support Thai — switch to Whisper
in Settings ▸ Models, or pick a supported language"). Reuse the existing advice-note affordance
(`LanguageSelect.tsx:57-62`, `role="note"`) rather than inventing a new pattern.

**D5 — Mirror the vocabulary sidecar-side with a conformance test.** The repo already has this
exact pattern for caption templates — a three-way mirror conformance-tested by
`app/renderer/src/lib/captionTemplates.conformance.test.ts` (cited at
`caption_remotion.py:69-72`). Reuse it so the renderer list and the sidecar validator cannot
drift.

### 2.3 Exactly which files change

| File | Change |
|---|---|
| `app/renderer/src/lib/languages.ts` | Expand `LANGUAGES` to the full set; add `COMMON_CODES` for the top group; add `ENGINE_LANGS = {whisper, parakeet}` + `mtTier(code)`; add `supportsLanguage(engine, code)` |
| **NEW** `sidecar/media_studio/features/languages.py` | `WHISPER_LANGS`, `PARAKEET_LANGS` as real frozensets; re-export `translation.TIER1_LANGS/TIER2_LANGS`; the sidecar-side validation half of D5 |
| `app/renderer/src/components/LanguageSelect.tsx` | `<select>` → filtering combobox; add `engine?: string` prop; render the D4 warning |
| `app/renderer/src/components/CaptionPreferences.tsx:165` | `includeAuto={false}` → `true` (delete the prop) |
| `app/renderer/src/lib/captionPreferences.ts:73-76` | `coerceLanguage` must accept `AUTO_DETECT` — **required, or D2 is cosmetic** |
| `app/renderer/src/features/Transcribe.tsx:27-38` | DELETE the duplicate array; use `LanguageSelect`; unify the `''` sentinel onto `AUTO_DETECT` |
| `app/renderer/src/components/OutputTray.tsx:126` | **No change** — `includeAuto={false}` is correct for a target |
| `app/renderer/src/lib/captionTemplates.conformance.test.ts` (or a sibling) | Extend to assert the renderer↔sidecar language mirror |

**Migration hazard (flagging, not solving):** `Transcribe.tsx` sends `''` for auto and the
contract note at `:25-26` says "empty = auto-detect (sent as undefined, not "")". Unifying on
`'auto'` means the wire value must still arrive as `undefined`, since the sidecar validates
`language` as "a string when given" (`transcribe.py:533-534`) and would treat the literal string
`"auto"` as a language code. **`'auto'` must be translated to `undefined` at the RPC boundary, not
forwarded.** Confidence that forwarding `"auto"` raw would degrade transcription: **almost
certain** (90-99%) — it would be passed straight to faster-whisper as a language id
(`transcribe.py:348-352`).

---

## 3. Translation quality — MEASURED + DESIGNED

Local/hosted split: tier1 40 languages local-fast, tier2 12 local-slow, everything else hosted
(`translation.py:104-157`). That split is sound. The quality problems are **not** in the tiering.

### 3.1 Root cause #1 — per-cue, context-free translation (the big one)

`_translate_with_tier` loops one cue at a time (`translation.py:419-437`); `_chat_one` sends only
that cue's text (`:490-493`); `build_messages` builds a 2-message chat with no neighbours and no
document context (`:222-230`). The same shape exists in the older seam
(`subtitles.make_provider_translator`, `subtitles.py:321-340`).

### 3.2 Root cause #2 — the cues are already split mid-sentence

`cues_from_transcript` splits any segment over `max_chars=84` **or** `max_duration=7.0` on word
boundaries (`subtitles.py:142-143`, split at `:160-161`, packer at `:167-207`). Translation then
runs on that split track (`subtitles.translate`, `:343-382`; `TieredTranslator.translate_track`,
`translation.py:334-358`).

**So a sentence spanning three cues is translated as three independent fragments.** For
verb-final or different-word-order targets (de, ja, ko, tr, hi — all in the UI's 19) a fragment
cannot be translated correctly in isolation: the model has to guess the clause it belongs to.
Confidence this is a **primary** contributor to the owner's "bad translations": **likely** (55-80%)
— the mechanism is certain from the code; its share of observed badness versus model quality is
not measured. *Settling experiment: translate one transcript twice — once per-cue as today, once
by joining cues into sentences first — and have a fluent speaker rank the two outputs blind.*

### 3.3 Root cause #3 — routing is TARGET-only

`route(target_lang)` (`translation.py:293-295`, called at `:326`); `source_lang` only appends one
sentence to the system prompt (`:226-227`). So `ro→en` routes **tier1** because `en` is tier1,
ignoring that the source is lower-resource. The heavier tier2 model is unreachable for exactly
the direction that needs it.

### 3.4 Root cause #4 — no glossary, no do-not-translate list

See §5.2 — nothing exists.

### 3.5 Root cause #5 — an EN-only punctuation/casing model runs on ALL languages

`polish_cues` applies the punctuation backend with **no language check**:

```python
# caption_polish.py:449-452
for cue in cues:
    text = str(cue.get("text", "") or "")
    if punct_backend is not None:
        text = punct_backend.restore(text)
```

The model is unambiguously English-only: `PUNCT_ASSET_NAME = "sherpa-onnx-punct-en"` (`:114`),
`PUNCT_HF_REPO = "lorneluo/sherpa-onnx-online-punct-en-2024-08-06"` (`:522`), label
`"sherpa-onnx punctuation + casing (EN, Apache-2.0)"` (`:543`).

**`_is_english` exists (`:75-77`) but gates only the CPS reading-speed limit (`:102`) — it is NOT
wired to the punctuation stage.** I initially assumed it gated the backend and was wrong; reading
the call site corrected it.

Latency of harm: gated behind two opt-ins — `captionPolish` defaults `false`
(`captionPreferences.ts:57`) and the asset must be installed (`:475-480`). Confidence the model
is EN-only: **almost certain** (90-99%, three independent naming signals). Confidence it actively
CORRUPTS non-English text rather than no-op'ing: **likely** (55-80%). *Settling experiment: run
`polish_cues` with the real backend on a Romanian and a Japanese cue and diff against input.*

### 3.6 Proposed changes, highest value first

**T1 — Translate at sentence level, then re-split (the keystone).** Reassemble cues into
sentences, translate with context, then re-segment using the machinery that already exists —
`caption_polish.enforce_cps_cpl` (`:238`) + `wrap_two_lines` (`:184`) + `enforce_min_gap`
(`:331`). Timings redistribute proportionally across the re-split. This reuses shipped, tested
code and addresses §3.1 and §3.2 together.

**T2 — Sliding context window (cheaper interim).** Keep per-cue calls but pass N previous and N
next cues as context in `build_messages` (`translation.py:222-230`), instructing the model to
return ONLY the target cue's translation. Lower risk than T1, lower payoff; a reasonable first
increment if T1 is too large for one work unit.

**T3 — Glossary / do-not-translate.** A `settings["translationGlossary"]` of `{source, target}`
pairs plus a proper-noun list, injected into **both** `build_messages` (`translation.py:222-230`)
and whisper's `initial_prompt` (`transcribe.py:348-352`). One feature fixes both ASR proper-noun
errors and translation drift.

**T4 — Route on the language PAIR.** `route(target)` → `route_pair(source, target)` selecting the
heavier of the two tiers, so a low-resource source escalates.

**T5 — Gate the punctuation stage on language.** Pass the track language into `polish_cues` and
skip the EN-only restorer for non-`en`. Whisper already emits punctuation natively, so skipping is
a safe default; a multilingual restorer is a later upgrade. **This is the cheapest of the five and
prevents an active regression.**

**T6 — Preserve the ASS/SRT escape contract across translation.** `subtitles.py:619-635` and
`caption.py:80-100` implement *different* escape schemes (`{` → `\(` vs `{` → `\{`). Translated
text re-enters the caption builders, so a model that emits a brace changes which path is safe.
*UNVERIFIED that this is exploitable or visible today; settling experiment: translate a cue whose
text contains `{` and `}` and inspect both the ASS and SRT outputs.*

*NOT-CHECKED: whether `captionPolish` runs BEFORE or AFTER `subtitles.translate` in the handler.
If polish runs first, `wrap_two_lines` (`caption_polish.py:184`) will have inserted hard newlines
into cue text before the model sees it, adding a fourth root cause. Settling experiment: read the
`subtitles_generate` / `subtitles.translate` bodies in `handlers/media_ops.py` (near `:179`) and
record the stage order.*

---

## 4. Caption parity — MEASURED. THREE engines, not two; the asymmetries are real

### 4.1 The router

`features/shortmaker.py:366-448` (`_lazy_caption`) picks the engine from
`settings["captionStyle"]`:

| `captionStyle` | Engine | Line |
|---|---|---|
| `"none"` / captions not embedded | skip entirely (pass-through) | `:399-400` |
| any of the **14** Remotion styles | `RemotionCaptionEngine` | `:405-422` |
| `"opusclip-karaoke"` | libass **karaoke** ASS | `:443` → `caption.py:640-648` |
| anything else / unset | libass **normal** ASS | `:428-448` |

The 14 Remotion styles (`caption_remotion.py:75+`, extracted mechanically): `bold, karaoke, clean,
bounce, hormozi, neon, tiktok, gradient, impact, mrbeast, pop, serif, fire, subtitle`.

**Trap: TWO different karaoke implementations behind two different style ids.** `"karaoke"` is in
`Remotion.STYLES` and the Remotion check runs FIRST (`:405`), so `captionStyle="karaoke"` →
**Remotion**; only the distinct id `"opusclip-karaoke"` reaches the libass word-by-word preset.
Nothing cross-references them, and `caption_karaoke.py:48-50` notes the id is deliberately "NOT a
member of `caption_remotion.STYLES`" — so the collision of the *word* "karaoke" across two
namespaces is by construction, undocumented at the router.

### 4.2 The parity matrix (each cell measured)

| Capability | libass NORMAL | libass KARAOKE | Remotion |
|---|---|---|---|
| `fontFamily` override | YES `caption_override.py:193-195` | **NO** — hardcoded `Anton` `caption_karaoke.py:75` | **NO** — not passed `shortmaker.py:407-422` |
| `sizeScale` | YES `caption.py:346` | **NO** — fixed `play_y*0.05` `caption_karaoke.py:258` | **NO** |
| `textColor` → Primary | YES `caption_override.py:197-200` | **NO** — fixed `KARAOKE_FILL` `:62` | **NO** |
| `activeColor` → Secondary | YES `caption_override.py:201` | **NO** — fixed yellow/green alternation `:68` | **NO** |
| `box` / `outline` (BorderStyle) | YES `caption_override.py:164-178` | **NO** — fixed `1/4/2` `:77-79` | **NO** |
| `uppercase` | YES `caption.py:450` | param EXISTS `caption_karaoke.py:237`, **not passed** → locked `True` | **NO** |
| `positionBand` | YES `caption.py:360-361` | param EXISTS `caption_karaoke.py:236`, **not passed** → locked `"bottom"` | **NO** |
| `captionPosition` box `{x,y,w,h}` | YES `caption.py:352-354` | **NO param at all** | **NO** — not passed |
| `hook_title` headline | YES `caption.py:373-387` | **NO param** | YES `shortmaker.py:416` |
| `hook_card` (OpusClip white card) | YES `caption.py:376`, `:417-422` | **NO param** | **NO** — not passed |
| `total_sec` (title span) | YES `caption.py:424-432` | **NO param** | YES `shortmaker.py:421` |
| `emphasis` spans → bold | YES `caption.py:190-206` | **NO** — `build_line_text` ignores it `caption_karaoke.py:187-206` | NOT-CHECKED |
| trailing `emoji` | YES `caption.py:207-209` | **NO** | NOT-CHECKED |
| **word-by-word reveal + scale-pop** | **NO** | **YES** `caption_karaoke.py:290-301` | YES (own `karaoke` style) |
| burn AND soft-mux | YES `caption.py:670-673` | YES — same path `caption.py:663-673` | YES `shortmaker.py:412` |

**The root cause is one call site** — `caption.py:640-648`:

```python
if karaoke:
    from . import caption_karaoke as _karaoke
    ass_doc = _karaoke.build_karaoke_ass(
        cues, width=width, height=height, source_start=source_start,
    )
```

`override`, `hook_title`, `position`, `total_sec`, `hook_card`, `hook_card_sec` are all in scope
and all dropped. Two of them (`position_band`, `uppercase`) are **already accepted** by
`build_karaoke_ass` and cost one line each.

The docstring at `caption.py:637-638` declares this deliberate ("its look is fixed by the
teardown"), so it is a **decision to revisit with evidence, not a bug to silently overturn** —
but the owner's ask ("properly captioned, for both shorts and/or karaoke captions and normal
subtitles") is precisely a request to revisit it.

**Answer to the brief's question:** No. Styling/timing capability is NOT available to all three
paths. libass-normal is the only full-featured path; karaoke is style-locked; Remotion gets
neither the override, nor the position box, nor the hook card.

**Suggested minimal fix, in cost order:** (a) thread `position_band` + `uppercase` into
`build_karaoke_ass` — two lines, zero new API; (b) give `build_karaoke_ass` a
`ResolvedCaptionStyle` for font/size/colours, keeping the alternating-accent and scale-pop as
karaoke-only; (c) pass `position` and `override` to `RemotionCaptionEngine.render`, which needs a
schema change in the vendored composition and is the largest of the three.

### 4.3 What IS shared (parity that already holds)

- Cue re-basing to clip-local time: one helper `rebase_cue_time` (`caption.py:122-129`), imported
  by `caption_karaoke.py:42` and used at `caption_remotion.py:426`.
- ASS override-injection escaping: `escape_ass_text` shared (`caption.py:80-100` →
  `caption_karaoke.py:42`). Note `subtitles.py:619-635` is an INDEPENDENT second implementation
  with a different scheme (see §3.6 T6).
- The Netflix CPS/CPL/min-gap timing gate runs at cue GENERATION
  (`subtitles.generate_polished:264-294` → `caption_polish.polish_cues:404`), i.e. **upstream of
  all three engines** — so timing polish is genuinely shared.

---

## 5. Escape hatches — MEASURED

### 5.1 Custom `.SRT` import — engine BUILT, RPC + UI **MISSING**

Parsing/loading is complete and tested:

| Piece | Location |
|---|---|
| `read_srt` (tolerant of CRLF, BOM, missing indices) | `features/subtitles.py:535-554` |
| `read_vtt` / `read_ass` | `:576-597` / `:682-706` |
| `parse(text, fmt)` dispatch | `:768-771` |
| `load(path, fmt=None)` — ext-inferred | `:786-790` |
| **`track_from_file(path, lang=…)` → full SubtitleTrack** | **`:793-812`** |

**But the RPC surface has exactly four `subtitles.*` methods** — `generate`, `edit`, `translate`,
`export` — registered at `handlers/composition.py:128-131`, mirrored client-side at
`app/renderer/src/lib/rpc/client.ts:197-208`. There is **no** `subtitles.import`.

Second, independent signal: `track_from_file` and `read_srt` have **no production caller** —
every hit outside `subtitles.py` is a test (`tests/test_subtitles.py:494`, `:505`, `:321-350`;
`tests/e2e/test_nasty_inputs.py:320-384`; `tests/test_subtitles_property.py:148-159`).

**Verdict: MISSING at the user-reachable boundary; ~90% of the work already exists.** Shipping it
is a handler + a client method + a file picker, not a parser.

*Governance note: `translation.py:39-41` states "A2's method names are frozen". Adding
`subtitles.import` therefore needs an explicit contract amendment, not a silent addition. Flagging
as a decision for the owner, not resolving it here.*

### 5.2 Custom dictionary / glossary for proper nouns & jargon — **MISSING** (nothing at all)

A repo-wide case-insensitive search for
`glossary|dictionary|custom_words|hotword|initial_prompt|proper_noun` returns **zero**
implementation hits. Only occurrences:

- `docs/plans/v1.5/competitor-research.md:22` — item 13 names exactly this gap: "Caption-accuracy
  escape hatches: custom .SRT import + custom dictionary (fixes #1 caption complaint: proper
  nouns/jargon/accents) — S."
- `app/renderer/src/lib/rpc.property.test.ts:198` — `fc.dictionary`, an unrelated generator.

**faster-whisper's `initial_prompt` — the standard zero-cost way to bias ASR toward proper nouns —
is not passed.** `transcribe_file` calls
`whisper_model.transcribe(audio_path, language=…, word_timestamps=True)` and nothing else
(`transcribe.py:348-352`). That is the cheapest accuracy lever available and it is unused.
Confidence it measurably improves proper-noun accuracy: **likely** (55-80%) — documented upstream
behaviour, not benchmarked here. *Settling experiment: transcribe one clip containing 5 known
proper nouns with and without `initial_prompt`; diff token-level errors.*

---

## Appendix — corrections made during this audit

Recorded so the dead ends are not re-walked:

1. I suspected `is_karaoke_style` had **no** production caller (a truncated grep). Re-probing with
   a script found `shortmaker.py:425` and `:443`. The karaoke preset **is** reachable.
2. I assumed `_is_english` (`caption_polish.py:75`) gated the punctuation backend. It gates only
   the CPS limit (`:102`). The real finding is worse — §3.5.
3. My language-diff script printed a count of `52` that contradicted its own 33-item list
   (operator precedence). The list was correct.
