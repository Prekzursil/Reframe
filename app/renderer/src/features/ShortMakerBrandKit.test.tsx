// ShortMakerBrandKit.test.tsx — behavioral tests for the pure presentational
// brand-kit section. Mounts the component directly and exercises: the collapse
// toggle, the logo row (set vs empty, pick + clear), the caption-template +
// font-family edits, and all three data-folder states (loading / path /
// unavailable) plus the change button and the pending-restart note.

// @vitest-environment jsdom
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
