// Lip-sync section of the Dub surface — re-lip the on-screen mouth to a finished
// dub (W20).
//
// MEASURED GAP. `tts.lipsync.start` is registered UNCONDITIONALLY
// (`sidecar/media_studio/features/tts/__init__.py:141`) and is frozen into the
// authoritative method list, but it had NO caller anywhere. Measured on the host
// tree: `Dub.tsx` was 519 lines with ZERO `lipSync`/`lipsync` references, and the
// only renderer matches for "lipsync" were `AiDisclosure.tsx` and
// `ThirdPartyNotices.tsx`, neither of which calls anything. It is registered
// unconditionally and refuses at CALL time on the flag (`tts/__init__.py:23-28`),
// so it was never flag-gated out of existence — it simply had no entry point.
//
// This is a SEPARATE component mounted inside the Dub panel rather than more code
// in `Dub.tsx`: that file was already 519 lines and this section carries four
// gates, three pickers and its own job lifecycle. It consumes the audio-track list
// Dub has already fetched (`tracks.audio.list`), so it adds no duplicate RPC, and
// it renders inside `.dub-panel` so the existing `.dub-consent` / `.dub-pickers`
// styling applies without touching a stylesheet (another lane owns those).
//
// WIRE: tts.lipsync.start({videoId, audioTrackId, engine?, quality?,
//                          likenessConsentAttested}) -> {jobId}
//         -> job.done {path, engine, syncConfidence}
//
// ─── THE FOUR GATES, ALL FAIL CLOSED ────────────────────────────────────────
// 1. BUILD FLAG (`lipsync.py:197-215`). `require_enabled` refuses unless the
//    `lipSyncEnabled` setting is the LITERAL `true`; the default is `False`
//    (`settings_store.py:178`). `lipSyncEnabledFrom` mirrors that literal-true rule
//    exactly, so a truthy `'true'`/`1` reads as OFF here as it does there.
//    Consequence, deliberate: with the flag off the button is DISABLED and names
//    the setting. It is not hidden — "disabled, here is how to enable it" is the
//    same honesty the sidecar chose by registering the method unconditionally.
// 2. LIKENESS CONSENT (`lipsync.py:218-225`). `likenessConsentAttested` must be
//    the literal `true`. `buildLipsyncParams` OMITS the key unless the user
//    actually ticked the box — it is never synthesized, and the tick is cleared
//    after a success so it cannot carry into a second run.
// 3. THE TRACK MUST BE A DUB (`lipsync.py:672-677`). Re-lipping the mouth to the
//    ORIGINAL audio is meaningless, so the picker offers `kind === 'dub'` only.
// 4. ENGINE. `wav2lip` is permanently in `DENIED_ENGINES` because it genuinely
//    forbids commercial use (`lipsync.py:120-126`), so it is not offerable at all.
//    The two offered engines are OpenRAIL — commercial use IS permitted, but with
//    behavioural use-restrictions that must be passed downstream
//    (`lipsync.py:23-30`), which is why each engine's licence is shown.
//
// ─── THE DISCLOSED RESIDUAL: WHY A RUN REFUSES TODAY ────────────────────────
// `_tts.register(...)` (`handlers/composition.py:327-336`) passes NO
// `lipsync_face_boxes_probe`, so `face_boxes_probe` is `None` in the real app and
// `require_face_boxes` (`lipsync.py:239-254`, called at `:699`) RAISES inside the
// job. A relip therefore refuses at job time today, naming S3FD.
//
// The panel states that BEFORE the user clicks (`data-section="unwired"`) instead
// of letting them discover it by clicking. It deliberately does NOT hard-disable
// the button on a client-side "wiring is incomplete" constant, for two reasons:
//   * the renderer cannot OBSERVE whether the probe is wired — no RPC reports it —
//     so such a constant would be an unverifiable claim baked into the UI; and
//   * it would go stale in the WORST direction: the moment the sibling lane wires
//     the probe, a hardcoded `false` would make the feature unreachable again,
//     recreating the exact defect class this lane exists to fix.
// So the UI reflects only what it can actually measure (`lipSyncEnabled`), states
// the residual as text, and lets the sidecar's own typed refusal surface LOUDLY as
// an alert. Fixing the sidecar wiring is out of this lane's scope.
//
// ─── AI DISCLOSURE: WHY `AiDisclosure.tsx` IS NOT CHANGED ───────────────────
// Checked, not ignored. That module's model is AUDIO-TRACK-scoped:
// `isAiGeneratedAudioTrack(track)` keys off the A3 `AudioTrack.kind`, and
// `AiDisclosurePanel`'s copy says "Audio produced here is synthesized, and every
// dub track is marked…". A lip-synced output is a VIDEO FILE — it is never
// registered as an `AudioTrack`, so it has no `kind` for that predicate to read and
// no row in the track list to badge. Widening that panel's copy to cover video
// would also change `ShortMakerControls.tsx`, its other consumer, which is outside
// this lane. So the synthetic-VIDEO disclosure lives here, and the one fact that IS
// shared — that no C2PA provenance manifest is written on export — is IMPORTED from
// `C2PA_EXPORT_STATUS` rather than restated, so there is a single source for it.
// Measured, and the reason the copy can claim it: `lipsync.py` contains zero
// `metadata` occurrences, so its remux writes no marking into the output container
// either — the same in-app-only limitation the audio badge already discloses.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './panels.css';
import { C2PA_EXPORT_STATUS } from './AiDisclosure';
import type { AudioTrack } from './Dub';
import { extractJobId, getApi, pickField, waitForJobDone, type MediaStudioApi } from './_api';

/** One offerable re-lip engine and the licence facts the user must be told. */
export interface LipSyncEngineOption {
  id: string;
  label: string;
  /** The HUB tag on the WEIGHTS (`lipsync.py` ENGINES), not the code licence. */
  weightsLicense: string;
  notice: string;
}

/**
 * The OpenRAIL obligation in user-facing words, mirroring `_OPENRAIL_NOTICE`
 * (`lipsync.py:128-134`). Commercial use is permitted; the restrictions are
 * behavioural and must be passed on.
 */
const OPENRAIL_OBLIGATION =
  'Commercial use IS permitted, but the licence attaches behavioural ' +
  'use-restrictions you must not breach and must pass on to anyone you give the ' +
  'output or the model to. Re-lipping a real person without their consent is not ' +
  'a use Reframe supports.';

/**
 * The engines this UI offers — exactly the keys of `lipsync.ENGINES`.
 * `wav2lip` is ABSENT on purpose: it is in `DENIED_ENGINES` (`lipsync.py:120-126`)
 * because its README forbids commercial use outright, and the sidecar raises a loud
 * refusal for it. Not offering it means a typo cannot reach it either.
 */
export const LIPSYNC_ENGINES: readonly LipSyncEngineOption[] = [
  {
    id: 'latentsync',
    label: 'LatentSync (ByteDance) — highest quality',
    weightsLicense: 'openrail++',
    notice: OPENRAIL_OBLIGATION,
  },
  {
    id: 'musetalk',
    label: 'MuseTalk (Tencent) — real-time capable',
    weightsLicense: 'creativeml-openrail-m',
    notice: OPENRAIL_OBLIGATION,
  },
];

/** `lipsync.DEFAULT_ENGINE` (`lipsync.py:160`). */
export const DEFAULT_LIPSYNC_ENGINE = 'latentsync';
/** `lipsync.QUALITIES` / `DEFAULT_QUALITY` (`lipsync.py:165-166`). */
export const LIPSYNC_QUALITIES: readonly string[] = ['fast', 'quality'];
export const DEFAULT_LIPSYNC_QUALITY = 'quality';

/** The exact attestation the user makes (higher bar than the dub's, by design). */
export const LIPSYNC_CONSENT_TEXT =
  'I am the person on screen, or I hold their documented permission to alter ' +
  'their face in this video.';

/** Shown when the build flag is off. Names the SETTING so it is actionable. */
export const LIPSYNC_DISABLED_REASON =
  'Lip-sync is OFF in this build. It ships disabled: set the lipSyncEnabled ' +
  'setting to true to enable it, and note that the engine weights are a separate ' +
  'opt-in download with their own licence acceptance.';

/**
 * The pre-click disclosure of the missing face-box provider. Rendered in BOTH flag
 * states, because it is a property of the BUILD, not of the setting.
 */
export const LIPSYNC_UNWIRED_NOTICE =
  'Known limitation in this build: no face-box provider is wired, so a run will ' +
  'refuse instead of producing a video. That refusal is deliberate — letting the ' +
  'engine detect faces itself would pull the S3FD weight, which ships under no ' +
  'licence at all — but it means lip-sync cannot complete here yet.';

/** The synthetic-VIDEO disclosure. The C2PA half is imported, never restated. */
export const LIPSYNC_AI_DISCLOSURE =
  'A re-lipped video is synthetic media: the mouth you see was generated, not ' +
  'recorded. Reframe writes no marking into the output file — nothing about the ' +
  'edit reaches the exported container.';

/** The `job.done` payload of `tts.lipsync.start` (`lipsync.py:575`). */
export interface LipSyncOutcome {
  path: string;
  /** The engine the sidecar reports it actually used; '' when it sent none. */
  engine: string;
  /** Null when the sidecar could not measure it — never a fabricated number. */
  syncConfidence: number | null;
}

// --- pure helpers (exported for tests) -------------------------------------

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * The build flag, read with the sidecar's own literal-`true` rule
 * (`lipsync.lipsync_enabled`, `lipsync.py:197-205`). A truthy string or `1` is NOT
 * an opt-in: this flag guards a face-manipulation path, so a sloppy value reads as
 * OFF on both sides of the wire rather than only one.
 *
 * A TYPED accessor exists and is deliberately NOT used:
 * `lib/rpc/generated/client.generated.ts` declares
 * `settings.get(): Promise<Settings>` with `Settings.lipSyncEnabled: boolean`
 * (`generated/schemas.generated.ts:54`). Two reasons to read `unknown` instead:
 *   * that type is a COMPILE-TIME claim about a value that comes off DISK, and the
 *     sidecar itself does not trust it — `lipsync_enabled` treats a truthy
 *     non-`true` as OFF precisely because a settings store can hold a malformed
 *     value. Consuming it as a declared `boolean` would make the renderer LESS
 *     defensive than the backend guarding the same path, which is the wrong
 *     direction for a safety gate;
 *   * `clientGenerated` calls the non-injectable module-level `rpc()`, so it cannot
 *     take the `api?` test bridge every panel in `features/` is built around.
 */
export function lipSyncEnabledFrom(settings: unknown): boolean {
  return pickField<unknown>(settings, 'lipSyncEnabled') === true;
}

/**
 * The audio tracks that can be re-lipped: dubs only. `lipsync_start` rejects any
 * other kind (`lipsync.py:672-677`) because re-lipping the mouth to the ORIGINAL
 * recorded audio is meaningless, so offering one would be offering a guaranteed
 * error.
 */
export function dubAudioTracks(tracks: readonly AudioTrack[]): AudioTrack[] {
  return tracks.filter((t) => t.kind === 'dub');
}

/**
 * Build the `tts.lipsync.start` params. `likenessConsentAttested` is present ONLY
 * when the user genuinely ticked the box — never `false`-but-present, never
 * synthesized.
 */
export function buildLipsyncParams(args: {
  videoId: string;
  audioTrackId: string;
  engine: string;
  quality: string;
  consentAttested: boolean;
}): Record<string, unknown> {
  const params: Record<string, unknown> = {
    videoId: args.videoId,
    audioTrackId: args.audioTrackId,
    engine: args.engine,
    quality: args.quality,
  };
  if (args.consentAttested) params.likenessConsentAttested = true;
  return params;
}

/**
 * Read a `tts.lipsync.start` job.done result. Null without a usable `path`, so a
 * shapeless payload renders nothing. A missing/malformed `syncConfidence` stays
 * NULL and is displayed as "not measured" rather than as a number the sidecar
 * never produced.
 */
export function lipsyncOutcome(result: unknown): LipSyncOutcome | null {
  const path = pickField<string>(result, 'path');
  if (typeof path !== 'string' || !path) return null;
  const engine = pickField<unknown>(result, 'engine');
  const confidence = pickField<unknown>(result, 'syncConfidence');
  return {
    path,
    engine: typeof engine === 'string' ? engine : '',
    syncConfidence: Number.isFinite(confidence) ? (confidence as number) : null,
  };
}

export interface LipSyncProps {
  videoId: string;
  /** The A3 audio-track list Dub has already fetched (no duplicate RPC here). */
  audioTracks: readonly AudioTrack[];
  /** Injectable bridge for tests; defaults to the preload-exposed api. */
  api?: MediaStudioApi;
  /**
   * The C2PA export status. Injectable for the same reason `AiDisclosurePanel`
   * makes it injectable — the shipped constant is a hardcoded `available: false`,
   * so without a seam the "available" wording could never be exercised, and an
   * untested branch is where a future signing-identity change would silently break
   * the disclosure. Defaults to the SHARED constant so production has one source.
   */
  c2pa?: typeof C2PA_EXPORT_STATUS;
}

export function LipSync({
  videoId,
  audioTracks,
  api,
  c2pa = C2PA_EXPORT_STATUS,
}: LipSyncProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);

  // null while settings.get is in flight — the control is disabled until it answers.
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [trackId, setTrackId] = useState<string>('');
  const [engine, setEngine] = useState<string>(DEFAULT_LIPSYNC_ENGINE);
  const [quality, setQuality] = useState<string>(DEFAULT_LIPSYNC_QUALITY);
  const [consentAttested, setConsentAttested] = useState<boolean>(false);
  const [busy, setBusy] = useState<boolean>(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [outcome, setOutcome] = useState<LipSyncOutcome | null>(null);

  const dubs = useMemo(() => dubAudioTracks(audioTracks), [audioTracks]);
  // `engine` is only ever set from the <select> whose options ARE LIPSYNC_ENGINES,
  // so the fallback is defensive and unreachable from the UI.
  const engineOption = useMemo(
    /* v8 ignore next */
    () => LIPSYNC_ENGINES.find((e) => e.id === engine) ?? LIPSYNC_ENGINES[0],
    [engine],
  );

  useEffect(() => {
    void (async () => {
      try {
        const settings = await bridge.rpc<unknown>('settings.get');
        setEnabled(lipSyncEnabledFrom(settings));
      } catch {
        // FAIL CLOSED, exactly as `LipSyncService._settings` does for an unreadable
        // store: lip-sync stays disabled rather than assuming it is on.
        setEnabled(false);
      }
    })();
  }, [bridge]);

  // A dub track that vanishes from the list (e.g. tracks.audio.strip) must not stay
  // selected, or the panel would dispatch a stale id the sidecar cannot resolve.
  useEffect(() => {
    if (trackId && !dubs.some((t) => t.id === trackId)) setTrackId('');
  }, [dubs, trackId]);

  useEffect(() => {
    if (!jobId) return;
    const off = bridge.onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setPct(ev.pct);
      setMessage(ev.message);
    });
    return off;
  }, [bridge, jobId]);

  const canStart = enabled === true && trackId !== '' && consentAttested;

  const start = useCallback(async (): Promise<void> => {
    // Defensive: the button is disabled unless `canStart` and not already busy.
    /* v8 ignore next */
    if (busy || !canStart) return;
    setBusy(true);
    setError('');
    setOutcome(null);
    setPct(0);
    setMessage('Starting…');
    try {
      const res = await bridge.rpc<unknown>(
        'tts.lipsync.start',
        buildLipsyncParams({ videoId, audioTrackId: trackId, engine, quality, consentAttested }),
      );
      const id = extractJobId(res) ?? null;
      setJobId(id);
      // waitForJobDone REJECTS on an {error} job.done payload, which is exactly how
      // the job-time face-box refusal reaches the user: as a loud alert carrying the
      // sidecar's own typed message, never as a silent no-op or an empty success.
      const result = id ? await waitForJobDone<unknown>(bridge, id, (r) => r ?? null) : null;
      const next = lipsyncOutcome(result);
      if (next) {
        setOutcome(next);
        setPct(100);
        setMessage('Done');
        // A fresh attestation per relip; kept on FAILURE so an unrelated retry does
        // not force a re-attestation (same shape as `Dub.tsx` addSample).
        setConsentAttested(false);
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
      setJobId(null);
    }
  }, [bridge, busy, canStart, consentAttested, engine, quality, trackId, videoId]);

  const cancel = useCallback(async (): Promise<void> => {
    // Defensive: Cancel renders only while `busy && jobId`.
    /* v8 ignore next */
    if (!jobId) return;
    try {
      await bridge.rpc('job.cancel', { jobId });
    } catch {
      // Best-effort — a failed cancel must not become a panel error.
    }
    setMessage('Cancelling…');
  }, [bridge, jobId]);

  return (
    <section className="lipsync-section" aria-label="Lip-sync">
      <h3>Lip-sync (re-lip the mouth to a dub)</h3>
      <p className="dub-intro">
        Re-generate the speaker&apos;s mouth so it matches a finished dub track instead of the
        original language. This alters a real person&apos;s face, so it is gated separately from the
        dub itself.
      </p>

      {enabled === false && (
        <p className="lipsync-disabled" data-section="disabled" role="status">
          {LIPSYNC_DISABLED_REASON}
        </p>
      )}

      {/* Stated in BOTH flag states: it is a property of the build, not the flag. */}
      <p className="lipsync-unwired" data-section="unwired" role="status">
        {LIPSYNC_UNWIRED_NOTICE}
      </p>

      <div className="dub-pickers">
        <label>
          Dub track to match{' '}
          <select
            data-picker="lipsync-track"
            value={trackId}
            onChange={(e) => setTrackId(e.target.value)}
            disabled={busy || dubs.length === 0}
          >
            <option value="">— pick a dub track —</option>
            {dubs.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({t.lang})
              </option>
            ))}
          </select>
        </label>

        <label>
          Engine{' '}
          <select
            data-picker="lipsync-engine"
            value={engine}
            onChange={(e) => setEngine(e.target.value)}
            disabled={busy}
          >
            {LIPSYNC_ENGINES.map((e) => (
              <option key={e.id} value={e.id}>
                {e.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          Quality{' '}
          <select
            data-picker="lipsync-quality"
            value={quality}
            onChange={(e) => setQuality(e.target.value)}
            disabled={busy}
          >
            {LIPSYNC_QUALITIES.map((q) => (
              <option key={q} value={q}>
                {q}
              </option>
            ))}
          </select>
        </label>
      </div>

      {dubs.length === 0 && (
        <p className="lipsync-no-dub" data-section="no-dub" role="status">
          This video has no dub track yet. Lip-sync re-lips the mouth to a GENERATED dub, so make
          one above first — the original recorded audio already matches the mouth.
        </p>
      )}

      <p className="lipsync-licence" data-section="licence">
        {engineOption.label} — weights licensed <code>{engineOption.weightsLicense}</code>.{' '}
        {engineOption.notice}
      </p>

      <p className="lipsync-ai-disclosure" data-section="ai-disclosure">
        {LIPSYNC_AI_DISCLOSURE} Content Credentials (C2PA) on export:{' '}
        {c2pa.available ? 'Available' : `not available — ${c2pa.reason}`}
      </p>

      <fieldset className="dub-consent" data-testid="lipsync-consent-gate">
        <legend>Face-alteration consent (required)</legend>
        <label className="dub-consent-attest">
          <input
            data-input="lipsync-consent"
            type="checkbox"
            checked={consentAttested}
            onChange={(e) => setConsentAttested(e.target.checked)}
            disabled={busy}
          />{' '}
          {LIPSYNC_CONSENT_TEXT}
        </label>
        <p className="dub-consent-hint">
          This attestation applies to THIS run only — it is not saved, so it can never authorise a
          later run. A dub voiced by a stored voice CLONE needs that sample&apos;s own consent
          record as well; the sidecar checks it independently and refuses without it.
        </p>
      </fieldset>

      <div className="actions">
        <button
          type="button"
          data-action="start-lipsync"
          onClick={() => void start()}
          disabled={busy || !canStart}
        >
          {busy ? 'Re-lipping…' : 'Re-lip to this dub'}
        </button>
        {busy && jobId && (
          <button
            type="button"
            data-action="lipsync-cancel"
            className="secondary"
            onClick={() => void cancel()}
          >
            Cancel
          </button>
        )}
      </div>

      {busy && (
        <div className="progress" aria-live="polite">
          <progress max={100} value={pct} />
          <span className="progress-pct">{Math.round(pct)}%</span>
          {message && <span className="progress-message"> · {message}</span>}
        </div>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {outcome && (
        <div className="output-done" data-section="lipsync-result">
          <span className="output-done-label">Re-lipped file</span>
          <code>{outcome.path}</code>
          <span className="lipsync-confidence">
            {' '}
            engine {outcome.engine} · sync confidence{' '}
            {outcome.syncConfidence === null ? 'not measured' : outcome.syncConfidence.toFixed(2)}
          </span>
        </div>
      )}
    </section>
  );
}

export default LipSync;
