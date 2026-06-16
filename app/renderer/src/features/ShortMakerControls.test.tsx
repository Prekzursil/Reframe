// ShortMakerControls.test.tsx — behavioral tests for the pure presentational
// controls form. Mounts the component directly (react-dom/client + act under
// jsdom) and drives EVERY control handler + the submit/batch/cancel buttons and
// the audio-track option rendering, so each callback prop is exercised.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ShortMakerControls } from './ShortMakerControls';
import {
  type AudioTrackOption,
  type ShortMakerControls as ShortMakerControlsState,
  DEFAULT_CONTROLS,
} from './shortMakerLogic';

const AUDIO_TRACKS: AudioTrackOption[] = [
  { id: 't-en', lang: 'en', name: 'English', kind: 'original' },
  { id: 't-es', lang: 'es', name: 'Spanish dub', kind: 'dub' },
];

interface Spies {
  setPrompt: ReturnType<typeof vi.fn>;
  setControl: ReturnType<typeof vi.fn>;
  setAudioTrackId: ReturnType<typeof vi.fn>;
  applyPlatformPreset: ReturnType<typeof vi.fn>;
  onSubmit: ReturnType<typeof vi.fn>;
  onBatch: ReturnType<typeof vi.fn>;
  onCancel: ReturnType<typeof vi.fn>;
}

describe('<ShortMakerControls />', () => {
  let container: HTMLDivElement;
  let root: Root;
  let spies: Spies;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    spies = {
      setPrompt: vi.fn(),
      setControl: vi.fn(),
      setAudioTrackId: vi.fn(),
      applyPlatformPreset: vi.fn(),
      onSubmit: vi.fn(),
      onBatch: vi.fn(),
      onCancel: vi.fn(),
    };
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function mount(
    over: {
      controls?: Partial<ShortMakerControlsState>;
      busy?: boolean;
      hasCandidates?: boolean;
      audioTracks?: AudioTrackOption[];
      audioTrackId?: string;
      videoId?: string;
      prompt?: string;
    } = {},
  ): void {
    const controls: ShortMakerControlsState = { ...DEFAULT_CONTROLS, ...over.controls };
    act(() => {
      root.render(
        <ShortMakerControls
          videoId={over.videoId ?? 'v1'}
          prompt={over.prompt ?? ''}
          controls={controls}
          audioTracks={over.audioTracks ?? AUDIO_TRACKS}
          audioTrackId={over.audioTrackId ?? ''}
          busy={over.busy ?? false}
          hasCandidates={over.hasCandidates ?? false}
          setPrompt={spies.setPrompt}
          setControl={spies.setControl}
          setAudioTrackId={spies.setAudioTrackId}
          applyPlatformPreset={spies.applyPlatformPreset}
          onSubmit={spies.onSubmit}
          onBatch={spies.onBatch}
          onCancel={spies.onCancel}
        />,
      );
    });
  }

  function byLabel(label: string): HTMLElement {
    return container.querySelector(`[aria-label="${label}"]`) as HTMLElement;
  }

  // Select elements drive React via the `change` event; text/number inputs and
  // textareas drive it via `input`. Use the native value setter so React's
  // controlled-input value tracker registers the change either way.
  function change(el: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement, value: string) {
    const proto =
      el instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : el instanceof HTMLTextAreaElement
          ? HTMLTextAreaElement.prototype
          : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')!.set!;
    act(() => {
      setter.call(el, value);
      const type = el instanceof HTMLSelectElement ? 'change' : 'input';
      el.dispatchEvent(new Event(type, { bubbles: true }));
    });
  }

  it('renders the audio-track picker with Original plus every track option', () => {
    mount();
    const select = byLabel('Audio track') as HTMLSelectElement;
    const opts = [...select.options].map((o) => `${o.value}:${o.textContent}`);
    expect(opts[0]).toBe(':Original');
    expect(opts[1]).toBe('t-en:English (en, original)');
    expect(opts[2]).toBe('t-es:Spanish dub (es, dub)');
  });

  it('forwards prompt edits to setPrompt', () => {
    mount();
    const textarea = byLabel('Prompt') as HTMLTextAreaElement;
    change(textarea, 'quotable moments');
    expect(spies.setPrompt).toHaveBeenCalledWith('quotable moments');
  });

  it('forwards every numeric/select/text control change to setControl with the parsed value', () => {
    mount();
    change(byLabel('Count') as HTMLInputElement, '8');
    expect(spies.setControl).toHaveBeenCalledWith('count', 8);

    change(byLabel('Min seconds') as HTMLInputElement, '25');
    expect(spies.setControl).toHaveBeenCalledWith('minSec', 25);

    change(byLabel('Max seconds') as HTMLInputElement, '55');
    expect(spies.setControl).toHaveBeenCalledWith('maxSec', 55);

    change(byLabel('Aspect') as HTMLSelectElement, '1:1');
    expect(spies.setControl).toHaveBeenCalledWith('aspect', '1:1');

    change(byLabel('Language') as HTMLInputElement, 'es');
    expect(spies.setControl).toHaveBeenCalledWith('language', 'es');

    change(byLabel('Caption style') as HTMLSelectElement, 'bold');
    expect(spies.setControl).toHaveBeenCalledWith('captionStyle', 'bold');

    change(byLabel('Reframe engine') as HTMLSelectElement, 'verthor');
    expect(spies.setControl).toHaveBeenCalledWith('reframeEngine', 'verthor');

    change(byLabel('Emphasis') as HTMLSelectElement, 'on');
    expect(spies.setControl).toHaveBeenCalledWith('emphasis', 'on');
  });

  it('forwards each toggle change to setControl with the checked bool', () => {
    mount();
    const toggle = (label: string) => byLabel(label) as HTMLInputElement;
    act(() => {
      toggle('Hook title').click(); // ON -> OFF
    });
    expect(spies.setControl).toHaveBeenCalledWith('hookTitle', false);
    act(() => toggle('Remove fillers').click()); // OFF -> ON
    expect(spies.setControl).toHaveBeenCalledWith('removeFillers', true);
    act(() => toggle('Auto zoom').click());
    expect(spies.setControl).toHaveBeenCalledWith('autoZoom', true);
    act(() => toggle('Trim silence').click());
    expect(spies.setControl).toHaveBeenCalledWith('silenceTrim', true);
    act(() => toggle('Stabilize').click());
    expect(spies.setControl).toHaveBeenCalledWith('stabilize', true);
  });

  it('forwards audio-track selection to setAudioTrackId', () => {
    mount();
    change(byLabel('Audio track') as HTMLSelectElement, 't-es');
    expect(spies.setAudioTrackId).toHaveBeenCalledWith('t-es');
  });

  it('applies a platform preset on click', () => {
    mount();
    const reels = container.querySelector('[data-preset="reels"]') as HTMLButtonElement;
    act(() => reels.click());
    expect(spies.applyPlatformPreset).toHaveBeenCalledWith('reels');
  });

  it('fires onSubmit on form submit (preventing default) and onBatch on the batch button', () => {
    mount();
    const form = container.querySelector('form')!;
    act(() => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    expect(spies.onSubmit).toHaveBeenCalled();

    act(() => (byLabel('Make N shorts') as HTMLButtonElement).click());
    expect(spies.onBatch).toHaveBeenCalled();
  });

  it('shows Find clips by default and Regenerate once candidates exist', () => {
    mount({ hasCandidates: false });
    expect(container.querySelector('button[type="submit"]')?.textContent).toBe('Find clips');
    mount({ hasCandidates: true });
    expect(container.querySelector('button[type="submit"]')?.textContent).toBe('Regenerate');
  });

  it('shows a Cancel button only while busy and fires onCancel when clicked', () => {
    mount({ busy: false });
    expect([...container.querySelectorAll('button')].find((b) => b.textContent === 'Cancel')).toBe(
      undefined,
    );
    mount({ busy: true });
    const cancel = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Cancel',
    ) as HTMLButtonElement;
    expect(cancel).toBeTruthy();
    act(() => cancel.click());
    expect(spies.onCancel).toHaveBeenCalled();
  });

  it('disables submit/batch when there is no videoId', () => {
    mount({ videoId: '' });
    expect((container.querySelector('button[type="submit"]') as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect((byLabel('Make N shorts') as HTMLButtonElement).disabled).toBe(true);
  });
});
