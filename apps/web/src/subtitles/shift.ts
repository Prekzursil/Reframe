type SubtitleFormat = "srt" | "vtt";

const SRT_TIMING_RE = /^(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})(.*)$/;
const VTT_TIMING_RE = /^((?:\d{2}:)?\d{2}:\d{2}\.\d{3})\s*-->\s*((?:\d{2}:)?\d{2}:\d{2}\.\d{3})(.*)$/;

function clampTime(seconds: number): number {
  if (!Number.isFinite(seconds)) return 0;
  return Math.max(0, seconds);
}

function parseSrtTimestamp(ts: string): number {
  const [hh, mm, ssMs] = ts.trim().split(":");
  if (hh === undefined || mm === undefined || ssMs === undefined) return 0;
  const [ss, ms] = ssMs.split(",");
  return Number(hh) * 3600 + Number(mm) * 60 + Number(ss) + Number(ms) / 1000;
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

function pad3(value: number): string {
  return String(value).padStart(3, "0");
}

function formatSrtTimestamp(seconds: number): string {
  const totalMs = Math.max(0, Math.round(seconds * 1000));
  const h = Math.floor(totalMs / 3_600_000);
  const m = Math.floor((totalMs % 3_600_000) / 60_000);
  const s = Math.floor((totalMs % 60_000) / 1000);
  const ms = totalMs % 1000;
  return `${pad2(h)}:${pad2(m)}:${pad2(s)},${pad3(ms)}`;
}

function parseVttTimestamp(ts: string): { seconds: number; includeHours: boolean } {
  const raw = ts.trim();
  const parts = raw.split(":");
  const includeHours = parts.length === 3;

  let h = 0;
  let m = 0;
  let sMs = "";

  if (parts.length === 3) {
    h = Number(parts[0] ?? 0);
    m = Number(parts[1] ?? 0);
    sMs = parts[2] ?? "0.000";
  } else if (parts.length === 2) {
    m = Number(parts[0] ?? 0);
    sMs = parts[1] ?? "0.000";
  } else {
    return { seconds: 0, includeHours: false };
  }

  const [s, ms] = sMs.split(".");
  const seconds = h * 3600 + m * 60 + Number(s || 0) + Number(ms || 0) / 1000;
  return { seconds, includeHours };
}

function formatVttTimestamp(seconds: number, includeHours: boolean): string {
  const totalMs = Math.max(0, Math.round(seconds * 1000));
  const h = Math.floor(totalMs / 3_600_000);
  const m = Math.floor((totalMs % 3_600_000) / 60_000);
  const s = Math.floor((totalMs % 60_000) / 1000);
  const ms = totalMs % 1000;

  if (includeHours || h > 0) {
    return `${pad2(h)}:${pad2(m)}:${pad2(s)}.${pad3(ms)}`;
  }
  return `${pad2(m)}:${pad2(s)}.${pad3(ms)}`;
}

export function detectSubtitleFormat(text: string): SubtitleFormat | null {
  const trimmed = text.trimStart();
  if (trimmed.toUpperCase().startsWith("WEBVTT")) return "vtt";
  if (SRT_TIMING_RE.test(trimmed.split(/\r?\n/).find((l) => l.includes("-->")) || "")) return "srt";
  if (VTT_TIMING_RE.test(trimmed.split(/\r?\n/).find((l) => l.includes("-->")) || "")) return "vtt";
  return null;
}

export function shiftSubtitleTimings(text: string, offsetSeconds: number): string {
  if (!offsetSeconds) return text;

  const lines = text.split(/\r?\n/);
  const out: string[] = [];

  for (const line of lines) {
    const srtMatch = line.match(SRT_TIMING_RE);
    if (srtMatch) {
      const start = clampTime(parseSrtTimestamp(srtMatch[1]!) + offsetSeconds);
      const end = clampTime(parseSrtTimestamp(srtMatch[2]!) + offsetSeconds);
      out.push(`${formatSrtTimestamp(start)} --> ${formatSrtTimestamp(Math.max(end, start))}${srtMatch[3] ?? ""}`);
      continue;
    }

    const vttMatch = line.match(VTT_TIMING_RE);
    if (vttMatch) {
      const startParsed = parseVttTimestamp(vttMatch[1]!);
      const endParsed = parseVttTimestamp(vttMatch[2]!);
      const includeHours = startParsed.includeHours || endParsed.includeHours;
      const start = clampTime(startParsed.seconds + offsetSeconds);
      const end = clampTime(endParsed.seconds + offsetSeconds);
      out.push(`${formatVttTimestamp(start, includeHours)} --> ${formatVttTimestamp(Math.max(end, start), includeHours)}${vttMatch[3] ?? ""}`);
      continue;
    }

    out.push(line);
  }

  return out.join("\n");
}

