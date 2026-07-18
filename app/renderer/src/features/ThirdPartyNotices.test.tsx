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
import {
  ThirdPartyNotices,
  THIRD_PARTY_NOTICES,
  FONT_NOTICES,
  FONT_LICENSE_FILE,
} from './ThirdPartyNotices';

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

describe('ThirdPartyNotices — bundled fonts (WU-1.5 fonts)', () => {
  it('surfaces the self-hosted OFL type trio with verbatim copyright + source', async () => {
    await mount();
    const text = container.textContent ?? '';
    // The three families, each by its verbatim OFL copyright line.
    expect(text).toContain('Inter');
    expect(text).toContain('Newsreader');
    expect(text).toContain('IBM Plex Mono');
    expect(text).toContain('Copyright 2020 The Inter Project Authors');
    expect(text).toContain('Copyright 2020 The Newsreader Project Authors');
    expect(text).toContain('IBM Corp. with Reserved Font Name');
    // The permissive OFL is named (not hue alone).
    expect(text).toContain('SIL Open Font License');
    // Source repos are linked.
    expect(container.querySelector('a[href="https://github.com/rsms/inter"]')).not.toBeNull();
    expect(
      container.querySelector('a[href="https://github.com/productiontype/Newsreader"]'),
    ).not.toBeNull();
    expect(container.querySelector('a[href="https://github.com/IBM/plex"]')).not.toBeNull();
  });

  it('points at the vendored OFL.txt that ships beside the woff2 binaries', async () => {
    await mount();
    const fontsSection = container.querySelector('.tpn__fonts');
    expect(fontsSection).not.toBeNull();
    const codes = Array.from(fontsSection?.querySelectorAll('code') ?? []).map(
      (c) => c.textContent,
    );
    expect(codes).toContain(FONT_LICENSE_FILE);
    expect(FONT_LICENSE_FILE).toBe('renderer/src/assets/fonts/OFL.txt');
  });

  it('chips every font OFL-1.1 without disturbing the model commercial/non-commercial chips', async () => {
    await mount();
    // Fonts carry their own OFL chip class, so the model chip counts are unchanged.
    expect(container.querySelectorAll('.tpn__chip--ofl')).toHaveLength(3);
    expect(container.querySelectorAll('.tpn__chip--ok')).toHaveLength(4);
  });

  it('exports exactly the three fonts, all OFL and commercial-OK', () => {
    expect(FONT_NOTICES.map((f) => f.name)).toEqual(['Inter', 'Newsreader', 'IBM Plex Mono']);
    expect(FONT_NOTICES.every((f) => f.license === 'OFL-1.1')).toBe(true);
    expect(FONT_NOTICES.every((f) => f.commercial)).toBe(true);
  });
});
