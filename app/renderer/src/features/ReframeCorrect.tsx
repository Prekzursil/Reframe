// ReframeCorrect.tsx — the Workspace mount for `panels/ReframeOverridePanel`
// (W17).
//
// WHY THIS FILE EXISTS. The correction panel was built, styled and covered to
// 100% — and imported by NOTHING except its own test
// (`panels/ReframeOverridePanel.tsx:1-14,73`;
// `panels/ReframeOverridePanel.test.tsx:13,65`). So a wrong auto-crop had no
// correction path anywhere in the shipped UI, and the three `reframe.*` client
// wrappers it needs (`lib/rpc/client.ts`) had no caller either. This container
// is the missing surface: it finds the clips that CAN be corrected, loads a real
// plan for one, and mounts the panel over it.
//
// WHAT IT CAN AND CANNOT DO — measured, and stated in the UI, not just here.
// The sidecar's registered reframe surface is exactly four methods
// (`sidecar/tests/test_handlers_rpc_surface.py:118-121`):
//   reframe.applyOverrides · reframe.eval · reframe.shotPlan · reframe.shotPlanFor
// There is NO `reframe.render`, NO `reframe.analyze`, and NO method that
// persists overrides back onto a clip's decision sidecar. Consequences:
//   * `reframe.shotPlan` is unusable from the renderer — it needs a `trace` no
//     renderer code can obtain. `reframe.shotPlanFor {clip}` is the only door,
//     and it reads the `<clip>.reframe.json` decision sidecar the multi-speaker
//     engine drops beside a rendered clip
//     (`sidecar/media_studio/features/reframe_override.py:35-44,644-660`).
//   * the panel's own "Re-render N shots" button therefore CANNOT re-encode.
//     Rather than hide the control (it is the panel's only way to report which
//     shots changed) this container states the limit INLINE, above the panel,
//     and reports the affected shots without claiming a render happened.
//     Pretending otherwise would be the exact failure mode this repo keeps
//     shipping: a true-looking sentence over code that cannot honour it.
// A clip whose engine wrote no sidecar yields `{plan: null}` — an honest empty
// state, never a correction panel over invented data.

import React, { useCallback, useEffect, useState } from 'react';

import ReframeOverridePanel from '../panels/ReframeOverridePanel';
import type { ShotPlan } from '../lib/reframeOverride';
import { client } from '../lib/rpc';
import type { ShortInfo } from '../lib/rpc';
import './panels.css';

const ERR = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** The trailing path segment, for a readable clip-picker label. */
function baseName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1];
}

export interface ReframeCorrectProps {
  videoId: string;
}

export function ReframeCorrect({ videoId }: ReframeCorrectProps): React.ReactElement {
  const [shorts, setShorts] = useState<ShortInfo[]>([]);
  const [selected, setSelected] = useState('');
  const [plan, setPlan] = useState<ShotPlan | null>(null);
  /** True ONLY after a successful probe that came back with `plan: null`. */
  const [planless, setPlanless] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [note, setNote] = useState('');

  const loadPlan = useCallback(async (clip: string): Promise<void> => {
    setSelected(clip);
    setError('');
    setNote('');
    // `setPlan(null)` is LOAD-BEARING, not tidying. ReframeOverridePanel seeds
    // its override map in `useState` ONCE (`panels/ReframeOverridePanel.tsx:77`)
    // and a new `plan` prop does NOT reset it — so if the panel stayed mounted
    // across a clip switch, edits made on the previous clip would be replayed by
    // shot INDEX onto the new one, which would open already "edited" against
    // decisions that were never its own. Clearing the plan first unmounts the
    // panel, so it remounts clean. Deleting this line turns
    // "does not carry one clip edits over to the next clip" red — verified by
    // mutation, not assumed.
    setPlan(null);
    setPlanless(false);
    try {
      const res = await client.reframe.shotPlanFor(clip);
      setPlan(res.plan);
      setPlanless(res.plan === null);
    } catch (err) {
      setError(ERR(err));
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    void (async () => {
      try {
        const res = await client.shorts.list(videoId);
        const list = res.shorts ?? [];
        setShorts(list);
        if (list.length > 0) await loadPlan(list[0].path);
      } catch (err) {
        setError(ERR(err));
      } finally {
        setLoading(false);
      }
    })();
  }, [videoId, loadPlan]);

  /**
   * The panel hands us EXACTLY the shot indices its edits changed. This build
   * has nowhere to send them, so we report them and say so. Shot numbers are
   * 1-based here to match the "Shot N" headings the panel renders.
   */
  const onRerender = useCallback((shotIndices: readonly number[]): void => {
    const shots = shotIndices.map((i) => `shot ${i + 1}`).join(', ');
    setNote(
      `Your corrections changed ${shots}. This build cannot re-render them: the sidecar ` +
        'registers no reframe.render method, so nothing has been re-encoded and nothing has ' +
        'been saved back to the clip. Re-export the short to pick up a different framing.',
    );
  }, []);

  return (
    <section className="feature-panel reframe-correct" aria-label="Fix the framing">
      <h2>Fix the framing</h2>
      <p className="assets-intro">
        Every clip the multi-speaker reframe engine renders keeps its per-shot decisions beside it.
        Open one here to see who the engine followed in each shot and how it cropped, and to correct
        the shots it got wrong.
      </p>

      {loading && <p data-section="loading">Looking for reframed clips…</p>}

      {error !== '' && (
        <p className="error" role="alert" data-section="error">
          {error}
        </p>
      )}

      {shorts.length > 0 && (
        <label className="reframe-correct__pick">
          Clip{' '}
          <select
            data-action="clip"
            value={selected}
            onChange={(e) => void loadPlan(e.target.value)}
          >
            {shorts.map((s) => (
              <option key={s.path} value={s.path}>
                {baseName(s.path)}
              </option>
            ))}
          </select>
        </label>
      )}

      {!loading && shorts.length === 0 && (
        <p data-section="no-clips">
          This video has no reframed clips yet. Make a short first — the engine writes its per-shot
          decisions next to each clip it renders, and those are what this panel corrects.
        </p>
      )}

      {planless && (
        <p data-section="no-plan">
          This clip carries no per-shot reframe decisions, so there is nothing to correct. That
          happens when it was rendered by an engine that writes no decision sidecar.
        </p>
      )}

      {plan !== null && (
        <>
          <p className="reframe-correct__limits" data-section="limits">
            <strong>What this panel can do here:</strong> it shows and edits the stored decisions
            and works out exactly which shots your edits change. It does{' '}
            <strong>not re-encode</strong> them — this build registers no{' '}
            <code>reframe.render</code> method, and no method that saves corrections back onto the
            clip. Treat &ldquo;Re-render&rdquo; as &ldquo;tell me which shots I changed&rdquo;.
          </p>
          <ReframeOverridePanel plan={plan} onRerender={onRerender} />
        </>
      )}

      {note !== '' && (
        <p data-section="rerender-note" role="status">
          {note}
        </p>
      )}
    </section>
  );
}

export default ReframeCorrect;
