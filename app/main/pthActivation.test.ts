// Tests for the embeddable ._pth activation helpers (WIRING-T5 §2 packaging fix).
//
// Root cause these guard against: a rebuilt/relocated portable ships a PRISTINE
// `python3XX._pth` while the SHARED appData env already exists, so the sidecar
// spawns with no path to its deps and dies ("No module named media_studio").
// ensurePthActivated() (main.ts) rewrites the ._pth each packaged launch using
// renderPthBody — which MUST stay byte-compatible with bootstrap.py render_pth.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { pthZipName, renderPthBody } from './pthActivation';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..');
const BOOTSTRAP_PY = resolve(REPO_ROOT, 'sidecar', 'runtime_setup', 'bootstrap.py');

describe('pthZipName', () => {
  it('maps the embeddable ._pth filename to its stdlib zip', () => {
    expect(pthZipName('python312._pth')).toBe('python312.zip');
    expect(pthZipName('python311._pth')).toBe('python311.zip');
  });

  it('is a no-op-friendly fallback for a name without the suffix', () => {
    expect(pthZipName('python313')).toBe('python313.zip');
  });
});

describe('renderPthBody', () => {
  const ENV = 'C:\\Users\\me\\AppData\\Roaming\\media-studio\\envs\\sidecar';
  const SIDECAR = 'C:\\app\\resources\\sidecar';

  it('emits the five activation lines in order, terminated by a newline', () => {
    const body = renderPthBody('python312.zip', ENV, SIDECAR);
    expect(body).toBe(`python312.zip\n.\n${ENV}\n${SIDECAR}\nimport site\n`);
    expect(body.split('\n')).toEqual([
      'python312.zip',
      '.',
      ENV,
      SIDECAR,
      'import site',
      '', // trailing newline
    ]);
  });

  it('uncomments import site (the embeddable default comments it out)', () => {
    const body = renderPthBody('python312.zip', ENV, SIDECAR);
    expect(body).toContain('\nimport site\n');
    expect(body).not.toContain('#import site');
  });

  it('puts the env dir BEFORE the sidecar source so deps win over source', () => {
    const body = renderPthBody('python312.zip', ENV, SIDECAR);
    expect(body.indexOf(ENV)).toBeLessThan(body.indexOf(SIDECAR));
  });
});

describe('drift guard — renderPthBody mirrors bootstrap.py render_pth', () => {
  it('python render_pth builds [zip, ".", env, sidecar, "import site"] in that order', () => {
    const py = readFileSync(BOOTSTRAP_PY, 'utf8');
    // render_pth: lines = [zip_name, ".", str(env_dir)]; (+ sidecar) ; "import site"
    expect(py).toContain('lines = [zip_name, ".", str(env_dir)]');
    expect(py).toContain('lines.append(str(sidecar_src))');
    expect(py).toContain('lines.append("import site")');
    expect(py).toContain('"\\n".join(lines) + "\\n"');
  });
});
