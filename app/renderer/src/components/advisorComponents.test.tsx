// advisorComponents.test.tsx — render tests for the Models & System building
// blocks: VerdictBadge / ResourceBar / TierCard / ModelCard / ModelsOnboarding.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { VerdictBadge } from './VerdictBadge';
import { ResourceBar } from './ResourceBar';
import { TierCard } from './TierCard';
import { ModelCard } from './ModelCard';
import { ModelsOnboarding, ONBOARDING_STEPS } from './ModelsOnboarding';
import type { ComponentStatus, TierStatus } from '../lib/rpc';

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

async function render(node: React.ReactElement): Promise<void> {
  await act(async () => {
    root.render(node);
  });
}

describe('<VerdictBadge />', () => {
  it('renders label + class + tooltip per verdict', async () => {
    await render(<VerdictBadge verdict="ok" reason="fits fine" />);
    const badge = container.querySelector('.verdict-badge') as HTMLElement;
    expect(badge.textContent).toBe('Will run');
    expect(badge.classList.contains('is-ok')).toBe(true);
    expect(badge.getAttribute('data-verdict')).toBe('ok');
    expect(badge.title).toContain('fits fine');
    expect(badge.title).toContain('one at a time');
  });
  it('handles the unavailable verdict without a reason', async () => {
    await render(<VerdictBadge verdict="unavailable" />);
    const badge = container.querySelector('.verdict-badge') as HTMLElement;
    expect(badge.textContent).toBe("Won't run");
    expect(badge.classList.contains('is-unavailable')).toBe(true);
  });
});

describe('<ResourceBar />', () => {
  it('renders used/total and an ok fill below the threshold', async () => {
    await render(<ResourceBar label="VRAM budget" used={3000} total={6000} />);
    const bar = container.querySelector('.resource-bar') as HTMLElement;
    expect(bar.querySelector('.resource-bar__value')?.textContent).toBe('2.9 GB / 5.9 GB');
    const fill = bar.querySelector('.resource-bar__fill') as HTMLElement;
    expect(fill.getAttribute('data-zone')).toBe('ok');
    expect(fill.style.width).toBe('50%');
    const meter = bar.querySelector('[role="meter"]') as HTMLElement;
    expect(meter.getAttribute('aria-valuenow')).toBe('50');
  });
  it('shows "not detected" + amber when tight, and appends a custom hint', async () => {
    await render(<ResourceBar label="VRAM budget" used={5500} total={6000} hint="extra note" />);
    let fill = container.querySelector('.resource-bar__fill') as HTMLElement;
    expect(fill.getAttribute('data-zone')).toBe('tight');
    expect((container.querySelector('.resource-bar') as HTMLElement).title).toContain('extra note');

    await render(<ResourceBar label="VRAM budget" used={null} total={null} />);
    expect(container.querySelector('.resource-bar__value')?.textContent).toBe('not detected');
    fill = container.querySelector('.resource-bar__fill') as HTMLElement;
    expect(fill.style.width).toBe('0%');
  });
});

function tier(over: Partial<TierStatus> = {}): TierStatus {
  return {
    tier: 1,
    label: 'Multimodal',
    verdict: 'ok',
    components: ['saliency', 'vlm_backbone'],
    ...over,
  };
}

describe('<TierCard />', () => {
  it('renders members, verdict, recommended chip, and fires onSelect', async () => {
    const onSelect = vi.fn();
    await render(<TierCard tier={tier()} selected={false} recommended onSelect={onSelect} />);
    const card = container.querySelector('.tier-card') as HTMLElement;
    expect(card.getAttribute('data-tier')).toBe('1');
    expect(card.querySelector('.tier-card__recommended')).not.toBeNull();
    expect(card.querySelector('.verdict-badge')?.textContent).toBe('Will run');
    expect(card.querySelector('.tier-card__members')?.textContent).toContain('SigLIP-2');
    // Not selected -> no aria-current, no Selected badge (selection clarity).
    expect(card.getAttribute('aria-current')).toBeNull();
    expect(card.querySelector('.tier-card__selected')).toBeNull();
    const radio = card.querySelector('input[type="radio"]') as HTMLInputElement;
    await act(async () => {
      radio.click();
    });
    expect(onSelect).toHaveBeenCalledWith(1);
  });
  it('marks the selected tier and tolerates an unknown tier number (no blurb/members)', async () => {
    await render(
      <TierCard
        tier={tier({ tier: 9, components: [] })}
        selected
        recommended={false}
        onSelect={vi.fn()}
      />,
    );
    const card = container.querySelector('.tier-card') as HTMLElement;
    expect(card.classList.contains('is-selected')).toBe(true);
    // Selected -> aria-current + a visible Selected badge (never color alone).
    expect(card.getAttribute('aria-current')).toBe('true');
    expect(card.querySelector('.tier-card__selected')).not.toBeNull();
    expect(card.querySelector('.tier-card__recommended')).toBeNull();
    expect(card.querySelector('.tier-card__members')).toBeNull();
  });
});

function comp(over: Partial<ComponentStatus> = {}): ComponentStatus {
  return {
    name: 'vlm_backbone',
    present: true,
    verdict: 'ok',
    vramMb: 2300,
    licenseCommercialOk: true,
    reason: 'Apache-2.0 SigLIP-2; fits 6GB',
    ...over,
  };
}

describe('<ModelCard />', () => {
  it('renders meters, chips, size, and an enabled Download when missing', async () => {
    const onDownload = vi.fn();
    await render(
      <ModelCard
        component={comp()}
        qualityFraction={0.5}
        vramBudgetMb={6000}
        installed={false}
        sizeMb={4540}
        downloading={false}
        onDownload={onDownload}
      />,
    );
    const card = container.querySelector('.model-card') as HTMLElement;
    expect(card.querySelector('.model-card__name')?.textContent).toContain('SigLIP-2');
    expect(card.querySelector('.license-chip')?.textContent).toBe('Commercial OK');
    expect(card.querySelector('.model-card__size')?.textContent).toBe('4.4 GB');
    const costFill = card.querySelector('.mini-meter__fill.is-cost') as HTMLElement;
    expect(costFill.style.width).toBe('38%'); // 2300/6000 -> 38%
    const qualFill = card.querySelector('.mini-meter__fill.is-quality') as HTMLElement;
    expect(qualFill.style.width).toBe('50%');
    const btn = card.querySelector('.model-card__download') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    // MODEL state clarity: the actionable size is on the button itself.
    expect(btn.textContent).toBe('Download (4.4 GB)');
    expect(btn.getAttribute('data-state')).toBe('download');
    expect(btn.querySelector('svg[data-icon="installed"]')).toBeNull();
    await act(async () => {
      btn.click();
    });
    expect(onDownload).toHaveBeenCalledWith('vlm_backbone');
  });

  it('shows CPU for a no-VRAM floor and "Installed" disabled when installed', async () => {
    await render(
      <ModelCard
        component={comp({ name: 'motion', vramMb: null })}
        qualityFraction={0}
        vramBudgetMb={6000}
        installed
        sizeMb={null}
        downloading={false}
        onDownload={vi.fn()}
      />,
    );
    const card = container.querySelector('.model-card') as HTMLElement;
    expect(card.querySelector('.model-card__vram')?.textContent).toBe('CPU');
    expect(card.querySelector('.model-card__size')?.textContent).toBe('—');
    const btn = card.querySelector('.model-card__download') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain('Installed');
    expect(btn.getAttribute('data-state')).toBe('installed');
    // MODEL state clarity: the installed check is an inline SVG, NOT an emoji.
    expect(btn.querySelector('svg[data-icon="installed"]')).not.toBeNull();
  });

  it('renders a bare "Download" (no size) when the asset size is unknown', async () => {
    await render(
      <ModelCard
        component={comp()}
        qualityFraction={0.5}
        vramBudgetMb={6000}
        installed={false}
        sizeMb={null}
        downloading={false}
        onDownload={vi.fn()}
      />,
    );
    const btn = container.querySelector('.model-card__download') as HTMLButtonElement;
    expect(btn.textContent).toBe('Download');
    expect(btn.getAttribute('data-state')).toBe('download');
  });

  it('greys Download for a license-blocked model and shows the blocked tooltip', async () => {
    await render(
      <ModelCard
        component={comp({ verdict: 'unavailable', licenseCommercialOk: false })}
        qualityFraction={1}
        vramBudgetMb={6000}
        installed={false}
        sizeMb={4540}
        downloading={false}
        onDownload={vi.fn()}
      />,
    );
    const btn = container.querySelector('.model-card__download') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.title).toContain('license');
  });

  it('shows "Downloading…" while a download is in flight', async () => {
    await render(
      <ModelCard
        component={comp()}
        qualityFraction={0.5}
        vramBudgetMb={6000}
        installed={false}
        sizeMb={4540}
        downloading
        onDownload={vi.fn()}
      />,
    );
    const btn = container.querySelector('.model-card__download') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toBe('Downloading…');
  });
});

describe('<ModelsOnboarding />', () => {
  it('walks all 3 steps with Next, Back, and finishes on Got it', async () => {
    const onDone = vi.fn();
    await render(<ModelsOnboarding onDone={onDone} />);

    const title = () => container.querySelector('.models-onboarding__title')?.textContent;
    expect(title()).toBe(ONBOARDING_STEPS[0].title);

    const next = () =>
      container.querySelector('button[data-action="next"]') as HTMLButtonElement | null;
    await act(async () => next()!.click());
    expect(title()).toBe(ONBOARDING_STEPS[1].title);

    // Back returns to step 1.
    await act(async () => {
      (container.querySelector('button[data-action="back"]') as HTMLButtonElement).click();
    });
    expect(title()).toBe(ONBOARDING_STEPS[0].title);

    // Next twice -> last step shows "Got it".
    await act(async () => next()!.click());
    await act(async () => next()!.click());
    expect(title()).toBe(ONBOARDING_STEPS[2].title);
    const done = container.querySelector('button[data-action="done"]') as HTMLButtonElement;
    await act(async () => done.click());
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('Skip tour dismisses immediately', async () => {
    const onDone = vi.fn();
    await render(<ModelsOnboarding onDone={onDone} />);
    await act(async () => {
      (container.querySelector('button[data-action="skip"]') as HTMLButtonElement).click();
    });
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});
