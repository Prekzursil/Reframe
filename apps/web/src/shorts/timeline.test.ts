import { describe, expect, it } from "vitest";

import { exportShortsTimelineCsv, exportShortsTimelineEdl } from "./timeline";

describe("exportShortsTimelineCsv", () => {
  it("exports header and rows", () => {
    const out = exportShortsTimelineCsv([
      { id: "clip-1", start: 1.5, end: 3.5, duration: 2, score: 0.9, uri: "/media/a.mp4" },
      { id: "clip-2", start: 10, end: 12, duration: 2, score: 0.8, subtitle_uri: "/media/b.srt" },
    ]);
    expect(out).toContain("clip_id,start_seconds,end_seconds");
    expect(out).toContain("clip-1,1.5,3.5,2,0.9");
    expect(out).toContain("clip-2,10,12,2,0.8");
  });

  it("escapes commas, quotes, and newlines in CSV fields", () => {
    const out = exportShortsTimelineCsv([
      {
        id: "clip,1",
        uri: "https://example.com/a\"b\".mp4",
        subtitle_uri: "line1\nline2",
      },
    ]);
    expect(out).toContain("\"clip,1\"");
    expect(out).toContain("\"https://example.com/a\"\"b\"\".mp4\"");
    expect(out).toContain("\"line1\nline2\"");
  });

  it("stringifies missing numeric fields as blanks", () => {
    const out = exportShortsTimelineCsv([{ id: "clip-3" }]);
    expect(out).toContain("clip-3,,,,,,,");
  });
});

describe("exportShortsTimelineEdl", () => {
  it("exports a basic EDL with sequential record timecodes", () => {
    const out = exportShortsTimelineEdl(
      [
        { id: "clip-1", start: 4, end: 8, uri: "/media/a.mp4" },
        { id: "clip-2", start: 12, end: 14, uri: "/media/b.mp4" },
      ],
      { fps: 30, title: "Test" }
    );
    expect(out).toContain("TITLE: Test");
    expect(out).toContain("001");
    expect(out).toContain("002");
    // record in/out should start at 00:00:00:00 and advance by each duration
    expect(out).toContain("00:00:00:00 00:00:04:00");
    expect(out).toContain("00:00:04:00 00:00:06:00");
  });

  it("supports per-clip reels and audio tracks", () => {
    const out = exportShortsTimelineEdl(
      [
        { id: "clip-1", start: 0, end: 2, uri: "/media/a.mp4" },
        { id: "clip-2", start: 2, end: 4, uri: "/media/b.mp4" },
      ],
      { fps: 30, title: "Test", includeAudio: true, perClipReel: true }
    );
    expect(out).toContain("CLIP001");
    expect(out).toContain("CLIP002");
    expect(out).toContain(" A");
  });

  it("normalizes invalid reel names and handles clips without uri", () => {
    const out = exportShortsTimelineEdl(
      [
        { id: "clip-1", reel_name: "!!!", start: undefined, end: undefined, uri: "" },
      ],
      { perClipReel: true }
    );
    expect(out).toContain("CLIP001");
    expect(out).toContain("00:00:00:00 00:00:00:00");
    expect(out).toContain("* FROM CLIP NAME: clip-1");
    expect(out).not.toContain("* SOURCE FILE:");
  });

  it("falls back to 30fps when non-positive fps is provided", () => {
    const out = exportShortsTimelineEdl([{ id: "clip-1", start: 0, end: 1 }], { fps: 0 });
    expect(out).toContain("00:00:00:00 00:00:01:00");
  });
});
