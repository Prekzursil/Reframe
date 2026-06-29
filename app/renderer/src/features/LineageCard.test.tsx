// LineageCard.test.tsx — the L4 provenance card (pure presentational).
// Covers: the raw-source note (with/without a created date), the full produced
// card (created + maker line + every friendly chip with raw id in the tooltip),
// and each chip/maker being omitted when its datum is absent.

// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { LineageCard } from './LineageCard';
import type { LineageEntity, LineageProvenance } from '../lib/rpc';

function entity(over: Partial<LineageEntity> = {}): LineageEntity {
  return {
    id: 'clip1',
    kind: 'short',
    role: 'output',
    path: '/x/clip.mp4',
    title: 'My clip',
    addedAt: '2026-06-29T12:00:00Z',
    durationSec: 30,
    contentHash: null,
    hasTranscript: false,
    thumbnailPath: '',
    ...over,
  };
}

function prov(over: Partial<LineageProvenance> = {}): LineageProvenance {
  return {
    op: 'shortmaker.select',
    status: 'done',
    startedAt: '2026-06-29T12:00:00Z',
    endedAt: '2026-06-29T12:00:00Z',
    params: { template: 'bold' },
    appVersion: '1.1.0',
    preset: 'Punchy',
    route: { mode: 'local', model: 'qwen2.5:7b' },
    ...over,
  };
}

describe('<LineageCard />', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function mount(props: { entity: LineageEntity | null; provenance: LineageProvenance | null }) {
    act(() => {
      root.render(<LineageCard {...props} />);
    });
  }

  it('shows the raw-source note with a created date when not made by Reframe', () => {
    mount({ entity: entity(), provenance: null });
    const text = container.textContent ?? '';
    expect(text).toContain('Added to your library on 2026-06-29.');
    expect(text).toContain('Not made by Reframe.');
  });

  it('shows the raw-source note without a date when the entity is unknown', () => {
    mount({ entity: null, provenance: null });
    expect(container.textContent).toContain('Added to your library.');
  });

  it('renders the full produced card with friendly labels + raw ids in tooltips', () => {
    mount({ entity: entity(), provenance: prov() });
    const text = container.textContent ?? '';
    expect(text).toContain('Created 2026-06-29');
    expect(text).toContain('by Reframe v1.1.0');

    const op = container.querySelector('.lineage-card__chip--op');
    expect(op?.textContent).toBe('Found highlights');
    expect(op?.getAttribute('title')).toBe('shortmaker.select');

    const model = container.querySelector('.lineage-card__chip--model');
    expect(model?.textContent).toBe('Qwen2.5 7B (on this PC)');
    expect(model?.getAttribute('title')).toBe('qwen2.5:7b');

    expect(container.querySelector('.lineage-card__chip--preset')?.textContent).toBe('Punchy');
    expect(container.querySelector('.lineage-card__chip--caption')?.textContent).toBe('Bold');
  });

  it('omits the created date prefix when the entity is unknown', () => {
    mount({ entity: null, provenance: prov() });
    const line = container.querySelector('.lineage-card__line');
    expect(line?.textContent?.startsWith('Created by')).toBe(true);
  });

  it('uses a date-only addedAt verbatim (no "T" to slice on)', () => {
    mount({ entity: entity({ addedAt: '2026-06-29' }), provenance: prov() });
    expect(container.querySelector('.lineage-card__line')?.textContent).toContain(
      'Created 2026-06-29',
    );
  });

  it('omits the maker line when no app version was recorded', () => {
    mount({ entity: entity(), provenance: prov({ appVersion: null }) });
    expect(container.querySelector('.lineage-card__maker')).toBeNull();
  });

  it('omits each chip whose datum is absent', () => {
    mount({
      entity: entity(),
      provenance: prov({ op: '', route: null, preset: null, params: null }),
    });
    expect(container.querySelector('.lineage-card__chip--op')).toBeNull();
    expect(container.querySelector('.lineage-card__chip--model')).toBeNull();
    expect(container.querySelector('.lineage-card__chip--preset')).toBeNull();
    expect(container.querySelector('.lineage-card__chip--caption')).toBeNull();
  });
});
