// ModelsOnboarding.tsx — a 3-step first-run coach-mark overlay for the
// "Models & System" panel. A clear 101: (1) this is your hardware, (2) pick a
// quality tier, (3) download what you need. Shown once (gated on
// settings.modelsOnboardingSeen by the parent); "Got it" persists the flag and
// closes. Self-contained (no portal): rendered as an overlay inside the panel.
//
// Lane 0 F4 (R-M10): the dialog now uses the shared useFocusTrap so focus moves
// into it on mount, Tab is trapped, Escape dismisses (same as "Skip tour"), and
// focus is restored to the opener on unmount.
import React, { useState } from 'react';

import { useFocusTrap } from '../hooks/useFocusTrap';

export interface OnboardingStep {
  title: string;
  body: string;
}

/** The 3 coach-mark steps (exported for tests + so copy is single-sourced). */
export const ONBOARDING_STEPS: OnboardingStep[] = [
  {
    title: 'This is your hardware',
    body: 'The bars at the top show your GPU VRAM and system RAM. Moment-finding models load one at a time, so each must fit under your VRAM budget — that is what the bars measure.',
  },
  {
    title: 'Pick a quality tier',
    body: 'Tier 0 is instant, works on silent video, and downloads nothing. Tier 1 (the default) adds visual + audio + transcript models and downloads them on first use. Tier 2 is a heavy video-LLM re-rank — opt-in, runs alone. The recommended tier for your machine is highlighted.',
  },
  {
    title: 'Download what you need',
    body: 'Each model card shows a will-it-run badge (green = will run, amber = tight, red = won’t run), its VRAM and download size, and a license chip (Commercial OK vs Local-only). Download only the models for the tier you chose; Tier 0 needs zero downloads.',
  },
];

export interface ModelsOnboardingProps {
  /** Dismiss the overlay and persist modelsOnboardingSeen=true (parent owns it). */
  onDone: () => void;
}

export function ModelsOnboarding({ onDone }: ModelsOnboardingProps): React.ReactElement {
  const [step, setStep] = useState<number>(0);
  const current = ONBOARDING_STEPS[step];
  const isLast = step === ONBOARDING_STEPS.length - 1;
  const trapRef = useFocusTrap<HTMLDivElement>({ onEscape: onDone });

  return (
    <div
      ref={trapRef}
      className="models-onboarding"
      role="dialog"
      aria-modal="true"
      aria-label="Models and System — first-run tour"
      data-step={step}
    >
      <div className="models-onboarding__card">
        <p className="models-onboarding__progress">
          Step {step + 1} of {ONBOARDING_STEPS.length}
        </p>
        <h3 className="models-onboarding__title">{current.title}</h3>
        <p className="models-onboarding__body">{current.body}</p>

        <div className="models-onboarding__dots" aria-hidden="true">
          {ONBOARDING_STEPS.map((s, i) => (
            <span
              key={s.title}
              className={`models-onboarding__dot${i === step ? ' is-active' : ''}`}
            />
          ))}
        </div>

        <div className="models-onboarding__actions">
          <button type="button" className="secondary" data-action="skip" onClick={onDone}>
            Skip tour
          </button>
          {step > 0 && (
            <button
              type="button"
              className="secondary"
              data-action="back"
              onClick={() => setStep((s) => Math.max(0, s - 1))}
            >
              Back
            </button>
          )}
          {isLast ? (
            <button type="button" data-action="done" onClick={onDone}>
              Got it
            </button>
          ) : (
            <button type="button" data-action="next" onClick={() => setStep((s) => s + 1)}>
              Next
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default ModelsOnboarding;
