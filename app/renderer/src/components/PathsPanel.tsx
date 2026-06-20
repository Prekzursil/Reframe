// PathsPanel.tsx — show WHERE everything lives + change the data root + open a
// folder in the OS file explorer (UX/QoL WU-12).
//
// Two independent sources, both INJECTED so the component unit-tests with no
// preload bridge (mirrors SavePresetsControls' injected `savePresets` slice):
//   * `rpc.describe()` (sidecar `paths.describe`, WU-1, read-only) -> the resolved
//     on-disk layout. Each DIRECTORY entry renders its path as selectable text +
//     a real <button> ("Open <label> folder") that reveals it via the bridge's
//     `openInFolder` (the existing `shell.showItemInFolder` channel — no new
//     channel). FILE entries (settings/library) are text-only (not directories).
//   * `bridge` — the MAIN-process data-root flow (`dataFolder.get/pick/set`, NOT
//     sidecar RPCs) + `openInFolder`. Each capability is optional: a missing piece
//     degrades that control to an "Unavailable" state rather than crashing the
//     panel (same fail-soft contract ShortMaker's data-root section uses).
//
// a11y: every row Open control is a real <button> with a per-row accessible name
// ("Open <label> folder"); the path string is inert selectable text, never an
// interactive element. Color is never the sole signal.
import React, { useCallback, useEffect, useState } from 'react';
import './pathsPanel.css';

/** The resolved on-disk data layout (`paths.describe`, WU-1). */
export interface PathsDescribe {
  dataDir: string;
  projectsDir: string;
  exportsDir: string;
  settingsPath: string;
  libraryPath: string;
  subDirs?: Record<string, string>;
}

/** The thin `paths.*` slice this component needs (injectable for tests). */
export interface PathsRpc {
  describe(): Promise<PathsDescribe>;
}

/**
 * The MAIN-process bridge slice (NOT sidecar RPCs). Every member is optional so a
 * missing preload capability degrades the matching control, never the panel.
 */
export interface PathsBridge {
  /** Reveal a directory in the OS file explorer (true on success). */
  openInFolder?(path: string): Promise<boolean>;
  /** The data root in use this session. */
  getDataFolder?(): Promise<string>;
  /** Native open-DIRECTORY picker (null when cancelled). */
  pickDataFolder?(): Promise<string | null>;
  /** Persist the chosen data root (a restart applies it). */
  setDataFolder?(path: string): Promise<{ ok: boolean }>;
}

export interface PathsPanelProps {
  /** The injected `paths.*` client slice (`client.paths` in the app). */
  rpc: PathsRpc;
  /** The injected MAIN-process bridge (`window.api` in the app). */
  bridge: PathsBridge;
}

/** A single layout row: a human label, its path, and whether it is a directory. */
interface PathRow {
  key: string;
  label: string;
  path: string;
  isDir: boolean;
}

const ROOT_UNKNOWN = 'Unknown';

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Build the ordered display rows from a `paths.describe` payload. */
function buildRows(layout: PathsDescribe): PathRow[] {
  const dirs: PathRow[] = [
    { key: 'dataDir', label: 'Data', path: layout.dataDir, isDir: true },
    { key: 'projectsDir', label: 'Projects', path: layout.projectsDir, isDir: true },
    { key: 'exportsDir', label: 'Exports', path: layout.exportsDir, isDir: true },
  ];
  const files: PathRow[] = [
    { key: 'settingsPath', label: 'Settings file', path: layout.settingsPath, isDir: false },
    { key: 'libraryPath', label: 'Library file', path: layout.libraryPath, isDir: false },
  ];
  const subDirs = Object.entries(layout.subDirs ?? {}).map(([name, path]) => ({
    key: `subDir:${name}`,
    label: name,
    path,
    isDir: true,
  }));
  return [...dirs, ...files, ...subDirs];
}

export function PathsPanel({ rpc, bridge }: PathsPanelProps): React.ReactElement {
  const [rows, setRows] = useState<PathRow[] | null>(null);
  const [root, setRoot] = useState<string>(ROOT_UNKNOWN);
  const [pendingRestart, setPendingRestart] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<boolean>(false);

  // Fetch the layout (read-only; independent of the bridge).
  useEffect(() => {
    let alive = true;
    rpc
      .describe()
      .then((layout) => {
        if (alive) setRows(buildRows(layout));
      })
      .catch((err) => {
        if (alive) {
          setError(errText(err));
          setRows([]);
        }
      });
    return () => {
      alive = false;
    };
  }, [rpc]);

  // Hydrate the current data root from the bridge (fail-soft -> "Unknown").
  const getRoot = bridge.getDataFolder;
  useEffect(() => {
    if (!getRoot) return undefined;
    let alive = true;
    getRoot()
      .then((folder) => {
        if (alive) setRoot(folder || ROOT_UNKNOWN);
      })
      .catch(() => {
        // Bridge present but failed -> leave the placeholder, never block.
      });
    return () => {
      alive = false;
    };
  }, [getRoot]);

  // Capture the open fn once (it is passed to handleOpen only from rows that
  // render it, so no in-handler null guard is needed).
  const openInFolder = bridge.openInFolder;
  const handleOpen = useCallback(async (open: (path: string) => Promise<boolean>, path: string) => {
    try {
      await open(path);
    } catch (err) {
      setError(errText(err));
    }
  }, []);

  // Capture the pick/set fns once; handleChangeRoot is only wired to the button
  // that renders when both exist, so it receives them as guaranteed args.
  const pickDataFolder = bridge.pickDataFolder;
  const setDataFolder = bridge.setDataFolder;
  const handleChangeRoot = useCallback(
    async (
      pick: () => Promise<string | null>,
      persist: (path: string) => Promise<{ ok: boolean }>,
    ) => {
      setBusy(true);
      try {
        const chosen = await pick();
        if (!chosen) return; // cancelled
        const res = await persist(chosen);
        if (!res.ok) {
          setError('Could not save the data folder (the install directory may be read-only).');
          return;
        }
        setRoot(chosen);
        setPendingRestart(true);
        setError(null);
      } catch (err) {
        setError(errText(err));
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  return (
    <section className="paths-panel" data-section="paths" aria-label="Data locations">
      <h3>Data locations</h3>

      {error ? (
        <div className="paths-panel__error" role="alert">
          {error}
        </div>
      ) : null}

      <div className="paths-panel__root">
        <span className="paths-panel__root-label">Data folder</span>
        <span className="paths-panel__root-value">{root}</span>
        {pickDataFolder && setDataFolder ? (
          <button
            type="button"
            className="paths-panel__change-root"
            disabled={busy}
            onClick={() => void handleChangeRoot(pickDataFolder, setDataFolder)}
          >
            Change data folder
          </button>
        ) : (
          <span className="paths-panel__root-unavailable">
            Changing the data folder is unavailable in this build.
          </span>
        )}
        {pendingRestart ? (
          <span className="paths-panel__restart-hint">Restart to apply the new data folder.</span>
        ) : null}
      </div>

      {rows === null ? (
        <div className="paths-panel__loading">Loading data locations…</div>
      ) : (
        <ul className="paths-panel__list">
          {rows.map((row) => (
            <li key={row.key} className="paths-panel__row" data-path-key={row.key}>
              <span className="paths-panel__row-label">{row.label}</span>
              <span className="paths-panel__path">{row.path}</span>
              {row.isDir && openInFolder ? (
                <button
                  type="button"
                  className="paths-panel__open"
                  aria-label={`Open ${row.label} folder`}
                  onClick={() => void handleOpen(openInFolder, row.path)}
                >
                  Open folder
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default PathsPanel;
