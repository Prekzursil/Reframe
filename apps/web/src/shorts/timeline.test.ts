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
});

