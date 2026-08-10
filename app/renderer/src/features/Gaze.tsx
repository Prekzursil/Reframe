// Gaze feature panel — "Eye contact" (W19: per-video eye-contact correction).
//
// WHY THIS PANEL EXISTS (measured, with the detector controlled first).
// `gaze.probe` and `gaze.run` are both registered
// (`sidecar/media_studio/features/gaze.py:699-700`) and both are frozen into the
// authoritative method list (`sidecar/tests/test_handlers_rpc_surface.py`), but the
// string `gaze` appeared ZERO times, case-insensitively, anywhere under
// `app/renderer`. Detector control: the same case-insensitive scan finds `gaze` in
// 9 files under `sidecar/`, so the zero was a real absence and not a broken
// matcher. `docs/wiring/WIRING-gaze.md:172` already presupposed "so the UI can
// disable the control" — there was no control to disable. This panel is it.
//
// TRANSPORT.
//   gaze.probe()  -> {available}   direct-return, offline (gaze.py:615-617)
//   gaze.run({videoId, strength, likenessSubject, likenessAttested?})
//       -> {jobId} -> job.done {path, strength, report, likeness}
// `gaze.run` is a deferred job, so the terminal payload arrives on the LATER
// `job.done` notification and never on the rpc promise (`_api.ts` CONTRACT-NOTE);
// we subscribe with `waitForJobDone`, the same shape as `Stabilize.tsx`.
//
// ─── THE ETHICS GATE, AND WHICH OF THE TWO ROUTES THIS UI USES ───────────────
// `gaze.run` alters a REAL PERSON'S FACE, so `gaze.py:633` calls
// `models/likeness.resolve_attestation(settings, params, scope=SCOPE_GAZE)` BEFORE
// the media is resolved and before any backend is built. That resolver
// (`likeness.py:137-160`) accepts, in order: (1) an EXPLICIT per-job attestation
// in the request (`likenessAttested is True` + a usable `likenessSubject`), else
// (2) the persisted grant `settings.likeness.attestations[subject].gaze`, else it
// RAISES.
//
// THIS PANEL USES ROUTE (1), THE EXPLICIT PER-JOB ATTESTATION. Three reasons,
// all measured:
//   * Route (2) has no setter. `likeness.py:34-37` states outright that the
//     persisted-grant SETTER "and its UI" belong to the shared voice/likeness
//     lane and are deliberately absent, and `settings_store.py` carries no
//     `likeness` key (measured: 0 hits for `likeness` in that file). So a UI
//     built on route (2) would have nothing to write to, and writing one here
//     would collide with that lane.
//   * Per-job is the stronger consent shape: there is no durable grant that can
//     silently authorise a LATER run, or a run against a DIFFERENT subject.
//   * The attestation is never minted by this UI. `buildGazeParams` OMITS
//     `likenessAttested` unless the user actually ticked the box, and the Run
//     button stays disabled until both the box and a non-blank subject exist. A
//     Tier-0 defect earlier in this programme was exactly a consent value the code
//     minted on the user's behalf; the sidecar refuses independently in any case,
//     and that refusal is surfaced as an alert rather than swallowed.
//
// ─── WHAT THIS PANEL DELIBERATELY DOES NOT CLAIM ────────────────────────────
// A finished run is reported with the sidecar's own tally, INCLUDING skips
// (`GazeReport.as_dict`, `gaze.py:432-439`). The engine leaves a frame PRISTINE
// on low confidence, eyes too small, or implausible head roll (`skip_reason`,
// `gaze.py:259`), so a run that corrected 0 of N frames is a legitimate outcome
// that must not read as a win — hence the explicit "corrected nothing" notice.
// Nothing about the alteration is written into the output container: the mux argv
// (`gaze_backend.py:200-219`) carries no `-metadata`, so the attestation lives in
// the job's audit trail only, which is why the panel renders it.
//
// ─── AI DISCLOSURE: WHY THIS PANEL CARRIES IT, AND `AiDisclosure.tsx` DOES NOT ─
// REFUTED IN REVIEW, correctly: the lip-sync sibling reasoned this interaction
// through and this panel silently skipped it (measured then: 12 hits for
// `C2PA|ai-disclosure|synthetic` in `LipSync.tsx`, ZERO in this file). A
// gaze-corrected clip is the same category of artifact — a real person's irises are
// WARPED, and per the note above the output container carries no marking either —
// so the same disclosure is owed here.
//
// `AiDisclosure.tsx` is still not changed, for the reason its own model gives:
// `isAiGeneratedAudioTrack(track)` keys off the A3 `AudioTrack.kind`, and
// `AiDisclosurePanel`'s copy is about dub AUDIO. A gaze output is a VIDEO FILE that
// is never registered as an `AudioTrack`, so there is no row to badge and no `kind`
// for that predicate to read; widening it would also change
// `ShortMakerControls.tsx`, its other consumer, which another live lane owns. So the
// synthetic-VIDEO disclosure lives in the panel that produces the video, and the one
// fact that IS shared — no C2PA provenance manifest on export — is IMPORTED from
// `C2PA_EXPORT_STATUS` rather than restated, so both panels have one source.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './panels.css';
import { C2PA_EXPORT_STATUS } from './AiDisclosure';
import { extractJobId, getApi, pickField, waitForJobDone, type MediaStudioApi } from './_api';

/** The sidecar's correction-strength default (`gaze.py:113` DEFAULT_STRENGTH). */
export const DEFAULT_GAZE_STRENGTH = 0.7;

/**
 * The exact attestation the user makes. Worded to match what
 * `models/likeness.py` actually enforces — a claim of the RIGHT to alter this
 * person's likeness, scoped to the face (`SCOPE_GAZE`), not a general consent.
 */
export const LIKENESS_ATTESTATION_TEXT =
  'I am the person shown, or I hold their documented permission to alter their ' +
  'likeness in this video.';

/**
 * Shown when `gaze.probe` answers `{available:false}`. It names the ASSET,
 * because that is the actionable half of the sidecar's own refusal message
 * (`gaze.py` `UNAVAILABLE_MESSAGE`), which a bare "unavailable" would drop.
 */
export const GAZE_UNAVAILABLE_REASON =
  'Eye-contact correction needs the yunet-face-detection model, which is not ' +
  'installed. Run first-run setup, or install it from the Assets tab, then ' +
  'reopen this tab. No new download is added by this feature — the same ' +
  'MIT-licensed detector the speaker-tracking path already uses.';

/** Prefix for the fail-CLOSED case where the availability check itself broke. */
export const GAZE_PROBE_FAILED_PREFIX =
  'Could not check whether eye-contact correction is available, so the control ' +
  'stays disabled:';

/** The honest tally of what a finished run did (`gaze.py` `GazeReport.as_dict`). */
export interface GazeReport {
  framesTotal: number;
  framesCorrected: number;
  eyesCorrected: number;
  /** `SkipReason` -> count. A skip is a deliberate pristine frame, not an error. */
  skipped: Record<string, number>;
}

/** The audit record naming which attestation authorised altering this face. */
export interface GazeAudit {
  subject: string;
  scope: string;
  source: string;
}

/** The `job.done` payload of `gaze.run` (`gaze.py:664-673`). */
export interface GazeOutcome {
  path: string;
  /** The strength the sidecar actually clamped to, or null if it sent none. */
  strength: number | null;
  report: GazeReport;
  /** Null when the payload carried no complete audit block (never invented). */
  likeness: GazeAudit | null;
}

// --- pure helpers (exported for tests) -------------------------------------

/** `Number.isFinite` does NOT coerce, so this rejects strings/null/undefined. */
function finiteOr(value: unknown, fallback: number): number {
  return Number.isFinite(value) ? (value as number) : fallback;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {};
}

/** The message text of any thrown value (shared by every catch in this panel). */
function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Build the `gaze.run` params.
 *
 * `likenessAttested` is present ONLY when the user genuinely ticked the box —
 * never `false`-but-present, and never synthesized. `likenessSubject` is always
 * sent (trimmed) because `resolve_attestation` requires a usable subject in EVERY
 * route and names it in the refusal, so sending it makes the sidecar's error
 * message precise even on the refusal path.
 */
export function buildGazeParams(args: {
  videoId: string;
  likenessSubject: string;
  likenessAttested: boolean;
  strength: number;
}): Record<string, unknown> {
  const params: Record<string, unknown> = {
    videoId: args.videoId,
    likenessSubject: args.likenessSubject.trim(),
    strength: args.strength,
  };
  if (args.likenessAttested) params.likenessAttested = true;
  return params;
}

/**
 * Read a `gaze.run` job.done result. Null when there is no usable `path`, so a
 * shapeless or error payload renders nothing rather than junk. A missing or
 * malformed report becomes explicit ZEROS (never an invented tally), and a
 * partial audit block is dropped entirely — an audit trail is all-or-nothing.
 */
export function gazeOutcome(result: unknown): GazeOutcome | null {
  const path = pickField<string>(result, 'path');
  if (typeof path !== 'string' || !path) return null;
  const raw = asRecord(pickField<unknown>(result, 'report'));
  const skipped: Record<string, number> = {};
  for (const [reason, count] of Object.entries(asRecord(raw.skipped))) {
    if (Number.isFinite(count)) skipped[reason] = count as number;
  }
  const strength = pickField<unknown>(result, 'strength');
  const audit = asRecord(pickField<unknown>(result, 'likeness'));
  const trio = [audit.subject, audit.scope, audit.source];
  return {
    path,
    strength: Number.isFinite(strength) ? (strength as number) : null,
    report: {
      framesTotal: finiteOr(raw.framesTotal, 0),
      framesCorrected: finiteOr(raw.framesCorrected, 0),
      eyesCorrected: finiteOr(raw.eyesCorrected, 0),
      skipped,
    },
    likeness: trio.every((v) => typeof v === 'string')
      ? {
          subject: audit.subject as string,
          scope: audit.scope as string,
          source: audit.source as string,
        }
      : null,
  };
}

/**
 * The synthetic-media disclosure for a gaze-corrected clip. The C2PA half is
 * imported from `C2PA_EXPORT_STATUS`, never restated.
 */
export const GAZE_AI_DISCLOSURE =
  'A gaze-corrected clip is edited media: the eyes you see were re-drawn, not ' +
  'recorded. Reframe writes no marking into the output file — nothing about the ' +
  'edit reaches the exported container, so only the job audit trail below records it.';

export interface GazeProps {
  videoId: string;
  /** Injectable bridge for tests; defaults to the preload-exposed api. */
  api?: MediaStudioApi;
  /**
   * The C2PA export status. Injectable for the same reason `AiDisclosurePanel` and
   * `LipSync` make it injectable: the shipped constant is a hardcoded
   * `available: false`, so without a seam the "available" wording could never be
   * exercised, and an untested branch is where a future signing-identity change
   * would silently break the disclosure. Defaults to the SHARED constant.
   */
  c2pa?: typeof C2PA_EXPORT_STATUS;
}

export function Gaze({ videoId, api, c2pa = C2PA_EXPORT_STATUS }: GazeProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);

  // null while the probe is in flight — the control is disabled until it answers.
  const [available, setAvailable] = useState<boolean | null>(null);
  const [unavailableReason, setUnavailableReason] = useState<string>('');
  // the ethics gate
  const [subject, setSubject] = useState<string>('');
  const [attested, setAttested] = useState<boolean>(false);
  const [strength, setStrength] = useState<number>(DEFAULT_GAZE_STRENGTH);
  // job state
  const [running, setRunning] = useState<boolean>(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [outcome, setOutcome] = useState<GazeOutcome | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const res = await bridge.rpc<unknown>('gaze.probe');
        const ok = pickField<boolean>(res, 'available') === true;
        setAvailable(ok);
        setUnavailableReason(ok ? '' : GAZE_UNAVAILABLE_REASON);
      } catch (err) {
        // FAIL CLOSED: an unreadable probe is "not available", never "probably fine".
        setAvailable(false);
        setUnavailableReason(`${GAZE_PROBE_FAILED_PREFIX} ${errText(err)}`);
      }
    })();
  }, [bridge]);

  useEffect(() => {
    if (!jobId) return;
    const off = bridge.onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setPct(ev.pct);
      setMessage(ev.message);
    });
    return off;
  }, [bridge, jobId]);

  const canRun = available === true && attested && subject.trim().length > 0;

  /**
   * Renaming the subject INVALIDATES the tick.
   *
   * REFUTED IN REVIEW and fixed here: `attested` used to be cleared only on a
   * successful run, so a tick made while the field read 'Ana' still satisfied
   * `canRun` after the field was changed to 'Bogdan'. That is the W02 class — the
   * code satisfying a consent question on the user's behalf from data it already
   * held — and it is not cosmetic: `likeness.py:156-157` stamps whichever subject
   * arrives into `Attestation(subject=…)`, which `gaze.py:668-672` writes into the
   * job's audit trail, so the record would assert a person the user never attested
   * for. A new name is a NEW question, so the answer is discarded.
   *
   * TRIMMED comparison, deliberately: `buildGazeParams` trims the subject, so
   * 'Ana' -> 'Ana ' sends the IDENTICAL payload. Re-asking there would be consent
   * theatre — a second tick that changes nothing about who was attested.
   */
  const changeSubject = useCallback(
    (next: string): void => {
      setSubject(next);
      if (next.trim() !== subject.trim()) setAttested(false);
    },
    [subject],
  );

  const run = useCallback(async (): Promise<void> => {
    // Defensive: the button is disabled unless `canRun` and not already running.
    /* v8 ignore next */
    if (running || !canRun) return;
    setRunning(true);
    setError('');
    setOutcome(null);
    setPct(0);
    setMessage('Starting…');
    try {
      const res = await bridge.rpc<unknown>(
        'gaze.run',
        buildGazeParams({
          videoId,
          likenessSubject: subject,
          likenessAttested: attested,
          strength,
        }),
      );
      const id = extractJobId(res) ?? null;
      setJobId(id);
      // waitForJobDone REJECTS on an {error} job.done payload (caught below), so a
      // refused or failed run is never laundered into a silent success.
      const result = id ? await waitForJobDone<unknown>(bridge, id, (r) => r ?? null) : null;
      const next = gazeOutcome(result);
      if (next) {
        setOutcome(next);
        setPct(100);
        setMessage('Done');
        // A fresh attestation per run. This is the RUN half of "one tick, one
        // subject"; the SUBJECT half is `changeSubject` above (a rename clears the
        // tick), and it was missing in the first draft — an adversarial probe
        // showed a tick made for 'Ana' still authorising a run against 'Bogdan'.
        // Mirrors the proven WU-A2 behaviour in `Dub.tsx` (`addSample`), including
        // keeping the tick on FAILURE so a retry for the SAME person after an
        // unrelated error does not force a re-attestation.
        setAttested(false);
      }
    } catch (err) {
      setError(errText(err));
    } finally {
      setRunning(false);
      setJobId(null);
    }
  }, [attested, bridge, canRun, running, strength, subject, videoId]);

  const cancel = useCallback(async (): Promise<void> => {
    // Defensive: Cancel renders only while `running && jobId`.
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
    <section className="feature-panel gaze-panel" aria-label="Eye contact">
      <h2>Eye Contact</h2>
      <p className="assets-intro">
        Nudge the speaker&apos;s irises toward the lens so they read as looking at the camera.
        Token-free and fully local; the original is never touched and a new file is written. The
        correction is deliberately partial and conservative — frames where the face is
        low-confidence, the eyes are too small to carry a warp, or the head is rolled too far are
        left completely untouched rather than mangled.
      </p>

      {unavailableReason && (
        <p className="gaze-unavailable" data-section="unavailable" role="status">
          {unavailableReason}
        </p>
      )}

      {/* THE ETHICS GATE (models/likeness.py). Not a notice — a gate: the Run
          button stays disabled until the user names the subject AND attests, and
          the sidecar refuses independently even if that were bypassed. */}
      <fieldset className="gaze-consent" data-testid="gaze-consent">
        <legend>Likeness attestation (required)</legend>
        <label className="gaze-consent-subject">
          Whose face is this?{' '}
          <input
            data-input="likeness-subject"
            type="text"
            placeholder="e.g. Marius (self), or the speaker's name"
            value={subject}
            onChange={(e) => changeSubject(e.target.value)}
            disabled={running}
          />
        </label>
        <label className="gaze-consent-attest" data-testid="gaze-attest-label">
          <input
            data-input="likeness-attest"
            type="checkbox"
            checked={attested}
            onChange={(e) => setAttested(e.target.checked)}
            disabled={running}
          />{' '}
          {LIKENESS_ATTESTATION_TEXT}
        </label>
        <p className="gaze-consent-hint">
          This attestation applies to THIS run only — it is not saved, and it is cleared both after
          a finished run and whenever you change the name above, so it can never authorise a later
          run or a different person. It is recorded in the finished job&apos;s audit trail (shown
          below); nothing about the edit is written into the output file itself.
        </p>
      </fieldset>

      <p className="gaze-ai-disclosure" data-section="ai-disclosure">
        {GAZE_AI_DISCLOSURE} Content Credentials (C2PA) on export:{' '}
        {c2pa.available ? 'Available' : `not available — ${c2pa.reason}`}
      </p>

      <div className="field gaze-strength">
        <label>
          Correction strength{' '}
          <input
            data-input="strength"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={strength}
            onChange={(e) => setStrength(Number(e.target.value))}
            disabled={running}
          />{' '}
          <span className="gaze-strength-value">{strength.toFixed(2)}</span>
        </label>
        <span className="gaze-strength-hint">
          0 = no change, 1 = fully re-centre. The default of {DEFAULT_GAZE_STRENGTH} is deliberate:
          a full re-centre often reads as uncanny, and displacement is capped regardless.
        </span>
      </div>

      <div className="actions">
        <button
          type="button"
          data-action="run"
          onClick={() => void run()}
          disabled={running || !canRun}
        >
          {running ? 'Correcting…' : 'Correct eye contact'}
        </button>
        {running && jobId && (
          <button
            type="button"
            data-action="cancel"
            className="secondary"
            onClick={() => void cancel()}
          >
            Cancel
          </button>
        )}
      </div>

      {running && (
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
        <div className="gaze-outcome">
          <div className="output-done" data-section="result">
            <span className="output-done-label">Corrected file</span>
            <code>{outcome.path}</code>
          </div>

          <p className="gaze-report" data-section="report">
            Corrected {outcome.report.framesCorrected} of {outcome.report.framesTotal} frames (
            {outcome.report.eyesCorrected} eyes).
            {Object.entries(outcome.report.skipped).map(([reason, count]) => (
              <span key={reason} className="gaze-skip">
                {' '}
                Left untouched — {reason}: {count}.
              </span>
            ))}
          </p>

          {outcome.report.framesCorrected === 0 && (
            <p className="gaze-nothing" data-section="nothing-corrected" role="status">
              The job finished, but NO frame was corrected — the output is effectively the source.
              Every frame was skipped by the safety gates above, so this is not a failure and not a
              correction either. Nothing here was altered.
            </p>
          )}

          {outcome.likeness && (
            <p className="gaze-audit" data-section="audit">
              Authorised by: {outcome.likeness.subject} · scope {outcome.likeness.scope} ·
              attestation source {outcome.likeness.source}.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

export default Gaze;
