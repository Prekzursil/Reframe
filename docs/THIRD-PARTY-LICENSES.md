# Reframe — third-party redistributables and the FFmpeg written source offer

> **Status:** ACTIVE. · **Date:** 2026-08-08
> **Charter:** the only place Reframe's obligations for REDISTRIBUTED BINARIES are
> recorded. Bundled ML **models** and **fonts** are a different surface and are owned
> by `app/renderer/src/features/ThirdPartyNotices.tsx` (Settings → Licenses), which
> renders them in-app; this file is the binary-redistribution half, and it is where
> the GPL written offer lives because an offer has to be a durable, quotable text.

## 1. FFmpeg — GPL-3.0-or-later (the written source offer)

Reframe ships **unmodified** `ffmpeg.exe` and `ffprobe.exe` binaries inside the
Windows installer at `resources/bin/`. They are prebuilt by the BtbN FFmpeg-Builds
project, and the exact artifact is pinned by URL **and** SHA-256 in
`build/python-embed-setup.ps1`:

| field | value |
|---|---|
| project | [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) |
| release tag | `autobuild-2026-06-30-13-34` |
| asset | `ffmpeg-n7.1.5-1-g7d0e842004-win64-gpl-7.1.zip` |
| asset SHA-256 | `405b190f746db40539eb453967f72c0e69d8bf260b10ceff36e0c2149a9ad22f` |
| FFmpeg version | `n7.1.5-1-g7d0e842004` (upstream commit `7d0e842004`) |
| licence | **GPL-3.0-or-later** (`--enable-gpl` **and** `--enable-version3`) |
| licence text shipped | `resources/bin/LICENSE.txt` (verbatim GNU GPL v3) |

**Written offer.** The corresponding source for these binaries is the FFmpeg source
at the exact upstream commit above, together with the build recipe that produced
them. Both are publicly available and permanently fetchable:

- FFmpeg source, exact revision:
  `https://github.com/FFmpeg/FFmpeg/tree/7d0e842004`
  (equivalently `git clone https://git.ffmpeg.org/ffmpeg.git && git checkout 7d0e842004`)
- Upstream project + release page: `https://ffmpeg.org/download.html`
- The build scripts and Dockerfiles that produced this exact binary:
  `https://github.com/BtbN/FFmpeg-Builds` at tag `autobuild-2026-06-30-13-34`
- The GPL-licensed encoder libraries linked into it, notably
  x264 (`https://code.videolan.org/videolan/x264`) and
  x265 (`https://bitbucket.org/multicoreware/x265_git`).

If you would prefer to receive the corresponding source on a physical medium rather
than by download, contact the address in [`SECURITY.md`](../SECURITY.md) and it will
be provided for no more than the cost of distribution.

**Why GPL and not LGPL — and why that does not relicense Reframe.** FFmpeg is
LGPL-2.1+ in its default configuration, but the software H.264/H.265 encoders
(`libx264`, `libx265`) are GPL-only, so a build that has them is GPL. Reframe needs
`libx264`: it is the encoder every export path names (see
`media_studio.ffmpeg.H264_ENCODER`). The previously shipped LGPL build was
configured `--disable-libx264`, which made **every export in the product fail** with
`Unknown encoder 'libx264'`.

Reframe does not link FFmpeg. The sidecar resolves an absolute path
(`media_studio/ffmpeg.py::resolve_binary`) and spawns the executable as a **separate
child process** over an argv list (`media_studio/ffmpeg.py::run`) — no library call,
no `shell=True`, no FFmpeg code in Reframe's address space. That is aggregation of
independent works, so the GPL does not extend to Reframe's own source. What it does
require, and what this section discharges, is that anyone who receives the binary can
get its corresponding source.

**If you rebuild or re-pin.** Changing `$FfmpegUrl` in
`build/python-embed-setup.ps1` changes what is redistributed, so the table above and
the `FFMPEG_NOTICE` entry in `app/renderer/src/features/ThirdPartyNotices.tsx` must
be updated in the same commit. `sidecar/tests/test_ffmpeg_encoders.py` fails the
build if the pin drifts back to a `-win64-lgpl-` asset.

## 2. Embeddable CPython — PSF-2.0

`resources/python/` and `resources/python-chatterbox/` are the unmodified
embeddable CPython distributions from python.org (3.12.10 and 3.14.0), pinned by URL
and SHA-256 in the same script. The PSF licence text ships with each distribution as
`LICENSE.txt`. It is a permissive licence with no source-offer obligation.

## 3. Bundled models and fonts

Owned by the in-app Settings → Licenses surface, not by this file:
`app/renderer/src/features/ThirdPartyNotices.tsx`. It reproduces each model's
attribution and carries the **non-commercial** callout for ViNet-S
(CC-BY-NC-SA-4.0), plus the OFL-1.1 notices for the bundled type trio.

## 4. Opt-in Responsible-AI (OpenRAIL) models — the pass-through obligation

The lip-sync engines are **not redistributed**: nothing ships, and nothing is
fetched unless the user enables `lipSyncEnabled`. Their attributions therefore
also live in `ThirdPartyNotices.tsx` (as `OPT_IN_MODEL_NOTICES`). They are
recorded here only because one of their obligations is *not* discharged by an
attribution block, and so belongs in a durable quotable text:

| Model | Weights licence | Code licence | Commercial | Use-restricted |
|---|---|---|---|---|
| LatentSync (`ByteDance/LatentSync-1.6`) | `openrail++` | Apache-2.0 | **yes** | **yes** |
| MuseTalk (`TMElyralab/MuseTalk`) | `creativeml-openrail-m` | MIT | **yes** | **yes** |

Verified 2026-08-08 by two mechanically independent probes: the Hub API metadata
for each repo, and a raw fetch of each repo's own `README.md` YAML frontmatter.

**Scope of that verification, stated narrowly:** neither repo ships a licence
file — a recursive `*LICENSE*` search of `ByteDance/LatentSync-1.6` returns
nothing, and `TMElyralab/MuseTalk`'s root is two weight directories plus a README
and `.gitattributes`. The licence is therefore declared **only by the Hub metadata
tag**. What was read verbatim is the canonical text *for that tag* (Stability's
CreativeML Open RAIL++-M and CompVis's CreativeML OpenRAIL-M). Treating the tag as
pointing at that text is the Hub's own convention and is strong, but it is an
inference, not a document either upstream published. If an upstream later ships a
modified licence file, that file governs and the URLs in
`app/renderer/src/features/ThirdPartyNotices.tsx` must be re-pointed at it. The
settling check is a re-run of the `*LICENSE*` search against each repo.

LatentSync's *code* licence is not an inference: `bytedance/LatentSync`'s GitHub
`LICENSE` is the verbatim Apache License 2.0 text.

**These are NOT non-commercial licences.** Both grants are royalty-free and
expressly permit hosting the model "for Third Party remote access purposes (e.g.
software-as-a-service)". What they add is Attachment A — a list of prohibited
USES — together with this clause, which is the obligation this section exists to
record:

> Use-based restrictions as referenced in paragraph 5 MUST be included as an
> enforceable provision by You in any type of legal agreement … governing the use
> and/or distribution

So if Reframe ever redistributes these weights, or offers lip-sync as a hosted
service, the Attachment A restrictions must be carried into the terms shown to
that downstream user. Rendering the notice in-app satisfies the attribution half;
it does **not** by itself satisfy the flow-down half for a hosted offering.

Two corrections to the v1.5 plan (`docs/plans/v1.5/flagship-lip-sync-dub.md`
§3.2) are recorded deliberately, because both would otherwise be re-derived wrong:

1. The plan lists both models as commercial **blockers**. They are not; the
   licence class was misread as non-commercial.
2. Attachment A, in **both** variants, has eleven items and **none names
   impersonation, likeness, identity, or a real person's image or voice**. A
   non-consensual relip is most plausibly caught by item 3 (verifiably false
   information to harm others) or item 5 (defame, disparage or harass), but that
   is an inference about application, not a verbatim prohibition — UNVERIFIED
   until licence counsel reads those items against a named fact pattern.
   Reframe's likeness-attestation gate is therefore justified on EU AI Act
   Art. 50 transparency duties and the plan's own §5 ethics gate, **not** on an
   OpenRAIL likeness clause.

**Wav2Lip is excluded outright**, and this one *is* a genuine non-commercial
wall: its README states "any form of commercial use is strictly prohibited".
It is named in `lipsync.DENIED_ENGINES` so a request for it is refused with that
reason rather than falling through to a generic "unknown engine".

## 5. Word-timing CTC forced aligners — one CC-BY-NC model, now opt-in

Karaoke-grade word timings come from a CTC forced-alignment model
(`sidecar/media_studio/features/ctc_align.py`), downloaded on demand. The
attributions render in-app as `ALIGNER_MODEL_NOTICES` in
`app/renderer/src/features/ThirdPartyNotices.tsx`; this section records the two
things an attribution block does not: **what was previously wrong, and how it was
measured.**

| Model | Licence | Commercial | Role |
|---|---|---|---|
| `facebook/wav2vec2-large-960h-lv60-self` | Apache-2.0 | yes | **packaged default** (English) |
| `facebook/wav2vec2-large-960h` | Apache-2.0 | yes | English alternative |
| `facebook/hubert-large-ls960-ft` | Apache-2.0 | yes | English alternative |
| `gigant/romanian-wav2vec2` | Apache-2.0 | yes | Romanian |
| `MahmoudAshraf/mms-300m-1130-forced-aligner` | **CC-BY-NC-4.0** | **no** | 158 languages, opt-in only |

Licences verified 2026-08-09 by a Hugging Face Hub metadata probe — a source
mechanically independent of the repo's own comments, which is exactly why it was
worth running.

**Two defects this closed.**

1. **The MMS model was disclosed nowhere.** It had been the packaged default
   since Phase-8, and searching `ThirdPartyNotices.tsx` and this file for
   `mms-300m`, `forced-aligner` or `MahmoudAshraf` returned nothing. CC-BY-NC-4.0
   requires **attribution**, and that obligation is independent of the commercial
   question — Reframe is already non-commercial while ViNet-S (CC-BY-NC-SA-4.0)
   is bundled, so this was not a *new* commercial breach, but it was a live
   attribution breach on its own.
2. **The permissive alternatives were mislabelled MIT.** The code called them
   `MIT_MODEL_IDS` and the asset label read "wav2vec2 (word timing, MIT
   commercial)". The Hub reports `license:apache-2.0` for all three. Both are
   permissive, so nothing shipped under a wrong grant, but Apache-2.0 carries a
   NOTICE/attribution condition MIT does not, and a licence claim restated from a
   neighbouring comment is how that kind of error survives. Renamed
   `PERMISSIVE_MODEL_IDS`.

**The gate.** `ctc_align._resolve_model_id` applies the licence check LAST, to
the *resolved* id, so no request shape routes around it: the packaged default,
the `ctcModelId` alias, a hand-typed full HF id and the per-job `model_id`
argument all pass through one check, and a `NON_COMMERCIAL_MODEL_IDS` member is
downgraded to the Apache-2.0 default unless `settings['allowNonCommercialAligner']`
is truthy. This implements
`docs/plans/v1.5/flagship-transcript-editing.md:94` ("must NOT be the packaged
default") and `:150` ("gate MMS behind `allowNonCommercialAligner`").

**The opt-in UNLOCKS the MMS model; it never selects it.** Reaching CC-BY-NC
weights takes the flag *and* an explicit choice in Settings. The first cut of
this section did not say that because the code did not do it: with the flag on
and nothing chosen, `_resolve_model_id` fell back to MMS while the Settings
dropdown still rendered "English wav2vec2 — default (Apache-2.0,
commercial-safe)" as the selected row — a screen asserting the wrong licence for
the model actually running, which is worse than the undisclosed dependency this
section was written to close. Three independent reviewers reproduced it with the
same probe. The fallback is removed. It shipped green because the sidecar suite
and the renderer suite each only checked their own half, so the guard is now a
cross-file test that reads both plus this table's in-app twin:
`test_the_settings_dropdown_label_matches_the_model_that_will_actually_run` in
`sidecar/tests/test_ctc_align.py`.

**What this does NOT do, stated so it is not assumed:**

- The per-language permissive-CTC map the same plan line asks for (the XLSR-53
  family) is **not built**. A non-English clip whose language has no permissive
  aligner now falls back to the ASR's own word timings — measurably looser
  (~100–500 ms Whisper DTW vs ~20–120 ms CTC) — unless the user picks the
  Romanian model or accepts the non-commercial terms. That is a real quality
  regression for non-English users and it is the deliberate price of the flip.
- The typed `Settings` keys (`ctcModelId`, `asrEngine`,
  `allowNonCommercialAligner`) in `sidecar/contract/spec.py` are **not added**;
  both keys stay stringly-accessed as before. Regenerating the contract
  artifacts was out of scope here.
- Nothing was checked with licence counsel. The claims above are licence *tags*
  and licence *text*, not legal advice.
