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
  it('scopes Deliver as batch/cross-video with the target aspect matrix, and routes back', () => {
    render(VIDEO);
    expect(q('.deliver-view__title')?.textContent).toBe('Deliver');
    // The 9:16 / 4:5 / 1:1 / 16:9 aspect matrix is shown.
    const ratios = all('.deliver-view__aspect-ratio').map((el) => el.textContent);
    expect(ratios).toEqual(['9:16', '4:5', '1:1', '16:9']);
    // Batch publish is the default landing.
    expect(q('[data-stub="batch-queue"]')).not.toBeNull();
    act(() => q<HTMLButtonElement>('.deliver-view__back')?.click());
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('switches to the platform-preset matrix', () => {
    render(VIDEO);
    clickTab('Platform presets');
    expect(q('[data-stub="export-presets"]')).not.toBeNull();
    expect(q('[data-stub="batch-queue"]')).toBeNull();
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
