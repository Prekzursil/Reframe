// EmptyState.tsx — the ONE empty state, EXTRACTED from the screens that already
// meet the bar. Not a new design.
//
// Three surfaces had independently hand-rolled the SAME anatomy — a ghost 16:9
// poster (play glyph + mono placeholder timecode) over a title, a hint, and a way
// forward: Edit.tsx's `edit__empty-*` (skin in components/shell.css),
// MakeShorts.tsx's `make-shorts__empty` (views/makeShorts.css) and Library.tsx's
// `library__empty`. Cited by selector, not by line — the shell.css anchors this
// file was written with drifted ~108 lines within days of the branch.
// Meanwhile other surfaces shipped a single grey paragraph with no action, so the
// quality of an empty state depended on which screen you happened to land on.
// This component is that anatomy once, so a surface inherits the bar by default.
//
// SKINNING, not re-designing: `block` picks the BEM prefix for the slots and
// `className` the root class, so an existing screen keeps its exact stylesheet
// (zero visual regression on the reference screens) while sharing ONE structure,
// ONE a11y contract, and ONE CTA affordance. New surfaces take the defaults and
// get the shared `.empty-state*` skin from emptyState.css.
import React from 'react';
import './emptyState.css';

/** The play glyph the ghost poster carries when a surface does not override it. */
export const EMPTY_STATE_GLYPH = '▶';

/** The mono placeholder timecode in the poster's corner. */
export const EMPTY_STATE_TIMECODE = '--:--';

/** The default BEM prefix for the slot classes (`empty-state-title`, …). */
export const EMPTY_STATE_BLOCK = 'empty-state';

/** The ghost poster's contents — both parts have a shared default. */
export interface EmptyStatePoster {
  /** Centre glyph. Defaults to {@link EMPTY_STATE_GLYPH}. */
  glyph?: string;
  /** Corner timecode. Defaults to {@link EMPTY_STATE_TIMECODE}. */
  timecode?: string;
}

/** The way forward. An empty state with no exit is a dead end — pass one. */
export interface EmptyStateAction {
  label: string;
  onClick: () => void;
  /** Override the derived `${block}-action` class (per-screen CTA skins). */
  className?: string;
}

export interface EmptyStateProps {
  /** The headline. Names the state, not the error ("No video open"). */
  title: string;
  /** One sentence saying what to do next. */
  hint?: React.ReactNode;
  /** The decorative ghost poster: `true` for the defaults, or an override. */
  poster?: boolean | EmptyStatePoster;
  /** The primary action out of this state. */
  action?: EmptyStateAction;
  /** BEM prefix for the slot classes. Defaults to {@link EMPTY_STATE_BLOCK}. */
  block?: string;
  /** Root class. Defaults to `block` (the shared `.empty-state` skin). */
  className?: string;
  /** `aria-label` for the region, when the surface has a name worth announcing. */
  label?: string;
}

/** Resolve the poster prop to its contents, or `undefined` for "no poster". */
function resolvePoster(poster: EmptyStateProps['poster']): EmptyStatePoster | undefined {
  if (poster === true) return {};
  if (poster === false) return undefined;
  return poster;
}

/** The shared empty state: ghost poster -> title -> hint -> a way forward. */
export function EmptyState({
  title,
  hint,
  poster,
  action,
  block = EMPTY_STATE_BLOCK,
  className,
  label,
}: EmptyStateProps): React.ReactElement {
  const art = resolvePoster(poster);
  return (
    <div className={className ?? block} aria-label={label}>
      {art ? (
        // Illustration, never content: it must not reach the a11y tree.
        <div className={`${block}-poster`} aria-hidden="true">
          <span className={`${block}-glyph`}>{art.glyph ?? EMPTY_STATE_GLYPH}</span>
          <span className={`${block}-timecode`}>{art.timecode ?? EMPTY_STATE_TIMECODE}</span>
        </div>
      ) : null}
      <p className={`${block}-title`}>{title}</p>
      {hint ? <p className={`${block}-hint`}>{hint}</p> : null}
      {action ? (
        <button
          type="button"
          className={action.className ?? `${block}-action`}
          onClick={action.onClick}
        >
          {action.label}
        </button>
      ) : null}
    </div>
  );
}

export default EmptyState;
