// Skeleton.tsx — the ONE loading skeleton.
//
// Library.tsx:616-618 already wrote the rule down ("never a bare LOADING…") and
// shipped a shaped skeleton for itself, while Settings.tsx, Workspace.tsx and
// App.tsx each rendered exactly the bare string the rule forbids. This is the
// shared shape so no surface has to hand-roll one — or skip it — again.
//
// It rides the SINGLE `.skeleton` shimmer rule at components/shell.css:634, which
// also owns the reduced-motion behaviour. Nothing here redefines that rule; the
// variants below are only SHAPES layered on it (pinned by Skeleton.test.tsx).
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
   * When set, the skeleton is an ANNOUNCED status region (`role="status"`) with
   * this label. Leave it off for a skeleton that sits inside an already-labelled
   * region: it is then pure decoration and stays out of the a11y tree.
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
  // Announced (labelled) or decorative — never both, never neither.
  const a11y = label
    ? ({ role: 'status', 'aria-label': label } as const)
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
    </div>
  );
}

export default Skeleton;
