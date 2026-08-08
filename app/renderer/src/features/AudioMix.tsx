// AudioMix.tsx — the audio MIXER panel (v1.5 audiomix-ui).
//
// Wires the previously-unreachable A/V mix engine
// (`sidecar/media_studio/features/audiomix.py`) to the UI. Both methods were
// registered (`audiomix.merge` / `audiomix.normalize`, features/audiomix.py:408-409,
// wired in handlers/composition.py:392-398) but had ZERO renderer callers, so a
// user could not lay a music bed under a speaker or hit a platform loudness
// target from the app at all.
//
// Two jobs, one panel:
//   audiomix.merge     {videoId, bgPath, bgGainDb?, duckThreshold?, duckRatio?,
//                       platform?} -> {jobId} -> job.done {path}
//       The bed is pre-attenuated, then `sidechaincompress` DUCKS it against the
//       clip's own audio (it dips when the speaker talks and swells in the gaps),
//       the two are summed, and the sum is EBU R128 `loudnorm`ed.
//   audiomix.normalize {videoId, platform?} -> {jobId} -> job.done {path}
//       The loudnorm alone — "make this export hit -14 LUFS" with no bed.
//
// The clip's VIDEO stays under stream copy: the output is a NEW mp4 under the
// exports `audiomix/` folder (the row `PathsPanel` already lists), and the source
// is never rewritten.
//
// LOUDNESS TARGETS: the panel sends `platform` (a NAME), never a hard-coded LUFS
// number, so the sidecar's `PLATFORM_LOUDNESS` map stays the single authority for
// the value applied — and it fails LOUD on an unknown name instead of silently
// exporting at the wrong loudness. The numbers mirrored below are for DISPLAY
// only and are gated against the real `.py` by AudioMix.conformance.test.ts.
//
// Consumes the FROZEN window.api bridge through the shared `./_api` helpers, the
// same pattern as the sibling long-job panels (Dub / Convert / Tracks).
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './panels.css';
import {
  DEFAULT_JOB_TIMEOUT_MS,
  JobAbortedError,
  extractJobId,
  getApi,
  pickField,
  waitForJobDone,
  type MediaStudioApi,
} from './_api';

// --- mirrored engine defaults (conformance-gated against audiomix.py) -------
/** Pre-attenuation applied to the bed before ducking (negative dB = quieter). */
export const DEFAULT_BG_GAIN_DB = -10;
/** sidechaincompress trigger level (0..1 linear) the speaker must exceed. */
export const DEFAULT_DUCK_THRESHOLD = 0.03;
/** sidechaincompress gain-reduction ratio applied while the speaker talks. */
export const DEFAULT_DUCK_RATIO = 8;

/** One row of the loudness picker: a sidecar `platform` name + what it means. */
export interface LoudnessTarget {
  /** The sidecar `platform` key — MUST exist in `PLATFORM_LOUDNESS`. */
  id: string;
  label: string;
  /** DISPLAY only; the sidecar resolves the applied value from `id`. */
  lufs: number;
}

/**
 * The pickable export loudness targets. The social platforms all normalise to
 * ~-14 LUFS; the broadcast standards keep their own (EBU R128 -23, ATSC A/85
 * -24). Sidecar aliases (`x`/`twitter`, `broadcast`/`ebu`) collapse to one row.
 */
export const LOUDNESS_TARGETS: LoudnessTarget[] = [
  { id: 'tiktok', label: 'TikTok', lufs: -14 },
  { id: 'reels', label: 'Instagram Reels', lufs: -14 },
  { id: 'shorts', label: 'YouTube Shorts', lufs: -14 },
  { id: 'youtube', label: 'YouTube', lufs: -14 },
  { id: 'instagram', label: 'Instagram (feed)', lufs: -14 },
  { id: 'facebook', label: 'Facebook', lufs: -14 },
  { id: 'x', label: 'X (Twitter)', lufs: -14 },
  { id: 'spotify', label: 'Spotify', lufs: -14 },
  { id: 'ebu', label: 'Broadcast (EBU R128)', lufs: -23 },
  { id: 'atsc', label: 'US broadcast (ATSC A/85)', lufs: -24 },
];

/**
 * The picker's starting choice. Every -14 row resolves to the SAME number the
 * sidecar already defaults to (`DEFAULT_LOUDNESS_TARGET = -14.0`), so this is a
 * labelling choice, not a behavioural one — short-form vertical is the app's
 * core job, so it names TikTok rather than leaving the target implicit.
 */
export const DEFAULT_TARGET_ID = 'tiktok';

// --- pure helpers (exported for tests) --------------------------------------

/** Resolve a platform id to its row; the first row backs an id off the list. */
export function targetFor(id: string): LoudnessTarget {
  return LOUDNESS_TARGETS.find((t) => t.id === id) ?? LOUDNESS_TARGETS[0];
}

/** `-14` -> `"-14 LUFS"` (integers render without a trailing `.0`). */
export function formatLufs(lufs: number): string {
  return `${lufs} LUFS`;
}

/** The `<option>` text: the human name plus the number that will be applied. */
export function targetOptionLabel(target: LoudnessTarget): string {
  return `${target.label} — ${formatLufs(target.lufs)}`;
}

/**
 * Parse a numeric field, falling back to the engine default on a blank or
 * non-numeric entry. A cleared `<input type="number">` reads as `''`, and
 * `Number('')` is `0` — sending that as `bgGainDb` would silently publish the bed
 * at FULL volume, so an empty field must mean "use the default", never zero.
 * A deliberate `"0"` is still honoured (0 is a value, not an absence).
 */
export function numOr(raw: string, fallback: number): number {
  const parsed = Number(raw);
  return raw.trim() !== '' && Number.isFinite(parsed) ? parsed : fallback;
}

/** Build the FROZEN `audiomix.merge` params from the picker state. */
export function buildMergeParams(args: {
  videoId: string;
  bgPath: string;
  bgGainDb: number;
  duckThreshold: number;
  duckRatio: number;
  platform: string;
}): Record<string, unknown> {
  return {
    videoId: args.videoId,
    bgPath: args.bgPath.trim(),
    bgGainDb: args.bgGainDb,
    duckThreshold: args.duckThreshold,
    duckRatio: args.duckRatio,
    platform: args.platform,
  };
}

/** Build the FROZEN `audiomix.normalize` params (loudnorm only, no bed). */
export function buildNormalizeParams(args: {
  videoId: string;
  platform: string;
}): Record<string, unknown> {
  return { videoId: args.videoId, platform: args.platform };
}

/** Which job produced the file currently shown in the result card. */
export type MixMode = 'merge' | 'normalize';

export interface AudioMixResult {
  mode: MixMode;
  path: string;
}

export interface AudioMixProps {
  videoId: string;
  /** Injectable bridge for tests; defaults to the preload-exposed api. */
  api?: MediaStudioApi;
}

export function AudioMix({ videoId, api }: AudioMixProps): React.ReactElement {
  const bridge = useMemo<MediaStudioApi>(() => api ?? getApi(), [api]);

  // mix controls (kept as STRINGS so a half-typed / cleared field is not coerced
  // to a silent 0 — `numOr` resolves them at submit time)
  const [bgPath, setBgPath] = useState<string>('');
  const [bgGain, setBgGain] = useState<string>(String(DEFAULT_BG_GAIN_DB));
  const [threshold, setThreshold] = useState<string>(String(DEFAULT_DUCK_THRESHOLD));
  const [ratio, setRatio] = useState<string>(String(DEFAULT_DUCK_RATIO));
  const [platform, setPlatform] = useState<string>(DEFAULT_TARGET_ID);

  // job state
  const [busy, setBusy] = useState<boolean>(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pct, setPct] = useState<number>(0);
  const [message, setMessage] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [result, setResult] = useState<AudioMixResult | null>(null);

  // A fresh controller is allocated per render but only the FIRST is kept
  // (React's `useRef` init caveat). An AbortController is a trivial object and
  // this panel re-renders only on user input; the nullable alternative would add
  // an unreachable null branch to the renderer's 100%-branch gate for no gain.
  const abortRef = useRef<AbortController>(new AbortController());

  const target = targetFor(platform);

  // Relay job.progress for the active job only.
  useEffect(() => {
    if (!jobId) return;
    const off = bridge.onProgress((ev) => {
      if (ev.jobId !== jobId) return;
      setPct(ev.pct);
      setMessage(ev.message);
    });
    return off;
  }, [bridge, jobId]);

  // Unmounting kills the panel that owns the wait; abort it so no timer and no
  // post-unmount settle outlive the component.
  useEffect(() => () => abortRef.current.abort(), []);

  const run = useCallback(
    async (mode: MixMode): Promise<void> => {
      setBusy(true);
      setError('');
      setResult(null);
      setPct(0);
      setMessage('Starting…');
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const method = mode === 'merge' ? 'audiomix.merge' : 'audiomix.normalize';
        const params =
          mode === 'merge'
            ? buildMergeParams({
                videoId,
                bgPath,
                bgGainDb: numOr(bgGain, DEFAULT_BG_GAIN_DB),
                duckThreshold: numOr(threshold, DEFAULT_DUCK_THRESHOLD),
                duckRatio: numOr(ratio, DEFAULT_DUCK_RATIO),
                platform,
              })
            : buildNormalizeParams({ videoId, platform });
        // §2 long job: the rpc resolves immediately with {jobId}; the terminal
        // {path} arrives later on job.done (see _api.ts waitForJobDone).
        const res = await bridge.rpc<{ jobId: string }>(method, params);
        const id = extractJobId(res) ?? null;
        setJobId(id);
        const path = id
          ? await waitForJobDone<string>(
              bridge,
              id,
              (r) => pickField<string>(r, 'path'),
              DEFAULT_JOB_TIMEOUT_MS,
              controller.signal,
            )
          : null;
        if (path) {
          setResult({ mode, path });
          setPct(100);
          setMessage('Done');
        }
      } catch (err) {
        // An abort is a CLEAN escape (the user cancelled, or the panel
        // unmounted), not a failure — leave `error` empty and just go idle.
        if (!(err instanceof JobAbortedError)) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        setBusy(false);
        setJobId(null);
      }
    },
    [bgGain, bgPath, bridge, platform, ratio, threshold, videoId],
  );

  const cancel = useCallback(
    async (id: string): Promise<void> => {
      setMessage('Cancelling…');
      try {
        await bridge.rpc('job.cancel', { jobId: id });
      } catch {
        // best-effort: the job may already have finished
      }
      // The sidecar emits NO job.done for a cancelled job, so the wait would
      // otherwise hang to the 35-minute ceiling — abort it and free the panel.
      abortRef.current.abort();
    },
    [bridge],
  );

  return (
    <section className="feature-panel audiomix-panel" aria-label="Audio mix">
      <h2>Audio mix &amp; loudness</h2>
      <p className="audiomix-intro">
        Lay a music bed or voiceover <strong>under</strong> the speaker — it ducks automatically
        whenever they talk and swells back in the gaps — then normalise the export to the loudness
        the platform expects. The video is stream-copied, so this writes a new file and never
        touches your source.
      </p>

      <div className="audiomix-controls">
        <label>
          Music bed / voiceover file{' '}
          <input
            data-input="bg-path"
            type="text"
            placeholder="C:\\path\\to\\bed.mp3"
            value={bgPath}
            onChange={(e) => setBgPath(e.target.value)}
            disabled={busy}
          />
        </label>

        <label>
          Bed volume (dB){' '}
          <input
            data-input="bg-gain"
            type="number"
            step="1"
            value={bgGain}
            onChange={(e) => setBgGain(e.target.value)}
            disabled={busy}
          />
        </label>

        <label>
          Loudness target{' '}
          <select
            data-picker="platform"
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
            disabled={busy}
          >
            {LOUDNESS_TARGETS.map((t) => (
              <option key={t.id} value={t.id}>
                {targetOptionLabel(t)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <p className="audiomix-target-note">
        Exports are normalised to <strong>{formatLufs(target.lufs)}</strong> integrated loudness
        ({target.label}).
      </p>

      <details className="audiomix-advanced">
        <summary>Advanced ducking</summary>
        <div className="audiomix-controls">
          <label>
            Duck trigger level (0–1){' '}
            <input
              data-input="duck-threshold"
              type="number"
              step="0.01"
              min="0"
              max="1"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              disabled={busy}
            />
          </label>
          <label>
            Duck strength (ratio){' '}
            <input
              data-input="duck-ratio"
              type="number"
              step="1"
              min="1"
              value={ratio}
              onChange={(e) => setRatio(e.target.value)}
              disabled={busy}
            />
          </label>
        </div>
        <p className="audiomix-advanced-hint">
          A LOWER trigger level dips the bed on quieter speech; a HIGHER ratio dips it further.
          Clear a field to fall back to the engine default.
        </p>
      </details>

      <div className="actions">
        <button
          type="button"
          data-action="mix"
          onClick={() => void run('merge')}
          disabled={busy || !videoId || !bgPath.trim()}
        >
          Mix bed under speaker
        </button>
        <button
          type="button"
          data-action="normalize"
          className="secondary"
          onClick={() => void run('normalize')}
          disabled={busy || !videoId}
        >
          Normalise loudness only
        </button>
        {busy && jobId !== null && (
          <button
            type="button"
            data-action="cancel"
            className="secondary"
            onClick={() => void cancel(jobId)}
          >
            Cancel
          </button>
        )}
      </div>

      {busy && (
        <div className="progress" aria-live="polite">
          <progress max={100} value={pct} />
          <span className="progress-pct">{Math.round(pct)}%</span>
          <span className="progress-message"> · {message}</span>
        </div>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {result && (
        <div className="audiomix-result" data-testid="audiomix-result">
          <h3>{result.mode === 'merge' ? 'Mixed' : 'Normalised'} file ready</h3>
          <p className="audiomix-result-path" title={result.path}>
            {result.path}
          </p>
        </div>
      )}
    </section>
  );
}

export default AudioMix;
