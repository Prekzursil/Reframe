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
  FFMPEG_NOTICE,
  OPT_IN_MODEL_NOTICES,
  ALIGNER_MODEL_NOTICES,
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
    // Scoped to the MODELS list (the section's own direct-child <ul>) so the
    // "exactly two" invariant keeps meaning "two vendored NETWORKS". The bundled-
    // programs section below ships its own LICENSE path (ffmpeg's GPL text), which
    // is a different obligation and is asserted separately.
    const files = Array.from(container.querySelectorAll('.tpn > .tpn__list .tpn__file code')).map(
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

  // --- FFmpeg: a REDISTRIBUTED GPL BINARY, not a model -------------------------
  // The models above are weights we load; ffmpeg.exe is a whole executable we ship
  // inside the installer, and it is GPL-3.0-or-later because Reframe needs the
  // GPL-only libx264 encoder. GPL redistribution obliges an offer of the
  // CORRESPONDING SOURCE, so the notice must name the exact upstream revision — a
  // generic "we use FFmpeg" credit does not discharge that.
  it('names the exact FFmpeg build it redistributes', () => {
    expect(FFMPEG_NOTICE.license).toBe('GPL-3.0-or-later');
    expect(FFMPEG_NOTICE.version).toBe('n7.1.5-1-g7d0e842004');
    expect(FFMPEG_NOTICE.buildTag).toBe('autobuild-2026-06-30-13-34');
    expect(FFMPEG_NOTICE.asset).toBe('ffmpeg-n7.1.5-1-g7d0e842004-win64-gpl-7.1.zip');
    // The one-letter difference that caused the defect. If this ever reads
    // `-lgpl-` again the shipped binary cannot encode H.264 at all.
    expect(FFMPEG_NOTICE.asset).toContain('-win64-gpl-');
    expect(FFMPEG_NOTICE.asset).not.toContain('-win64-lgpl-');
  });

  it('offers the corresponding source at the pinned commit, not just a project link', async () => {
    await mount();
    const text = container.textContent ?? '';
    expect(text).toContain('GPL-3.0-or-later');
    // A source offer has to be reachable and revision-exact.
    expect(FFMPEG_NOTICE.sourceUrl).toBe('https://github.com/FFmpeg/FFmpeg/tree/7d0e842004');
    expect(text).toContain(FFMPEG_NOTICE.sourceUrl);
    expect(text).toContain(FFMPEG_NOTICE.buildScriptsUrl);
    // ...and the full licence text has to travel with the binary.
    expect(FFMPEG_NOTICE.licenseFile).toBe('resources/bin/LICENSE.txt');
    const binaryFiles = Array.from(
      container.querySelectorAll('.tpn__binaries .tpn__file code'),
    ).map((c) => c.textContent);
    expect(binaryFiles).toEqual([FFMPEG_NOTICE.licenseFile]);
  });

  it('states that shipping GPL ffmpeg does not relicense Reframe, and why', async () => {
    await mount();
    const text = container.textContent ?? '';
    expect(text).toContain('separate child process');
    expect(FFMPEG_NOTICE.note).toContain('separate child process');
  });

  it('renders ffmpeg in its own section so the model chip counts are undisturbed', async () => {
    await mount();
    expect(container.querySelector('.tpn__binaries')).not.toBeNull();
    // The pre-existing model/font chip counts are load-bearing assertions above;
    // a GPL binary is neither "Commercial OK" nor OFL, so it gets its own chip.
    expect(container.querySelectorAll('.tpn__chip--ok')).toHaveLength(4);
    expect(container.querySelectorAll('.tpn__chip--ofl')).toHaveLength(3);
    expect(container.querySelectorAll('.tpn__chip--copyleft')).toHaveLength(1);
  });
});

// --- OPT-IN OpenRAIL models (lip-sync, WU-B1) ---------------------------------
// Weights that are NOT shipped: downloaded only when `lipSyncEnabled` is on. The
// licence class is the whole point of this block — OpenRAIL PERMITS commercial
// use and attaches behavioural use-restrictions, and a notice that states only
// one of those two halves is a misrepresentation either way.
describe('ThirdPartyNotices — opt-in OpenRAIL models (WU-B1 lip-sync)', () => {
  it('names both engines with their VERIFIED weights licence tags', async () => {
    await mount();
    const text = container.textContent ?? '';
    expect(text).toContain('LatentSync');
    expect(text).toContain('MuseTalk');
    // The Hub tags, exactly as the Hub reports them (verified 2026-08-08).
    expect(text).toContain('openrail++');
    expect(text).toContain('creativeml-openrail-m');
    // The code licence differs from the weights licence for both, and saying so
    // is the point: quoting only one of the pair misstates the position.
    expect(text).toContain('Apache-2.0');
    expect(text).toContain('MIT');
  });

  it('states BOTH halves of the OpenRAIL position, not just the permissive half', async () => {
    await mount();
    const section = container.querySelector('.tpn__optin');
    expect(section).not.toBeNull();
    const text = section?.textContent ?? '';
    expect(text).toContain('Commercial use IS permitted');
    expect(text).toContain('prohibited USES');
    expect(text).toContain('pass those same restrictions on');
    // ...and it must NOT claim the licence is non-commercial.
    expect(text).not.toContain('Non-commercial');
  });

  it('surfaces the likeness attestation and the S3FD avoidance as obligations', async () => {
    await mount();
    const text = container.querySelector('.tpn__optin')?.textContent ?? '';
    expect(text).toContain('right to modify the on-screen person');
    expect(text).toContain('S3FD');
    // Each engine names the setting that gates its download.
    expect(container.querySelectorAll('.tpn__optin code')).toHaveLength(2);
    expect(text).toContain('lipSyncEnabled');
  });

  it('chips them as their own third state, leaving every existing count intact', async () => {
    await mount();
    const chips = container.querySelectorAll('.tpn__chip--userestricted');
    expect(chips).toHaveLength(2);
    // Both halves in the chip TEXT, so the meaning survives without colour.
    expect(chips[0]?.textContent).toContain('commercial OK, use-restricted');
    expect(chips[0]?.getAttribute('data-commercial')).toBe('yes');
    expect(chips[0]?.getAttribute('data-use-restricted')).toBe('yes');
    // The pre-existing chip counts are unchanged — an OpenRAIL model is neither
    // "Commercial OK" (incomplete) nor "Non-commercial" (false), so it does not
    // borrow either class, and it is not OFL or copyleft.
    expect(container.querySelectorAll('.tpn__chip--ok')).toHaveLength(4);
    expect(container.querySelectorAll('.tpn__chip--nc')).toHaveLength(1);
    expect(container.querySelectorAll('.tpn__chip--ofl')).toHaveLength(3);
    expect(container.querySelectorAll('.tpn__chip--copyleft')).toHaveLength(1);
  });

  it('keeps opt-in models OUT of the bundled-model list', () => {
    // THIRD_PARTY_NOTICES documents what SHIPS. Listing an un-shipped weight
    // there would misreport the build, and would silently break the "exactly one
    // non-commercial model" invariant above.
    const bundled = THIRD_PARTY_NOTICES.map((n) => n.name);
    for (const n of OPT_IN_MODEL_NOTICES) expect(bundled).not.toContain(n.name);
  });

  it('exports exactly the two OpenRAIL engines, both commercial-OK and use-restricted', () => {
    expect(OPT_IN_MODEL_NOTICES.map((n) => n.name)).toEqual(['LatentSync', 'MuseTalk']);
    expect(OPT_IN_MODEL_NOTICES.every((n) => n.commercial)).toBe(true);
    expect(OPT_IN_MODEL_NOTICES.every((n) => n.useRestricted)).toBe(true);
    expect(OPT_IN_MODEL_NOTICES.every((n) => n.gatedBy === 'lipSyncEnabled')).toBe(true);
    // Wav2Lip is genuinely non-commercial and must never appear here.
    expect(OPT_IN_MODEL_NOTICES.map((n) => n.name.toLowerCase())).not.toContain('wav2lip');
  });

  it('renders the optional-paper branch for LatentSync and omits it for MuseTalk', async () => {
    await mount();
    const items = Array.from(container.querySelectorAll('.tpn__optin .tpn__item'));
    expect(items).toHaveLength(2);
    expect(items[0]?.querySelector('.tpn__paper')?.textContent).toContain('arXiv:2412.09262');
    expect(items[1]?.querySelector('.tpn__paper')).toBeNull();
  });
});

// --- Word-timing CTC aligners (v1.5 WU-T0 / B1) --------------------------------
// The CC-BY-NC-4.0 MMS aligner shipped from Phase-8 with NO user-facing notice at
// all — searching this file for `mms-300m`, `forced-aligner` or `MahmoudAshraf`
// returned nothing before this block existed. CC-BY-NC REQUIRES attribution, so
// the absence was a live licence breach independent of the commercial question.
// It gets its OWN list because neither existing list can hold it: adding it to
// THIRD_PARTY_NOTICES breaks the asserted "exactly one non-commercial model
// (ViNet-S)" invariant and the `.tpn__chip--nc` count, and adding it to
// OPT_IN_MODEL_NOTICES would be false — that list is OpenRAIL, commercial-OK by
// construction, and asserts `every(n => n.commercial)`.
describe('ThirdPartyNotices — word-timing aligners (WU-T0)', () => {
  it('discloses the CC-BY-NC MMS aligner that previously appeared nowhere', async () => {
    await mount();
    const text = container.querySelector('.tpn__aligners')?.textContent ?? '';
    expect(text).toContain('MMS-300M');
    expect(text).toContain('MahmoudAshraf/mms-300m-1130-forced-aligner');
    expect(text).toContain('CC-BY-NC-4.0');
    // Attribution is the actual CC-BY-NC obligation — the author must be named.
    expect(text).toContain('Mahmoud Ashraf');
    expect(
      container.querySelector('a[href="https://creativecommons.org/licenses/by-nc/4.0/"]'),
    ).not.toBeNull();
  });

  it('names the setting that gates the non-commercial model and says it is off', async () => {
    await mount();
    const text = container.querySelector('.tpn__aligners')?.textContent ?? '';
    expect(text).toContain('allowNonCommercialAligner');
    expect(text).toContain('off by default');
    const mms = ALIGNER_MODEL_NOTICES.find((n) => n.name.includes('MMS-300M'));
    expect(mms?.commercial).toBe(false);
    expect(mms?.gatedBy).toBe('allowNonCommercialAligner');
  });

  it('names the Apache-2.0 packaged default and never calls it MIT', async () => {
    const def = ALIGNER_MODEL_NOTICES.find((n) => n.packagedDefault);
    expect(def?.modelId).toBe('facebook/wav2vec2-large-960h-lv60-self');
    expect(def?.license).toBe('Apache-2.0');
    // The code called these three "MIT_MODEL_IDS"; the HF Hub says apache-2.0
    // for all of them (probed 2026-08-09). A licence claim must not be restated
    // from a neighbouring comment.
    expect(ALIGNER_MODEL_NOTICES.every((n) => n.license !== 'MIT')).toBe(true);
    expect(ALIGNER_MODEL_NOTICES.filter((n) => n.packagedDefault)).toHaveLength(1);
  });

  it('chips aligners as their own state, leaving every existing count intact', async () => {
    await mount();
    expect(container.querySelectorAll('.tpn__chip--aligner').length).toBe(
      ALIGNER_MODEL_NOTICES.length,
    );
    // The pre-existing counts are load-bearing assertions elsewhere in this file.
    expect(container.querySelectorAll('.tpn__chip--ok')).toHaveLength(4);
    expect(container.querySelectorAll('.tpn__chip--nc')).toHaveLength(1);
    expect(container.querySelectorAll('.tpn__chip--ofl')).toHaveLength(3);
    expect(container.querySelectorAll('.tpn__chip--copyleft')).toHaveLength(1);
    expect(container.querySelectorAll('.tpn__chip--userestricted')).toHaveLength(2);
  });

  it('keeps aligners out of the bundled and OpenRAIL lists', () => {
    const bundled = THIRD_PARTY_NOTICES.map((n) => n.name);
    const optIn = OPT_IN_MODEL_NOTICES.map((n) => n.name);
    for (const n of ALIGNER_MODEL_NOTICES) {
      expect(bundled).not.toContain(n.name);
      expect(optIn).not.toContain(n.name);
    }
    // ...and the "exactly one non-commercial bundled model" invariant survives.
    expect(THIRD_PARTY_NOTICES.filter((n) => !n.commercial)).toHaveLength(1);
  });

  it('renders the optional gate/note branches for the gated model only', async () => {
    await mount();
    const items = Array.from(container.querySelectorAll('.tpn__aligners .tpn__item'));
    expect(items).toHaveLength(ALIGNER_MODEL_NOTICES.length);
    // The permissive entries carry no gate chip text and no obligation note.
    const permissive = items.filter((i) => i.querySelector('.tpn__note') === null);
    expect(permissive.length).toBe(ALIGNER_MODEL_NOTICES.filter((n) => !n.note).length);
    expect(permissive.length).toBeGreaterThan(0);
  });
});
