// TierCard.tsx — one selectable quality tier (Tier-0/1/2) in the tier picker.
// Shows the tier label, its will-it-run verdict badge, the member-component
// summary, and a radio to select it (writes settings.phase8Tier upstream). The
// Tier-2 card carries the "heavy, opt-in, runs alone" + SmolVLM2-int8-broken
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
  2: 'Heavy video-LLM re-rank of the top clips. Opt-in; runs alone; SmolVLM2 int8 is broken — uses BF16.',
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
