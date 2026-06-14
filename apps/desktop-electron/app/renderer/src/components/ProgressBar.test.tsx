import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ProgressBar, clampPct } from './ProgressBar';

describe('clampPct', () => {
  it('passes through in-range values', () => {
    expect(clampPct(0)).toBe(0);
    expect(clampPct(50)).toBe(50);
    expect(clampPct(100)).toBe(100);
  });

  it('clamps below 0 and above 100', () => {
    expect(clampPct(-5)).toBe(0);
    expect(clampPct(250)).toBe(100);
  });

  it('treats non-finite as 0', () => {
    expect(clampPct(NaN)).toBe(0);
    expect(clampPct(Infinity)).toBe(100);
    expect(clampPct(-Infinity)).toBe(0);
  });
});

describe('ProgressBar', () => {
  it('renders a progressbar with the clamped aria-valuenow', () => {
    const html = renderToStaticMarkup(<ProgressBar pct={150} />);
    expect(html).toContain('role="progressbar"');
    expect(html).toContain('aria-valuenow="100"');
    expect(html).toContain('width:100%');
  });

  it('renders the message label when provided', () => {
    const html = renderToStaticMarkup(<ProgressBar pct={42} message="Encoding…" />);
    expect(html).toContain('Encoding');
    expect(html).toContain('aria-valuenow="42"');
  });

  it('omits the label when message is empty', () => {
    const html = renderToStaticMarkup(<ProgressBar pct={10} message="" />);
    expect(html).not.toContain('progress__label');
  });
});
