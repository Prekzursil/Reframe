// NLE export panel (captions-export).
//
// Exports a video's approved short-maker clips as an editable NLE timeline —
// a CMX3600 `.edl` or a `.csv` — for Premiere / DaVinci Resolve. The user picks
// the format and the frame rate (24/25/30/60); the sidecar reads the project's
// persisted approved clips and writes the timeline file under the exports dir.
//
// Calls `nle.export({videoId, format, fps})` -> {path, clipCount} (direct-return,
// no job). Consumes the canonical typed client (lib/rpc.ts).
import React, { useCallback, useState } from 'react';
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

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function NleExport({ videoId }: NleExportProps): React.ReactElement {
  const [format, setFormat] = useState<NleFormat>('edl');
  const [fps, setFps] = useState<NleFps>(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [lastPath, setLastPath] = useState('');
  const [clipCount, setClipCount] = useState<number | null>(null);

  const runExport = useCallback(async () => {
    if (!hasApi()) {
      setError('The sidecar bridge is not available.');
      return;
    }
    setBusy(true);
    setError('');
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
    } catch (err) {
      setError(errText(err));
      setStatus('');
    } finally {
      setBusy(false);
    }
  }, [videoId, format, fps]);

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
          onChange={(e) => setFormat(e.target.value as NleFormat)}
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
          onChange={(e) => setFps(Number(e.target.value) as NleFps)}
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

      {status && !error && <p className="status">{status}</p>}
      {lastPath && (
        <p className="export-path">
          Saved {clipCount !== null ? `${clipCount} clip${clipCount === 1 ? '' : 's'} ` : ''}to{' '}
          <code>{lastPath}</code>
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

export default NleExport;
