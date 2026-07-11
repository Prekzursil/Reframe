// TierCard.tsx — one selectable quality tier (Tier-0/1/2) in the tier picker.
// Shows the tier label, its will-it-run verdict badge, the member-component
// summary, and a radio to select it (writes settings.phase8Tier upstream). The
// Tier-2 card carries the "heaviest, opt-in, runs on its own, needs more memory"
// warning. Pure presentational: selection + apply are callbacks.
import React from 'react';
import type { TierStatus } from '../lib/rpc';
import { prettyName } from './advisorMeta';
import { VerdictBadge } from './VerdictBadge';

export interface TierCardProps {
  tier: TierStatus;
  /** Currently-selected tier number (drives the radio checked state). */
  selected: boolean;
  /** Whether this tier matches the advisor's recommended preset. */
  recommended: boolean;
  /** Select this tier (writes settings.phase8Tier). */
  onSelect: (tier: number) => void;
}

/** Human one-liner per tier (what picking it means). */
const TIER_BLURB: Record<number, string> = {
  0: 'Instant, silent-video OK, zero downloads. Runs on any machine.',
  1: 'Default. Adds visual + audio + transcript models (downloads on first use).',
  2: 'The heaviest option — an AI watches the top clips to re-rank them. Opt-in; runs on its own and needs more memory.',
};

export function TierCard({
  tier,
  selected,
  recommended,
  onSelect,
}: TierCardProps): React.ReactElement {
  const blurb = TIER_BLURB[tier.tier] ?? '';
  const members = tier.components.map(prettyName).join(' · ');
  return (
    <label
      className={`tier-card${selected ? ' is-selected' : ''}`}
      data-tier={tier.tier}
      data-verdict={tier.verdict}
      // SELECTION clarity: aria-current marks the active tier for assistive tech;
      // the visible "Selected" badge below conveys it sighted (color is never the
      // sole signal). `undefined` (not false) so the attribute is fully absent
      // on unselected cards.
      aria-current={selected ? 'true' : undefined}
      title={`${tier.label}. ${blurb}`}
    >
      <div className="tier-card__head">
        <input
          type="radio"
          name="phase8-tier"
          className="tier-card__radio"
          checked={selected}
          onChange={() => onSelect(tier.tier)}
          aria-label={`Select ${tier.label}`}
        />
        <span className="tier-card__title">
          Tier {tier.tier}
          {selected && (
            <span className="tier-card__selected" title="This tier is currently selected">
              Selected
            </span>
          )}
          {recommended && (
            <span className="tier-card__recommended" title="Recommended for your hardware">
              Recommended
            </span>
          )}
        </span>
        <VerdictBadge verdict={tier.verdict} />
      </div>
      <p className="tier-card__label">{tier.label}</p>
      <p className="tier-card__blurb">{blurb}</p>
      {members && <p className="tier-card__members">{members}</p>}
    </label>
  );
}

export default TierCard;
