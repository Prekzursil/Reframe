// NLE export panel (captions-export).
//
// Exports a video's approved short-maker clips as an editable NLE timeline —
// a CMX3600 `.edl` or a `.csv` — for Premiere / DaVinci Resolve. The user picks
// the format and the frame rate (24/25/30/60); the sidecar reads the project's
// persisted approved clips and writes the timeline file under the exports dir.
//
// Calls `nle.export({videoId, format, fps})` -> {path, clipCount} (direct-return,
// no job). Consumes the canonical typed client (lib/rpc.ts).
//
// The two picks round-trip through the persisted `exportDefaults` slice
// ({subtitleFormat, nleFormat, nleFps}) so they survive leaving the tab — both
// mount sites are conditional renders (views/Deliver.tsx, views/Workspace.tsx),
// so the panel genuinely unmounts and un-persisted state is lost every visit.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import './panels.css';
import { client, hasApi, type NleFormat, type NleFps } from '../lib/rpc';

export interface NleExportProps {
  videoId: string;
}

const FORMATS: Array<{ value: NleFormat; label: string }> = [
  { value: 'edl', label: 'CMX3600 EDL (.edl)' },
  { value: 'csv', label: 'Spreadsheet (.csv)' },
];

const FPS_CHOICES: NleFps[] = [24, 25, 30, 60];

const DEFAULT_FORMAT: NleFormat = 'edl';
const DEFAULT_FPS: NleFps = 30;

/**
 * The persisted `exportDefaults` slice as it arrives on the wire: every field is
 * `unknown` on purpose. `ExportDefaults.nleFormat` is declared a bare `string`
 * (lib/rpc/schemas.ts) and the sidecar documents `fcpxml` as legal
 * (settings_store.py exportDefaults default), so a stored value may name a
 * format this panel does not offer — an unmatched `<select>` value renders blank.
 */
interface RawExportDefaults {
  readonly nleFormat?: unknown;
  readonly nleFps?: unknown;
}

/**
 * Pull the `exportDefaults` sub-object out of a `settings.get()` payload.
 *
 * Object-only — `null` is deliberately allowed through because it is harmless
 * (an optional-chain read short-circuits and spreading it yields `{}`), whereas a
 * corrupt SCALAR must not reach the write path: spreading a string there would
 * persist index keys ({0:'c',1:'o',…}) into the slice.
 */
function rawExportDefaults(
  settings: Record<string, unknown>,
): RawExportDefaults | null | undefined {
  const slice = settings.exportDefaults;
  return typeof slice === 'object' ? (slice as RawExportDefaults | null) : undefined;
}

/** Narrow a persisted `nleFormat` to a format this panel offers, else the default. */
function narrowFormat(raw: unknown): NleFormat {
  return FORMATS.find((f) => f.value === raw)?.value ?? DEFAULT_FORMAT;
}

/** Narrow a persisted `nleFps` to a frame rate this panel offers, else the default. */
function narrowFps(raw: unknown): NleFps {
  return FPS_CHOICES.find((f) => f === raw) ?? DEFAULT_FPS;
}

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function NleExport({ videoId }: NleExportProps): React.ReactElement {
  const [format, setFormat] = useState<NleFormat>(DEFAULT_FORMAT);
  const [fps, setFps] = useState<NleFps>(DEFAULT_FPS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [lastPath, setLastPath] = useState('');
  const [clipCount, setClipCount] = useState<number | null>(null);
  // Set as soon as the user touches either select: a pick always beats a
  // settings read that resolves after it.
  const picked = useRef(false);

  // Seed the two selects from the persisted `exportDefaults`. `hasApi()` is
  // checked FIRST and returns before `client` is touched: `client.settings.get`
  // -> `rpc()` -> `bridge()` THROWS SYNCHRONOUSLY without a preload
  // (lib/rpc/client.ts), so no promise would exist for `.catch()` to attach to
  // and the throw would escape this effect at commit — turning the graceful
  // no-bridge degrade below into a mount-time crash. Best-effort throughout: an
  // absent slice, an unreadable store, or an unrecognised stored value all keep
  // the built-in edl + 30 fps.
  useEffect(() => {
    if (!hasApi()) return;
    let cancelled = false;
    void client.settings
      .get()
      .then((settings) => {
        // `cancelled` covers unmount-during-fetch (both mount sites are
        // conditional renders); `picked` covers a late resolve after a pick.
        if (cancelled || picked.current) return;
        const slice = rawExportDefaults(settings);
        setFormat(narrowFormat(slice?.nleFormat));
        setFps(narrowFps(slice?.nleFps));
      })
      .catch(() => {
        // An unreadable settings store keeps the built-in defaults.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Write side. RE-READS immediately before writing: the sidecar `settings.set`
  // is a SHALLOW top-level merge, so it REPLACES the whole `exportDefaults`
  // object — writing a mount-time snapshot would silently revert a
  // `subtitleFormat` another surface persisted meanwhile. Best-effort: neither
  // the read nor the write may ever surface as an export error.
  const persistDefaults = useCallback(async (): Promise<void> => {
    try {
      const slice = rawExportDefaults(await client.settings.get());
      await client.settings.set({
        exportDefaults: { ...slice, nleFormat: format, nleFps: fps },
      });
    } catch {
      // The export itself succeeded; a failed preference write is not an export
      // failure and must never reach the error banner.
    }
  }, [format, fps]);

  const runExport = useCallback(async () => {
    if (!hasApi()) {
      // USER-FACING COPY: product noun, not the internal process name. This
      // branch is unreachable in a working packaged install (the preload always
      // installs `window.api`), so it is fixed for consistency, not for a
      // reported symptom.
      setError('The engine is not available.');
      return;
    }
    setBusy(true);
    setError('');
    // Drop the previous outcome up front: now that the saved path lives inside
    // the polite region, a later failure would otherwise leave a stale success
    // path being announced right beside the error alert.
    setLastPath('');
    setClipCount(null);
    setStatus(`Exporting ${format.toUpperCase()} at ${fps} fps…`);
    try {
      const res = await client.nle.export(videoId, { format, fps });
      setLastPath(res.path);
      setClipCount(res.clipCount);
      setStatus(
        res.clipCount > 0
          ? `Exported ${res.clipCount} clip${res.clipCount === 1 ? '' : 's'}`
          : 'Exported an empty timeline (no approved clips yet)',
      );
      await persistDefaults();
    } catch (err) {
      setError(errText(err));
      setStatus('');
    } finally {
      setBusy(false);
    }
  }, [videoId, format, fps, persistDefaults]);

  // The "N clip(s) " prefix for the saved-path line. clipCount is always set
  // alongside lastPath by runExport, so the null arm is defensive only.
  const savedClipPrefix =
    /* v8 ignore next */
    clipCount !== null ? `${clipCount} clip${clipCount === 1 ? '' : 's'} ` : '';

  return (
    <section className="feature-panel nle-panel" aria-label="NLE timeline export">
      <h2>Editing timeline (EDL / CSV)</h2>
      <p className="nle-intro">
        Export your approved clips as an editable timeline for Premiere or DaVinci Resolve. The EDL
        relinks to your original footage; the CSV is a per-clip spreadsheet.
      </p>

      <div className="field nle-format-row">
        <label htmlFor="nle-format">Format</label>
        <select
          id="nle-format"
          value={format}
          disabled={busy}
          onChange={(e) => {
            picked.current = true;
            setFormat(e.target.value as NleFormat);
          }}
        >
          {FORMATS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </select>
      </div>

      <div className="field nle-fps-row">
        <label htmlFor="nle-fps">Frame rate</label>
        <select
          id="nle-fps"
          value={fps}
          disabled={busy}
          onChange={(e) => {
            picked.current = true;
            setFps(Number(e.target.value) as NleFps);
          }}
        >
          {FPS_CHOICES.map((f) => (
            <option key={f} value={f}>
              {f} fps
            </option>
          ))}
        </select>
      </div>

      <div className="actions">
        <button type="button" onClick={runExport} disabled={busy || !videoId}>
          {busy ? 'Exporting…' : 'Export timeline'}
        </button>
      </div>

      {/*
        Always mounted, even while empty: a live region inserted together with
        its text is not reliably announced (components/ToastHost.tsx). Both class
        names are load-bearing — the unit tests and the e2e locator
        `.export-path code` (app/e2e/preview.spec.ts) select them. No CSS is
        needed: `.feature-panel .status` / `.feature-panel .export-path` are
        DESCENDANT selectors (components/shell.css) and `.feature-panel` is plain
        block flow with no `gap`, so an empty wrapper adds nothing.
      */}
      <div className="nle-live" role="status" aria-live="polite">
        {status && !error && <p className="status">{status}</p>}
        {lastPath && (
          <p className="export-path">
            Saved {savedClipPrefix}to <code>{lastPath}</code>
          </p>
        )}
      </div>
      {/* The failure branch stays OUTSIDE: `role="alert"` is assertive, and
          nesting it here would announce one failure twice. */}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

export default NleExport;
