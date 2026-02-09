import { describe, expect, it } from "vitest";

import { detectSubtitleFormat, shiftSubtitleTimings } from "./shift";

describe("shiftSubtitleTimings", () => {
  it("shifts srt timestamps", () => {
    const input = [
      "1",
      "00:00:00,000 --> 00:00:01,000",
      "Hello",
      "",
      "2",
      "00:00:02,500 --> 00:00:03,000",
      "World",
      "",
    ].join("\n");

    const out = shiftSubtitleTimings(input, 1.0);
    expect(out).toContain("00:00:01,000 --> 00:00:02,000");
    expect(out).toContain("00:00:03,500 --> 00:00:04,000");
  });

  it("clamps negative times to zero", () => {
    const input = ["1", "00:00:00,100 --> 00:00:01,000", "Hi", ""].join("\n");
    const out = shiftSubtitleTimings(input, -2.0);
    expect(out).toContain("00:00:00,000 --> 00:00:00,000");
  });

  it("shifts vtt timestamps", () => {
    const input = ["WEBVTT", "", "00:00.000 --> 00:01.000", "Hello", ""].join("\n");
    const out = shiftSubtitleTimings(input, 2.5);
    expect(out).toContain("00:02.500 --> 00:03.500");
  });
});

describe("detectSubtitleFormat", () => {
  it("detects vtt by header", () => {
    expect(detectSubtitleFormat("WEBVTT\n\n00:00.000 --> 00:01.000\nhi\n")).toBe("vtt");
  });

  it("detects srt by timing line", () => {
    expect(detectSubtitleFormat("1\n00:00:00,000 --> 00:00:01,000\nhi\n")).toBe("srt");
  });
});

