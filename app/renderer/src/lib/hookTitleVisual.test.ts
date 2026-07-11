// Unit test for the vendored Remotion hook-headline resolver (P3-A).
//
// The sidecar build_job forwards a `hookTitle` into the Remotion render, and the
// vendor composition must render it (parity with the libass hook burn) — this
// covers the pure look-resolution the <HookTitle> wrapper renders. The helper is
// remotion-free + zod-free, so it imports cleanly here without the Remotion
// runtime (the composition itself is validated by the vendor's own typecheck).
import { describe, expect, it } from 'vitest';
import { hookTitleVisual } from '../../../../vendor/remotion-captions/src/components/hookTitleStyle';

describe('hookTitleVisual (vendor Remotion hook headline)', () => {
  it('returns null for blank / whitespace-only text (no hook)', () => {
    expect(hookTitleVisual('', 'bold')).toBeNull();
    expect(hookTitleVisual('   ', 'bold')).toBeNull();
  });

  it('resolves the trimmed title + the style theme for a premium style', () => {
    const v = hookTitleVisual('  The Big Hook  ', 'hormozi');
    expect(v).not.toBeNull();
    expect(v?.title).toBe('The Big Hook');
    expect(v?.textColor).toBe('#FFFFFF'); // hormozi theme textColor
    expect(v?.shadowColor).toBe('#000000');
    expect(v?.fontFamily).toContain('Montserrat');
  });

  it('mirrors each style theme (colour + font differ per style)', () => {
    expect(hookTitleVisual('x', 'neon')?.textColor).toBe('#39FF14');
    expect(hookTitleVisual('x', 'serif')?.fontFamily).toContain('Georgia');
    expect(hookTitleVisual('x', 'tiktok')?.textColor).toBe('#FFFFFF');
  });

  it('falls back to the bold theme for an unknown style id', () => {
    const v = hookTitleVisual('Hook', 'not-a-real-style');
    expect(v?.title).toBe('Hook');
    expect(v?.fontFamily).toContain('Montserrat'); // bold family default
  });
});
