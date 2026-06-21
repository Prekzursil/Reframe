// providerLinkIcon.tsx — inline Lucide-style "external-link" glyph for the
// "Get a free key" links in the Providers & Keys picker. Decorative (the link
// text carries the accessible name); 24×24, currentColor stroke so it tints with
// the surrounding link color.
import React from 'react';

/** An external-link arrow (Lucide "external-link"). */
export function ExternalLinkIcon(): React.ReactElement {
  return (
    <svg
      className="external-link-icon"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M15 3h6v6" />
      <path d="M10 14 21 3" />
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
    </svg>
  );
}
