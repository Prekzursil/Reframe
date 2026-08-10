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
  AiAudioBadge,
  AiDisclosurePanel,
  C2PA_EXPORT_STATUS,
  PERTH_WATERMARK_ENGINES,
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

  it('does NOT flag an original row', () => {
    expect(isAiGeneratedAudioTrack({ kind: 'original' })).toBe(false);
  });

  it('does NOT flag a row whose kind is absent', () => {
    expect(isAiGeneratedAudioTrack({})).toBe(false);
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

  it('renders the badge label and explains what the label is derived from', () => {
    act(() => {
      root = createRoot(container);
      root.render(<AiAudioBadge />);
    });
    const badge = container.querySelector('[data-testid="ai-audio-badge"]');
    expect(badge?.textContent).toBe(AI_AUDIO_BADGE_LABEL);
    // The tooltip must disclose the over-labelling direction, not hide it.
    expect(badge?.getAttribute('title')).toContain('over-label');
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

  it('surfaces the Perth watermark note for chatterbox only', () => {
    mount(<AiDisclosurePanel engineId="chatterbox" />);
    expect(container.querySelector('[data-testid="perth-note"]')?.textContent).toContain('Perth');
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
