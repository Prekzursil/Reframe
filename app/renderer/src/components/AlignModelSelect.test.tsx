// AlignModelSelect.test.tsx — M5 word-timing alignment model opt-in (incl. RO).
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import {
  AlignModelSelect,
  ALIGN_MODEL_CHOICES,
  MMS_ALIGNER_ALIAS,
  MMS_ALIGNER_MODEL_ID,
  type AlignModelSelectProps,
} from './AlignModelSelect';

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

// The non-commercial opt-in props are REQUIRED (a licence gate must not be
// silently omittable), so the helper supplies inert defaults and each test
// overrides only what it exercises.
function mount(props: Partial<AlignModelSelectProps> & { value: string }): void {
  const full: AlignModelSelectProps = {
    onChange: () => {},
    allowNonCommercial: false,
    onAllowNonCommercialChange: () => {},
    ...props,
  };
  act(() => {
    root.render(<AlignModelSelect {...full} />);
  });
}

function select(): HTMLSelectElement {
  return container.querySelector('select[data-action="align-model"]') as HTMLSelectElement;
}

function ncToggle(): HTMLInputElement {
  return container.querySelector(
    'input[data-action="allow-non-commercial-aligner"]',
  ) as HTMLInputElement;
}

// A real `.click()` so React's own value-tracker sees the flip; assigning
// `.checked` by hand and dispatching a synthetic event makes React treat it as
// a no-change and the handler never fires.
function toggleNc(el: HTMLInputElement): void {
  act(() => {
    el.click();
  });
}

function setValue(el: HTMLSelectElement, value: string): void {
  act(() => {
    el.value = value;
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

describe('AlignModelSelect', () => {
  it('exposes the permissive default + the Romanian and MMS opt-ins', () => {
    const ids = ALIGN_MODEL_CHOICES.map((c) => c.id);
    expect(ids).toContain('');
    expect(ids).toContain('romanian-wav2vec2');
    expect(ids).toContain('wav2vec2-960h-lv60');
    expect(ids).toContain(MMS_ALIGNER_ALIAS);
  });

  it('shows the packaged default when value is blank', () => {
    mount({ value: '' });
    expect(select().value).toBe('');
  });

  it('reflects the Romanian opt-in selection', () => {
    mount({ value: 'romanian-wav2vec2' });
    expect(select().value).toBe('romanian-wav2vec2');
  });

  it('persists the Romanian choice', () => {
    const onChange = vi.fn();
    mount({ value: '', onChange });
    setValue(select(), 'romanian-wav2vec2');
    expect(onChange).toHaveBeenCalledWith('romanian-wav2vec2');
  });

  it('persists an empty id when reverting to the default', () => {
    const onChange = vi.fn();
    mount({ value: 'romanian-wav2vec2', onChange });
    setValue(select(), '');
    expect(onChange).toHaveBeenCalledWith('');
  });

  it('keeps an unknown custom id without losing it (shows default row + a badge)', () => {
    mount({ value: 'facebook/some-other-ctc' });
    expect(select().value).toBe('');
    expect(container.querySelector('[data-testid="align-model-custom"]')?.textContent).toContain(
      'facebook/some-other-ctc',
    );
  });

  it('shows no custom badge for a blank value', () => {
    mount({ value: '' });
    expect(container.querySelector('[data-testid="align-model-custom"]')).toBeNull();
  });

  it('disables the control while busy', () => {
    mount({ value: '', busy: true });
    expect(select().disabled).toBe(true);
    expect(ncToggle().disabled).toBe(true);
  });

  it('is enabled by default', () => {
    mount({ value: '' });
    expect(select().disabled).toBe(false);
    expect(ncToggle().disabled).toBe(false);
  });
});

// --- WU-T0/B1: the CC-BY-NC MMS aligner is an explicit opt-in ------------------
// The sidecar `ctc_align._resolve_model_id` refuses the MMS model unless
// `allowNonCommercialAligner` is on, so the picker must not offer it as if it
// were free to choose — an option the backend silently downgrades is worse than
// no option at all. This block is the UI half of that gate.
describe('AlignModelSelect — non-commercial gate', () => {
  function mmsOption(): HTMLOptionElement {
    return container.querySelector(`option[value="${MMS_ALIGNER_ALIAS}"]`) as HTMLOptionElement;
  }

  it('names the packaged default as Apache-2.0, never MIT', () => {
    const def = ALIGN_MODEL_CHOICES.find((c) => c.id === '');
    expect(def?.label).toContain('Apache-2.0');
    expect(ALIGN_MODEL_CHOICES.every((c) => !c.label.includes('MIT'))).toBe(true);
  });

  it('labels the MMS row with its CC-BY-NC licence', () => {
    mount({ value: '' });
    expect(mmsOption().textContent).toContain('CC-BY-NC');
  });

  it('disables the MMS row until the opt-in is on', () => {
    mount({ value: '' });
    expect(mmsOption().disabled).toBe(true);
  });

  it('enables the MMS row once the opt-in is on', () => {
    mount({ value: '', allowNonCommercial: true });
    expect(mmsOption().disabled).toBe(false);
  });

  it('reflects the opt-in state on the toggle', () => {
    mount({ value: '', allowNonCommercial: true });
    expect(ncToggle().checked).toBe(true);
  });

  it('persists turning the opt-in on', () => {
    const onAllowNonCommercialChange = vi.fn();
    mount({ value: '', onAllowNonCommercialChange });
    toggleNc(ncToggle());
    expect(onAllowNonCommercialChange).toHaveBeenCalledWith(true);
  });

  it('clears an MMS selection when the opt-in is turned back off', () => {
    const onChange = vi.fn();
    const onAllowNonCommercialChange = vi.fn();
    mount({
      value: MMS_ALIGNER_ALIAS,
      allowNonCommercial: true,
      onChange,
      onAllowNonCommercialChange,
    });
    toggleNc(ncToggle());
    expect(onAllowNonCommercialChange).toHaveBeenCalledWith(false);
    // Leaving `ctcModelId` on a model the sidecar will refuse is a lie in the UI.
    expect(onChange).toHaveBeenCalledWith('');
  });

  it('clears a full-HF-id MMS selection too, not just the alias', () => {
    const onChange = vi.fn();
    mount({ value: MMS_ALIGNER_MODEL_ID, allowNonCommercial: true, onChange });
    toggleNc(ncToggle());
    expect(onChange).toHaveBeenCalledWith('');
  });

  it('leaves a permissive selection alone when the opt-in is turned off', () => {
    const onChange = vi.fn();
    mount({ value: 'romanian-wav2vec2', allowNonCommercial: true, onChange });
    toggleNc(ncToggle());
    expect(onChange).not.toHaveBeenCalled();
  });

  it('warns that turning it on makes the output non-commercial', () => {
    mount({ value: '' });
    expect(container.textContent).toContain('non-commercial');
  });

  // --- the shape three reviewers proved was uncovered: opted IN, nothing chosen.
  // The sidecar used to fall back to MMS in exactly this state while this select
  // kept rendering the commercial-safe row as chosen. The backend fallback is
  // gone (ctc_align._resolve_model_id); these pin the UI half of that contract.
  it('keeps the commercial-safe default selected when opted in with no choice', () => {
    mount({ value: '', allowNonCommercial: true });
    expect(select().value).toBe('');
    const chosen = select().selectedOptions[0];
    expect(chosen.textContent).toContain('Apache-2.0');
    expect(chosen.textContent).toContain('commercial-safe');
  });

  it('offers MMS but does not preselect it once the opt-in is on', () => {
    mount({ value: '', allowNonCommercial: true });
    expect(mmsOption().disabled).toBe(false);
    expect(mmsOption().selected).toBe(false);
  });

  it('re-picking the default row after trying MMS persists the empty id', () => {
    // The exact user story: opt in, try MMS, go back to the row labelled
    // commercial-safe. `''` is what gets persisted, and `''` must mean Apache.
    const onChange = vi.fn();
    mount({ value: MMS_ALIGNER_ALIAS, allowNonCommercial: true, onChange });
    setValue(select(), '');
    expect(onChange).toHaveBeenCalledWith('');
  });

  it('says the opt-in only unlocks MMS rather than switching to it', () => {
    mount({ value: '' });
    const copy = container.textContent ?? '';
    expect(copy).toContain('UNLOCKS');
    expect(copy).toContain('does not switch to it');
  });
});
