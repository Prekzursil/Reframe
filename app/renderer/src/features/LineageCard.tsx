import React from 'react';

import {
  captionLabel,
  makerLabel,
  modelLabel,
  opLabel,
  presetLabel,
  type FriendlyLabel,
} from '../lib/lineageLabels';
import type { LineageEntity, LineageProvenance } from '../lib/rpc';

// LineageCard.tsx — L4 asset-detail provenance card (DESIGN §3.4).
//
// "Created 2026-… by Reframe v… · Found highlights · preset Punchy · moments
//  by Qwen2.5 7B (on this PC) · captions Bold." — the RAW op/model ids live in
// each chip's `title` tooltip (lineageLabels), never on screen. A raw imported
// source (no producing activity) shows a plain "added to your library" note
// instead of an empty card. Pure presentational: the Reveal/Regenerate actions
// are L5 and are deliberately NOT stubbed here (no fake disabled buttons).

export interface LineageCardProps {
  /** The queried asset (for its created date), or `null` for an unknown id. */
  entity: LineageEntity | null;
  /** Its producing activity + agent, or `null` for a raw imported source. */
  provenance: LineageProvenance | null;
}

/** ISO timestamp -> its date portion ("2026-06-29T..." -> "2026-06-29"). */
function asDate(addedAt: string): string {
  const t = addedAt.indexOf('T');
  return t === -1 ? addedAt : addedAt.slice(0, t);
}

/** One friendly chip with the raw id surfaced in a `title` tooltip. */
function Chip({ kind, value }: { kind: string; value: FriendlyLabel }): React.ReactElement {
  return (
    <span className={`lineage-card__chip lineage-card__chip--${kind}`} title={value.raw}>
      {value.label}
    </span>
  );
}

export function LineageCard({ entity, provenance }: LineageCardProps): React.ReactElement {
  const created = entity === null ? '' : asDate(entity.addedAt);

  if (provenance === null) {
    return (
      <div className="lineage-card lineage-card--source">
        <p className="lineage-card__note">
          {created === '' ? 'Added to your library.' : `Added to your library on ${created}.`} Not
          made by Reframe.
        </p>
      </div>
    );
  }

  const maker = makerLabel(provenance);
  const op = opLabel(provenance.op);
  const model = modelLabel(provenance.route);
  const preset = presetLabel(provenance.preset);
  const captions = captionLabel(provenance.params);

  return (
    <div className="lineage-card">
      <p className="lineage-card__line">
        {created === '' ? 'Created' : `Created ${created}`}
        {maker === null ? null : <span className="lineage-card__maker"> by {maker}</span>}
      </p>
      <div className="lineage-card__chips">
        {op === null ? null : <Chip kind="op" value={op} />}
        {model === null ? null : <Chip kind="model" value={model} />}
        {preset === null ? null : <Chip kind="preset" value={preset} />}
        {captions === null ? null : <Chip kind="caption" value={captions} />}
      </div>
    </div>
  );
}

export default LineageCard;
