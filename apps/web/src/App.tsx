import { useEffect, useMemo, useRef, useState } from "react";
import "./styles.css";
import { apiClient, type Job, type JobStatus, type MediaAsset, type SystemStatusResponse } from "./api/client";
import { Button, Card, Chip, Input, TextArea } from "./components/ui";
import { Spinner } from "./components/Spinner";
import { SettingsModal } from "./components/SettingsModal";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { detectSubtitleFormat, shiftSubtitleTimings } from "./subtitles/shift";
import { cuesToSubtitles, sortCuesByStart, subtitlesToCues, type SubtitleCue, validateCues } from "./subtitles/cues";
import { exportShortsTimelineCsv, exportShortsTimelineEdl, type ShortsClip } from "./shorts/timeline";

const NAV_ITEMS = [
  { id: "shorts", label: "Shorts" },
  { id: "captions", label: "Captions" },
  { id: "subtitles", label: "Subtitles" },
  { id: "utilities", label: "Utilities" },
  { id: "jobs", label: "Jobs" },
  { id: "system", label: "System" },
];

const PRESETS = [
  { name: "TikTok Bold", accent: "var(--accent-coral)", desc: "High contrast with warm highlight" },
  { name: "Clean Slate", accent: "var(--accent-mint)", desc: "Minimalist white/gray with subtle shadow" },
  { name: "Night Runner", accent: "var(--accent-blue)", desc: "Dark base with electric cyan highlight" },
];

const OUTPUT_FORMATS = ["srt", "vtt", "ass"];
const BACKENDS = ["noop", "faster_whisper", "whisper_cpp"];
const FONTS = ["Inter", "Space Grotesk", "Montserrat", "Open Sans"];
const ASPECTS = ["9:16", "16:9", "1:1"];
const LANGS = ["en", "es", "fr", "de", "it", "pt", "ja", "ko", "zh"];

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const el = document.createElement("textarea");
      el.value = text;
      el.style.position = "fixed";
      el.style.left = "-9999px";
      el.style.top = "0";
      document.body.appendChild(el);
      el.focus();
      el.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(el);
      return ok;
    } catch {
      return false;
    }
  }
}

function CopyCommandButton({ command, label = "Copy curl" }: { command: string; label?: string }) {
  const [status, setStatus] = useState<string | null>(null);

  const onCopy = async () => {
    const ok = await copyToClipboard(command);
    setStatus(ok ? "Copied" : "Copy failed");
    window.setTimeout(() => setStatus(null), 1500);
  };

  return (
    <Button type="button" variant="ghost" onClick={onCopy}>
      {status || label}
    </Button>
  );
}

function useLiveJobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const data = await apiClient.listJobs();
      setJobs(data.slice(0, 5));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  return { jobs, loading, error, refresh };
}

function JobStatusPill({ status }: { status: JobStatus }) {
  const toneMap: Record<JobStatus, "neutral" | "info" | "success" | "danger" | "muted"> = {
    queued: "neutral",
    running: "info",
    completed: "success",
    failed: "danger",
    cancelled: "muted",
  };
  return <Chip tone={toneMap[status]}>{status}</Chip>;
}

function CaptionsForm({ onCreated, initialVideoId }: { onCreated: (job: Job) => void; initialVideoId?: string }) {
  const [videoId, setVideoId] = useState(initialVideoId || "");
  const [sourceLang, setSourceLang] = useState("auto");
  const [backend, setBackend] = useState("faster_whisper");
  const [model, setModel] = useState("whisper-large-v3");
  const [formats, setFormats] = useState<string[]>(["srt"]);
  const [speakerLabels, setSpeakerLabels] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialVideoId) {
      setVideoId(initialVideoId);
    }
  }, [initialVideoId]);

  const toggleFormat = (fmt: string) => {
    setFormats((prev) => (prev.includes(fmt) ? prev.filter((f) => f !== fmt) : [...prev, fmt]));
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const job = await apiClient.createCaptionJob({
        video_asset_id: videoId.trim(),
        options: {
          source_language: sourceLang || "auto",
          backend,
          model,
          formats,
          speaker_labels: speakerLabels,
          diarization_backend: speakerLabels ? "pyannote" : "noop",
        },
      });
      onCreated(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create caption job");
    } finally {
      setBusy(false);
    }
  };

  const backendHelp =
    backend === "noop"
      ? "No transcription runs; generates placeholder captions (offline-safe)."
      : backend === "faster_whisper"
      ? "Runs locally via faster-whisper. Long videos can take minutes on CPU; GPU recommended."
      : "Runs locally via whisper.cpp (offline). Model download/setup required.";

  const curlCommand = useMemo(() => {
    const payload = {
      video_asset_id: videoId.trim() || "<VIDEO_ASSET_ID>",
      options: {
        source_language: sourceLang || "auto",
        backend,
        model,
        formats,
        speaker_labels: speakerLabels,
        diarization_backend: speakerLabels ? "pyannote" : "noop",
      },
    };
    return `curl -sS -X POST \"${apiClient.baseUrl}/captions/jobs\" -H \"Content-Type: application/json\" -d '${JSON.stringify(payload)}'`;
  }, [videoId, sourceLang, backend, model, formats, speakerLabels]);

  return (
    <form className="form-grid" onSubmit={submit}>
      <label className="field">
        <span>Video asset ID</span>
        <Input value={videoId} onChange={(e) => setVideoId(e.target.value)} required />
      </label>
      <div className="field checkbox-group">
        <span>Output formats</span>
        <div className="checkbox-row">
          {OUTPUT_FORMATS.map((fmt) => (
            <label key={fmt} className="checkbox">
              <input type="checkbox" checked={formats.includes(fmt)} onChange={() => toggleFormat(fmt)} />
              <span>{fmt.toUpperCase()}</span>
            </label>
          ))}
        </div>
      </div>
      <details className="field full">
        <summary>Advanced settings</summary>
        <div className="form-grid" style={{ marginTop: 12 }}>
          <label className="field" title="ISO language code. Use 'auto' to let the backend decide.">
            <span>Source language</span>
            <Input value={sourceLang} onChange={(e) => setSourceLang(e.target.value)} placeholder="auto" />
          </label>
          <label
            className="field"
            title="Transcription backend. Use 'noop' for offline-safe placeholder output. Local backends require extra installs."
          >
            <span>Backend</span>
            <select className="input" value={backend} onChange={(e) => setBackend(e.target.value)}>
              {BACKENDS.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </label>
          <label className="field" title="Model name used by the selected backend. Ignored for 'noop'.">
            <span>Model</span>
            <Input value={model} onChange={(e) => setModel(e.target.value)} />
          </label>
          <label
            className="field"
            title="Adds speaker labels (e.g. SPEAKER_01) using optional diarization. Requires extra worker deps; offline mode disables model downloads."
          >
            <span>Speaker labels</span>
            <select className="input" value={speakerLabels ? "on" : "off"} onChange={(e) => setSpeakerLabels(e.target.value === "on")}>
              <option value="off">Off</option>
              <option value="on">On (pyannote)</option>
            </select>
          </label>
          <div className="field full">
            <p className="muted">{backendHelp}</p>
            {speakerLabels && (
              <p className="muted">
                Speaker labels are experimental and require a worker build that includes diarization deps (pyannote + torch). If
                the worker can’t diarize, it will fall back without failing the job.
              </p>
            )}
          </div>
        </div>
      </details>
      {backend !== "noop" && (
        <div className="field full">
          <p className="muted">Heads-up: transcription can take a while on CPU for long videos.</p>
        </div>
      )}
      {error && <div className="error-inline">{error}</div>}
      <div className="actions-row">
        <CopyCommandButton command={curlCommand} />
        <Button type="submit" disabled={busy}>
          {busy ? "Submitting..." : "Create caption job"}
        </Button>
      </div>
    </form>
  );
}

function TranslateForm({ onCreated }: { onCreated: (job: Job) => void }) {
  const [subtitleId, setSubtitleId] = useState("");
  const [targetLang, setTargetLang] = useState("es");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const curlCommand = useMemo(() => {
    const payload = {
      subtitle_asset_id: subtitleId.trim() || "<SUBTITLE_ASSET_ID>",
      target_language: targetLang.trim() || "es",
      options: notes ? { notes } : {},
    };
    return `curl -sS -X POST \"${apiClient.baseUrl}/subtitles/translate\" -H \"Content-Type: application/json\" -d '${JSON.stringify(payload)}'`;
  }, [subtitleId, targetLang, notes]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const job = await apiClient.createTranslateJob({
        subtitle_asset_id: subtitleId.trim(),
        target_language: targetLang.trim(),
        options: notes ? { notes } : {},
      });
      onCreated(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create translation job");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="form-grid" onSubmit={submit}>
      <label className="field">
        <span>Subtitle asset ID</span>
        <Input value={subtitleId} onChange={(e) => setSubtitleId(e.target.value)} required />
      </label>
      <label className="field">
        <span>Target language</span>
        <Input value={targetLang} onChange={(e) => setTargetLang(e.target.value)} required />
      </label>
      <label className="field">
        <span>Notes / instructions</span>
        <TextArea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      {error && <div className="error-inline">{error}</div>}
      <div className="actions-row">
        <CopyCommandButton command={curlCommand} />
        <Button type="submit" disabled={busy} variant="secondary">
          {busy ? "Submitting..." : "Request translation"}
        </Button>
      </div>
    </form>
  );
}

function UploadPanel({
  onAssetId,
  onPreview,
}: {
  onAssetId: (id: string) => void;
  onPreview: (url: string | null) => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0 || uploading) return;
    const file = files[0];
    const objectUrl = URL.createObjectURL(file);
    setUploading(true);
    setError(null);
    try {
      const asset = await apiClient.uploadAsset(file, "video");
      onPreview(objectUrl);
      onAssetId(asset.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    handleFiles(e.dataTransfer.files);
  };

  return (
    <div
      className="dropzone"
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
      onClick={() => inputRef.current?.click()}
    >
      <input
        type="file"
        accept="video/*"
        style={{ display: "none" }}
        ref={inputRef}
        onChange={(e) => void handleFiles(e.target.files)}
      />
      <p className="metric-value">Upload a video</p>
      <p className="muted">Drop a file here or click to select. Uploads to the backend and returns an asset id.</p>
      {uploading && <p className="muted">Uploading...</p>}
      {error && <div className="error-inline">{error}</div>}
    </div>
  );
}

function AudioUploadPanel({
  onAssetId,
  onPreview,
}: {
  onAssetId: (id: string) => void;
  onPreview: (url: string | null) => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0 || uploading) return;
    const file = files[0];
    const objectUrl = URL.createObjectURL(file);
    setUploading(true);
    setError(null);
    try {
      const asset = await apiClient.uploadAsset(file, "audio");
      onPreview(objectUrl);
      onAssetId(asset.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="dropzone" onDragOver={(e) => e.preventDefault()} onDrop={(e) => handleFiles(e.dataTransfer.files)} onClick={() => inputRef.current?.click()}>
      <input
        type="file"
        accept="audio/*"
        style={{ display: "none" }}
        ref={inputRef}
        onChange={(e) => handleFiles(e.target.files)}
      />
      <p className="metric-value">Upload audio</p>
      <p className="muted">Drop a file or click to select. Uploads to the backend and returns an asset id.</p>
      <Button variant="ghost" type="button">
        Browse audio
      </Button>
      {uploading && <p className="muted">Uploading...</p>}
      {error && <div className="error-inline">{error}</div>}
    </div>
  );
}

function SubtitleUpload({
  onAssetId,
  onPreview,
  label = "Upload subtitles (SRT/VTT)",
}: {
  onAssetId: (id: string) => void;
  onPreview: (url: string | null, name?: string | null) => void;
  label?: string;
}) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0 || uploading) return;
    const file = files[0];
    const objectUrl = URL.createObjectURL(file);
    setUploading(true);
    setError(null);
    try {
      const asset = await apiClient.uploadAsset(file, "subtitle");
      onAssetId(asset.id);
      onPreview(objectUrl, file.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <label className="button-like">
      {label}
      <input
        type="file"
        accept=".srt,.vtt,text/plain"
        style={{ display: "none" }}
        onChange={(e) => void handleFiles(e.target.files)}
      />
      {uploading && <span className="muted">Uploading...</span>}
      {error && <div className="error-inline">{error}</div>}
    </label>
  );
}

function SubtitleEditorCard({
  initialAssetId,
  onAssetChosen,
}: {
  initialAssetId?: string;
  onAssetChosen: (asset: MediaAsset) => void;
}) {
  const [assetId, setAssetId] = useState(initialAssetId || "");
  const [contents, setContents] = useState("");
  const [original, setOriginal] = useState<string | null>(null);
  const [offsetSeconds, setOffsetSeconds] = useState(0);
  const [editorMode, setEditorMode] = useState<"raw" | "cues">("raw");
  const [cues, setCues] = useState<SubtitleCue[]>([]);
  const [cuesFormat, setCuesFormat] = useState<"srt" | "vtt">("srt");
  const [cuesError, setCuesError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<MediaAsset | null>(null);

  useEffect(() => {
    if (initialAssetId) setAssetId(initialAssetId);
  }, [initialAssetId]);

  const syncCuesFromText = (text: string) => {
    const parsed = subtitlesToCues(text);
    setCuesFormat(parsed.format);
    setCues(parsed.cues);
    setCuesError(null);
  };

  const setCuesAndRewriteText = (nextCues: SubtitleCue[]) => {
    setCues(nextCues);
    setContents(cuesToSubtitles(cuesFormat, nextCues));
  };

  const loadFromAssetId = async () => {
    const id = assetId.trim();
    if (!id) return;
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const resp = await apiClient.fetcher(`${apiClient.baseUrl}/assets/${id}/download`);
      if (!resp.ok) {
        const msg = await resp.text().catch(() => resp.statusText);
        throw new Error(msg || "Failed to download subtitle asset");
      }
      const text = await resp.text();
      setOriginal(text);
      setContents(text);
      if (editorMode === "cues") {
        try {
          syncCuesFromText(text);
        } catch (err) {
          setCuesError(err instanceof Error ? err.message : "Failed to parse cues");
          setEditorMode("raw");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load subtitle asset");
    } finally {
      setBusy(false);
    }
  };

  const applyShift = () => {
    const next = shiftSubtitleTimings(contents, offsetSeconds);
    setContents(next);
    if (editorMode === "cues") {
      try {
        syncCuesFromText(next);
      } catch (err) {
        setCuesError(err instanceof Error ? err.message : "Failed to parse cues");
        setEditorMode("raw");
      }
    }
  };

  const reset = () => {
    if (original == null) return;
    setContents(original);
    if (editorMode === "cues") {
      try {
        syncCuesFromText(original);
      } catch (err) {
        setCuesError(err instanceof Error ? err.message : "Failed to parse cues");
        setEditorMode("raw");
      }
    }
  };

  const downloadLocal = () => {
    const fmt = detectSubtitleFormat(contents) || "srt";
    const filename = `edited.${fmt}`;
    const blob = new Blob([contents], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const saveToBackend = async () => {
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const fmt = detectSubtitleFormat(contents) || "srt";
      const filename = `edited.${fmt}`;
      const file = new File([contents], filename, { type: "text/plain" });
      const asset = await apiClient.uploadAsset(file, "subtitle");
      setSaved(asset);
      setAssetId(asset.id);
      onAssetChosen(asset);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save subtitle asset");
    } finally {
      setBusy(false);
    }
  };

  const fmt = detectSubtitleFormat(contents);
  const cueWarnings = editorMode === "cues" ? validateCues(cues) : [];

  return (
    <div className="form-grid">
      <p className="muted">Edit subtitles inline and optionally shift all timings, then re-upload as a new subtitle asset.</p>
      <label className="field">
        <span>Subtitle asset ID</span>
        <div className="actions-row">
          <Input value={assetId} onChange={(e) => setAssetId(e.target.value)} placeholder="Paste an asset id or upload first" />
          <Button type="button" variant="secondary" onClick={() => void loadFromAssetId()} disabled={busy || !assetId.trim()}>
            {busy ? "Loading..." : "Load"}
          </Button>
        </div>
      </label>
      <label className="field">
        <span>Editor mode</span>
        <div className="actions-row">
          <Button type="button" variant={editorMode === "raw" ? "primary" : "secondary"} onClick={() => setEditorMode("raw")}>
            Raw text
          </Button>
          <Button
            type="button"
            variant={editorMode === "cues" ? "primary" : "secondary"}
            onClick={() => {
              try {
                syncCuesFromText(contents);
                setEditorMode("cues");
              } catch (err) {
                setCuesError(err instanceof Error ? err.message : "Failed to parse cues");
                setEditorMode("raw");
              }
            }}
            disabled={!contents.trim()}
            title="Cue table rewrites the subtitle file and may drop advanced WEBVTT blocks (STYLE/NOTE)."
          >
            Cue table
          </Button>
          {editorMode === "cues" && (
            <>
              <Button
                type="button"
                variant="secondary"
                onClick={() => setCuesAndRewriteText(sortCuesByStart(cues))}
                disabled={cues.length < 2}
                title="Sort by start time (and rewrite subtitle file)."
              >
                Sort cues
              </Button>
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  const last = cues[cues.length - 1];
                  const start = last ? Math.max(0, Number(last.end) || 0) : 0;
                  setCuesAndRewriteText([...cues, { start, end: start + 1, text: "" }]);
                }}
              >
                Add cue
              </Button>
            </>
          )}
        </div>
        {cuesError && <div className="error-inline">{cuesError}</div>}
        {editorMode === "cues" && <p className="muted">Cue table mode rewrites the subtitle file; use raw mode for advanced VTT styling.</p>}
      </label>
      <label className="field">
        <span>Shift timings (seconds)</span>
        <div className="actions-row">
          <Input
            type="number"
            step="0.1"
            value={offsetSeconds}
            onChange={(e) => setOffsetSeconds(Number(e.target.value))}
            title="Positive shifts subtitles forward; negative shifts earlier (clamped to 0)."
          />
          <Button type="button" variant="secondary" onClick={applyShift} disabled={!contents}>
            Apply shift
          </Button>
          <Button type="button" variant="ghost" onClick={reset} disabled={original == null}>
            Reset
          </Button>
        </div>
      </label>
      {editorMode === "raw" ? (
        <label className="field full">
          <span>
            Subtitle contents {fmt ? <span className="muted">({fmt.toUpperCase()})</span> : <span className="muted">(unknown format)</span>}
          </span>
          <TextArea
            rows={14}
            value={contents}
            onChange={(e) => {
              setContents(e.target.value);
              setCuesError(null);
            }}
            placeholder="Paste SRT/VTT here…"
          />
        </label>
      ) : (
        <div className="field full">
          <span className="muted">Cue table ({cuesFormat.toUpperCase()})</span>
          {cueWarnings.length > 0 && (
            <div className="output-card">
              <p className="metric-label">Validation</p>
              <ul className="muted">
                {cueWarnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="cue-table">
            {cues.length === 0 && <p className="muted">No cues parsed. Switch to raw mode to edit text directly.</p>}
            {cues.map((cue, idx) => (
              <div key={`${idx}-${cue.start}-${cue.end}`} className="cue-row">
                <div className="cue-index muted">{idx + 1}</div>
                <label className="field" style={{ margin: 0 }}>
                  <span className="muted">Start</span>
                  <Input
                    type="number"
                    step="0.001"
                    value={cue.start}
                    onChange={(e) => {
                      const next = [...cues];
                      next[idx] = { ...cue, start: Number(e.target.value) };
                      setCuesAndRewriteText(next);
                    }}
                  />
                </label>
                <label className="field" style={{ margin: 0 }}>
                  <span className="muted">End</span>
                  <Input
                    type="number"
                    step="0.001"
                    value={cue.end}
                    onChange={(e) => {
                      const next = [...cues];
                      next[idx] = { ...cue, end: Number(e.target.value) };
                      setCuesAndRewriteText(next);
                    }}
                  />
                </label>
                <label className="field" style={{ margin: 0 }}>
                  <span className="muted">Text</span>
                  <TextArea
                    rows={2}
                    value={cue.text}
                    onChange={(e) => {
                      const next = [...cues];
                      next[idx] = { ...cue, text: e.target.value };
                      setCuesAndRewriteText(next);
                    }}
                  />
                </label>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setCuesAndRewriteText(cues.filter((_, i) => i !== idx))}
                  title="Remove cue"
                >
                  Remove
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}
      {error && <div className="error-inline">{error}</div>}
      {saved?.id && (
        <div className="output-card">
          <p className="metric-label">Saved subtitle asset</p>
          <p className="metric-value">{saved.id}</p>
          {saved.uri && (
            <div className="actions-row">
              <Button type="button" variant="secondary" onClick={() => window.open(apiClient.mediaUrl(saved.uri!), "_blank")}>
                Open
              </Button>
              <Button type="button" variant="ghost" onClick={() => navigator.clipboard.writeText(saved.id).catch(() => {})}>
                Copy ID
              </Button>
            </div>
          )}
        </div>
      )}
      <div className="actions-row">
        <Button type="button" variant="ghost" onClick={downloadLocal} disabled={!contents}>
          Download locally
        </Button>
        <Button type="button" variant="primary" onClick={() => void saveToBackend()} disabled={busy || !contents.trim()}>
          {busy ? "Saving..." : "Save as new subtitle asset"}
        </Button>
      </div>
    </div>
  );
}

function SubtitleToolsForm({ onCreated }: { onCreated: (job: Job, bilingual: boolean) => void }) {
  const [subtitleId, setSubtitleId] = useState("");
  const [targetLang, setTargetLang] = useState("es");
  const [bilingual, setBilingual] = useState(false);
  const [uploadPreview, setUploadPreview] = useState<string | null>(null);
  const [uploadName, setUploadName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const job = await apiClient.translateSubtitleAsset({
        subtitle_asset_id: subtitleId.trim(),
        target_language: targetLang.trim(),
        bilingual,
      });
      onCreated(job, bilingual);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit translation");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="form-grid" onSubmit={handleSubmit}>
      <label className="field">
        <span>Subtitle asset ID</span>
        <Input value={subtitleId} onChange={(e) => setSubtitleId(e.target.value)} required />
      </label>
      <SubtitleUpload
        label="Upload SRT/VTT (uploads to backend)"
        onAssetId={(id) => setSubtitleId(id)}
        onPreview={(url, name) => {
          setUploadPreview(url);
          setUploadName(name || null);
        }}
      />
      <label className="field">
        <span>Target language</span>
        <select className="input" value={targetLang} onChange={(e) => setTargetLang(e.target.value)}>
          {LANGS.map((l) => (
            <option key={l}>{l}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Bilingual output</span>
        <div className="checkbox-row">
          <label className="checkbox">
            <input type="checkbox" checked={bilingual} onChange={(e) => setBilingual(e.target.checked)} />
            <span>Include original + translated</span>
          </label>
        </div>
      </label>
      {uploadPreview && (
        <div className="output-card">
          <p className="metric-label">Uploaded subtitle preview {uploadName ? `(${uploadName})` : ""}</p>
          <iframe className="preview-text" src={uploadPreview} title="subtitle-tools-preview" />
        </div>
      )}
      {error && <div className="error-inline">{error}</div>}
      <div className="actions-row">
        <Button type="submit" disabled={busy}>
          {busy ? "Submitting..." : "Translate subtitles"}
        </Button>
      </div>
    </form>
  );
}

function MergeAvForm({ onCreated, initialVideoId, initialAudioId }: { onCreated: (job: Job) => void; initialVideoId?: string; initialAudioId?: string }) {
  const [videoId, setVideoId] = useState(initialVideoId || "");
  const [audioId, setAudioId] = useState(initialAudioId || "");
  const [offset, setOffset] = useState(0);
  const [ducking, setDucking] = useState(false);
  const [normalize, setNormalize] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const curlCommand = useMemo(() => {
    const payload = {
      video_asset_id: videoId.trim() || "<VIDEO_ASSET_ID>",
      audio_asset_id: audioId.trim() || "<AUDIO_ASSET_ID>",
      offset,
      ducking,
      normalize,
    };
    return `curl -sS -X POST \"${apiClient.baseUrl}/utilities/merge-av\" -H \"Content-Type: application/json\" -d '${JSON.stringify(payload)}'`;
  }, [videoId, audioId, offset, ducking, normalize]);

  useEffect(() => {
    if (initialVideoId) setVideoId(initialVideoId);
  }, [initialVideoId]);

  useEffect(() => {
    if (initialAudioId) setAudioId(initialAudioId);
  }, [initialAudioId]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const job = await apiClient.mergeAv({
        video_asset_id: videoId.trim(),
        audio_asset_id: audioId.trim(),
        offset,
        ducking,
        normalize,
      });
      onCreated(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit merge job");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="form-grid" onSubmit={submit}>
      <label className="field">
        <span>Video asset ID</span>
        <Input value={videoId} onChange={(e) => setVideoId(e.target.value)} required />
      </label>
      <label className="field">
        <span>Audio asset ID</span>
        <Input value={audioId} onChange={(e) => setAudioId(e.target.value)} required />
      </label>
      <label className="field">
        <span>Offset (seconds)</span>
        <Input type="number" step="0.1" value={offset} onChange={(e) => setOffset(Number(e.target.value))} />
      </label>
      <label className="field">
        <span>Ducking</span>
        <div className="checkbox-row">
          <label className="checkbox">
            <input type="checkbox" checked={ducking} onChange={(e) => setDucking(e.target.checked)} />
            <span>Lower background audio under narration</span>
          </label>
        </div>
      </label>
      <label className="field">
        <span>Normalize</span>
        <div className="checkbox-row">
          <label className="checkbox">
            <input type="checkbox" checked={normalize} onChange={(e) => setNormalize(e.target.checked)} />
            <span>Normalize output loudness</span>
          </label>
        </div>
      </label>
      {error && <div className="error-inline">{error}</div>}
      <div className="actions-row">
        <CopyCommandButton command={curlCommand} />
        <Button type="submit" disabled={busy}>
          {busy ? "Submitting..." : "Merge audio/video"}
        </Button>
      </div>
    </form>
  );
}

function ShortsForm({ onCreated }: { onCreated: (job: Job) => void }) {
  const [videoId, setVideoId] = useState("");
  const [numClips, setNumClips] = useState(3);
  const [minDuration, setMinDuration] = useState(10);
  const [maxDuration, setMaxDuration] = useState(45);
  const [aspect, setAspect] = useState(ASPECTS[0]);
  const [useSubtitles, setUseSubtitles] = useState(false);
  const [trimSilence, setTrimSilence] = useState(false);
  const [silenceNoiseDb, setSilenceNoiseDb] = useState(-35);
  const [silenceMinDuration, setSilenceMinDuration] = useState(0.4);
  const [subtitleForScoringId, setSubtitleForScoringId] = useState("");
  const [useGroqScoring, setUseGroqScoring] = useState(false);
  const [stylePreset, setStylePreset] = useState("TikTok Bold");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const curlCommand = useMemo(() => {
    const payload = {
      video_asset_id: videoId.trim() || "<VIDEO_ASSET_ID>",
      max_clips: numClips,
      min_duration: minDuration,
      max_duration: maxDuration,
      aspect_ratio: aspect,
      options: {
        use_subtitles: useSubtitles,
        trim_silence: trimSilence,
        ...(trimSilence ? { silence_noise_db: silenceNoiseDb, silence_min_duration: silenceMinDuration } : {}),
        subtitle_asset_id: subtitleForScoringId.trim() || undefined,
        segment_scoring_backend: useGroqScoring ? "groq" : undefined,
        style_preset: stylePreset,
        prompt: prompt || undefined,
      },
    };
    return `curl -sS -X POST \"${apiClient.baseUrl}/shorts/jobs\" -H \"Content-Type: application/json\" -d '${JSON.stringify(payload)}'`;
  }, [
    videoId,
    numClips,
    minDuration,
    maxDuration,
    aspect,
    useSubtitles,
    trimSilence,
    silenceNoiseDb,
    silenceMinDuration,
    subtitleForScoringId,
    useGroqScoring,
    stylePreset,
    prompt,
  ]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const job = await apiClient.createShortsJob({
        video_asset_id: videoId.trim(),
        max_clips: numClips,
        min_duration: minDuration,
        max_duration: maxDuration,
        aspect_ratio: aspect,
        options: {
          use_subtitles: useSubtitles,
          trim_silence: trimSilence,
          ...(trimSilence ? { silence_noise_db: silenceNoiseDb, silence_min_duration: silenceMinDuration } : {}),
          subtitle_asset_id: subtitleForScoringId.trim() || undefined,
          segment_scoring_backend: useGroqScoring ? "groq" : undefined,
          style_preset: stylePreset,
          prompt: prompt || undefined,
        },
      });
      onCreated(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create shorts job");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="form-grid" onSubmit={submit}>
      <label className="field">
        <span>Video asset ID or URL</span>
        <Input value={videoId} onChange={(e) => setVideoId(e.target.value)} required />
      </label>
      <label className="field">
        <span>Number of clips</span>
        <Input type="number" min={1} max={10} value={numClips} onChange={(e) => setNumClips(Number(e.target.value))} />
      </label>
      <label className="field">
        <span>Min duration (s)</span>
        <Input type="number" min={5} value={minDuration} onChange={(e) => setMinDuration(Number(e.target.value))} />
      </label>
      <label className="field">
        <span>Max duration (s)</span>
        <Input type="number" min={5} value={maxDuration} onChange={(e) => setMaxDuration(Number(e.target.value))} />
      </label>
      <label className="field">
        <span>Aspect ratio</span>
        <select className="input" value={aspect} onChange={(e) => setAspect(e.target.value)}>
          {ASPECTS.map((a) => (
            <option key={a}>{a}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Use subtitles</span>
        <div className="checkbox-row">
          <label className="checkbox">
            <input type="checkbox" checked={useSubtitles} onChange={(e) => setUseSubtitles(e.target.checked)} />
            <span>Attach styled subtitles</span>
          </label>
        </div>
      </label>
      <details className="field full">
        <summary>Advanced selection</summary>
        <div className="form-grid" style={{ marginTop: 12 }}>
          <label className="field">
            <span>Trim silence</span>
            <div className="checkbox-row">
              <label className="checkbox">
                <input type="checkbox" checked={trimSilence} onChange={(e) => setTrimSilence(e.target.checked)} />
                <span>Prefer non-silent segments (experimental)</span>
              </label>
            </div>
          </label>
          <label className="field" title="Silence threshold in dB. More negative = stricter (detects quieter audio as silence).">
            <span>Silence threshold (dB)</span>
            <Input
              type="number"
              min={-80}
              max={0}
              step={1}
              value={silenceNoiseDb}
              onChange={(e) => setSilenceNoiseDb(Number(e.target.value))}
              disabled={!trimSilence}
            />
          </label>
          <label className="field" title="Minimum contiguous silence duration to consider (seconds).">
            <span>Min silence duration (s)</span>
            <Input
              type="number"
              min={0}
              step={0.1}
              value={silenceMinDuration}
              onChange={(e) => setSilenceMinDuration(Number(e.target.value))}
              disabled={!trimSilence}
            />
          </label>
          <div className="field full">
            <p className="muted">
              Uses ffmpeg <code>silencedetect</code> to down-rank clips with more silence. Enable only for videos with clear speech/audio
              tracks.
            </p>
          </div>
          <label className="field full">
            <span>Subtitle asset for prompt scoring (optional)</span>
            <Input value={subtitleForScoringId} onChange={(e) => setSubtitleForScoringId(e.target.value)} placeholder="SRT/VTT asset id (timed captions)" />
            <p className="muted">
              Used only when <b>Groq scoring</b> is enabled. Generate captions first, then paste the subtitle asset id here.
            </p>
          </label>
          <label className="field">
            <span>Groq prompt scoring</span>
            <div className="checkbox-row">
              <label className="checkbox">
                <input type="checkbox" checked={useGroqScoring} onChange={(e) => setUseGroqScoring(e.target.checked)} />
                <span>Use Groq (requires GROQ_API_KEY on the worker)</span>
              </label>
            </div>
          </label>
        </div>
      </details>
      <label className="field">
        <span>Style preset</span>
        <select className="input" value={stylePreset} onChange={(e) => setStylePreset(e.target.value)}>
          {PRESETS.map((p) => (
            <option key={p.name}>{p.name}</option>
          ))}
        </select>
      </label>
      <label className="field full">
        <span>Prompt to guide selection</span>
        <TextArea rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Highlight the funniest moments..." />
        {prompt.trim() && !useGroqScoring && <p className="muted">Tip: enable Groq scoring (advanced) to use the prompt for segment selection.</p>}
        {prompt.trim() && useGroqScoring && (
          <p className="muted">
            Groq scoring uses your prompt + a timed subtitle asset to score segments. Requires <code>GROQ_API_KEY</code> on the worker.
          </p>
        )}
      </label>
      {(useSubtitles || numClips > 6 || maxDuration > 60) && (
        <div className="field full">
          <p className="muted">
            Heads-up: generating many/long clips can take a while. Subtitles for clips are currently placeholders (real per-clip captions are a follow-up).
          </p>
        </div>
      )}
      {error && <div className="error-inline">{error}</div>}
      <div className="actions-row">
        <CopyCommandButton command={curlCommand} />
        <Button type="submit" disabled={busy}>
          {busy ? "Submitting..." : "Create shorts job"}
        </Button>
      </div>
    </form>
  );
}

function StyleEditor({
  onPreview,
  onRender,
  onJobCreated,
  videoId,
  subtitleId,
}: {
  onPreview: (payload: any) => Promise<Job | void> | void;
  onRender: (payload: any) => Promise<Job | void> | void;
  onJobCreated?: (job: Job) => void;
  videoId: string;
  subtitleId: string;
}) {
  const [font, setFont] = useState(FONTS[0]);
  const [fontSize, setFontSize] = useState(42);
  const [textColor, setTextColor] = useState("#ffffff");
  const [highlightColor, setHighlightColor] = useState("#facc15");
  const [strokeWidth, setStrokeWidth] = useState(3);
  const [outlineEnabled, setOutlineEnabled] = useState(true);
  const [outlineColor, setOutlineColor] = useState("#000000");
  const [shadowEnabled, setShadowEnabled] = useState(true);
  const [shadowOffset, setShadowOffset] = useState(4);
  const [position, setPosition] = useState("bottom");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const stylePayload = {
    font,
    font_size: fontSize,
    text_color: textColor,
    highlight_color: highlightColor,
    stroke_width: strokeWidth,
    outline_enabled: outlineEnabled,
    outline_color: outlineColor,
    shadow_enabled: shadowEnabled,
    shadow_offset: shadowOffset,
    position,
  };

  const act = async (cb: (payload: any) => Promise<Job | void> | void, preview: boolean) => {
    setBusy(true);
    setMessage(null);
    try {
      const payload = {
        video_asset_id: videoId,
        subtitle_asset_id: subtitleId,
        style: stylePayload,
        ...(preview ? { preview_seconds: 5 } : {}),
      };
      const result = await cb(payload);
      if (result && onJobCreated) {
        onJobCreated(result as Job);
      }
      setMessage(preview ? "Preview requested" : "Render requested");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="style-grid">
      <label className="field">
        <span>Font family</span>
        <select className="input" value={font} onChange={(e) => setFont(e.target.value)}>
          {FONTS.map((f) => (
            <option key={f}>{f}</option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Font size</span>
        <input type="range" min={24} max={72} value={fontSize} onChange={(e) => setFontSize(Number(e.target.value))} />
        <p className="muted">{fontSize}px</p>
      </label>
      <label className="field">
        <span>Text color</span>
        <input type="color" value={textColor} onChange={(e) => setTextColor(e.target.value)} />
      </label>
      <label className="field">
        <span>Highlight color</span>
        <input type="color" value={highlightColor} onChange={(e) => setHighlightColor(e.target.value)} />
      </label>
      <label className="field">
        <span>Stroke width</span>
        <input type="range" min={0} max={8} value={strokeWidth} onChange={(e) => setStrokeWidth(Number(e.target.value))} />
      </label>
      <label className="field">
        <span>Outline</span>
        <div className="checkbox-row">
          <label className="checkbox">
            <input type="checkbox" checked={outlineEnabled} onChange={(e) => setOutlineEnabled(e.target.checked)} />
            <span>Enabled</span>
          </label>
          <input type="color" value={outlineColor} disabled={!outlineEnabled} onChange={(e) => setOutlineColor(e.target.value)} />
        </div>
      </label>
      <label className="field">
        <span>Shadow</span>
        <div className="checkbox-row">
          <label className="checkbox">
            <input type="checkbox" checked={shadowEnabled} onChange={(e) => setShadowEnabled(e.target.checked)} />
            <span>Enabled</span>
          </label>
          <input
            type="range"
            min={0}
            max={16}
            value={shadowOffset}
            disabled={!shadowEnabled}
            onChange={(e) => setShadowOffset(Number(e.target.value))}
          />
        </div>
      </label>
      <label className="field">
        <span>Position</span>
        <select className="input" value={position} onChange={(e) => setPosition(e.target.value)}>
          <option value="bottom">Bottom</option>
          <option value="center">Center</option>
          <option value="top">Top</option>
        </select>
      </label>
      {message && <div className="muted">{message}</div>}
      <div className="actions-row">
        <Button variant="secondary" type="button" onClick={() => act(onPreview, true)} disabled={busy || !videoId}>
          {busy ? "Working..." : "Preview 5s"}
        </Button>
        <Button variant="primary" type="button" onClick={() => act(onRender, false)} disabled={busy || !videoId}>
          {busy ? "Working..." : "Render full video"}
        </Button>
      </div>
    </div>
  );
}

	function AppShell() {
	  const [active, setActive] = useState(NAV_ITEMS[0].id);
	  const [theme, setTheme] = useState<"light" | "dark">("dark");
	  const [showSettings, setShowSettings] = useState(false);
		  const { jobs, loading, error, refresh } = useLiveJobs();
		  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
		  const [inputAsset, setInputAsset] = useState<MediaAsset | null>(null);
		  const [outputAsset, setOutputAsset] = useState<MediaAsset | null>(null);
		  const [assetError, setAssetError] = useState<string | null>(null);
		  const [assetLoading, setAssetLoading] = useState(false);
		  const jobVideoRef = useRef<HTMLVideoElement | null>(null);
		  const [transcriptCues, setTranscriptCues] = useState<SubtitleCue[]>([]);
		  const [transcriptSearch, setTranscriptSearch] = useState("");
		  const [transcriptError, setTranscriptError] = useState<string | null>(null);
		  const [transcriptLoading, setTranscriptLoading] = useState(false);
	  const [uploadedVideoId, setUploadedVideoId] = useState<string>("");
  const [uploadedPreview, setUploadedPreview] = useState<string | null>(null);
  const [subtitleAssetId, setSubtitleAssetId] = useState<string>("");
  const [subtitlePreview, setSubtitlePreview] = useState<string | null>(null);
  const [subtitleFileName, setSubtitleFileName] = useState<string | null>(null);
  const [captionJob, setCaptionJob] = useState<Job | null>(null);
  const [captionOutput, setCaptionOutput] = useState<MediaAsset | null>(null);
  const [translateJob, setTranslateJob] = useState<Job | null>(null);
  const [translateOutput, setTranslateOutput] = useState<MediaAsset | null>(null);
		const [shortsClips, setShortsClips] = useState<
	    ShortsClip[]
	  >([]);
    const [timelineFps, setTimelineFps] = useState(30);
    const [timelineIncludeAudio, setTimelineIncludeAudio] = useState(false);
    const [timelinePerClipReel, setTimelinePerClipReel] = useState(false);
  const [shortsJob, setShortsJob] = useState<Job | null>(null);
  const [shortsStatusPolling, setShortsStatusPolling] = useState(false);
  const [subtitleToolsJob, setSubtitleToolsJob] = useState<Job | null>(null);
  const [mergeJob, setMergeJob] = useState<Job | null>(null);
  const [styleJob, setStyleJob] = useState<Job | null>(null);
  const [shortsOutput, setShortsOutput] = useState<MediaAsset | null>(null);
  const [subtitleToolsOutput, setSubtitleToolsOutput] = useState<MediaAsset | null>(null);
  const [mergeOutput, setMergeOutput] = useState<MediaAsset | null>(null);
  const [styleOutput, setStyleOutput] = useState<MediaAsset | null>(null);
  const [mergeVideoPreview, setMergeVideoPreview] = useState<string | null>(null);
  const [mergeAudioPreview, setMergeAudioPreview] = useState<string | null>(null);
  const [mergeVideoId, setMergeVideoId] = useState<string>("");
  const [mergeAudioId, setMergeAudioId] = useState<string>("");
  const [recentVideoAssets, setRecentVideoAssets] = useState<MediaAsset[]>([]);
	  const [recentSubtitleAssets, setRecentSubtitleAssets] = useState<MediaAsset[]>([]);
	  const [recentAssetsLoading, setRecentAssetsLoading] = useState(false);
	  const [recentAssetsError, setRecentAssetsError] = useState<string | null>(null);
		  const [jobsPageJobs, setJobsPageJobs] = useState<Job[]>([]);
		  const [jobsPageLoading, setJobsPageLoading] = useState(false);
		  const [jobsPageError, setJobsPageError] = useState<string | null>(null);
		  const [deletingJobId, setDeletingJobId] = useState<string | null>(null);
		  const [jobsStatusFilter, setJobsStatusFilter] = useState<JobStatus | "">("");
		  const [jobsTypeFilter, setJobsTypeFilter] = useState("");
		  const [jobsDateFrom, setJobsDateFrom] = useState("");
		  const [jobsDateTo, setJobsDateTo] = useState("");
    const [systemStatus, setSystemStatus] = useState<SystemStatusResponse | null>(null);
    const [systemLoading, setSystemLoading] = useState(false);
    const [systemError, setSystemError] = useState<string | null>(null);

  const [showQuickStart, setShowQuickStart] = useState(() => {
    try {
      return localStorage.getItem("reframe_quickstart_dismissed") !== "1";
    } catch {
      return true;
    }
  });

  const dismissQuickStart = () => {
    setShowQuickStart(false);
    try {
      localStorage.setItem("reframe_quickstart_dismissed", "1");
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const refreshRecentAssets = async () => {
    setRecentAssetsLoading(true);
    setRecentAssetsError(null);
    try {
      const [videos, subtitles] = await Promise.all([
        apiClient.listAssets({ kind: "video", limit: 25 }),
        apiClient.listAssets({ kind: "subtitle", limit: 25 }),
      ]);
      setRecentVideoAssets(videos);
      setRecentSubtitleAssets(subtitles);
    } catch (err) {
      setRecentAssetsError(err instanceof Error ? err.message : "Failed to load assets");
    } finally {
      setRecentAssetsLoading(false);
    }
  };

	  useEffect(() => {
	    if (active === "subtitles") {
	      void refreshRecentAssets();
	    }
	  }, [active]);

		  const loadJobsPage = async () => {
		    setJobsPageLoading(true);
		    setJobsPageError(null);
		    try {
		      const data = await apiClient.listJobs();
		      setJobsPageJobs(data);
		    } catch (err) {
		      setJobsPageError(err instanceof Error ? err.message : "Failed to load jobs");
		    } finally {
		      setJobsPageLoading(false);
		    }
		  };

		  const deleteJobAndRefresh = async (job: Job) => {
		    const confirmed = window.confirm(
		      "Delete this job and its derived assets?\n\nThis removes generated files (clips/subtitles/manifests) stored under media/tmp. Input uploads are kept.",
		    );
		    if (!confirmed) return;

		    setJobsPageError(null);
		    setDeletingJobId(job.id);
		    try {
		      await apiClient.deleteJob(job.id, { deleteAssets: true });
		      if (selectedJob?.id === job.id) {
		        setSelectedJob(null);
		        setInputAsset(null);
		        setOutputAsset(null);
		      }
		      await loadJobsPage();
		      refresh();
		    } catch (err) {
		      setJobsPageError(err instanceof Error ? err.message : "Failed to delete job");
		    } finally {
		      setDeletingJobId(null);
		    }
		  };

		  useEffect(() => {
		    if (active === "jobs") {
		      void loadJobsPage();
		    }
		  }, [active]);

    const loadSystemStatus = async () => {
      setSystemLoading(true);
      setSystemError(null);
      try {
        const status = await apiClient.getSystemStatus();
        setSystemStatus(status);
      } catch (err) {
        setSystemError(err instanceof Error ? err.message : "Failed to load system status");
      } finally {
        setSystemLoading(false);
      }
    };

    useEffect(() => {
      if (active === "system") {
        void loadSystemStatus();
      }
    }, [active]);

		  const formatTimestamp = (value?: string | null) => {
		    if (!value) return "n/a";
		    const date = new Date(value);
		    if (Number.isNaN(date.getTime())) return value;
		    return date.toLocaleString();
		  };

		  const formatCueTime = (seconds: number) => {
		    const total = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
		    const h = Math.floor(total / 3600);
		    const m = Math.floor((total % 3600) / 60);
		    const s = total % 60;
		    const pad2 = (v: number) => String(v).padStart(2, "0");
		    return h > 0 ? `${h}:${pad2(m)}:${pad2(s)}` : `${m}:${pad2(s)}`;
		  };

		  const jobTypeOptions = useMemo(() => {
		    const types = new Set(jobsPageJobs.map((job) => job.job_type).filter(Boolean));
		    return Array.from(types).sort();
		  }, [jobsPageJobs]);

	  const filteredJobs = useMemo(() => {
	    const from = jobsDateFrom ? new Date(`${jobsDateFrom}T00:00:00`) : null;
	    const to = jobsDateTo ? new Date(`${jobsDateTo}T23:59:59`) : null;
	    return jobsPageJobs
	      .filter((job) => (jobsStatusFilter ? job.status === jobsStatusFilter : true))
	      .filter((job) => (jobsTypeFilter ? job.job_type === jobsTypeFilter : true))
	      .filter((job) => {
	        if (!from && !to) return true;
	        if (!job.created_at) return false;
	        const created = new Date(job.created_at);
	        if (Number.isNaN(created.getTime())) return false;
	        if (from && created < from) return false;
	        if (to && created > to) return false;
	        return true;
	      })
	      .sort((a, b) => {
	        const aDate = a.created_at ? new Date(a.created_at).getTime() : 0;
	        const bDate = b.created_at ? new Date(b.created_at).getTime() : 0;
	        return bDate - aDate;
	      });
	  }, [jobsPageJobs, jobsDateFrom, jobsDateTo, jobsStatusFilter, jobsTypeFilter]);

	  const pollJob = (job: Job | null, onUpdate: (j: Job) => void, onAsset?: (a: MediaAsset | null) => void) => {
    if (!job || ["completed", "failed", "cancelled"].includes(job.status)) return null;
    return setInterval(async () => {
      try {
        const refreshed = await apiClient.getJob(job.id);
        onUpdate(refreshed);
        if (job.job_type === "shorts" && refreshed.payload && "clip_assets" in (refreshed.payload as any)) {
          const resolveUri = (value: unknown): string | null => {
            if (!value || typeof value !== "string") return null;
            return apiClient.mediaUrl(value);
          };
	          const clips = ((refreshed.payload as any).clip_assets as any[]).map((c, i) => ({
	            id: c.id || `${refreshed.id}-clip-${i + 1}`,
              start: c.start ?? null,
              end: c.end ?? null,
	            duration: c.duration ?? null,
	            score: c.score ?? null,
	            uri: resolveUri(c.uri ?? c.url),
	            subtitle_uri: resolveUri(c.subtitle_uri),
	            thumbnail_uri: resolveUri(c.thumbnail_uri),
	          }));
	          setShortsClips(clips.filter(Boolean));
	        }
        if (onAsset && refreshed.output_asset_id) {
          try {
            const asset = await apiClient.getAsset(refreshed.output_asset_id);
            onAsset(asset);
          } catch {
            onAsset(null);
          }
        }
      } catch {
        /* ignore */
      }
    }, 5000);
  };

  useEffect(() => {
    if (!shortsJob || ["completed", "failed", "cancelled"].includes(shortsJob.status)) {
      setShortsStatusPolling(false);
      return;
    }
    setShortsStatusPolling(true);
    const id = pollJob(shortsJob, setShortsJob, setShortsOutput);
    return () => {
      if (id) clearInterval(id);
    };
  }, [shortsJob]);

  useEffect(() => {
    const id = pollJob(subtitleToolsJob, setSubtitleToolsJob, setSubtitleToolsOutput);
    return () => {
      if (id) clearInterval(id);
    };
  }, [subtitleToolsJob]);

  useEffect(() => {
    const id = pollJob(mergeJob, setMergeJob, setMergeOutput);
    return () => {
      if (id) clearInterval(id);
    };
  }, [mergeJob]);

  useEffect(() => {
    const id = pollJob(styleJob, setStyleJob, setStyleOutput);
    return () => {
      if (id) clearInterval(id);
    };
  }, [styleJob]);

  useEffect(() => {
    const id = pollJob(captionJob, setCaptionJob, setCaptionOutput);
    return () => {
      if (id) clearInterval(id);
    };
  }, [captionJob]);

  useEffect(() => {
    const id = pollJob(translateJob, setTranslateJob, setTranslateOutput);
    return () => {
      if (id) clearInterval(id);
    };
  }, [translateJob]);

  useEffect(() => {
    if (captionOutput?.id) {
      setSubtitleAssetId(captionOutput.id);
      if (captionOutput.uri && captionOutput.mime_type?.includes("text")) {
        setSubtitlePreview(apiClient.mediaUrl(captionOutput.uri));
        const ext = captionOutput.uri.split(".").pop();
        setSubtitleFileName(ext ? `captions.${ext}` : "captions");
      }
    }
  }, [captionOutput]);

  useEffect(() => {
    if (translateOutput?.id) {
      setSubtitleAssetId(translateOutput.id);
      if (translateOutput.uri && translateOutput.mime_type?.includes("text")) {
        setSubtitlePreview(apiClient.mediaUrl(translateOutput.uri));
        const ext = translateOutput.uri.split(".").pop();
        setSubtitleFileName(ext ? `translated.${ext}` : "translated");
      }
    }
  }, [translateOutput]);


  const waitForJobAsset = async (jobId: string, timeoutMs = 10 * 60_000) => {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const refreshed = await apiClient.getJob(jobId);
      if (["completed", "failed", "cancelled"].includes(refreshed.status)) {
        if (refreshed.output_asset_id) {
          try {
            const asset = await apiClient.getAsset(refreshed.output_asset_id);
            return { job: refreshed, asset };
          } catch {
            return { job: refreshed, asset: null };
          }
        }
        return { job: refreshed, asset: null };
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    throw new Error("Timed out waiting for job output");
  };

	  const ensureSubtitleAssetForStyling = async (): Promise<string> => {
	    if (subtitleAssetId) return subtitleAssetId;
	    if (captionOutput?.id) return captionOutput.id;
	    if (!uploadedVideoId) throw new Error("Upload a video or provide a subtitle asset id first.");
	    setCaptionOutput(null);
	    setCaptionJob(null);
	    const job = await apiClient.createCaptionJob({ video_asset_id: uploadedVideoId, options: {} });
	    setCaptionJob(job);
	    const { job: finished, asset } = await waitForJobAsset(job.id);
	    setCaptionJob(finished);
	    if (asset?.id) {
	      setCaptionOutput(asset);
	      setSubtitleAssetId(asset.id);
	      return asset.id;
	    }
	    throw new Error("Captions did not produce an output asset.");
	  };

		  const selectJobAndAssets = async (job: Job) => {
		    setSelectedJob(job);
		    setInputAsset(null);
		    setOutputAsset(null);
		    setAssetError(null);
		    setAssetLoading(true);
		    try {
	      const refreshed = await apiClient.getJob(job.id);
	      setSelectedJob(refreshed);

	      const inputId = refreshed.input_asset_id;
	      const outputId = refreshed.output_asset_id;
	      const [input, output] = await Promise.all([
	        inputId ? apiClient.getAsset(inputId).catch(() => null) : Promise.resolve(null),
	        outputId ? apiClient.getAsset(outputId).catch(() => null) : Promise.resolve(null),
	      ]);
	      setInputAsset(input);
	      setOutputAsset(output);
	    } catch (err) {
	      setAssetError(err instanceof Error ? err.message : "Failed to fetch job details");
	    } finally {
	      setAssetLoading(false);
		    }
		  };

		  useEffect(() => {
		    setTranscriptCues([]);
		    setTranscriptError(null);
		    setTranscriptLoading(false);
		    setTranscriptSearch("");

		    if (!selectedJob || !outputAsset || outputAsset.kind !== "subtitle" || !outputAsset.uri) return;

		    let cancelled = false;
		    const load = async () => {
		      setTranscriptLoading(true);
		      try {
		        const url = apiClient.mediaUrl(outputAsset.uri!);
		        const resp = await fetch(url);
		        const text = await resp.text();
		        const { cues } = subtitlesToCues(text);
		        if (!cancelled) setTranscriptCues(cues);
		      } catch (err) {
		        if (!cancelled) setTranscriptError(err instanceof Error ? err.message : "Failed to load transcript");
		      } finally {
		        if (!cancelled) setTranscriptLoading(false);
		      }
		    };

		    void load();
		    return () => {
		      cancelled = true;
		    };
		  }, [selectedJob?.id, outputAsset?.uri]);

		  const recentStatuses = useMemo(
		    () => ({
		      completed: jobs.filter((j) => j.status === "completed").length,
		      running: jobs.filter((j) => j.status === "running").length,
      queued: jobs.filter((j) => j.status === "queued").length,
    }),
    [jobs]
  );

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <span className="dot" />
          <div>
            <div className="brand-title">Reframe</div>
            <div className="brand-sub">Media toolkit</div>
          </div>
        </div>
        <nav>
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              className={`nav-link ${active === item.id ? "active" : ""}`}
              onClick={() => setActive(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <Button variant="ghost" onClick={() => setShowSettings(true)}>
            Settings
          </Button>
          <Button variant="ghost" onClick={() => setTheme(theme === "light" ? "dark" : "light")}>
            {theme === "light" ? "Dark theme" : "Light theme"}
          </Button>
        </div>
      </aside>

      <main className="content">
        <header className="topbar">
          <div>
            <p className="eyebrow">Dashboard</p>
            <h1>Creative media pipeline</h1>
            <p className="lead">
              Kick off captions, translations, styled subtitles, and shorts in one place. Jobs are listed
              below once created through the API.
            </p>
          </div>
          <div className="topbar-actions">
            <Button variant="primary" onClick={() => setShowSettings(true)}>
              Quick settings
            </Button>
          </div>
        </header>

        {showQuickStart && (
          <section className="grid">
            <Card title="Quick start">
              <ol className="muted">
                <li>
                  Start the stack: <code>./start.sh up</code>
                </li>
                <li>
                  (Optional) Generate sample media: <code>make tools-ffmpeg &amp;&amp; make sample-media</code>
                </li>
                <li>Upload a video, then create a captions/shorts job.</li>
              </ol>
              <div className="actions-row">
                <CopyCommandButton command={`./start.sh up`} label="Copy start command" />
                <CopyCommandButton command={`make tools-ffmpeg && make sample-media`} label="Copy sample media command" />
                <Button type="button" variant="ghost" onClick={dismissQuickStart}>
                  Dismiss
                </Button>
              </div>
            </Card>
          </section>
        )}

        <section className="grid">
          <Card title="System health">
            <div className="metric-row">
              <div>
                <p className="metric-label">API Base</p>
                <p className="metric-value">{apiClient.baseUrl}</p>
              </div>
              <div>
                <p className="metric-label">Theme</p>
                <p className="metric-value">{theme}</p>
              </div>
            </div>
          </Card>

          <Card title="Recent jobs">
            {loading && <Spinner label="Loading jobs..." />}
            {error && <div className="error-inline">{error}</div>}
            {!loading && !error && jobs.length === 0 && <p className="muted">No jobs yet.</p>}
            {!loading &&
	              jobs.map((job) => (
	                <button key={job.id} className="job-row selectable" onClick={() => void selectJobAndAssets(job)}>
	                  <div>
	                    <p className="metric-label">{job.job_type}</p>
	                    <p className="metric-value">{job.id}</p>
	                  </div>
	                  <JobStatusPill status={job.status} />
	                </button>
	              ))}
          </Card>

          <Card title="Status snapshot">
            <div className="snapshot">
              <div>
                <p className="metric-label">Queued</p>
                <p className="metric-value">{recentStatuses.queued}</p>
              </div>
              <div>
                <p className="metric-label">Running</p>
                <p className="metric-value">{recentStatuses.running}</p>
              </div>
              <div>
                <p className="metric-label">Completed</p>
                <p className="metric-value">{recentStatuses.completed}</p>
              </div>
            </div>
          </Card>

          <Card title="Outputs & preview">
            {!selectedJob && <p className="muted">Select a completed job to view outputs.</p>}
            {selectedJob && (
              <>
                <p className="metric-label">Job</p>
                <p className="metric-value">{selectedJob.id}</p>
                {!selectedJob.output_asset_id && <p className="muted">No output asset yet.</p>}
                {assetLoading && <Spinner label="Loading asset..." />}
                {assetError && <div className="error-inline">{assetError}</div>}
                {outputAsset && (
                  <div className="output-card">
                    <p className="metric-label">Asset</p>
                    <p className="metric-value">{outputAsset.id}</p>
                    <p className="muted">{outputAsset.mime_type || outputAsset.kind}</p>
                    {outputAsset.uri && (
                      <div className="actions-row">
                        <a className="btn btn-primary" href={apiClient.mediaUrl(outputAsset.uri)} download>
                          Download
                        </a>
                      </div>
                    )}
                    {outputAsset.uri && outputAsset.mime_type?.includes("video") && (
                      <video className="preview" controls src={apiClient.mediaUrl(outputAsset.uri)} />
                    )}
                    {outputAsset.uri && outputAsset.mime_type?.includes("text") && (
                      <iframe className="preview-text" src={apiClient.mediaUrl(outputAsset.uri)} title="subtitle-preview" />
                    )}
                  </div>
                )}
              </>
            )}
          </Card>
        </section>

	        {active === "shorts" && (
	          <section className="grid two-col">
            <Card title="Upload or link video">
              <UploadPanel onAssetId={(id) => setUploadedVideoId(id)} onPreview={(url) => setUploadedPreview(url)} />
              {uploadedPreview && <video className="preview" controls src={uploadedPreview} />}
            </Card>
            <Card title="Shorts maker">
              <ShortsForm
                onCreated={(job) => {
                  setShortsJob(job);
                  setShortsClips([]);
                  setShortsOutput(null);
                  refresh();
                }}
              />
            </Card>
	          <Card title="Progress">
	            {shortsJob ? (
	              <div className="snapshot">
                <div>
                  <p className="metric-label">Job</p>
                  <p className="metric-value">{shortsJob.id}</p>
                </div>
                <div>
                  <p className="metric-label">Status</p>
                  <JobStatusPill status={shortsJob.status} />
                </div>
                <div className="progress-bar">
                  <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${Math.round((shortsJob.progress || 0) * 100)}%` }} />
                  </div>
                  <p className="muted">{Math.round((shortsJob.progress || 0) * 100)}% complete</p>
                </div>
                <p className="muted">Steps: transcribe → segment → render</p>
                {shortsStatusPolling && <Spinner label="Polling job status..." />}
	                {(shortsOutput?.uri || shortsClips.length > 0) && (
	                  <div className="actions-row">
	                    {shortsOutput?.uri && (
	                      <a className="btn btn-primary" href={apiClient.mediaUrl(shortsOutput.uri)} download>
	                        Download manifest
	                      </a>
	                    )}
                      {shortsClips.length > 0 && (
                        <>
                          <label className="field" style={{ margin: 0 }}>
                            <span className="muted">FPS</span>
                            <select className="input" value={timelineFps} onChange={(e) => setTimelineFps(Number(e.target.value))}>
                              <option value={24}>24</option>
                              <option value={25}>25</option>
                              <option value={30}>30</option>
                              <option value={60}>60</option>
                            </select>
                          </label>
                          <label className="checkbox" title="Include an audio track line per clip (A) in the EDL export.">
                            <input type="checkbox" checked={timelineIncludeAudio} onChange={(e) => setTimelineIncludeAudio(e.target.checked)} />
                            <span>Audio</span>
                          </label>
                          <label className="checkbox" title="Use unique reel names per clip in the EDL export (helps NLE imports).">
                            <input type="checkbox" checked={timelinePerClipReel} onChange={(e) => setTimelinePerClipReel(e.target.checked)} />
                            <span>Per-clip reel</span>
                          </label>
                          <Button
                            type="button"
                            variant="secondary"
                            onClick={() => {
                              const csv = exportShortsTimelineCsv(shortsClips);
                              const blob = new Blob([csv], { type: "text/csv" });
                              const url = URL.createObjectURL(blob);
                              const a = document.createElement("a");
                              a.href = url;
                              a.download = "shorts_timeline.csv";
                              document.body.appendChild(a);
                              a.click();
                              document.body.removeChild(a);
                              window.setTimeout(() => URL.revokeObjectURL(url), 1000);
                            }}
                          >
                            Download CSV
                          </Button>
                          <Button
                            type="button"
                            variant="secondary"
                            onClick={() => {
                              const edl = exportShortsTimelineEdl(shortsClips, {
                                fps: timelineFps,
                                title: `Reframe Shorts (${shortsJob.id})`,
                                includeAudio: timelineIncludeAudio,
                                perClipReel: timelinePerClipReel,
                              });
                              const blob = new Blob([edl], { type: "text/plain" });
                              const url = URL.createObjectURL(blob);
                              const a = document.createElement("a");
                              a.href = url;
                              a.download = "shorts_timeline.edl";
                              document.body.appendChild(a);
                              a.click();
                              document.body.removeChild(a);
                              window.setTimeout(() => URL.revokeObjectURL(url), 1000);
                            }}
                          >
                            Download EDL
                          </Button>
                        </>
                      )}
	                    </div>
	                  )}
	                </div>
	              ) : (
	                <p className="muted">Create a shorts job to view progress.</p>
	              )}
	            </Card>
          <Card title="Results">
            {shortsClips.length === 0 && (
              <p className="muted">
                {shortsJob && ["running", "queued"].includes(shortsJob.status)
                  ? "Waiting for clips from backend..."
                  : "No clips yet."}
              </p>
            )}
            <div className="clip-grid">
              {shortsClips.map((clip) => (
                <div key={clip.id} className="clip-card">
                  <div className="clip-thumb">
                    {clip.thumbnail_uri ? <img src={apiClient.mediaUrl(clip.thumbnail_uri)} alt="Clip thumbnail" /> : <div className="placeholder-thumb" />}
                  </div>
                  <p className="metric-value">{clip.duration ? `${clip.duration}s` : "?"}</p>
                  <p className="muted">Score: {clip.score ?? "?"}</p>
                  <div className="actions-row">
                    <Button variant="secondary" disabled={!clip.uri} onClick={() => clip.uri && window.open(apiClient.mediaUrl(clip.uri), "_blank")}>
                      {clip.uri ? "Download video" : "Video not ready"}
                    </Button>
                    <Button variant="ghost" disabled={!clip.subtitle_uri} onClick={() => clip.subtitle_uri && window.open(apiClient.mediaUrl(clip.subtitle_uri), "_blank")}>
                      {clip.subtitle_uri ? "Download subs" : "Subs not ready"}
                    </Button>
                    <Button variant="ghost" onClick={() => setShortsClips((prev) => prev.filter((c) => c.id !== clip.id))}>
                      Remove
                    </Button>
                  </div>
                </div>
                ))}
              </div>
            </Card>
          </section>
        )}

        {active === "captions" && (
          <section className="grid two-col">
            <Card title="Upload video">
              <UploadPanel onAssetId={(id) => setUploadedVideoId(id)} onPreview={(url) => setUploadedPreview(url)} />
              {uploadedPreview && <video className="preview" controls src={uploadedPreview} />}
            </Card>
            <Card title="Captions & Translate">
              <p className="muted">Create caption jobs with backend/model and format options.</p>
              <CaptionsForm onCreated={() => refresh()} initialVideoId={uploadedVideoId} />
            </Card>
            <Card title="Translate subtitles">
          <p className="muted">Submit translation jobs for existing subtitle assets.</p>
          <TranslateForm
            onCreated={(job) => {
              setTranslateJob(job);
              setTranslateOutput(null);
              refresh();
            }}
          />
          {translateJob && (
            <div className="output-card">
              <p className="metric-label">Translation job {translateJob.id}</p>
              <div className="snapshot">
                <div>
                  <p className="metric-label">Status</p>
                  <JobStatusPill status={translateJob.status} />
                </div>
                <div>
                  <p className="metric-label">Target language</p>
                  <p className="metric-value">{(translateJob.payload as any)?.target_language ?? "n/a"}</p>
                </div>
              </div>
              {translateOutput?.uri ? (
                <div className="actions-row">
                  <a className="btn btn-primary" href={apiClient.mediaUrl(translateOutput.uri)} download>
                    Download translated subtitles
                  </a>
                  <Button variant="ghost" onClick={() => setSubtitlePreview(translateOutput.uri ? apiClient.mediaUrl(translateOutput.uri) : null)}>
                    Preview
                  </Button>
                </div>
              ) : (
                <p className="muted">Waiting for translated subtitles...</p>
              )}
            </div>
          )}
        </Card>
      </section>
        )}

		        {active === "subtitles" && (
		          <section className="grid two-col">
		            <Card title="Select assets">
	              <label className="field">
	                <span>Video asset ID</span>
	                <Input value={uploadedVideoId} onChange={(e) => setUploadedVideoId(e.target.value)} />
	              </label>
	              <label className="field">
	                <span>Or pick a recent video asset</span>
	                <div className="actions-row">
	                  <select
	                    className="input"
	                    value=""
	                    onChange={(e) => {
	                      const id = e.target.value;
	                      if (!id) return;
	                      const asset = recentVideoAssets.find((a) => a.id === id);
	                      setUploadedVideoId(id);
	                      setUploadedPreview(asset?.uri ? apiClient.mediaUrl(asset.uri) : null);
	                    }}
	                  >
	                    <option value="">Select a video asset…</option>
	                    {recentVideoAssets.map((asset) => (
	                      <option key={asset.id} value={asset.id}>
	                        {asset.id}
	                      </option>
	                    ))}
	                  </select>
	                  <Button type="button" variant="ghost" onClick={() => void refreshRecentAssets()} disabled={recentAssetsLoading}>
	                    {recentAssetsLoading ? "Refreshing..." : "Refresh"}
	                  </Button>
	                </div>
	                {recentAssetsError && <div className="error-inline">{recentAssetsError}</div>}
	              </label>
	              <label className="field">
	                <span>Subtitle asset ID</span>
	                <Input value={subtitleAssetId} onChange={(e) => setSubtitleAssetId(e.target.value)} />
	              </label>
	              <label className="field">
	                <span>Or pick a recent subtitle asset</span>
	                <div className="actions-row">
	                  <select
	                    className="input"
	                    value=""
	                    onChange={(e) => {
	                      const id = e.target.value;
	                      if (!id) return;
	                      const asset = recentSubtitleAssets.find((a) => a.id === id);
	                      setSubtitleAssetId(id);
	                      if (asset?.uri) {
	                        setSubtitlePreview(apiClient.mediaUrl(asset.uri));
	                        const ext = asset.uri.split(".").pop();
	                        setSubtitleFileName(ext ? `subtitles.${ext}` : "subtitles");
	                      } else {
	                        setSubtitlePreview(null);
	                        setSubtitleFileName(null);
	                      }
	                    }}
	                  >
	                    <option value="">Select a subtitle asset…</option>
	                    {recentSubtitleAssets.map((asset) => (
	                      <option key={asset.id} value={asset.id}>
	                        {asset.id}
	                      </option>
	                    ))}
	                  </select>
	                  <Button type="button" variant="ghost" onClick={() => void refreshRecentAssets()} disabled={recentAssetsLoading}>
	                    {recentAssetsLoading ? "Refreshing..." : "Refresh"}
	                  </Button>
	                </div>
	                {recentAssetsError && <div className="error-inline">{recentAssetsError}</div>}
	              </label>
	              <SubtitleUpload
	                onAssetId={(id) => setSubtitleAssetId(id)}
	                onPreview={(url, name) => {
	                  setSubtitlePreview(url);
                  setSubtitleFileName(name || null);
                }}
              />
              <div className="actions-row">
                <Button
                  type="button"
                  variant="secondary"
                  disabled={!uploadedVideoId || (captionJob && !["failed", "cancelled", "completed"].includes(captionJob.status))}
                  onClick={async () => {
                    setCaptionOutput(null);
                    setCaptionJob(null);
                    if (!uploadedVideoId) return;
                    try {
                      const job = await apiClient.createCaptionJob({ video_asset_id: uploadedVideoId, options: {} });
                      setCaptionJob(job);
                    } catch (err) {
                      setAssetError(err instanceof Error ? err.message : "Failed to request captions");
                    }
                  }}
                >
                  {captionJob && ["running", "queued"].includes(captionJob.status) ? "Generating captions..." : "Generate captions from video"}
                </Button>
                {captionJob && <JobStatusPill status={captionJob.status} />}
              </div>
              <UploadPanel onAssetId={(id) => setUploadedVideoId(id)} onPreview={(url) => setUploadedPreview(url)} />
              {uploadedPreview && <video className="preview" controls src={uploadedPreview} />}
              {subtitlePreview && (
                <div className="output-card">
                  <p className="metric-label">Subtitle preview {subtitleFileName ? `(${subtitleFileName})` : ""}</p>
                  <iframe className="preview-text" src={subtitlePreview} title="subtitle-upload-preview" />
                </div>
              )}
            </Card>
		            <Card title="Style editor">
              <p className="muted">Tune subtitle styling; if no subtitles are set, we will auto-generate captions first.</p>
              <StyleEditor
                videoId={uploadedVideoId}
                subtitleId={subtitleAssetId}
                onPreview={async (payload) => {
                  const sid = await ensureSubtitleAssetForStyling();
                  const job = await apiClient.createStyledSubtitleJob({ ...payload, subtitle_asset_id: sid, preview_seconds: 5 });
                  setStyleJob(job);
                  setStyleOutput(null);
                  refresh();
                  return job;
                }}
                onRender={async (payload) => {
                  const sid = await ensureSubtitleAssetForStyling();
                  const job = await apiClient.createStyledSubtitleJob({ ...payload, subtitle_asset_id: sid });
                  setStyleJob(job);
                  setStyleOutput(null);
                  refresh();
                  return job;
                }}
                onJobCreated={(job) => {
                  setStyleJob(job);
                  setStyleOutput(null);
                }}
              />
	              {styleJob && (
	                <div className="output-card">
	                  <p className="metric-label">Styling job {styleJob.id}</p>
	                  <p className="muted">Status: {styleJob.status}</p>
                  {styleOutput?.uri && (
                    <div className="actions-row">
                      <a className="btn btn-primary" href={apiClient.mediaUrl(styleOutput.uri)} download>
                        {styleJob.payload && (styleJob.payload as any).preview_seconds ? "Download preview" : "Download render"}
                      </a>
                    </div>
                  )}
	                  {styleOutput?.uri && styleOutput.mime_type?.includes("video") && (
	                    <video className="preview" controls src={apiClient.mediaUrl(styleOutput.uri)} />
	                  )}
	                </div>
	              )}
		            </Card>
                <Card title="Subtitle editor">
                  <SubtitleEditorCard
                    initialAssetId={subtitleAssetId}
                    onAssetChosen={(asset) => {
                      setSubtitleAssetId(asset.id);
                      setSubtitlePreview(asset.uri ? apiClient.mediaUrl(asset.uri) : null);
                      setSubtitleFileName(asset.uri?.split("/").pop() || "edited.srt");
                    }}
                  />
                </Card>
		          </section>
		        )}

	        {active === "utilities" && (
	          <section className="grid two-col">
            <Card title="Subtitle tools">
              <p className="muted">Upload or specify subtitle asset to translate; bilingual option available.</p>
              <SubtitleToolsForm
                onCreated={(job) => {
                  setSubtitleToolsJob(job);
                  setSubtitleToolsOutput(null);
                }}
              />
              {subtitleToolsJob && (
                <div className="output-card">
                  <p className="metric-label">Job {subtitleToolsJob.id}</p>
                  <p className="muted">Status: {subtitleToolsJob.status}</p>
                  {["running", "queued"].includes(subtitleToolsJob.status) && <Spinner label="Polling job status..." />}
                  <div className="actions-row">
                    {subtitleToolsOutput?.uri ? (
                      <a className="btn btn-primary" href={apiClient.mediaUrl(subtitleToolsOutput.uri)} download>
                        Download translated subtitles
                      </a>
                    ) : (
                      <div className="muted">Waiting for translated subtitles...</div>
                    )}
                  </div>
                </div>
              )}
            </Card>

            <Card title="Video / Audio merge">
              <p className="muted">Merge audio into a video with optional offset, ducking, and normalization.</p>
              <UploadPanel onAssetId={(id) => setMergeVideoId(id)} onPreview={(url) => setMergeVideoPreview(url)} />
              {mergeVideoPreview && <video className="preview" controls src={mergeVideoPreview} />}
              <AudioUploadPanel onAssetId={(id) => setMergeAudioId(id)} onPreview={(url) => setMergeAudioPreview(url)} />
              {mergeAudioPreview && <audio controls src={mergeAudioPreview} />}
              <MergeAvForm
                onCreated={(job) => {
                  setMergeJob(job);
                  setMergeOutput(null);
                }}
                initialVideoId={mergeVideoId}
                initialAudioId={mergeAudioId}
              />
              {mergeJob && (
                <div className="output-card">
                  <p className="metric-label">Job {mergeJob.id}</p>
                  <p className="muted">Status: {mergeJob.status}</p>
                  {["running", "queued"].includes(mergeJob.status) && <Spinner label="Polling job status..." />}
                  <div className="actions-row">
                    {mergeOutput?.uri ? (
                      <a className="btn btn-primary" href={apiClient.mediaUrl(mergeOutput.uri)} download>
                        Download merged output
                      </a>
                    ) : (
                      <div className="muted">Waiting for merged output...</div>
                    )}
                  </div>
                </div>
              )}
            </Card>
	          </section>
	        )}

		        {active === "jobs" && (
		          <section className="grid two-col">
		            <Card title="Jobs">
		              <div className="form-grid">
		                <label className="field">
		                  <span>Status</span>
		                  <select className="input" value={jobsStatusFilter} onChange={(e) => setJobsStatusFilter(e.target.value as JobStatus | "")}>
		                    <option value="">All</option>
		                    <option value="queued">Queued</option>
		                    <option value="running">Running</option>
		                    <option value="completed">Completed</option>
		                    <option value="failed">Failed</option>
		                    <option value="cancelled">Cancelled</option>
		                  </select>
		                </label>
		                <label className="field">
		                  <span>Type</span>
		                  <select className="input" value={jobsTypeFilter} onChange={(e) => setJobsTypeFilter(e.target.value)}>
		                    <option value="">All</option>
		                    {jobTypeOptions.map((t) => (
		                      <option key={t} value={t}>
		                        {t}
		                      </option>
		                    ))}
		                  </select>
		                </label>
		                <label className="field">
		                  <span>From</span>
		                  <Input type="date" value={jobsDateFrom} onChange={(e) => setJobsDateFrom(e.target.value)} />
		                </label>
		                <label className="field">
		                  <span>To</span>
		                  <Input type="date" value={jobsDateTo} onChange={(e) => setJobsDateTo(e.target.value)} />
		                </label>
		              </div>
		              <div className="actions-row">
		                <Button type="button" variant="ghost" onClick={() => void loadJobsPage()} disabled={jobsPageLoading}>
		                  {jobsPageLoading ? "Refreshing..." : "Refresh"}
		                </Button>
		                <Button
		                  type="button"
		                  variant="ghost"
		                  onClick={() => {
		                    setJobsStatusFilter("");
		                    setJobsTypeFilter("");
		                    setJobsDateFrom("");
		                    setJobsDateTo("");
		                  }}
		                >
		                  Clear filters
		                </Button>
		              </div>
	              {jobsPageError && <div className="error-inline">{jobsPageError}</div>}
	              {jobsPageLoading && <Spinner label="Loading jobs..." />}
	              {!jobsPageLoading && filteredJobs.length === 0 && <p className="muted">No jobs match the current filters.</p>}
	              {!jobsPageLoading && filteredJobs.length > 0 && (
	                <div className="table-scroll">
	                  <table className="table">
	                    <thead>
	                      <tr>
	                        <th>Type</th>
	                        <th>Status</th>
	                        <th>Progress</th>
	                        <th>Created</th>
	                        <th></th>
	                      </tr>
	                    </thead>
	                    <tbody>
	                      {filteredJobs.map((job) => (
	                        <tr
	                          key={job.id}
	                          className={selectedJob?.id === job.id ? "row-selected" : undefined}
	                          onClick={() => void selectJobAndAssets(job)}
	                        >
	                          <td>
	                            <div className="metric-value">{job.job_type}</div>
	                            <div className="muted mono">{job.id}</div>
	                          </td>
	                          <td>
	                            <JobStatusPill status={job.status} />
	                          </td>
	                          <td>
	                            <div className="progress-track">
	                              <div className="progress-fill" style={{ width: `${Math.round((job.progress || 0) * 100)}%` }} />
	                            </div>
	                            <div className="muted">{Math.round((job.progress || 0) * 100)}%</div>
	                          </td>
	                          <td className="muted">{formatTimestamp(job.created_at)}</td>
	                          <td>
	                            <Button
	                              type="button"
	                              variant="ghost"
	                              onClick={(e) => {
	                                e.stopPropagation();
	                                void selectJobAndAssets(job);
	                              }}
	                            >
	                              View
	                            </Button>
	                          </td>
	                        </tr>
	                      ))}
	                    </tbody>
	                  </table>
	                </div>
	              )}
	            </Card>

	            <Card title="Job detail">
	              {!selectedJob && <p className="muted">Select a job to view details.</p>}
	              {selectedJob && (
	                <>
		                  <div className="snapshot">
		                    <div>
		                      <p className="metric-label">Type</p>
		                      <p className="metric-value">{selectedJob.job_type}</p>
		                    </div>
		                    <div>
		                      <p className="metric-label">Status</p>
		                      <JobStatusPill status={selectedJob.status} />
		                    </div>
		                    <div>
		                      <p className="metric-label">Progress</p>
		                      <p className="metric-value">{Math.round((selectedJob.progress || 0) * 100)}%</p>
		                    </div>
		                    {(() => {
		                      const payload = (selectedJob.payload || {}) as any;
		                      const attempt = payload.retry_attempt;
		                      const max = payload.retry_max_attempts;
		                      const step = payload.retry_step;
		                      if (!attempt || !max) return null;
		                      return (
		                        <div>
		                          <p className="metric-label">Retry</p>
		                          <p className="metric-value">
		                            {String(attempt)}/{String(max)}
		                          </p>
		                          {step && <p className="muted">{String(step)}</p>}
		                        </div>
		                      );
		                    })()}
		                  </div>
	                  <div className="output-card">
	                    <p className="metric-label">IDs</p>
	                    <p className="muted mono">Job: {selectedJob.id}</p>
	                    {selectedJob.input_asset_id && <p className="muted mono">Input: {selectedJob.input_asset_id}</p>}
	                    {selectedJob.output_asset_id && <p className="muted mono">Output: {selectedJob.output_asset_id}</p>}
	                    <p className="muted">Created: {formatTimestamp(selectedJob.created_at)}</p>
	                    <p className="muted">Updated: {formatTimestamp(selectedJob.updated_at)}</p>
	                  </div>
	                  {assetLoading && <Spinner label="Loading assets..." />}
	                  {assetError && <div className="error-inline">{assetError}</div>}

			                  <div className="actions-row">
			                    <Button
			                      type="button"
			                      variant="ghost"
			                      onClick={async () => {
		                        try {
		                          await navigator.clipboard.writeText(JSON.stringify(selectedJob, null, 2));
		                        } catch {
		                          /* ignore */
		                        }
		                      }}
		                    >
		                      Copy job JSON
		                    </Button>
			                    <a className="btn btn-secondary" href={`${apiClient.baseUrl}/jobs/${selectedJob.id}/bundle`}>
			                      Download bundle
			                    </a>
			                    {outputAsset?.uri && (
			                      <a className="btn btn-secondary" href={apiClient.mediaUrl(outputAsset.uri)} target="_blank" rel="noreferrer">
			                        Open output
			                      </a>
			                    )}
			                    <Button
			                      type="button"
			                      variant="danger"
			                      disabled={
			                        deletingJobId === selectedJob.id ||
			                        !["completed", "failed", "cancelled"].includes(selectedJob.status)
			                      }
			                      onClick={() => void deleteJobAndRefresh(selectedJob)}
			                    >
			                      {deletingJobId === selectedJob.id ? "Deleting..." : "Delete job"}
			                    </Button>
			                  </div>

			                  {outputAsset?.kind === "subtitle" && (
			                    <div className="output-card">
			                      <p className="metric-label">Transcript viewer</p>
			                      {inputAsset?.kind === "video" && inputAsset.uri && (
			                        <video
			                          ref={jobVideoRef}
			                          className="video-preview"
			                          controls
			                          src={apiClient.mediaUrl(inputAsset.uri)}
			                        />
			                      )}
			                      <div className="form-grid">
			                        <label className="field">
			                          <span>Search</span>
			                          <Input
			                            type="text"
			                            value={transcriptSearch}
			                            placeholder="Find text…"
			                            onChange={(e) => setTranscriptSearch(e.target.value)}
			                          />
			                        </label>
			                      </div>
			                      {transcriptLoading && <Spinner label="Loading transcript..." />}
			                      {transcriptError && <div className="error-inline">{transcriptError}</div>}
			                      {!transcriptLoading && !transcriptError && transcriptCues.length === 0 && (
			                        <p className="muted">No cues found for this output.</p>
			                      )}
			                      {!transcriptLoading && transcriptCues.length > 0 && (
			                        <div className="table-scroll">
			                          <table className="table">
			                            <thead>
			                              <tr>
			                                <th>Time</th>
			                                <th>Text</th>
			                              </tr>
			                            </thead>
			                            <tbody>
			                              {transcriptCues
			                                .filter((cue) => {
			                                  const q = transcriptSearch.trim().toLowerCase();
			                                  if (!q) return true;
			                                  return cue.text.toLowerCase().includes(q);
			                                })
			                                .map((cue, idx) => (
			                                  <tr
			                                    key={`${idx}-${cue.start}-${cue.end}`}
			                                    className="row-clickable"
			                                    onClick={() => {
			                                      if (!jobVideoRef.current) return;
			                                      jobVideoRef.current.currentTime = cue.start;
			                                      void jobVideoRef.current.play().catch(() => {});
			                                    }}
			                                  >
			                                    <td className="muted mono">
			                                      {formatCueTime(cue.start)}–{formatCueTime(cue.end)}
			                                    </td>
			                                    <td>
			                                      <pre className="code-block">{cue.text}</pre>
			                                    </td>
			                                  </tr>
			                                ))}
			                            </tbody>
			                          </table>
			                        </div>
			                      )}
			                    </div>
			                  )}

		                  {selectedJob.error && (
		                    <div className="output-card">
		                      <p className="metric-label">Logs / error</p>
		                      <pre className="code-block">{selectedJob.error}</pre>
		                    </div>
	                  )}

	                  {(selectedJob.payload || inputAsset || outputAsset) && (
	                    <div className="output-card">
	                      <p className="metric-label">Inputs / outputs</p>
	                      {inputAsset && (
	                        <div className="output-card">
	                          <p className="metric-label">Input asset</p>
	                          <p className="muted mono">{inputAsset.id}</p>
	                          {inputAsset.uri && (
	                            <div className="actions-row">
	                              <a className="btn btn-ghost" href={apiClient.mediaUrl(inputAsset.uri)} target="_blank" rel="noreferrer">
	                                Open
	                              </a>
	                            </div>
	                          )}
	                        </div>
	                      )}
	                      {outputAsset && (
	                        <div className="output-card">
	                          <p className="metric-label">Output asset</p>
	                          <p className="muted mono">{outputAsset.id}</p>
	                          <p className="muted">{outputAsset.mime_type || outputAsset.kind}</p>
	                          {outputAsset.uri && (
	                            <div className="actions-row">
	                              <a className="btn btn-primary" href={apiClient.mediaUrl(outputAsset.uri)} download>
	                                Download
	                              </a>
	                              {outputAsset.mime_type?.includes("text") && (
	                                <Button
	                                  type="button"
	                                  variant="ghost"
	                                  onClick={async () => {
	                                    if (!outputAsset.uri) return;
	                                    try {
	                                      const resp = await fetch(apiClient.mediaUrl(outputAsset.uri));
	                                      const text = await resp.text();
	                                      await navigator.clipboard.writeText(text);
	                                    } catch {
	                                      /* ignore */
	                                    }
	                                  }}
	                                >
	                                  Copy output text
	                                </Button>
	                              )}
	                            </div>
	                          )}
	                          {outputAsset.uri && outputAsset.mime_type?.includes("video") && (
	                            <video className="preview" controls src={apiClient.mediaUrl(outputAsset.uri)} />
	                          )}
	                          {outputAsset.uri && outputAsset.mime_type?.includes("text") && (
	                            <iframe className="preview-text" src={apiClient.mediaUrl(outputAsset.uri)} title="job-output-preview" />
	                          )}
	                        </div>
	                      )}
	                      {selectedJob.payload && (
	                        <div className="output-card">
	                          <p className="metric-label">Payload</p>
	                          <pre className="code-block">{JSON.stringify(selectedJob.payload, null, 2)}</pre>
	                        </div>
	                      )}
	                    </div>
	                  )}
	                </>
	              )}
	            </Card>
	          </section>
	        )}

          {active === "system" && (
            <section className="grid">
              <Card title="Diagnostics">
                {systemLoading && <Spinner label="Loading system status..." />}
                {systemError && <div className="error-inline">{systemError}</div>}
                {systemStatus && (
                  <>
                    <div className="snapshot">
                      <div>
                        <p className="metric-label">API version</p>
                        <p className="metric-value">{systemStatus.api_version}</p>
                      </div>
                      <div>
                        <p className="metric-label">Offline mode</p>
                        <p className="metric-value">{systemStatus.offline_mode ? "on" : "off"}</p>
                      </div>
                      <div>
                        <p className="metric-label">Storage</p>
                        <p className="metric-value">{systemStatus.storage_backend}</p>
                      </div>
                    </div>

                    <div className="output-card">
                      <p className="metric-label">Worker</p>
                      <p className="muted">Ping: {systemStatus.worker.ping_ok ? "ok" : "no response"}</p>
                      {systemStatus.worker.workers?.length ? (
                        <ul className="muted">
                          {systemStatus.worker.workers.map((w) => (
                            <li key={w}>
                              <code>{w}</code>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {systemStatus.worker.error && <div className="error-inline">{systemStatus.worker.error}</div>}
                    </div>

                    {systemStatus.worker.system_info && (
                      <div className="output-card">
                        <p className="metric-label">Worker system info</p>
                        <pre className="code-block">{JSON.stringify(systemStatus.worker.system_info, null, 2)}</pre>
                      </div>
                    )}
                  </>
                )}

                <div className="actions-row">
                  <Button type="button" variant="ghost" onClick={() => void loadSystemStatus()} disabled={systemLoading}>
                    {systemLoading ? "Refreshing..." : "Refresh"}
                  </Button>
                  <CopyCommandButton
                    command={`docker compose -f infra/docker-compose.yml run --rm worker python /worker/scripts/prefetch_whisper_model.py --model whisper-large-v3`}
                    label="Copy Whisper model prefetch"
                  />
                  <CopyCommandButton
                    command={`docker compose -f infra/docker-compose.yml run --rm worker python /worker/scripts/install_argos_pack.py --list`}
                    label="Copy Argos pack list"
                  />
                </div>
              </Card>
            </section>
          )}

	        {(active === "shorts" || active === "subtitles") && (
	          <section className="grid two-col">
            <Card title="Preset styles">
              <ul className="preset-list">
                {PRESETS.map((preset) => (
                  <li key={preset.name}>
                    <span className="preset-accent" style={{ background: preset.accent }} />
                    <div>
                      <p className="metric-value">{preset.name}</p>
                      <p className="muted">{preset.desc}</p>
                    </div>
                    <Button variant="ghost">Preview</Button>
                  </li>
                ))}
              </ul>
            </Card>

            <Card title="Notes / prompts">
              <TextArea rows={6} placeholder="Describe what to prioritize when generating shorts..." />
              <div className="actions-row">
                <Button variant="secondary">Save draft</Button>
                <Button variant="primary">Share with team</Button>
              </div>
            </Card>
          </section>
        )}
      </main>

      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
    </div>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <AppShell />
    </ErrorBoundary>
  );
}

export default App;
