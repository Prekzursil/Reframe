// pthActivation.ts — pure helpers for re-activating the embeddable CPython
// `python3XX._pth` (WIRING-T5 §2 packaging hardening).
//
// WHY this exists: the embeddable interpreter runs ISOLATED — it ignores
// PYTHONPATH and does not add the cwd — so the ONLY thing that puts the
// first-run env (%APPDATA%/media-studio/envs/sidecar) + the bundled sidecar
// source on `sys.path` is `resources/python/python3XX._pth`. That file is
// PER-COPY (ships in each build), while the env-success sentinel is SHARED in
// appData. A rebuilt/relocated portable therefore has a PRISTINE `._pth` but a
// populated appData env → the sidecar can't import anything ("No module named
// media_studio"). main.ts (ensurePthActivated) rewrites the `._pth` for the
// running copy each launch; these pure parts render the body it writes.
//
// The IO orchestration lives in main.ts so this module stays electron-free and
// unit-testable (pthActivation.test.ts). KEEP render IN SYNC with
// sidecar/runtime_setup/bootstrap.py `render_pth` — the drift-guard test asserts
// the two formats match.

/** Derive the stdlib zip name from the `._pth` filename (python312._pth -> python312.zip). */
export function pthZipName(pthFileName: string): string {
  const base = pthFileName.endsWith('._pth') ? pthFileName.slice(0, -'._pth'.length) : pthFileName;
  return `${base}.zip`;
}

/**
 * The full embeddable `._pth` activation body (pure).
 *
 * MUST mirror `render_pth` in sidecar/runtime_setup/bootstrap.py:
 *   <stdlib zip>, `.` (the embed dir), <env dir>, <sidecar source>, `import site`
 * Order matters, and `import site` MUST be present/uncommented — the embeddable
 * default comments it out, which breaks the env's `.pth` processing.
 */
export function renderPthBody(zipName: string, envDir: string, sidecarDir: string): string {
  return `${zipName}\n.\n${envDir}\n${sidecarDir}\nimport site\n`;
}
