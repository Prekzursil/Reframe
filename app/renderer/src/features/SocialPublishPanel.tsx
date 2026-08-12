// SocialPublishPanel.tsx — Deliver -> "Publish": ONE honest blocked state (Q4).
//
// WHAT THIS REPLACED, AND WHY.
// The panel used to render a platform picker, a title field, a scheduler and a
// "Publish now / Schedule" button. That button could not be enabled by any sequence
// of user actions: its enable condition required a non-empty clip path, the prop
// defaulted to empty, and the ONLY production mount (views/Deliver.tsx) never passed
// one — nor did any other surface in the tree. Its empty state told the user to
// export a clip first, an instruction that screen offered no affordance to satisfy.
// And directly above the permanently-disabled button, a platform-held plan asserted
// that the post survives the machine being switched off: a capability claim painted
// over a control that cannot fire. A disabled control the user cannot ever enable is
// worse than an absent one, because it reads as "you have not done the setup yet".
//
// THE BLOCKER IS NOT A MISSING BACKEND — do not "just wire it up".
// The capability matrix, the schedule planner, the atomic queue store, the five
// registered social.* RPC methods and the PKCE/authorize-URL builders are all built
// and unit-tested. What is missing is the EXECUTION layer, enumerated in
// docs/wiring/WIRING-social-publish.md section 4: no loopback listener, no live
// token exchange, no uploader, and no scheduler runner — so social.enqueue records
// an intent that nothing performs. app/main/socialAuth.ts additionally has NO
// production importer at all (waived as a REAL GAP in
// .quality/reachability_allowlist.json), so no main-process code can even start a
// sign-in. Restoring a live button is therefore a BUILD task, not a wiring task, and
// mis-sizing it as wiring is exactly how a live button over a missing uploader ships.
//
// Deliberately NO RPC call from here. Consulting a backend that cannot publish would
// only manufacture the appearance of a live feature, and the per-platform reasons it
// returns (an account type, an app review) are not the operative blocker — this build
// is. One statement, one alternative, nothing that pretends to act.
import React from 'react';
import './panels.css';

/** Deliver -> Publish: says plainly that this build cannot publish for you. */
export function SocialPublishPanel(): React.ReactElement {
  return (
    <section className="social-publish" aria-label="Direct publish">
      <p className="social-publish__blocked">
        Direct publish is not available in this build; use Platform presets and upload manually.
      </p>
      <p className="social-publish__blocked">
        Reframe cannot sign in to a platform or upload on your behalf yet. Render the
        platform-shaped file under Platform presets, then post it from that platform.
      </p>
    </section>
  );
}

export default SocialPublishPanel;
