// AI-content disclosure surface (W21 — docs/plans/v1.5/flagship-lip-sync-dub.md
// lines 165 / 184-190, EU AI Act Article 50 transparency).
//
// Consent gates 1 (voice-clone attestation) and 2 (likeness attestation) already
// ship. This is gate 3: LABEL the generated result and be explicit about what the
// label does and does not cover.
//
// WHERE THE LABEL COMES FROM — the sidecar does NOT emit an `isAiGenerated`
// field. Measured on this tree:
//   * `sidecar/media_studio/features/tracks_audio.py:105-126` —
//     `normalize_audio_track` builds exactly {id, lang, name, kind, path} (+
//     optional `voice`). No `isAiGenerated`, and no engine field either.
//   * the only `isAiGenerated` occurrence in `sidecar/` is a *test fixture*
//     (`sidecar/tests/test_tts_lipsync.py:46`), not produced data.
// So the honest signal available to the renderer is the track's `kind`, which the
// dub pipeline writes via `tracks_audio.mux_for_dub`
// (`sidecar/media_studio/features/tracks_audio.py:591-601`, called from
// `features/tts/dub.py:382`). See `isAiGeneratedAudioTrack` for the direction of
// its error.
import React from 'react';

/** The subset of the A3 AudioTrack this module reads. */
export interface DisclosableAudioTrack {
  kind?: string;
}

/**
 * The one A3 `kind` that means "the container's own, human-recorded audio"
 * (`KIND_ORIGINAL`, `sidecar/media_studio/features/tracks_audio.py:67`). It is
 * the ONLY value that suppresses the label.
 */
export const NON_AI_TRACK_KIND = 'original';

/** The exact badge wording. */
export const AI_AUDIO_BADGE_LABEL = 'AI-generated audio';

/**
 * Tooltip for the badge. Plain shipped copy — it names no renderer identifier
 * and no RPC method, because it is read by end users, not by maintainers. The
 * same sentence is ALSO rendered as visible text by `AiDisclosurePanel`
 * (`AI_LABEL_DIRECTION_NOTE`): a `title=` attribute is unreachable by keyboard,
 * unreliable for screen readers and absent on touch, so the caveat cannot live
 * only here.
 */
export const AI_AUDIO_BADGE_TITLE =
  'Reframe errs toward marking: every audio track except the video’s own ' +
  'recorded audio carries this mark, so an imported human recording added as a ' +
  'dub is marked too.';

/**
 * The same caveat as `AI_AUDIO_BADGE_TITLE`, rendered as visible panel text.
 */
export const AI_LABEL_DIRECTION_NOTE =
  'Reframe errs toward marking: every audio track except the video’s own ' +
  'recorded audio carries the “' +
  AI_AUDIO_BADGE_LABEL +
  '” mark, so an imported human recording added as a dub is marked too. The ' +
  'mark is withheld only for a track that is explicitly the original recording.';

/**
 * True when the row should carry the AI-generated label.
 *
 * ERROR DIRECTION — the fallback points at LABELLING. Only an explicit
 * `"original"` suppresses the badge; a missing or unrecognized `kind` is
 * labelled. Two consequences, both deliberate:
 *   * OVER-labelling: a human-recorded track registered through
 *     `tracks.audio.mux` with kind `"dub"` (or with no kind at all — the sidecar
 *     defaults it to `"dub"`, `tracks_audio.py:114`) is labelled as well.
 *   * a future non-AI kind (say `"music"`) would be labelled until it is added
 *     to the non-AI set. That is a real cost, stated here rather than hidden.
 * For an Article-50 transparency duty over-disclosure is the recoverable side
 * and under-disclosure is the harm.
 *
 * REVISED after adversarial review. The first version was `kind === 'dub'`,
 * which failed the OTHER way: a row whose `kind` was absent or unrecognized
 * rendered with NO label — under-disclosure — and it disagreed with the
 * sidecar's own fallback, which defaults a missing `kind` to `"dub"`
 * (`tracks_audio.py:114`). Both sides now fail in the same direction. The
 * renderer's `AudioTrack.kind` is typed `'original' | 'dub'` and required
 * (`lib/rpc/schemas.ts:409-414`), so on a well-typed payload the two predicates
 * agree; the change only decides what happens when that contract is not held.
 */
export function isAiGeneratedAudioTrack(track: DisclosableAudioTrack): boolean {
  return track.kind !== NON_AI_TRACK_KIND;
}

/**
 * The option text for an audio-track `<select>` — used by the ShortMaker export
 * picker, which is where a dub is actually chosen to be muxed into an exported
 * short. A `<select>` cannot host a badge element, so the disclosure has to be
 * part of the label text.
 */
export function audioTrackPickerLabel(track: { name: string; lang: string; kind: string }): string {
  const base = `${track.name} (${track.lang}, ${track.kind})`;
  return isAiGeneratedAudioTrack(track) ? `${base} — ${AI_AUDIO_BADGE_LABEL}` : base;
}

/**
 * Shown next to the export picker when the selected track is AI-generated. The
 * marking is in-app only: `shortmaker.build_audio_mux_argv`
 * (`sidecar/media_studio/features/shortmaker.py:512-539`) emits no `-metadata`
 * of any kind, so nothing about the label reaches the exported container.
 */
export const AI_EXPORT_LABEL_NOTE =
  'This short will be exported with an AI-generated audio track. The ' +
  '“' +
  AI_AUDIO_BADGE_LABEL +
  '” marking is shown inside Reframe only — it is not written into the ' +
  'exported file.';

/**
 * Engines whose upstream model embeds Resemble AI's inaudible **Perth**
 * watermark in what it generates. Only the chatterbox voice-clone engine does
 * (`chatterbox-tts==0.1.7`, pinned in
 * `sidecar/runtime_setup/requirements-chatterbox.txt`).
 */
export const PERTH_WATERMARK_ENGINES: readonly string[] = ['chatterbox'];

/** Whether `engineId`'s generated audio carries a Perth watermark. */
export function engineEmbedsPerthWatermark(engineId: string): boolean {
  return PERTH_WATERMARK_ENGINES.includes(engineId);
}

/**
 * The Perth disclosure copy.
 *
 * FORWARD-LOOKING, and the copy now says so. The note is keyed to the engine
 * PICKER, so it describes the dub the user is about to make. Read
 * retrospectively it would assert that a dub already in the track list carries a
 * Perth watermark, which it may not: an A3 AudioTrack has no engine FIELD
 * (`normalize_audio_track` keeps only id/lang/name/kind/path/voice,
 * `tracks_audio.py:117-126`). The engine does survive inside the display NAME the
 * sidecar writes as `Dub (<engine>, <lang>)` (`features/tts/dub.py:386`). That is
 * free text a user can rename and no other producer is obliged to follow, so the
 * panel neither asserts provenance from it nor claims the engine is unknowable —
 * the copy below says only that an existing track "may have been made with a
 * different engine", which holds either way.
 *
 * It also deliberately does NOT promise the watermark survives the pipeline: the
 * dub is re-encoded to AAC (`features/tts/dub.py:376`) and nothing in this repo
 * verifies survival.
 *
 * UNVERIFIED — that chatterbox-tts 0.1.7 in fact applies the Perth watermarker,
 * and whether it survives the AAC encode. Settling experiment: run the
 * `resemble-perth` detector over a chatterbox-produced WAV and over the muxed
 * `.m4a`. Neither `perth` nor any watermark-stripping step appears anywhere in
 * `sidecar/media_studio/features/tts/` (measured: 0 matches), so Reframe adds no
 * removal of its own — that part is measured, the upstream embed is not.
 */
export const PERTH_WATERMARK_NOTE =
  'Chatterbox — the engine selected above — embeds Resemble AI’s inaudible ' +
  'Perth watermark in the speech it generates. That describes the dub you are ' +
  'about to make, not the tracks already listed below: those may have been made ' +
  'with a different engine. Reframe never ' +
  'strips the watermark deliberately, but the dub is re-encoded to AAC before ' +
  'it becomes a track and Reframe does not verify the watermark survives that ' +
  'encode.';

/** Status of Content Credentials (C2PA) signing on export. */
export interface C2paExportStatus {
  readonly available: boolean;
  readonly reason: string;
}

/**
 * C2PA manifest emit is NOT implemented in this tree. Measured: no `c2patool`
 * reference exists anywhere in the repo, and `docs/V1.1-FEATURES.md:575` lists
 * "Optional C2PA Content-Credentials manifest emit on export" as an L7 item
 * deferred to V2 because it needs a signing identity.
 *
 * This is exposed as a STATUS, not a checkbox, on purpose: a toggle that
 * persists a preference nothing consumes would tell the user their exports carry
 * provenance when they do not.
 */
export const C2PA_EXPORT_STATUS: C2paExportStatus = {
  available: false,
  reason:
    'C2PA manifest signing is not implemented — it needs a signing identity ' +
    '(deferred to V2, docs/V1.1-FEATURES.md L7).',
};

/** The "AI-generated audio" badge. */
export function AiAudioBadge(): React.ReactElement {
  return (
    <span className="ai-audio-badge" data-testid="ai-audio-badge" title={AI_AUDIO_BADGE_TITLE}>
      {AI_AUDIO_BADGE_LABEL}
    </span>
  );
}

export interface AiDisclosurePanelProps {
  /** The engine currently selected in the dub picker. */
  engineId: string;
  /** Injectable so the panel can be exercised in both C2PA states. */
  c2pa?: C2paExportStatus;
}

/**
 * The disclosure block for the Dub panel: what is labelled, which way the
 * labelling errs, what the label does NOT cover, the engine-specific watermark
 * note, and the C2PA export status.
 */
export function AiDisclosurePanel({
  engineId,
  c2pa = C2PA_EXPORT_STATUS,
}: AiDisclosurePanelProps): React.ReactElement {
  return (
    <section
      className="ai-disclosure"
      data-testid="ai-disclosure"
      aria-label="AI content disclosure"
    >
      <h3>AI-content disclosure</h3>
      <p className="ai-disclosure-scope">
        Audio produced here is synthesized, and every dub track is marked
        {` “${AI_AUDIO_BADGE_LABEL}” `}
        in the track list below. That marking is in-app only: it is not embedded in exported files.
      </p>
      <p className="ai-disclosure-direction" data-testid="ai-disclosure-direction">
        {AI_LABEL_DIRECTION_NOTE}
      </p>
      {engineEmbedsPerthWatermark(engineId) && (
        <p className="ai-disclosure-perth" data-testid="perth-note">
          {PERTH_WATERMARK_NOTE}
        </p>
      )}
      <p className="ai-disclosure-c2pa" data-testid="c2pa-status">
        <span className="ai-disclosure-c2pa-label">Content Credentials (C2PA) on export: </span>
        {c2pa.available ? 'Available' : `Not available — ${c2pa.reason}`}
      </p>
    </section>
  );
}

export default AiDisclosurePanel;
