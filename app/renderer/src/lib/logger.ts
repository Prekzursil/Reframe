/**
 * Minimal renderer logging seam.
 *
 * Centralizes the few best-effort diagnostic writes so renderer feature code never
 * calls `console.*` directly (a code-quality cleanup, F4b). Fire-and-forget
 * telemetry that must NEVER block or surface a user error routes its swallowed
 * failures through here, giving one greppable surface tests can spy on.
 */

/** Log a non-fatal warning for a swallowed (fire-and-forget) failure. */
export function logWarn(message: string, ...details: unknown[]): void {
  // The single intentional console site in the renderer; routed through this util
  // so callers stay clean and the diagnostic surface is centralized.
  console.warn(message, ...details);
}
