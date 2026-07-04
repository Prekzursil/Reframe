// DirectorOnboarding.tsx — a 3-step first-run coach-mark overlay for the AI
// Director panel (WU-E2). A plain-language 101 so a novice knows what Director
// does: (1) describe the edit in words, (2) nothing changes until you review +
// confirm, (3) start from an example chip. Shown once, gated on
// settings.directorOnboardingSeen by the parent panel; "Got it"/"Skip"/Escape
// all persist the flag and close. Self-contained overlay (no portal).
//
// Reuses the shared useFocusTrap (Lane 0 F4 / R-M10), mirroring ModelsOnboarding:
// focus moves into the dialog on mount, Tab is trapped, Escape dismisses (same as
// "Skip"), and focus is restored to the opener on unmount.
import React, { useState } from 'react';

import { useFocusTrap } from '../hooks/useFocusTrap';

export interface DirectorOnboardingStep {
  title: string;
  body: string;
}

/** The 3 coach-mark steps (exported for tests + so copy is single-sourced). */
export const DIRECTOR_ONBOARDING_STEPS: DirectorOnboardingStep[] = [
  {
    title: 'Describe the edit in your own words',
    body: 'Tell the Director what you want in plain language — “make the scrolling smooth” or “turn this into a Q&A showcase”. It reads the video you have open and plans the edit for you; you never touch a timeline.',
  },
  {
    title: 'Nothing changes until you confirm',
    body: 'The Director proposes a reviewable storyboard with a plain-language summary and a cost & privacy banner. Your video is untouched until you press Apply — and every edit is reversible with one-shot Undo.',
  },
  {
    title: 'Start from an example',
    body: 'New here? Click one of the example chips under the prompt to fill it in, then press “Plan edit”. You can always tweak the goal and re-plan — the previous plan stays on screen until the new one is ready.',
  },
];

export interface DirectorOnboardingProps {
  /** Dismiss the overlay and persist directorOnboardingSeen=true (parent owns it). */
  onDone: () => void;
}

export function DirectorOnboarding({ onDone }: DirectorOnboardingProps): React.ReactElement {
  const [step, setStep] = useState<number>(0);
  const current = DIRECTOR_ONBOARDING_STEPS[step];
  const isLast = step === DIRECTOR_ONBOARDING_STEPS.length - 1;
  const trapRef = useFocusTrap<HTMLDivElement>({ onEscape: onDone });

  return (
    <div
      ref={trapRef}
      className="director-onboarding"
      role="dialog"
      aria-modal="true"
      aria-label="AI Director — first-run tour"
      data-step={step}
    >
      <div className="director-onboarding__card">
        <p className="director-onboarding__progress">
          Step {step + 1} of {DIRECTOR_ONBOARDING_STEPS.length}
        </p>
        <h3 className="director-onboarding__title">{current.title}</h3>
        <p className="director-onboarding__body">{current.body}</p>

        <div className="director-onboarding__dots" aria-hidden="true">
          {DIRECTOR_ONBOARDING_STEPS.map((s, i) => (
            <span
              key={s.title}
              className={`director-onboarding__dot${i === step ? ' is-active' : ''}`}
            />
          ))}
        </div>

        <div className="director-onboarding__actions">
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

export default DirectorOnboarding;
