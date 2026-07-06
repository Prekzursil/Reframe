// @vitest-environment jsdom
// ProfilePicker.test.tsx — the first-ever-run install-profile picker (WU-1c), held
// to 100%. Drives the radio group, the Custom feature-bundle reveal + toggles, and
// the confirm commit; asserts the approx-size labels come from the single-source
// map so they can't drift from what actually installs.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { DEFAULT_PROFILE_ID, ProfilePicker } from './ProfilePicker';
import { profileSizeLabel } from '../../../main/installProfiles';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

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

function render(onChoose: (profile: string, bundles: string[]) => void): void {
  act(() => {
    root.render(React.createElement(ProfilePicker, { onChoose }));
  });
}

function option(id: string): HTMLLabelElement {
  return container.querySelector<HTMLLabelElement>(`[data-profile="${id}"]`)!;
}

function radio(id: string): HTMLInputElement {
  return option(id).querySelector<HTMLInputElement>('input[type="radio"]')!;
}

function confirmBtn(): HTMLButtonElement {
  return container.querySelector<HTMLButtonElement>('[data-action="confirm-profile"]')!;
}

function selectProfile(id: string): void {
  // React normalises radio/checkbox onChange onto the native `click`, so click the
  // control (jsdom flips `checked` + fires the event React listens to).
  act(() => radio(id).click());
}

function toggleBundle(id: string): void {
  act(() => {
    container
      .querySelector(`[data-bundle="${id}"]`)!
      .querySelector<HTMLInputElement>('input[type="checkbox"]')!
      .click();
  });
}

describe('DEFAULT_PROFILE_ID', () => {
  it('is the recommended profile (Default)', () => {
    expect(DEFAULT_PROFILE_ID).toBe('default');
  });
});

describe('ProfilePicker', () => {
  it('renders all four profiles with Default pre-selected + a Recommended badge', () => {
    render(vi.fn());
    for (const id of ['minimum', 'default', 'full', 'custom']) {
      expect(option(id)).not.toBeNull();
    }
    expect(radio('default').checked).toBe(true);
    expect(option('default').className).toContain('is-selected');
    // exactly one Recommended badge, on Default
    const badges = container.querySelectorAll('.profile-picker__badge');
    expect(badges).toHaveLength(1);
    expect(option('default').querySelector('.profile-picker__badge')).not.toBeNull();
  });

  it('shows each profile its single-source approx download size', () => {
    render(vi.fn());
    expect(container.querySelector('[data-testid="size-minimum"]')!.textContent).toBe(
      profileSizeLabel('minimum'),
    );
    expect(container.querySelector('[data-testid="size-full"]')!.textContent).toBe(
      profileSizeLabel('full'),
    );
  });

  it('hides the feature-bundle packs until Custom is selected', () => {
    render(vi.fn());
    expect(container.querySelector('.profile-picker__bundles')).toBeNull();
    selectProfile('custom');
    expect(container.querySelector('.profile-picker__bundles')).not.toBeNull();
    // the two bundles render
    expect(container.querySelector('[data-bundle="transcription"]')).not.toBeNull();
    expect(container.querySelector('[data-bundle="ai-director"]')).not.toBeNull();
  });

  it('commits a fixed profile with NO bundles', () => {
    const onChoose = vi.fn();
    render(onChoose);
    selectProfile('minimum');
    act(() => confirmBtn().click());
    expect(onChoose).toHaveBeenCalledWith('minimum', []);
  });

  it('commits Custom with the toggled bundles and reflects their size live', () => {
    const onChoose = vi.fn();
    render(onChoose);
    selectProfile('custom');
    // custom size starts at the floor-only size
    expect(container.querySelector('[data-testid="size-custom"]')!.textContent).toBe(
      profileSizeLabel('custom', []),
    );
    toggleBundle('ai-director');
    // the custom option size + confirm button now reflect the pick
    expect(container.querySelector('[data-testid="size-custom"]')!.textContent).toBe(
      profileSizeLabel('custom', ['ai-director']),
    );
    expect(confirmBtn().textContent).toBe(`Install ${profileSizeLabel('custom', ['ai-director'])}`);
    act(() => confirmBtn().click());
    expect(onChoose).toHaveBeenCalledWith('custom', ['ai-director']);
  });

  it('toggling a bundle twice removes it again', () => {
    const onChoose = vi.fn();
    render(onChoose);
    selectProfile('custom');
    toggleBundle('transcription');
    toggleBundle('transcription');
    act(() => confirmBtn().click());
    expect(onChoose).toHaveBeenCalledWith('custom', []);
  });

  it('switching away from Custom commits the fixed profile (bundles ignored)', () => {
    const onChoose = vi.fn();
    render(onChoose);
    selectProfile('custom');
    toggleBundle('ai-director');
    selectProfile('full');
    expect(container.querySelector('.profile-picker__bundles')).toBeNull();
    act(() => confirmBtn().click());
    expect(onChoose).toHaveBeenCalledWith('full', []);
  });
});
