// SocialPublishPanel.tsx — C14 direct publish / scheduling (Deliver → "Publish").
//
// THE PANEL'S JOB IS TO NOT LIE. Two of the four platforms C14 named cannot publish
// to a personal account at all, and a desktop app cannot publish while the machine
// is off. Both facts are surfaced from the SERVER rather than hardcoded here:
//
//   * the platform <select> is built from `social.capabilities()`, and a platform
//     whose `publishable` is false is rendered as DISABLED with its own
//     `blockedReason` shown verbatim — so the UI cannot offer a publish the platform
//     would refuse, and the user learns WHY (e.g. Instagram needs a professional
//     account, which they change in the Instagram app, not here);
//   * choosing a time calls `social.plan()` FIRST, purely to preview where that time
//     would be held. When the plan comes back `local-queue` the panel shows the
//     server's `warning` text verbatim, because that is the sentence explaining the
//     post goes out when Reframe next runs rather than at the chosen time.
//
// The pre-audit visibility cap (`unauditedVisibility`) is shown before the first
// publish too — an upload that silently lands as PRIVATE would otherwise look broken.
//
// No credential is handled here. OAuth tokens live in the main-process keystore; the
// renderer never sees one.
import React, { useCallback, useEffect, useState } from 'react';
import {
  client,
  type SocialCapability,
  type SocialQueueEntry,
  type SocialSchedulePlan,
} from '../lib/rpc';
import './panels.css';

/** Local-time `datetime-local` value -> epoch seconds, or null when unset/unparseable. */
export function toEpochSeconds(value: string): number | null {
  if (value === '') return null;
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? null : Math.floor(ms / 1000);
}

/**
 * The display label for a platform id, falling back to the id itself.
 *
 * Extracted as a pure function rather than written inline as
 * `selected?.label ?? plan.platform`: inline, the fallback arm was UNREACHABLE
 * (`selected` is non-null wherever a plan exists), so it cost a coverage branch that
 * no test could honestly reach — and the test that claimed to cover it was passing
 * vacuously on the non-fallback arm. It is also more correct this way: the label
 * should track the PLAN's platform, which can momentarily differ from the currently
 * selected one while a preview is in flight.
 */
export function platformLabel(platforms: readonly SocialCapability[], id: string): string {
  return platforms.find((p) => p.id === id)?.label ?? id;
}

/** A queue row's status rendered for humans (kept beside the wire values it maps). */
export function statusLabel(entry: SocialQueueEntry): string {
  if (entry.status === 'pending' && entry.kind === 'platform') {
    // A platform-held schedule is NOT waiting on Reframe, so "pending" alone would
    // wrongly imply the app has to stay open for it.
    return 'scheduled on the platform';
  }
  if (entry.status === 'pending' && entry.requiresAppRunning) {
    return 'queued in Reframe';
  }
  return entry.status;
}

export interface SocialPublishPanelProps {
  /** The clip to publish (a rendered export path); empty when nothing is selected. */
  clipPath?: string;
  /** Provenance link back to the library item, carried onto the queue entry. */
  videoId?: string;
}

/** The Publish panel: pick a platform + time, preview the honest plan, queue it. */
export function SocialPublishPanel({
  clipPath = '',
  videoId = '',
}: SocialPublishPanelProps): React.ReactElement {
  const [platforms, setPlatforms] = useState<SocialCapability[]>([]);
  const [platform, setPlatform] = useState('');
  const [title, setTitle] = useState('');
  const [when, setWhen] = useState('');
  const [plan, setPlan] = useState<SocialSchedulePlan | null>(null);
  const [entries, setEntries] = useState<SocialQueueEntry[]>([]);
  const [error, setError] = useState('');
  /**
   * The schedule-PREVIEW error, kept apart from {@link error} on purpose.
   *
   * The preview effect re-runs on every platform/time keystroke, so if it shared one
   * slot it would clear whatever the last load or action had reported — a failed
   * `social.queue()` was measurably erased this way, leaving the panel silent about a
   * queue it could not read. Each slot is now owned by exactly one code path.
   */
  const [planError, setPlanError] = useState('');

  const selected = platforms.find((p) => p.id === platform) ?? null;

  const reloadQueue = useCallback(async () => {
    try {
      const { entries: rows } = await client.social.queue();
      setEntries(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load the publish queue');
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const { platforms: rows } = await client.social.capabilities();
        setPlatforms(rows);
        // Default to the first platform that can ACTUALLY publish, so the panel does
        // not open pre-set to a blocked one.
        setPlatform(rows.find((p) => p.publishable)?.id ?? '');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load platforms');
      }
      await reloadQueue();
    })();
  }, [reloadQueue]);

  // Preview the plan whenever the platform or the time changes. This is the whole
  // honesty mechanism: the disclosure appears BEFORE anything is committed.
  useEffect(() => {
    if (platform === '' || selected?.publishable !== true) {
      setPlan(null);
      return;
    }
    void (async () => {
      try {
        const { plan: preview } = await client.social.plan(platform, toEpochSeconds(when));
        setPlan(preview);
        setPlanError('');
      } catch (err) {
        setPlan(null);
        setPlanError(err instanceof Error ? err.message : 'Could not check that time');
      }
    })();
  }, [platform, when, selected?.publishable]);

  const handleQueue = useCallback(async () => {
    try {
      await client.social.enqueue({
        platform,
        clipPath,
        title,
        description: '',
        videoId,
        publishAt: toEpochSeconds(when),
      });
      await reloadQueue();
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not queue that publish');
    }
  }, [platform, clipPath, title, videoId, when, reloadQueue]);

  const handleCancel = useCallback(
    async (id: string) => {
      try {
        await client.social.cancel(id);
        await reloadQueue();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Cancel failed');
      }
    },
    [reloadQueue],
  );

  const canQueue = clipPath !== '' && title.trim() !== '' && selected?.publishable === true;

  return (
    <section className="social-publish" aria-label="Publish to social platforms">
      {error !== '' ? (
        <p role="alert" className="social-publish__error">
          {error}
        </p>
      ) : null}
      {planError !== '' ? (
        <p role="alert" className="social-publish__plan-error">
          {planError}
        </p>
      ) : null}

      <label className="social-publish__field">
        <span>Platform</span>
        <select
          aria-label="Platform"
          value={platform}
          onChange={(e) => setPlatform(e.target.value)}
        >
          {platforms.map((p) => (
            <option key={p.id} value={p.id} disabled={!p.publishable}>
              {p.publishable ? p.label : `${p.label} — unavailable`}
            </option>
          ))}
        </select>
      </label>

      {selected !== null && !selected.publishable ? (
        <p role="note" className="social-publish__blocked">
          {selected.blockedReason}
        </p>
      ) : null}

      <label className="social-publish__field">
        <span>Title</span>
        <input aria-label="Post title" value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>

      <label className="social-publish__field">
        <span>Publish at (leave empty to publish now)</span>
        <input
          type="datetime-local"
          aria-label="Publish at"
          value={when}
          onChange={(e) => setWhen(e.target.value)}
        />
      </label>

      {plan !== null ? (
        <div className="social-publish__plan">
          {plan.requiresAppRunning ? (
            // Verbatim server text — see the module note. This is the sentence that
            // stops the UI implying a desktop app can post while the machine is off.
            <p role="alert" className="social-publish__warning">
              {plan.warning}
            </p>
          ) : null}
          {plan.kind === 'platform' ? (
            <p className="social-publish__held">
              Scheduled on {platformLabel(platforms, plan.platform)} itself, so it posts even if
              this computer is off.
            </p>
          ) : null}
          {plan.unauditedVisibility !== '' ? (
            <p className="social-publish__audit">{plan.unauditedVisibility}</p>
          ) : null}
        </div>
      ) : null}

      {clipPath === '' ? (
        <p className="social-publish__empty">
          Export a clip first — Publish sends a rendered file, not the source video.
        </p>
      ) : null}

      <button type="button" disabled={!canQueue} onClick={() => void handleQueue()}>
        {when === '' ? 'Publish now' : 'Schedule'}
      </button>

      <h4>Queue</h4>
      {entries.length === 0 ? (
        <p className="social-publish__empty">Nothing queued yet.</p>
      ) : (
        <ul className="social-publish__queue">
          {entries.map((entry) => (
            <li key={entry.id}>
              <span>
                {entry.platform} — {entry.title} ({statusLabel(entry)})
              </span>
              {entry.status === 'pending' ? (
                <button type="button" onClick={() => void handleCancel(entry.id)}>
                  Cancel
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default SocialPublishPanel;
