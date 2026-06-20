// BatchConsentCard.test.tsx — pre-run consent summary + visible skip (§9.1).

// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { BatchConsentCard } from './BatchConsentCard';
import type { BatchConsent } from '../lib/rpc';

let container: HTMLElement;
let root: Root;

function render(ui: React.ReactElement): void {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root.render(ui);
  });
}

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const CONSENT: BatchConsent = {
  decisions: [
    {
      videoId: 'v1',
      action: 'run',
      skipReason: null,
      confirmBudget: 'k1',
      willEgress: true,
      cacheHit: false,
    },
    {
      videoId: 'v2',
      action: 'skip',
      skipReason: 'would egress — not acknowledged',
      confirmBudget: null,
      willEgress: true,
      cacheHit: false,
    },
  ],
  willRun: 1,
  willSkip: 1,
  costEst: { usd: 0.2 },
  budget: { usd: 5 },
};

const titleFor = (id: string): string => (id === 'v2' ? 'Episode Two' : id);

describe('BatchConsentCard', () => {
  it('shows the run/skip split', () => {
    render(
      <BatchConsentCard
        consent={CONSENT}
        confirmCloudBudget
        acknowledged={false}
        onAcknowledge={vi.fn()}
        titleFor={titleFor}
      />,
    );
    expect(container.textContent).toContain('1 of 2 sources will run; 1 skipped');
  });

  it('names each skipped source with its reason (visible skip, §9.1)', () => {
    render(
      <BatchConsentCard
        consent={CONSENT}
        confirmCloudBudget
        acknowledged={false}
        onAcknowledge={vi.fn()}
        titleFor={titleFor}
      />,
    );
    const skip = container.querySelector('.batch-consent__skip');
    expect(skip?.textContent).toContain('Episode Two');
    expect(skip?.textContent).toContain('would egress — not acknowledged');
  });

  it('falls back to a generic reason when skipReason is null', () => {
    const consent: BatchConsent = {
      ...CONSENT,
      decisions: [
        {
          videoId: 'v3',
          action: 'skip',
          skipReason: null,
          confirmBudget: null,
          willEgress: true,
          cacheHit: false,
        },
      ],
      willRun: 0,
      willSkip: 1,
    };
    render(
      <BatchConsentCard
        consent={consent}
        confirmCloudBudget
        acknowledged={false}
        onAcknowledge={vi.fn()}
        titleFor={titleFor}
      />,
    );
    expect(container.querySelector('.batch-consent__skip-reason')?.textContent).toContain(
      'skipped',
    );
  });

  it('omits the skip section when nothing is skipped', () => {
    const consent: BatchConsent = { ...CONSENT, decisions: [CONSENT.decisions[0]], willSkip: 0 };
    render(
      <BatchConsentCard
        consent={consent}
        confirmCloudBudget
        acknowledged={false}
        onAcknowledge={vi.fn()}
        titleFor={titleFor}
      />,
    );
    expect(container.querySelector('.batch-consent__skips')).toBeNull();
  });

  it('the ack button fires onAcknowledge and reflects pressed state', () => {
    const onAck = vi.fn();
    render(
      <BatchConsentCard
        consent={CONSENT}
        confirmCloudBudget
        acknowledged={false}
        onAcknowledge={onAck}
        titleFor={titleFor}
      />,
    );
    const btn = container.querySelector('.batch-consent__ack') as HTMLButtonElement;
    expect(btn.getAttribute('aria-pressed')).toBe('false');
    act(() => btn.dispatchEvent(new MouseEvent('click', { bubbles: true })));
    expect(onAck).toHaveBeenCalledTimes(1);
  });

  it('shows the acknowledged state (disabled, pressed)', () => {
    render(
      <BatchConsentCard
        consent={CONSENT}
        confirmCloudBudget
        acknowledged
        onAcknowledge={vi.fn()}
        titleFor={titleFor}
      />,
    );
    const btn = container.querySelector('.batch-consent__ack') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.getAttribute('aria-pressed')).toBe('true');
    expect(container.querySelector('.batch-consent__hint')).toBeNull();
  });

  it('is informational only when confirmCloudBudget is off (no ack control)', () => {
    render(
      <BatchConsentCard
        consent={CONSENT}
        confirmCloudBudget={false}
        acknowledged={false}
        onAcknowledge={vi.fn()}
        titleFor={titleFor}
      />,
    );
    expect(container.querySelector('.batch-consent__ack')).toBeNull();
    expect(container.querySelector('.batch-consent__info')?.textContent).toContain(
      'all sources run',
    );
  });
});
