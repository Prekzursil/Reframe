// Skeleton.tsx — the ONE loading skeleton.
//
// Library.tsx already wrote the rule down (its own comment: never a bare
// "LOADING…") and shipped a shaped skeleton for itself, while Settings.tsx,
// Workspace.tsx and App.tsx each rendered exactly the bare string the rule
// forbids. This is the shared shape so no surface has to hand-roll one — or skip
// it — again. (Cited by selector, not by line: shell.css is owned by other lanes
// and every line number this file quoted at branch time has already drifted.)
//
// It rides the SINGLE `.skeleton` shimmer rule in components/shell.css, which
// also owns the reduced-motion behaviour. Nothing here redefines that rule; the
// variants below are only SHAPES layered on it (pinned by Skeleton.test.tsx).
//
// A11Y — the honest scope. A labelled skeleton is `role="status"` +
// `aria-busy="true"` + the wait as a REAL text node (clipped, not display:none).
// That is the contract every other loading surface in this app already carries
// (Library's skeleton, ManagedStoreMeter, SetupStatusPanel, ReadinessRollup) and
// it means a screen-reader user who reaches the region meets actual text rather
// than an unnamed div. It is NOT a promise that anything is SPOKEN on insertion:
// this repo's own ToastHost/LiveStatusRegion keep their live regions permanently
// mounted precisely because "freshly-inserted polite/status regions are announced
// unreliably by NVDA/JAWS", and a Suspense fallback is freshly inserted by
// definition. NOT-CHECKED with a real screen reader; jsdom cannot check it.
// Settling experiment: drive the built app with NVDA while the Models & System
// chunk resolves and record whether anything is spoken.
import React from 'react';
import './emptyState.css';

/**
 * The shapes. `panel` is the composite a lazy panel's Suspense fallback wants
 * (a heading bar over body lines); `title`/`line` are its parts, reusable alone.
 */
export type SkeletonVariant = 'line' | 'title' | 'panel';

export interface SkeletonProps {
  /** Which shape to render. Defaults to a single body line. */
  variant?: SkeletonVariant;
  /** Extra root classes — e.g. `panel` so the ghost inherits the real surface. */
  className?: string;
  /**
   * When set, the skeleton is a BUSY status region (`role="status"` +
   * `aria-busy`) and this string is rendered as clipped text inside it, so the
   * region has content to read rather than only a name. Leave it off for a
   * skeleton that sits inside an already-labelled region: it is then pure
   * decoration and stays out of the a11y tree.
   */
  label?: string;
}

/** One shimmer bar. Always carries the shared `.skeleton` base class. */
function Bar({ shape }: { shape: 'title' | 'line' }): React.ReactElement {
  return <span className={`skeleton skeleton--${shape}`} />;
}

/** The shared loading skeleton: a shape that echoes what is about to land. */
export function Skeleton({
  variant = 'line',
  className,
  label,
}: SkeletonProps): React.ReactElement {
  const root = ['skeleton-group', `skeleton-group--${variant}`, className]
    .filter(Boolean)
    .join(' ');
  // Labelled (a busy status region) or decorative — never both, never neither.
  // No `aria-label`: the label below is real text, and a name would only shadow
  // the content a live region actually reads.
  const a11y = label
    ? ({ role: 'status', 'aria-busy': true } as const)
    : ({ 'aria-hidden': true } as const);
  return (
    <div className={root} {...a11y}>
      {variant === 'panel' ? (
        <>
          <Bar shape="title" />
          <Bar shape="line" />
          <Bar shape="line" />
          <Bar shape="line" />
        </>
      ) : (
        <Bar shape={variant} />
      )}
      {/* LAST, deliberately: emptyState.css tapers and staggers the bars with
          :nth-child(2..4), so a label rendered first would shift every index by
          one and silently re-point the taper. Pinned by Skeleton.test.tsx. */}
      {label ? <span className="skeleton-group__label">{label}</span> : null}
    </div>
  );
}

export default Skeleton;
