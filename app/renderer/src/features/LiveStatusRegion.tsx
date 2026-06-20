// LiveStatusRegion.tsx — the net-new BatchQueue a11y live-status announcer (§7.1,
// G-A11Y). The reused JobQueue carries NO aria-live region, so this is net-new
// UX, not "reuse." It adopts the SAME idiom as `ShortMaker.tsx:773`
// (`role="status" aria-live="polite"`) and `SidecarBanner.tsx:72`
// (`role="alert" aria-live="assertive"` for the one transition important enough
// to interrupt).
//
// Two regions:
//   * a POLITE aggregate region holding the debounced "source k/N · …" message;
//   * an ASSERTIVE alert region that surfaces the most recent terminal-error
//     announcement so a failed source interrupts and is not missed.
// Non-error terminal announcements (done/cancelled/skipped) ride the polite log.
//
// Pure presentational: the parent (BatchQueue) owns the progress stream and the
// terminal-flip detection; it passes the already-decided strings in.
import React from 'react';

export interface LiveStatusRegionProps {
  /** The debounced aggregate progress text (announced politely on source flip). */
  aggregate: string;
  /** Discrete polite log lines (done/cancelled/skipped terminal flips). */
  politeLog: readonly string[];
  /** The most recent assertive (error) announcement, or '' for none. */
  assertive: string;
}

/**
 * The BatchQueue live-status announcer: a polite aggregate + polite log + an
 * assertive alert region. All status is text (never color-only).
 */
export function LiveStatusRegion({
  aggregate,
  politeLog,
  assertive,
}: LiveStatusRegionProps): React.ReactElement {
  return (
    <div className="batch-livestatus">
      <div role="status" aria-live="polite" className="batch-livestatus__aggregate">
        {aggregate}
      </div>
      <div role="log" aria-live="polite" className="batch-livestatus__log">
        {politeLog.map((line, index) => (
          // The log is append-only per render; index keys are stable enough here.
          // eslint-disable-next-line react/no-array-index-key
          <p key={`${index}-${line}`} className="batch-livestatus__line">
            {line}
          </p>
        ))}
      </div>
      <div role="alert" aria-live="assertive" className="batch-livestatus__alert">
        {assertive}
      </div>
    </div>
  );
}

export default LiveStatusRegion;
