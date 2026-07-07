// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Video } from '../lib/rpc';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

import { TaskHub } from './TaskHub';

function makeVideo(): Video {
  return {
    id: 'v1',
    path: '/movies/talk.mp4',
    title: 'A Long Talk',
    addedAt: '2026-06-27T00:00:00Z',
    durationSec: 120,
    hasTranscript: false,
  };
}

describe('<TaskHub />', () => {
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

  function cardByText(text: string): HTMLButtonElement {
    const cards = Array.from(container.querySelectorAll<HTMLButtonElement>('.task-hub__card'));
    const found = cards.find((c) => c.textContent?.includes(text));
    if (!found) throw new Error(`card "${text}" not found`);
    return found;
  }

  it('renders the video title + the four job cards and the advanced escape', () => {
    act(() => root.render(<TaskHub video={makeVideo()} lastChoice={null} onChoose={() => undefined} />));
    expect(container.querySelector('.task-hub__title')?.textContent).toBe('A Long Talk');
    expect(container.querySelector('.task-hub__title')?.getAttribute('title')).toBe('/movies/talk.mp4');
    expect(container.querySelectorAll('.task-hub__card').length).toBe(4);
    expect(cardByText('Reframe to vertical')).toBeTruthy();
    expect(cardByText('Make shorts')).toBeTruthy();
    expect(cardByText('Add subtitles')).toBeTruthy();
    expect(cardByText('Director')).toBeTruthy();
    expect(container.querySelector('.task-hub__advanced')).toBeTruthy();
    // with no last choice, nothing is marked.
    expect(container.querySelector('.is-last')).toBeNull();
    expect(container.querySelector('.task-hub__last')).toBeNull();
  });

  it('emits the chosen card id', () => {
    const onChoose = vi.fn();
    act(() => root.render(<TaskHub video={makeVideo()} lastChoice={null} onChoose={onChoose} />));
    act(() => cardByText('Add subtitles').click());
    expect(onChoose).toHaveBeenCalledWith('subtitles');
    act(() => cardByText('Reframe to vertical').click());
    expect(onChoose).toHaveBeenCalledWith('reframe');
  });

  it('emits "advanced" from the all-tools escape', () => {
    const onChoose = vi.fn();
    act(() => root.render(<TaskHub video={makeVideo()} lastChoice={null} onChoose={onChoose} />));
    act(() => (container.querySelector('.task-hub__advanced') as HTMLButtonElement).click());
    expect(onChoose).toHaveBeenCalledWith('advanced');
  });

  it('marks the last-used job card', () => {
    act(() => root.render(<TaskHub video={makeVideo()} lastChoice="reframe" onChoose={() => undefined} />));
    expect(cardByText('Reframe to vertical').classList.contains('is-last')).toBe(true);
    // exactly one "Last used" badge, on the reframe card.
    const badges = container.querySelectorAll('.task-hub__last');
    expect(badges.length).toBe(1);
    expect(cardByText('Reframe to vertical').querySelector('.task-hub__last')).not.toBeNull();
    expect(container.querySelector('.task-hub__advanced')?.classList.contains('is-last')).toBe(false);
  });

  it('marks the advanced escape as last-used when it was the last choice', () => {
    act(() => root.render(<TaskHub video={makeVideo()} lastChoice="advanced" onChoose={() => undefined} />));
    const advanced = container.querySelector('.task-hub__advanced') as HTMLButtonElement;
    expect(advanced.classList.contains('is-last')).toBe(true);
    expect(advanced.querySelector('.task-hub__last')).not.toBeNull();
    // no job card is marked.
    expect(container.querySelectorAll('.task-hub__card.is-last').length).toBe(0);
  });
});
