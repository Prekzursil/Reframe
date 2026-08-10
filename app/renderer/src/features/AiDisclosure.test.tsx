// AiDisclosure.test.tsx — the AI-content disclosure surface (W21).
//
// Covers the pure predicates/constants with LITERAL expectations (never derived
// from the value under test) and the two components under jsdom. The
// Dub-panel wiring is asserted in Dub.test.tsx.

// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import {
  AI_AUDIO_BADGE_LABEL,
  AI_EXPORT_LABEL_NOTE,
  AI_LABEL_DIRECTION_NOTE,
  AiAudioBadge,
  AiDisclosurePanel,
  C2PA_EXPORT_STATUS,
  NON_AI_TRACK_KIND,
  PERTH_WATERMARK_ENGINES,
  audioTrackPickerLabel,
  engineEmbedsPerthWatermark,
  isAiGeneratedAudioTrack,
} from './AiDisclosure';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---------------------------------------------------------------------------
// pure constants + predicates
// ---------------------------------------------------------------------------

describe('AI_AUDIO_BADGE_LABEL', () => {
  it('is the exact Article-50 wording the UI shows', () => {
    expect(AI_AUDIO_BADGE_LABEL).toBe('AI-generated audio');
  });
});

describe('isAiGeneratedAudioTrack', () => {
  it('flags a dub row (the sidecar AudioTrack.kind the dub pipeline writes)', () => {
    expect(isAiGeneratedAudioTrack({ kind: 'dub' })).toBe(true);
  });

  it('does NOT flag the original recording, and that is the ONLY suppressing kind', () => {
    expect(NON_AI_TRACK_KIND).toBe('original');
    expect(isAiGeneratedAudioTrack({ kind: NON_AI_TRACK_KIND })).toBe(false);
  });

  // REVISED after adversarial review. These two cases previously asserted
  // `false` (the absent-kind one existed; the unrecognized-kind one did not).
  // Asserting `false` LOCKED IN the unsafe direction: a row whose `kind` never
  // arrived, or arrived as something the renderer does not know, rendered with
  // no label at all. That is UNDER-disclosure — the Article-50 harm direction —
  // and it disagreed with the sidecar, whose `normalize_audio_track` defaults a
  // missing `kind` to "dub" (sidecar/media_studio/features/tracks_audio.py:114).
  it('FLAGS a row whose kind is absent — the fallback points at labelling', () => {
    expect(isAiGeneratedAudioTrack({})).toBe(true);
  });

  it('FLAGS a row whose kind is unrecognized', () => {
    expect(isAiGeneratedAudioTrack({ kind: 'music' })).toBe(true);
  });
});

describe('audioTrackPickerLabel', () => {
  it('appends the AI label to a dub option (a <select> cannot host a badge element)', () => {
    expect(audioTrackPickerLabel({ name: 'Spanish dub', lang: 'es', kind: 'dub' })).toBe(
      `Spanish dub (es, dub) — ${AI_AUDIO_BADGE_LABEL}`,
    );
  });

  it('leaves an original option unlabelled', () => {
    expect(audioTrackPickerLabel({ name: 'English', lang: 'en', kind: 'original' })).toBe(
      'English (en, original)',
    );
  });
});

describe('AI_EXPORT_LABEL_NOTE', () => {
  it('says the marking is in-app only, at the surface where a dub is exported', () => {
    expect(AI_EXPORT_LABEL_NOTE).toContain('not written into the exported file');
  });
});

describe('PERTH_WATERMARK_ENGINES', () => {
  it('lists exactly the engines that embed a Perth watermark', () => {
    // Literal expectation: an added/removed engine must break this test.
    expect([...PERTH_WATERMARK_ENGINES]).toEqual(['chatterbox']);
  });
});

describe('engineEmbedsPerthWatermark', () => {
  it('is true for chatterbox', () => {
    expect(engineEmbedsPerthWatermark('chatterbox')).toBe(true);
  });

  it('is false for the local and hosted non-clone engines', () => {
    expect(engineEmbedsPerthWatermark('kokoro')).toBe(false);
    expect(engineEmbedsPerthWatermark('edgetts')).toBe(false);
  });
});

describe('C2PA_EXPORT_STATUS', () => {
  it('reports C2PA export as NOT available and names the blocker', () => {
    expect(C2PA_EXPORT_STATUS.available).toBe(false);
    expect(C2PA_EXPORT_STATUS.reason).toContain('signing identity');
  });
});

// ---------------------------------------------------------------------------
// components
// ---------------------------------------------------------------------------

describe('<AiAudioBadge />', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('renders the badge label with a plain-language tooltip, free of internal API jargon', () => {
    act(() => {
      root = createRoot(container);
      root.render(<AiAudioBadge />);
    });
    const badge = container.querySelector('[data-testid="ai-audio-badge"]');
    expect(badge?.textContent).toBe(AI_AUDIO_BADGE_LABEL);
    const title = badge?.getAttribute('title') ?? '';
    // The tooltip must still disclose the direction of the error...
    expect(title).toContain('errs toward marking');
    // ...but in shipped copy, not in the renderer's internal identifiers.
    expect(title).not.toContain('AudioTrack.kind');
    expect(title).not.toContain('tracks.audio.mux');
  });
});

describe('<AiDisclosurePanel />', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function mount(node: React.ReactElement): void {
    act(() => {
      root = createRoot(container);
      root.render(node);
    });
  }

  it('always states that the in-app label is not embedded in exported files', () => {
    mount(<AiDisclosurePanel engineId="kokoro" />);
    const panel = container.querySelector('[data-testid="ai-disclosure"]');
    expect(panel).toBeTruthy();
    expect(panel?.textContent).toContain('not embedded in exported files');
  });

  // The badge tooltip is unreachable by keyboard, unreliable for screen readers
  // and absent on touch, so the direction caveat cannot live only there.
  it('states the labelling direction as VISIBLE text, not only inside a tooltip', () => {
    mount(<AiDisclosurePanel engineId="kokoro" />);
    const note = container.querySelector('[data-testid="ai-disclosure-direction"]');
    expect(note?.textContent).toBe(AI_LABEL_DIRECTION_NOTE);
    expect(AI_LABEL_DIRECTION_NOTE).toContain('errs toward marking');
  });

  it('surfaces the Perth watermark note for chatterbox only', () => {
    mount(<AiDisclosurePanel engineId="chatterbox" />);
    expect(container.querySelector('[data-testid="perth-note"]')?.textContent).toContain('Perth');
  });

  // The note is keyed to the engine PICKER, so it is a pre-generation notice.
  // Read retrospectively it would tell a user that a dub already in the list is
  // watermarked when it may have been produced by a different engine.
  it('scopes the Perth note to the engine about to be used, not to existing tracks', () => {
    mount(<AiDisclosurePanel engineId="chatterbox" />);
    const note = container.querySelector('[data-testid="perth-note"]')?.textContent ?? '';
    expect(note).toContain('about to make');
    expect(note).toContain('not the tracks already listed');
  });

  it('omits the Perth watermark note for a non-watermarking engine', () => {
    mount(<AiDisclosurePanel engineId="kokoro" />);
    expect(container.querySelector('[data-testid="perth-note"]')).toBeNull();
  });

  it('reports C2PA export as unavailable with its reason, and NOT as a toggle', () => {
    mount(<AiDisclosurePanel engineId="kokoro" />);
    const row = container.querySelector('[data-testid="c2pa-status"]');
    expect(row?.textContent).toContain('Not available');
    expect(row?.textContent).toContain(C2PA_EXPORT_STATUS.reason);
    // A checkbox here would promise provenance signing that does not exist.
    expect(container.querySelector('[data-testid="ai-disclosure"] input')).toBeNull();
  });

  it('reports C2PA export as available when the injected status says so', () => {
    mount(
      <AiDisclosurePanel
        engineId="kokoro"
        c2pa={{ available: true, reason: 'signing identity configured' }}
      />,
    );
    const row = container.querySelector('[data-testid="c2pa-status"]');
    expect(row?.textContent).toContain('Available');
    expect(row?.textContent).not.toContain('Not available');
  });
});
