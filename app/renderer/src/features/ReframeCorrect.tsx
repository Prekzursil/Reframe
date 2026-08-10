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
//
// CORRECTION 2026-08-10. The first version of this file said the corrections
// cannot be applied because "the sidecar registers no reframe.render method …
// reframe.render (or an override-persist method) has to be built sidecar-side
// first". That named the WRONG BLOCKER and it is retracted here. The literal
// half is still true — the registered reframe surface really is exactly four
// methods (`sidecar/tests/test_handlers_rpc_surface.py:118-121`):
//   reframe.applyOverrides · reframe.eval · reframe.shotPlan · reframe.shotPlanFor
// — but the re-render path was never supposed to live in that namespace. It is
// BUILT, and it lives in the export pipeline:
//   * `MultiSpeakerReframeEngine.rerender_with_overrides` replays corrections
//     onto the persisted plan without re-running the ML analysis;
//   * `shortmaker.export` accepts `reframeOverrides: {clipPath: [ShotOverride]}`
//     and threads each clip's entry into its own reframe stage
//     (`shortmaker.py:257,1344-1355,1450-1455`), failing LOUD when a correction
//     matched no exported clip (`shortmaker.py:1358-1367`).
//   * `docs/plans/v1.5/SCOPE.md:47-74` records both prerequisites as BUILT and
//     names the remaining work as the RENDERER surface — which is this file.
// Pointing the next reader at a sidecar method that does not need building is
// worse than naming no blocker, because it hides the wiring that does.
//
// THE THREE RENDERER GAPS, precisely — one closed here, two open:
//   1. CLOSED. `ReframeOverridePanel.onRerender` handed back shot INDICES only,
//      so the `ShotOverride` objects never left the panel and a host had nothing
//      to send. The callback now hands out the corrections too.
//   2. OPEN. `client.shortmaker.export` (`lib/rpc/client.ts:296-309`) exposes no
//      `reframeOverrides` option, so no renderer call can carry the map yet.
//   3. OPEN, and the reason the loop cannot be closed from THIS tab. A re-export
//      needs the CANDIDATE that produced the clip: `shortmaker.export` resolves
//      candidates by id out of the select cache (`shortmaker.py:1525-1549`), and
//      a produced clip carries no candidate id, no `rank` and no source
//      `start`/`end` — `shorts.META_FIELDS` is {videoId, sourceTitle, template,
//      viralityPct, durationSec, hook, createdAt} (`shorts.py:64-72`) and
//      `shorts.reexport` returns a hook/template/virality/duration SKELETON
//      (`shorts.py:457-477`).
//      On top of that `_assert_overrides_matched` keys the map on the NEW
//      export's final path, so the re-export must reproduce the same
//      rank-ordered stem. The correction loop therefore belongs on the
//      Short-maker export surface, which still holds the live candidates.
// Until (2) and (3) land this container does NOT offer to re-export: doing so
// would re-cut from scratch and THROW AWAY the corrections the user just made.
// It says so, and it hands the corrections back as the exact
// `reframeOverrides` payload so the work is not silently discarded.
//
// `reframe.shotPlan` is unusable from the renderer — it needs a `trace` no
// renderer code can obtain. `reframe.shotPlanFor {clip}` is the only door, and
// it reads the `<clip>.reframe.json` decision sidecar the multi-speaker engine
// drops beside a rendered clip
// (`sidecar/media_studio/features/reframe_override.py:35-44,644-660`).
// A clip whose engine wrote no sidecar yields `{plan: null}` — an honest empty
// state, never a correction panel over invented data.

import React, { useCallback, useEffect, useState } from 'react';

import ReframeOverridePanel from '../panels/ReframeOverridePanel';
import type { ShotOverride, ShotPlan } from '../lib/reframeOverride';
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
  /**
   * The corrections the user made, serialised as the EXACT `reframeOverrides`
   * payload `shortmaker.export` takes (`shortmaker.py:1344-1355`). This build
   * cannot send it (gaps 2 and 3 in the header), so it is shown instead of
   * dropped — the user's work leaves the session in the shape that will apply it.
   */
  const [payload, setPayload] = useState('');

  const loadPlan = useCallback(async (clip: string): Promise<void> => {
    setSelected(clip);
    setError('');
    setNote('');
    setPayload('');
    // `setPlan(null)` is LOAD-BEARING, not tidying. ReframeOverridePanel seeds
    // its override map in `useState` ONCE (`panels/ReframeOverridePanel.tsx:96`)
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
   * The panel hands us the affected shot indices AND the corrections. This build
   * cannot send them (header gaps 2 and 3), so we report what changed, say
   * plainly that nothing was applied, and keep the corrections rather than
   * discard them. Shot numbers are 1-based to match the panel's "Shot N"
   * headings.
   *
   * We deliberately do NOT suggest re-exporting the short. That path is
   * `shortmaker.export` WITHOUT `reframeOverrides`: it re-cuts from scratch and
   * throws these corrections away, so offering it as a remedy would cost the
   * user the work they just did.
   */
  const onRerender = useCallback(
    (shotIndices: readonly number[], overrides: readonly ShotOverride[]): void => {
      const shots = shotIndices.map((i) => `shot ${i + 1}`).join(', ');
      setNote(
        `Your corrections changed ${shots}. Reframe cannot apply them yet, so nothing has been ` +
          're-encoded and nothing has been written onto the clip. The engine that replays ' +
          'corrections is built — shortmaker.export takes a reframeOverrides map — but no ' +
          'renderer call carries that map yet, and a produced clip cannot re-drive its own ' +
          'export because it does not record the candidate it came from. Re-exporting the short ' +
          'is NOT a workaround: it re-cuts from scratch and discards these corrections. They are ' +
          'kept below, in the exact shape the export takes.',
      );
      setPayload(JSON.stringify({ [selected]: overrides }, null, 2));
    },
    [selected],
  );

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
            <strong>not re-encode</strong> them and does not save them onto the clip. The engine
            that replays corrections already exists — <code>shortmaker.export</code> takes a{' '}
            <code>reframeOverrides</code> map — but this screen cannot reach it yet, so treat
            &ldquo;Re-render&rdquo; as &ldquo;show me what I changed and give me back my
            corrections&rdquo;. <strong>Re-exporting the short is not a workaround:</strong> it
            re-cuts from scratch and throws your corrections away.
          </p>
          <ReframeOverridePanel plan={plan} onRerender={onRerender} />
        </>
      )}

      {note !== '' && (
        <p data-section="rerender-note" role="status">
          {note}
        </p>
      )}

      {payload !== '' && (
        <label className="reframe-correct__payload" data-section="payload">
          Your corrections, unapplied — the <code>reframeOverrides</code> entry for this clip
          <textarea readOnly rows={8} data-action="payload" value={payload} />
        </label>
      )}
    </section>
  );
}

export default ReframeCorrect;
