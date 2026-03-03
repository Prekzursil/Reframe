import { describe, expect, it } from "vitest";

import { detectSubtitleFormat, shiftSubtitleTimings } from "./shift";

describe("shiftSubtitleTimings", () => {
  it("returns source unchanged when offset is zero", () => {
    const input = "1\n00:00:00,000 --> 00:00:01,000\nHello\n";
    expect(shiftSubtitleTimings(input, 0)).toBe(input);
  });

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

  it("handles VTT hour timestamps and invalid timing rows", () => {
    const input = [
      "WEBVTT",
      "",
      "01:00:00.000 --> 01:00:01.500",
      "Long",
      "",
      "bad --> row",
      "Ignore",
      "",
    ].join("\n");
    const out = shiftSubtitleTimings(input, -0.5);
    expect(out).toContain("00:59:59.500 --> 01:00:01.000");
    expect(out).toContain("bad --> row");
  });
});

describe("detectSubtitleFormat", () => {
  it("detects vtt by header", () => {
    expect(detectSubtitleFormat("WEBVTT\n\n00:00.000 --> 00:01.000\nhi\n")).toBe("vtt");
  });

  it("detects srt by timing line", () => {
    expect(detectSubtitleFormat("1\n00:00:00,000 --> 00:00:01,000\nhi\n")).toBe("srt");
  });

  it("detects vtt by timing line without WEBVTT header", () => {
    expect(detectSubtitleFormat("00:00.000 --> 00:00.500\nhi\n")).toBe("vtt");
  });

  it("returns null for unsupported content", () => {
    expect(detectSubtitleFormat("hello world")).toBeNull();
  });
});
