// FirstRunChooser.tsx — the first-run local-vs-cloud chooser (WU-presets P1 #6).
//
// On the very first run (`firstRunChoiceMade=false`) the user picks how Reframe
// runs its AI: fully LOCAL (privacy, nothing leaves the machine — the safe
// default) or BEST FREE CLOUD (rotation across free providers for speed, opt-in
// egress). The local option is the explicit, always-labelled "Recommended"
// default so the privacy-safe path is unmistakable (not signalled by color
// alone — WCAG). Picking either calls `onChoose(presetName)`; the parent applies
// the preset (`providers.firstRun`) and flips the flag.
//
// Pure presentational: the parent owns the busy state + the apply call.
import React from 'react';

export interface FirstRunChooserProps {
  /** Apply the chosen first-run preset ("privacy" local-safe | "bestFreeCloud"). */
  onChoose: (choice: 'privacy' | 'bestFreeCloud') => void;
  /** True while the choice is being applied (disables both buttons). */
  busy?: boolean;
}

export function FirstRunChooser({
  onChoose,
  busy = false,
}: FirstRunChooserProps): React.ReactElement {
  return (
    <div className="first-run-chooser" role="dialog" aria-label="Choose how Reframe runs AI">
      <h3 className="first-run-chooser__title">How should Reframe run AI?</h3>
      <p className="first-run-chooser__intro">
        Pick where your transcripts and frames are processed. You can change this any time in Models
        &amp; System.
      </p>
      <div className="first-run-chooser__options">
        <button
          type="button"
          className="first-run-chooser__option is-local"
          data-choice="privacy"
          data-default="true"
          disabled={busy}
          onClick={() => onChoose('privacy')}
        >
          <span className="first-run-chooser__badge">Recommended</span>
          <span className="first-run-chooser__name">Local only</span>
          <span className="first-run-chooser__desc">
            Everything runs on your machine. Nothing is ever uploaded. Best for private footage.
          </span>
        </button>
        <button
          type="button"
          className="first-run-chooser__option is-cloud"
          data-choice="bestFreeCloud"
          disabled={busy}
          onClick={() => onChoose('bestFreeCloud')}
        >
          <span className="first-run-chooser__name">Best free cloud</span>
          <span className="first-run-chooser__desc">
            Faster on weak hardware using free provider rotation. Opt-in — you bring the keys and
            confirm before anything leaves the machine.
          </span>
        </button>
      </div>
    </div>
  );
}

export default FirstRunChooser;
