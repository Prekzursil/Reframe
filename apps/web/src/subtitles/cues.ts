import { detectSubtitleFormat } from "./shift";

export type SubtitleCue = {
  start: number;
  end: number;
  text: string;
};

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

function parseVttTimestamp(ts: string): number {
  const raw = ts.trim();
  const parts = raw.split(":");
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
    return 0;
  }

  const [s, ms] = sMs.split(".");
  return h * 3600 + m * 60 + Number(s || 0) + Number(ms || 0) / 1000;
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

function formatVttTimestamp(seconds: number, includeHours: boolean): string {
  const totalMs = Math.max(0, Math.round(seconds * 1000));
  const h = Math.floor(totalMs / 3_600_000);
  const m = Math.floor((totalMs % 3_600_000) / 60_000);
  const s = Math.floor((totalMs % 60_000) / 1000);
  const ms = totalMs % 1000;
  if (includeHours || h > 0) return `${pad2(h)}:${pad2(m)}:${pad2(s)}.${pad3(ms)}`;
  return `${pad2(m)}:${pad2(s)}.${pad3(ms)}`;
}

export function subtitlesToCues(text: string): { format: SubtitleFormat; cues: SubtitleCue[] } {
  const format = detectSubtitleFormat(text);
  if (!format) throw new Error("Unsupported subtitle format; expected SRT or VTT.");
  const lines = text.replace(/\r\n/g, "\n").split("\n");

  const cues: SubtitleCue[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = (lines[i] ?? "").trimEnd();
    const srtMatch = format === "srt" ? line.match(SRT_TIMING_RE) : null;
    const vttMatch = format === "vtt" ? line.match(VTT_TIMING_RE) : null;

    if (!srtMatch && !vttMatch) {
      i += 1;
      continue;
    }

    let start = 0;
    let end = 0;
    if (srtMatch) {
      start = parseSrtTimestamp(srtMatch[1]!);
      end = parseSrtTimestamp(srtMatch[2]!);
    } else if (vttMatch) {
      start = parseVttTimestamp(vttMatch[1]!);
      end = parseVttTimestamp(vttMatch[2]!);
    }

    i += 1;
    const textLines: string[] = [];
    while (i < lines.length) {
      const next = lines[i] ?? "";
      if (next.trim() === "") break;
      textLines.push(next);
      i += 1;
    }

    cues.push({ start: clampTime(start), end: clampTime(Math.max(end, start)), text: textLines.join("\n").trimEnd() });
    while (i < lines.length && (lines[i] ?? "").trim() === "") i += 1;
  }

  return { format, cues };
}

export function validateCues(cues: SubtitleCue[]): string[] {
  const warnings: string[] = [];
  for (let idx = 0; idx < cues.length; idx += 1) {
    const cue = cues[idx]!;
    if (!Number.isFinite(cue.start) || cue.start < 0) warnings.push(`Cue ${idx + 1}: start time is invalid.`);
    if (!Number.isFinite(cue.end) || cue.end < 0) warnings.push(`Cue ${idx + 1}: end time is invalid.`);
    if (cue.end < cue.start) warnings.push(`Cue ${idx + 1}: end time is before start time.`);
    if (!cue.text.trim()) warnings.push(`Cue ${idx + 1}: text is empty.`);
  }

  for (let idx = 1; idx < cues.length; idx += 1) {
    const prev = cues[idx - 1]!;
    const curr = cues[idx]!;
    if (curr.start < prev.start) warnings.push("Cues are not sorted by start time.");
    if (curr.start < prev.end) warnings.push(`Cue ${idx + 1} overlaps cue ${idx}.`);
  }

  return Array.from(new Set(warnings));
}

export function sortCuesByStart(cues: SubtitleCue[]): SubtitleCue[] {
  return [...cues].sort((a, b) => (a.start - b.start) || (a.end - b.end));
}

export function cuesToSubtitles(format: SubtitleFormat, cues: SubtitleCue[]): string {
  if (format === "srt") {
    const out: string[] = [];
    cues.forEach((cue, idx) => {
      out.push(String(idx + 1));
      out.push(`${formatSrtTimestamp(cue.start)} --> ${formatSrtTimestamp(Math.max(cue.end, cue.start))}`);
      out.push(...cue.text.split("\n"));
      out.push("");
    });
    return out.join("\n").trimEnd() + "\n";
  }

  const includeHours = cues.some((c) => c.start >= 3600 || c.end >= 3600);
  const out: string[] = ["WEBVTT", ""];
  cues.forEach((cue) => {
    out.push(`${formatVttTimestamp(cue.start, includeHours)} --> ${formatVttTimestamp(Math.max(cue.end, cue.start), includeHours)}`);
    out.push(...cue.text.split("\n"));
    out.push("");
  });
  return out.join("\n").trimEnd() + "\n";
}

