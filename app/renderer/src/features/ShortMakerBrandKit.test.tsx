// ShortMakerBrandKit.test.tsx — behavioral tests for the pure presentational
// brand-kit section. Mounts the component directly and exercises: the collapse
// toggle, the logo row (set vs empty, pick + clear), the caption-template +
// font-family edits, and all three data-folder states (loading / path /
// unavailable) plus the change button and the pending-restart note.

// @vitest-environment jsdom
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ShortMakerBrandKit } from './ShortMakerBrandKit';
import { EMPTY_BRAND_SETTINGS, type BrandSettings } from './shortMakerPresets';

describe('<ShortMakerBrandKit />', () => {
  let container: HTMLDivElement;
  let root: Root;
  let onToggle: ReturnType<typeof vi.fn>;
  let onPickLogo: ReturnType<typeof vi.fn>;
  let setBrandField: ReturnType<typeof vi.fn>;
  let onChangeDataFolder: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    onToggle = vi.fn();
    onPickLogo = vi.fn();
    setBrandField = vi.fn();
    onChangeDataFolder = vi.fn();
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function mount(
    over: {
      brand?: Partial<BrandSettings>;
      open?: boolean;
      dataFolder?: string | null;
      dataFolderLoaded?: boolean;
      dataFolderPendingRestart?: boolean;
    } = {},
  ) {
    const brand: BrandSettings = { ...EMPTY_BRAND_SETTINGS, ...over.brand };
    act(() => {
      root.render(
        <ShortMakerBrandKit
          brand={brand}
          open={over.open ?? true}
          onToggle={onToggle}
          onPickLogo={onPickLogo}
          setBrandField={setBrandField}
          dataFolder={over.dataFolder ?? null}
          dataFolderLoaded={over.dataFolderLoaded ?? true}
          dataFolderPendingRestart={over.dataFolderPendingRestart ?? false}
          onChangeDataFolder={onChangeDataFolder}
        />,
      );
    });
  }

  function byLabel(label: string): HTMLElement {
    return container.querySelector(`[aria-label="${label}"]`) as HTMLElement;
  }

  it('collapses the body when closed and fires onToggle on the header', () => {
    mount({ open: false });
    expect(container.querySelector('.sm-brand-body')).toBeNull();
    act(() => (container.querySelector('.sm-brand-toggle') as HTMLButtonElement).click());
    expect(onToggle).toHaveBeenCalled();
  });

  it('shows "No logo set" and only the pick button when no logo is configured', () => {
    mount({ brand: { brandLogoPath: '' } });
    expect(container.querySelector('.sm-brand-logo-empty')?.textContent).toContain('No logo set');
    expect(container.querySelector('[aria-label="Clear logo"]')).toBeNull();
    act(() => (byLabel('Pick logo file') as HTMLButtonElement).click());
    expect(onPickLogo).toHaveBeenCalled();
  });

  it('shows the logo path with a Clear button that clears the field', () => {
    mount({ brand: { brandLogoPath: '/logos/me.png' } });
    expect(container.querySelector('.sm-brand-logo-path')?.textContent).toBe('/logos/me.png');
    act(() => (byLabel('Clear logo') as HTMLButtonElement).click());
    expect(setBrandField).toHaveBeenCalledWith('brandLogoPath', '');
  });

  it('forwards caption-template and font-family edits to setBrandField', () => {
    mount();
    const template = byLabel('Default caption template') as HTMLSelectElement;
    act(() => {
      template.value = 'hormozi';
      template.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(setBrandField).toHaveBeenCalledWith('brandCaptionTemplate', 'hormozi');

    const font = byLabel('Default font family') as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(font, 'Inter');
      font.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(setBrandField).toHaveBeenCalledWith('brandFontFamily', 'Inter');
  });

  it('shows the data-folder loading state before it resolves', () => {
    mount({ dataFolderLoaded: false });
    expect(container.querySelector('.sm-data-folder-loading')).toBeTruthy();
    expect(container.querySelector('.sm-data-folder-path')).toBeNull();
  });

  // THE FOURTH BARE "Loading…". The EmptyState/Skeleton lane enumerated three
  // (Settings.tsx, Workspace.tsx, App.tsx) and shipped components/Skeleton.tsx;
  // this site was named nowhere on that branch and kept a hand-rolled
  // `<span aria-live="polite">Loading…</span>`. These two tests pin the adoption
  // so it cannot silently revert to a bare string.
  it('renders the SHARED skeleton for the data-folder wait, not a bare "Loading…"', () => {
    mount({ dataFolderLoaded: false });
    const region = container.querySelector('.sm-data-folder-loading') as HTMLElement;
    // The shared component, identified by ITS class — a hand-rolled span cannot
    // pass this without becoming the component.
    expect(region.classList.contains('skeleton-group')).toBe(true);
    expect(region.classList.contains('skeleton-group--line')).toBe(true);
    // One shimmer bar riding the single `.skeleton` base rule in shell.css.
    expect(region.querySelectorAll('span.skeleton.skeleton--line')).toHaveLength(1);
    // The bare string is gone from the VISIBLE design (it survives only as the
    // clipped label asserted below).
    expect(region.textContent).not.toBe('Loading…');
  });

  // THE 0px TRAP — now pinned where the FIX lives, not where the workaround did.
  //
  // MEASURED IN REAL CHROMIUM: this adoption, shipped bare, computed 0.00 x 10 px and
  // was INVISIBLE, where the span it replaced measured 47.14 x 16.50. `.skeleton-group`
  // is a shrink-to-fit flex item of `.sm-data-folder-row` and its only in-flow child is
  // an EMPTY span at `width: 100%`, so the percentage resolves against an indefinite
  // width and contributes 0 to intrinsic sizing (the label that would have given it
  // content is `position: absolute`).
  //
  // It was first fixed with an inline `width: 160px` wrapper at THIS call site, and two
  // tests here pinned that wrapper as the contract — which made the proper stylesheet
  // fix red-on-arrival for whoever attempted it. The floor now lives once in
  // emptyState.css (`.skeleton-group { min-width: 8rem }`), so the wrapper is gone and
  // every future adopter inherits it. These assertions moved with the fix.
  //
  // jsdom has no layout engine, so this pins the MECHANISM — a definite floor exists on
  // the box that establishes the bar's containing block — not the pixel count. Deleting
  // the rule makes the skeleton invisible again and no other test would notice.
  it('the shared skeleton group declares a width floor, so a 100%-wide bar is never 0px', () => {
    const css = readFileSync(
      resolve(dirname(fileURLToPath(import.meta.url)), '../components/emptyState.css'),
      'utf8',
    ).replace(/\/\*[\s\S]*?\*\//g, ' '); // use-not-mention: prose must not satisfy this

    const body = /(?:^|\})\s*\.skeleton-group\s*\{([^}]*)\}/m.exec(css)?.[1] ?? null;
    // DETECTOR CONTROL: if the rule is not found, every assertion below is vacuous.
    expect(body, 'no `.skeleton-group` rule found in emptyState.css').not.toBeNull();
    expect(body).toContain('display: flex');

    const minWidth = /(?:^|;)\s*min-width\s*:\s*([^;]+)/.exec(body as string)?.[1]?.trim();
    expect(
      minWidth,
      '`.skeleton-group` must declare a min-width: as a flex item it is shrink-to-fit, ' +
        'so its 100%-wide bars resolve to 0 and the skeleton renders invisible',
    ).toBeTruthy();
    // Not a truthy-string check: "0" and "0px" are truthy and would re-ship the bug.
    expect(Number.parseFloat(minWidth ?? '0')).toBeGreaterThan(0);
  });

  it('no longer carries a per-call-site inline width workaround', () => {
    // The complement: proves the fix REPLACED the workaround rather than sitting
    // beside it. A stray inline width here would mask a regression of the rule above.
    mount({ dataFolderLoaded: false });
    const region = container.querySelector('.sm-data-folder-loading') as HTMLElement;
    const sized = region.closest('[style]') as HTMLElement | null;
    const row = region.closest('.sm-data-folder-row');
    expect(sized === null || sized === row || !row?.contains(sized)).toBe(true);
  });

  it('pins a busy status region whose clipped text names the data folder', () => {
    mount({ dataFolderLoaded: false });
    const region = container.querySelector('.sm-data-folder-loading') as HTMLElement;
    // `role="status"` carries an IMPLICIT `aria-live="polite"` (+ aria-atomic)
    // per WAI-ARIA, which is why dropping the explicit attribute preserves the
    // semantics rather than losing them. jsdom computes no implicit ARIA, so the
    // role is the thing a test can pin — pinned here precisely so a future edit
    // cannot delete the role and leave the wait with no live semantics at all.
    // The title deliberately does NOT say "announceable": that is a property this
    // test cannot reach, and ShortMakerBrandKit.tsx records that the `aria-busy`
    // asserted below — mounted true, never cleared — makes announcement LESS
    // likely, not more. Announceability stays NOT-CHECKED until the both-states
    // NVDA probe runs; what is pinned here is the role, the busy flag, and the text.
    expect(region.getAttribute('role')).toBe('status');
    expect(region.getAttribute('aria-busy')).toBe('true');
    // Content, not a name: Skeleton renders the wait as a clipped text node and
    // deliberately ships no aria-label (pinned by Skeleton.test.tsx).
    expect(region.getAttribute('aria-label')).toBeNull();
    expect(region.querySelector('.skeleton-group__label')?.textContent).toBe('Loading data folder');
  });

  it('shows the resolved data-folder path once loaded', () => {
    mount({ dataFolderLoaded: true, dataFolder: 'D:/MediaStudio/data' });
    expect(container.querySelector('.sm-data-folder-path')?.textContent).toBe(
      'D:/MediaStudio/data',
    );
  });

  it('shows "Unavailable" when loaded with no data folder', () => {
    mount({ dataFolderLoaded: true, dataFolder: null });
    expect(container.querySelector('.sm-data-folder-empty')?.textContent).toContain('Unavailable');
  });

  it('fires onChangeDataFolder on the Change… button', () => {
    mount();
    act(() => (byLabel('Change data folder') as HTMLButtonElement).click());
    expect(onChangeDataFolder).toHaveBeenCalled();
  });

  it('shows the pending-restart note after a change', () => {
    mount({ dataFolderPendingRestart: true });
    expect(container.querySelector('.sm-data-folder-restart')?.textContent).toContain(
      'Restart to apply',
    );
  });
});
