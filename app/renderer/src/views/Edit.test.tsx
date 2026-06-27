// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Video } from '../lib/rpc';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

// The Workspace is the heavy per-video body (owns its own tests); stub it.
vi.mock('./Workspace', () => ({
  Workspace: ({ video, onBack }: { video: Video; onBack: () => void }) => (
    <div data-testid="workspace" data-video-id={video.id}>
      <button type="button" onClick={onBack}>
        back
      </button>
    </div>
  ),
}));

import { Edit } from './Edit';

function makeVideo(): Video {
  return {
    id: 'v1',
    path: '/m/a.mp4',
    title: 'A',
    addedAt: '2026-06-27T00:00:00Z',
    durationSec: 100,
    hasTranscript: false,
  };
}

describe('<Edit />', () => {
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

  it('shows the empty state when no video is open', () => {
    act(() => root.render(<Edit video={null} onBack={() => undefined} />));
    expect(container.querySelector('.edit--empty')).toBeTruthy();
    expect(container.querySelector('.edit__empty-title')?.textContent).toBe('No video open');
    expect(container.querySelector('[data-testid="workspace"]')).toBeNull();
  });

  it('hosts the per-video Workspace when a video is open', () => {
    const onBack = vi.fn();
    act(() => root.render(<Edit video={makeVideo()} onBack={onBack} />));
    const ws = container.querySelector('[data-testid="workspace"]');
    expect(ws).toBeTruthy();
    expect(ws!.getAttribute('data-video-id')).toBe('v1');
    act(() =>
      (container.querySelector('[data-testid="workspace"] button') as HTMLButtonElement).click(),
    );
    expect(onBack).toHaveBeenCalled();
  });
});
