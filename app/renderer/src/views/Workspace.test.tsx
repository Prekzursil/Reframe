// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const rpcMock = vi.fn();
vi.mock('../components/api', () => ({
  rpc: (...args: unknown[]) => rpcMock(...args),
  onProgress: () => () => {},
  hasApi: () => true,
}));

import { Workspace, WORKSPACE_TABS } from './Workspace';
import type { Video, Project } from '../components/api';

// CONTRACT-NOTE: the feature panels (../features/*) are authored by a sibling unit
// and do not exist on disk when this shell is tested in isolation. The Workspace
// loads them lazily and falls back to a "panel is not available" placeholder when
// the dynamic import fails — that fallback is what these tests assert. Once the
// feature modules land, the real panels render in their place (covered by their
// own unit tests). This keeps the shell's tests independent of sibling units.

const video: Video = {
  id: 'v1',
  path: '/movies/talk.mp4',
  title: 'Talk',
  addedAt: '2026-06-11T00:00:00Z',
  durationSec: 605,
  hasTranscript: false,
};

const project: Project = {
  id: 'v1',
  video,
  tracks: [],
  clips: [],
  settings: {},
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  rpcMock.mockReset();
  rpcMock.mockResolvedValue({ project });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function flush(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 8; i++) {
      // eslint-disable-next-line no-await-in-loop
      await Promise.resolve();
    }
  });
}

describe('Workspace', () => {
  it('exposes the contract tabs in order (P2: +Timeline/Dub/Assets; captions-export: +Timeline export; system-advanced: +Diarize/Recipes)', () => {
    expect(WORKSPACE_TABS.map((t) => t.label)).toEqual([
      'Transcribe',
      'Subtitles',
      'Diarize',
      'Tracks',
      'Convert',
      'Short-maker',
      'Timeline',
      'Dub',
      'Timeline export',
      'Recipes',
      'Assets',
    ]);
  });

  it('opens the project via project.open and shows the title + tabs', async () => {
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();

    expect(rpcMock).toHaveBeenCalledWith('project.open', { id: 'v1' });
    expect(container.textContent).toContain('Talk');
    expect(container.querySelectorAll('[role="tab"]').length).toBe(WORKSPACE_TABS.length);
  });

  it('mounts a feature panel slot (placeholder until the panel module exists)', async () => {
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();
    // The default (Transcribe) tab renders either the real panel or the fallback.
    expect(container.querySelector('.workspace__body')).not.toBeNull();
    expect(container.textContent).toContain('Transcribe');
  });

  it('switches the active tab when clicked', async () => {
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();

    const tabs = container.querySelectorAll('[role="tab"]');
    // index 1 = Subtitles
    await act(async () => {
      (tabs[1] as HTMLButtonElement).dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();
    expect(tabs[1].getAttribute('aria-selected')).toBe('true');
    expect(tabs[0].getAttribute('aria-selected')).toBe('false');
  });

  it('calls onBack when the back button is pressed', async () => {
    const onBack = vi.fn();
    await act(async () => {
      root.render(<Workspace video={video} onBack={onBack} />);
    });
    await flush();

    const back = container.querySelector('button.workspace__back') as HTMLButtonElement;
    await act(async () => {
      back.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('surfaces a project.open error', async () => {
    rpcMock.mockReset();
    rpcMock.mockRejectedValue(new Error('open failed'));
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();
    expect(container.textContent).toContain('open failed');
  });
});
