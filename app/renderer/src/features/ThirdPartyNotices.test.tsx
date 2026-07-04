// ThirdPartyNotices.test.tsx — the Settings → Licenses surface (WU-F1).
//
// Asserts the mandatory ViNet-S CC-BY-NC-SA-4.0 attribution block is reproduced
// verbatim (authors + paper + license URL + the NON-COMMERCIAL callout), and that
// every other bundled model's license is surfaced, so the security-review HIGH#1b
// attribution obligation is met by the shipped UI, not just documentation.

// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ThirdPartyNotices, THIRD_PARTY_NOTICES } from './ThirdPartyNotices';

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

async function mount(): Promise<void> {
  await act(async () => {
    root.render(<ThirdPartyNotices />);
  });
}

describe('ThirdPartyNotices', () => {
  it('reproduces the ViNet-S CC-BY-NC-SA-4.0 attribution block verbatim', async () => {
    await mount();
    const text = container.textContent ?? '';
    // Authors + affiliation.
    expect(text).toContain(
      '© 2025 Rohit Girmaji, Siddharth Jain, Bhav Beri, Sarthak Bansal, Vineet Gandhi (IIIT Hyderabad)',
    );
    // Paper + arXiv id.
    expect(text).toContain('ViNet-S / ViNet (ICASSP 2025), arXiv:2502.00397');
    // License id + canonical URL.
    expect(text).toContain('CC-BY-NC-SA-4.0');
    const ccLink = container.querySelector<HTMLAnchorElement>(
      'a[href="https://creativecommons.org/licenses/by-nc-sa/4.0/"]',
    );
    expect(ccLink).not.toBeNull();
    // The non-commercial callout is present and marked as a note.
    const note = container.querySelector('.tpn__note');
    expect(note).not.toBeNull();
    expect(note?.textContent).toContain('NON-COMMERCIAL');
    expect(note?.textContent).toContain('remove or replace');
    // ViNet-S is chipped non-commercial (text, not hue alone).
    const vinet = container.querySelector('[data-license="CC-BY-NC-SA-4.0"]');
    expect(vinet?.querySelector('.tpn__chip--nc')?.textContent).toBe('Non-commercial');
  });

  it('surfaces the other bundled model licenses alongside ViNet-S', async () => {
    await mount();
    const text = container.textContent ?? '';
    expect(text).toContain('YuNet');
    expect(text).toContain('EdgeTAM');
    expect(text).toContain('TransNetV2');
    expect(text).toContain('LR-ASD');
    expect(text).toContain('Apache-2.0');
    expect(text).toContain('MIT');
    // Commercial-OK models are chipped as such (both chip branches render).
    const okChips = container.querySelectorAll('.tpn__chip--ok');
    expect(okChips.length).toBe(4);
    expect(okChips[0]?.textContent).toBe('Commercial OK');
  });

  it('points at the vendored LICENSE files for the two vendored networks', async () => {
    await mount();
    const files = Array.from(container.querySelectorAll('.tpn__file code')).map(
      (c) => c.textContent,
    );
    expect(files).toContain('sidecar/media_studio/features/_vinet_s/LICENSE');
    expect(files).toContain('sidecar/media_studio/features/_transnetv2/LICENSE');
    // Exactly the two vendored-network LICENSE paths are surfaced.
    expect(files).toHaveLength(2);
  });

  it('exports the notice list with a single non-commercial model (ViNet-S)', () => {
    const nonCommercial = THIRD_PARTY_NOTICES.filter((n) => !n.commercial);
    expect(nonCommercial.map((n) => n.name)).toEqual(['ViNet-S / ViNet']);
    // A paper citation only exists on the one academic model.
    expect(THIRD_PARTY_NOTICES.filter((n) => n.paper).map((n) => n.name)).toEqual([
      'ViNet-S / ViNet',
    ]);
  });
});
