import { describe, expect, it } from "vitest";

import { cuesToSubtitles, sortCuesByStart, subtitlesToCues, validateCues } from "./cues";

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

  it("parses VTT cues that include hours", () => {
    const vtt = `WEBVTT\n\n01:00:00.000 --> 01:00:01.250\nHour mark\n`;
    const parsed = subtitlesToCues(vtt);
    expect(parsed.format).toBe("vtt");
    expect(parsed.cues[0]?.start).toBeCloseTo(3600, 3);
    expect(parsed.cues[0]?.end).toBeCloseTo(3601.25, 3);
  });

  it("throws for unsupported subtitle text", () => {
    expect(() => subtitlesToCues("not a subtitle payload")).toThrow("Unsupported subtitle format");
  });

  it("clamps malformed and negative SRT timestamps", () => {
    const srt = `1\n00:00:01,000 --> 00:00:00,500\nClamped\n`;
    const parsed = subtitlesToCues(srt);
    expect(parsed.format).toBe("srt");
    expect(parsed.cues[0]?.start).toBeCloseTo(1, 3);
    expect(parsed.cues[0]?.end).toBeCloseTo(1, 3);
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

  it("renders VTT with hour timestamps when cues exceed one hour", () => {
    const cues = [{ start: 3605.2, end: 3608.9, text: "Long form" }];
    const out = cuesToSubtitles("vtt", cues);
    expect(out).toContain("01:00:05.200 --> 01:00:08.900");
    expect(out.startsWith("WEBVTT")).toBe(true);
  });

  it("renders VTT without hour prefix when cues are short", () => {
    const cues = [{ start: 5.2, end: 8.9, text: "Short form" }];
    const out = cuesToSubtitles("vtt", cues);
    expect(out).toContain("00:05.200 --> 00:08.900");
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

  it("reports invalid values, ordering, and empty cue text", () => {
    const warnings = validateCues([
      { start: Number.NaN, end: 1, text: "ok" },
      { start: -1, end: -2, text: " " },
      { start: -2, end: 0.2, text: "fine" },
    ]);
    expect(warnings.some((w) => w.includes("start time is invalid"))).toBe(true);
    expect(warnings.some((w) => w.includes("end time is invalid"))).toBe(true);
    expect(warnings.some((w) => w.includes("end time is before start time"))).toBe(true);
    expect(warnings.some((w) => w.includes("text is empty"))).toBe(true);
    expect(warnings.some((w) => w.includes("not sorted"))).toBe(true);
  });
});

describe("sortCuesByStart", () => {
  it("sorts by start time then end time", () => {
    const sorted = sortCuesByStart([
      { start: 2, end: 3, text: "b" },
      { start: 1, end: 4, text: "a2" },
      { start: 1, end: 2, text: "a1" },
    ]);
    expect(sorted.map((cue) => cue.text)).toEqual(["a1", "a2", "b"]);
  });
});
