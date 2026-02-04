export type ShortsClip = {
  id: string;
  start?: number | null;
  end?: number | null;
  duration?: number | null;
  score?: number | null;
  uri?: string | null;
  subtitle_uri?: string | null;
  thumbnail_uri?: string | null;
};

function secondsToTimecode(seconds: number, fps: number): string {
  const safeFps = fps > 0 ? fps : 30;
  const totalFrames = Math.max(0, Math.round(seconds * safeFps));
  const frames = totalFrames % safeFps;
  const totalSeconds = Math.floor(totalFrames / safeFps);
  const s = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  const m = totalMinutes % 60;
  const h = Math.floor(totalMinutes / 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}:${String(frames).padStart(2, "0")}`;
}

export function exportShortsTimelineCsv(clips: ShortsClip[]): string {
  const header = ["clip_id", "start_seconds", "end_seconds", "duration_seconds", "score", "video_uri", "subtitle_uri", "thumbnail_uri"];
  const rows = clips.map((clip) => [
    clip.id,
    clip.start ?? "",
    clip.end ?? "",
    clip.duration ?? "",
    clip.score ?? "",
    clip.uri ?? "",
    clip.subtitle_uri ?? "",
    clip.thumbnail_uri ?? "",
  ]);
  const escape = (value: unknown) => {
    const s = String(value ?? "");
    if (s.includes(",") || s.includes("\"") || s.includes("\n")) return `"${s.replaceAll("\"", "\"\"")}"`;
    return s;
  };
  return [header, ...rows].map((row) => row.map(escape).join(",")).join("\n") + "\n";
}

export function exportShortsTimelineEdl(clips: ShortsClip[], opts?: { fps?: number; title?: string }): string {
  const fps = opts?.fps ?? 30;
  const title = opts?.title ?? "Reframe Shorts Timeline";
  const lines: string[] = [];
  lines.push(`TITLE: ${title}`);
  lines.push("FCM: NON-DROP FRAME");
  lines.push("");

  let recordCursorSeconds = 0;
  clips.forEach((clip, idx) => {
    const start = Number(clip.start ?? 0);
    const end = Number(clip.end ?? start);
    const duration = Math.max(0, end - start);

    const recIn = recordCursorSeconds;
    const recOut = recordCursorSeconds + duration;
    recordCursorSeconds = recOut;

    const event = String(idx + 1).padStart(3, "0");
    const reel = "AX";
    const track = "V";
    const transition = "C";
    const srcIn = secondsToTimecode(start, fps);
    const srcOut = secondsToTimecode(end, fps);
    const recInTc = secondsToTimecode(recIn, fps);
    const recOutTc = secondsToTimecode(recOut, fps);

    lines.push(`${event}  ${reel}       ${track}     ${transition}        ${srcIn} ${srcOut} ${recInTc} ${recOutTc}`);
    lines.push(`* FROM CLIP NAME: ${clip.id}`);
    if (clip.uri) lines.push(`* SOURCE FILE: ${clip.uri}`);
    lines.push("");
  });

  return lines.join("\n").trimEnd() + "\n";
}

