// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Deliver } from './Deliver';
import type { Video } from '../lib/rpc';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

// Deliver only COMPOSES the (separately-covered) cluster panels; stub them so this
// test exercises Deliver's own tabs/routing, not the children's mount effects.
vi.mock('../features/BatchQueue', () => ({
  BatchQueue: () => <div data-stub="batch-queue" />,
}));
vi.mock('../features/ExportPresetsPanel', () => ({
  ExportPresetsPanel: () => <div data-stub="export-presets" />,
}));
vi.mock('../features/NleExport', () => ({
  NleExport: ({ videoId }: { videoId: string }) => (
    <div data-stub="nle-export" data-video={videoId} />
  ),
}));
// Records the prop KEYS it was mounted with. Q4 removed every control from the
// Publish panel, so it now takes nothing: passing it a videoId again would be the
// first step back to a per-video publish action this build cannot perform.
vi.mock('../features/SocialPublishPanel', () => ({
  SocialPublishPanel: (props: Record<string, unknown>) => (
    <div data-stub="social-publish" data-props={JSON.stringify(Object.keys(props))} />
  ),
}));

const VIDEO: Video = {
  id: 'v1',
  path: '/clips/x.mp4',
  title: 'My Clip',
  addedAt: '2026-01-01',
  durationSec: 40,
  hasTranscript: true,
};

let container: HTMLDivElement;
let root: Root;
const onBack = vi.fn();

beforeEach(() => {
  onBack.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

const q = <T extends Element>(sel: string): T | null => container.querySelector<T>(sel);
const all = (sel: string): Element[] => Array.from(container.querySelectorAll(sel));

function render(video: Video | null): void {
  act(() => {
    root.render(<Deliver video={video} onBack={onBack} />);
  });
}

const clickTab = (label: string): void => {
  const tab = all('[role="tab"]').find((el) => el.textContent === label);
  act(() => (tab as HTMLElement | undefined)?.click());
};

describe('Deliver view', () => {
  it('scopes Deliver as batch/cross-video, states the aspect matrix as prose, and routes back', () => {
    render(VIDEO);
    expect(q('.deliver-view__title')?.textContent).toBe('Deliver');
    // Q5: the four ratios are INFORMATION, so they read as prose in the intro.
    const intro = q('.deliver-view__intro')?.textContent ?? '';
    expect(intro).toContain('9:16');
    expect(intro).toContain('4:5');
    expect(intro).toContain('1:1');
    expect(intro).toContain('16:9');
    // Batch publish is the default landing.
    expect(q('[data-stub="batch-queue"]')).not.toBeNull();
    act(() => q<HTMLButtonElement>('.deliver-view__back')?.click());
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('renders the ratios as text, NOT as pills in the grammar of a target selector', () => {
    // Q5. The row of labelled spans had no handler and no role while sitting
    // directly above the tab strip, where the real multi-select (one tab away in
    // ExportPresetsPanel) trained the user to expect a chooser. Absence is the
    // assertion, so each locator is anchored to a different attribute of the old
    // markup — class, element vocabulary, and the accessible name.
    render(VIDEO);
    expect(q('.deliver-view__aspects')).toBeNull();
    expect(all('.deliver-view__aspect')).toEqual([]);
    expect(all('.deliver-view__aspect-ratio')).toEqual([]);
    expect(all('.deliver-view__aspect-label')).toEqual([]);
    expect(q('[aria-label="Target aspect ratios"]')).toBeNull();
  });

  it('keeps all four Deliver destinations reachable from one tab strip', () => {
    // Wave-1 acceptance, structural half: removing the pill row must not cost a
    // destination. Geometric overflow at 1280px is NOT measurable under jsdom
    // (no layout engine) — that check belongs to the Playwright pass, and this
    // change only ever REMOVES a horizontally-laid-out row above the strip.
    render(VIDEO);
    expect(all('[role="tab"]').map((el) => el.textContent)).toEqual([
      'Batch publish',
      'Platform presets',
      'Publish',
      'Pro handoff',
    ]);
    clickTab('Platform presets');
    expect(q('[data-stub="export-presets"]')).not.toBeNull();
    clickTab('Publish');
    expect(q('[data-stub="social-publish"]')).not.toBeNull();
    clickTab('Pro handoff');
    expect(q('[data-stub="nle-export"]')).not.toBeNull();
  });

  it('switches to the platform-preset matrix', () => {
    render(VIDEO);
    clickTab('Platform presets');
    expect(q('[data-stub="export-presets"]')).not.toBeNull();
    expect(q('[data-stub="batch-queue"]')).toBeNull();
  });

  it('switches to the Publish panel and mounts it with NO props', () => {
    // Q4: the panel is a blocked state, not a per-video action. Handing it a
    // videoId again would re-imply that opening a video enables a publish.
    render(VIDEO);
    clickTab('Publish');
    expect(q('[data-stub="social-publish"]')?.getAttribute('data-props')).toBe('[]');
    expect(q('[data-stub="batch-queue"]')).toBeNull();
  });

  it('still shows Publish with no video open (it is a destination, not a per-video action)', () => {
    render(null);
    clickTab('Publish');
    expect(q('[data-stub="social-publish"]')?.getAttribute('data-props')).toBe('[]');
  });

  it('hands the open video off to the pro-editor export', () => {
    render(VIDEO);
    clickTab('Pro handoff');
    expect(q('[data-stub="nle-export"]')?.getAttribute('data-video')).toBe('v1');
  });

  it('explains the pro handoff needs an open video when none is open', () => {
    render(null);
    clickTab('Pro handoff');
    expect(q('[data-stub="nle-export"]')).toBeNull();
    expect(q('.deliver-view__empty')?.textContent).toContain('Open a video from the Library');
  });
});
