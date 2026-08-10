// AI-content disclosure surface (W21 — docs/plans/v1.5/flagship-lip-sync-dub.md
// lines 165 / 184-190, EU AI Act Article 50 transparency).
//
// Consent gates 1 (voice-clone attestation) and 2 (likeness attestation) already
// ship. This is gate 3: LABEL the generated result and be explicit about what the
// label does and does not cover.
//
// WHERE THE LABEL COMES FROM — the sidecar does NOT emit an `isAiGenerated`
// field. Measured on this tree:
//   * `sidecar/media_studio/features/tracks_audio.py:117-126` — `normalize_audio_track`
//     builds exactly {id, lang, name, kind, path} (+ optional `voice`). No
//     `isAiGenerated`.
//   * the only `isAiGenerated` occurrence in `sidecar/` is a *test fixture*
//     (`sidecar/tests/test_tts_lipsync.py:46`), not produced data.
// So the honest signal available to the renderer is `AudioTrack.kind === 'dub'`,
// which the dub pipeline writes via `tracks_audio.mux_for_dub`
// (`sidecar/media_studio/features/tts/dub.py:382`). See
// `isAiGeneratedAudioTrack` for the direction of its error.
import React from 'react';

/** The subset of the A3 AudioTrack this module reads. */
export interface DisclosableAudioTrack {
  kind?: string;
}

/** The exact badge wording. */
export const AI_AUDIO_BADGE_LABEL = 'AI-generated audio';

/**
 * Tooltip for the badge — it discloses the predicate AND the direction in which
 * it is wrong, because a label whose basis is hidden invites over-trust.
 */
export const AI_AUDIO_BADGE_TITLE =
  'Derived from the sidecar AudioTrack.kind === "dub". A human-recorded file ' +
  'registered through tracks.audio.mux with kind "dub" is labelled too, so this ' +
  'can over-label; it never leaves a dub produced by this panel unlabelled.';

/**
 * True when the row should carry the AI-generated label.
 *
 * ERROR DIRECTION (deliberate): `tracks.audio.mux` defaults `kind` to `"dub"`
 * (`sidecar/media_studio/features/tracks_audio.py:498`), so a human-recorded
 * track imported that way is ALSO labelled. That is over-disclosure. For an
 * Article-50 transparency duty over-disclosure is the safe side and
 * under-disclosure is the harm, so the predicate is intentionally not narrowed.
 */
export function isAiGeneratedAudioTrack(track: DisclosableAudioTrack): boolean {
  return track.kind === 'dub';
}

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
 * The Perth disclosure copy. Deliberately does NOT promise the watermark
 * survives the pipeline: the dub is re-encoded to AAC
 * (`sidecar/media_studio/features/tts/dub.py:376`) and nothing in this repo
 * verifies that the watermark survives that encode.
 *
 * UNVERIFIED — that chatterbox-tts 0.1.7 in fact applies the Perth watermarker,
 * and whether it survives the AAC encode. Settling experiment: run the
 * `resemble-perth` detector over a chatterbox-produced WAV and over the muxed
 * `.m4a`. Neither `perth` nor any watermark-stripping step appears anywhere in
 * `sidecar/media_studio/features/tts/` (measured: 0 matches), so Reframe adds no
 * removal of its own — that part is measured, the upstream embed is not.
 */
export const PERTH_WATERMARK_NOTE =
  'Chatterbox embeds Resemble AI’s inaudible Perth watermark in the speech it ' +
  'generates. Reframe never strips it deliberately — but the dub is re-encoded ' +
  'to AAC before it becomes a track, and Reframe does not verify the watermark ' +
  'survives that encode.';

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
 * The disclosure block for the Dub panel: what is labelled, what the label does
 * NOT cover, the engine-specific watermark note, and the C2PA export status.
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
