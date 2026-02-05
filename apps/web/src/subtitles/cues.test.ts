import { describe, expect, it } from "vitest";

import { cuesToSubtitles, subtitlesToCues, validateCues } from "./cues";

describe("subtitlesToCues", () => {
  it("parses basic SRT cues", () => {
    const srt = `1\n00:00:00,000 --> 00:00:01,000\nHello\n\n2\n00:00:01,000 --> 00:00:02,000\nWorld\n`;
    const parsed = subtitlesToCues(srt);
    expect(parsed.format).toBe("srt");
    expect(parsed.cues).toHaveLength(2);
    expect(parsed.cues[0]?.text).toBe("Hello");
    expect(parsed.cues[1]?.start).toBeCloseTo(1, 3);
  });

  it("parses basic VTT cues", () => {
    const vtt = `WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n\n00:01.000 --> 00:02.000\nWorld\n`;
    const parsed = subtitlesToCues(vtt);
    expect(parsed.format).toBe("vtt");
    expect(parsed.cues).toHaveLength(2);
    expect(parsed.cues[0]?.text).toBe("Hello");
    expect(parsed.cues[1]?.end).toBeCloseTo(2, 3);
  });
});

describe("cuesToSubtitles", () => {
  it("roundtrips cues for SRT", () => {
    const cues = [
      { start: 0, end: 1.2, text: "Hello" },
      { start: 1.2, end: 2.0, text: "World" },
    ];
    const out = cuesToSubtitles("srt", cues);
    const parsed = subtitlesToCues(out);
    expect(parsed.format).toBe("srt");
    expect(parsed.cues).toHaveLength(2);
    expect(parsed.cues[0]?.text).toBe("Hello");
  });
});

describe("validateCues", () => {
  it("reports overlapping cues", () => {
    const warnings = validateCues([
      { start: 0, end: 2, text: "a" },
      { start: 1, end: 3, text: "b" },
    ]);
    expect(warnings.some((w) => w.includes("overlaps"))).toBe(true);
  });
});

