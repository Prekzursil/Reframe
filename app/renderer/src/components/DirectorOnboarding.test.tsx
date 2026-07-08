// DirectorOnboarding.test.tsx — the AI Director first-run coach-mark overlay
// (WU-E2). Mirrors the ModelsOnboarding pattern: a 3-step, focus-trapped,
// dismissible dialog that explains what Director does. Full-branch coverage of
// step navigation (Next/Back/dots), Skip/Got it dismissal, and Escape (the
// shared useFocusTrap onEscape seam).

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import { DirectorOnboarding, DIRECTOR_ONBOARDING_STEPS } from './DirectorOnboarding';

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
  vi.restoreAllMocks();
});

function $(sel: string): HTMLElement {
  const el = container.querySelector(sel);
  if (!el) throw new Error(`no element for ${sel}`);
  return el as HTMLElement;
}

async function mount(onDone: () => void): Promise<void> {
  await act(async () => {
    root.render(<DirectorOnboarding onDone={onDone} />);
  });
}

async function click(sel: string): Promise<void> {
  await act(async () => {
    $(sel).click();
  });
}

describe('DIRECTOR_ONBOARDING_STEPS', () => {
  it('is a non-empty ordered list of {title, body} steps', () => {
    expect(DIRECTOR_ONBOARDING_STEPS.length).toBeGreaterThanOrEqual(3);
    for (const step of DIRECTOR_ONBOARDING_STEPS) {
      expect(typeof step.title).toBe('string');
      expect(step.title.length).toBeGreaterThan(0);
      expect(typeof step.body).toBe('string');
      expect(step.body.length).toBeGreaterThan(0);
    }
  });
});

describe('DirectorOnboarding', () => {
  it('opens on step 1 as a labelled modal dialog (no Back yet, Next not Done)', async () => {
    await mount(vi.fn());
    const dialog = $('.director-onboarding');
    expect(dialog.getAttribute('role')).toBe('dialog');
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(dialog.getAttribute('aria-label')).toMatch(/director/i);
    expect(dialog.getAttribute('data-step')).toBe('0');
    expect($('.director-onboarding__title').textContent).toBe(DIRECTOR_ONBOARDING_STEPS[0].title);
    expect($('.director-onboarding__progress').textContent).toBe(
      `Step 1 of ${DIRECTOR_ONBOARDING_STEPS.length}`,
    );
    // First step: no Back, a Next (not the final Got it), and a Skip.
    expect(container.querySelector('button[data-action="back"]')).toBeNull();
    expect(container.querySelector('button[data-action="next"]')).not.toBeNull();
    expect(container.querySelector('button[data-action="done"]')).toBeNull();
    expect(container.querySelector('button[data-action="skip"]')).not.toBeNull();
    // The active dot tracks the step.
    const dots = Array.from(container.querySelectorAll('.director-onboarding__dot'));
    expect(dots.length).toBe(DIRECTOR_ONBOARDING_STEPS.length);
    expect(dots[0].classList.contains('is-active')).toBe(true);
    expect(dots[1].classList.contains('is-active')).toBe(false);
  });

  it('Next walks to the last step where Got it (not Next) is shown; Back walks return', async () => {
    await mount(vi.fn());
    // Advance to the final step.
    for (let i = 0; i < DIRECTOR_ONBOARDING_STEPS.length - 1; i += 1) {
      await click('button[data-action="next"]');
    }
    const last = DIRECTOR_ONBOARDING_STEPS.length - 1;
    expect($('.director-onboarding').getAttribute('data-step')).toBe(String(last));
    expect($('.director-onboarding__title').textContent).toBe(
      DIRECTOR_ONBOARDING_STEPS[last].title,
    );
    // Last step: Got it replaces Next; Back is available.
    expect(container.querySelector('button[data-action="next"]')).toBeNull();
    expect(container.querySelector('button[data-action="done"]')).not.toBeNull();
    expect(container.querySelector('button[data-action="back"]')).not.toBeNull();
    // Back returns to the previous step.
    await click('button[data-action="back"]');
    expect($('.director-onboarding').getAttribute('data-step')).toBe(String(last - 1));
  });

  it('Skip calls onDone', async () => {
    const onDone = vi.fn();
    await mount(onDone);
    await click('button[data-action="skip"]');
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('Got it on the final step calls onDone', async () => {
    const onDone = vi.fn();
    await mount(onDone);
    for (let i = 0; i < DIRECTOR_ONBOARDING_STEPS.length - 1; i += 1) {
      await click('button[data-action="next"]');
    }
    await click('button[data-action="done"]');
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('Escape dismisses the dialog (useFocusTrap onEscape → onDone)', async () => {
    const onDone = vi.fn();
    await mount(onDone);
    await act(async () => {
      $('.director-onboarding').dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
      );
    });
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});
