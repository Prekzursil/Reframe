import { useEffect, useMemo, useRef, useState } from "react";
import "./styles.css";
import {
  apiClient,
  type AuthMeResponse,
  type BillingPlan,
  type BillingSeatUsage,
  type BillingSubscription,
  type BillingUsageSummary,
  type Job,
  type JobStatus,
  type MediaAsset,
  type OrgContextResponse,
  type OrgInviteResolveResponse,
  type OrgInviteView,
  type Project,
  type ProjectShareLink,
  type SystemStatusResponse,
  type UsageSummary,
} from "./api/client";
import { Button, Card, Chip, Input, TextArea } from "./components/ui";
import { Spinner } from "./components/Spinner";
import { SettingsModal } from "./components/SettingsModal";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { detectSubtitleFormat, shiftSubtitleTimings } from "./subtitles/shift";
import { cuesToSubtitles, sortCuesByStart, subtitlesToCues, type SubtitleCue, validateCues } from "./subtitles/cues";
import { exportShortsTimelineCsv, exportShortsTimelineEdl, type ShortsClip } from "./shorts/timeline";
import { toSafeExternalUrl, toSafeMediaUrl } from "./security/url";

const NAV_ITEMS = [
  { id: "shorts", label: "Shorts" },
  { id: "captions", label: "Captions" },
  { id: "subtitles", label: "Subtitles" },
  { id: "utilities", label: "Utilities" },
  { id: "jobs", label: "Jobs" },
  { id: "usage", label: "Usage" },
  { id: "projects", label: "Projects" },
  { id: "account", label: "Account" },
  { id: "billing", label: "Billing" },
  { id: "system", label: "System" },
];

const PRESETS: { name: string; accent: string; desc: string; style: Record<string, unknown> }[] = [
  {
    name: "TikTok Bold",
    accent: "var(--accent-coral)",
    desc: "High contrast with warm highlight",
    style: {
      font: "Inter",
      font_size: 48,
      text_color: "#ffffff",
      highlight_color: "#facc15",
      stroke_width: 3,
      outline_enabled: true,
      outline_color: "#000000",
      shadow_enabled: true,
      shadow_offset: 4,
      position: "bottom",
    },
  },
  {
    name: "Clean Slate",
    accent: "var(--accent-mint)",
    desc: "Minimalist white/gray with subtle shadow",
    style: {
      font: "Inter",
      font_size: 44,
      text_color: "#f9fafb",
      highlight_color: "#34d399",
      stroke_width: 2,
      outline_enabled: false,
      outline_color: "#000000",
      shadow_enabled: true,
      shadow_offset: 3,
      position: "bottom",
    },
  },
  {
    name: "Night Runner",
    accent: "var(--accent-blue)",
    desc: "Dark base with electric cyan highlight",
    style: {
      font: "Space Grotesk",
      font_size: 46,
      text_color: "#e5e7eb",
      highlight_color: "#22d3ee",
      stroke_width: 3,
      outline_enabled: true,
      outline_color: "#111827",
      shadow_enabled: true,
      shadow_offset: 4,
      position: "bottom",
    },
  },
];

const OUTPUT_FORMATS = ["srt", "vtt", "ass"];
const BACKENDS = ["noop", "faster_whisper", "whisper_cpp"];
const FONTS = ["Inter", "Space Grotesk", "Montserrat", "Open Sans"];
const ASPECTS = ["9:16", "16:9", "1:1"];
const LANGS = ["en", "es", "fr", "de", "it", "pt", "ja", "ko", "zh"];
const ORG_ROLE_OPTIONS = ["owner", "admin", "editor", "viewer"];
const ORG_MANAGER_ROLES = ["owner", "admin"];

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

function TextPreview({
  url,
  title,
  maxChars = 12000,
}: {
  url: string;
  title: string;
  maxChars?: number;
}) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setContent("");

    const safeUrl = toSafeMediaUrl(url);
    if (!safeUrl) {
      setLoading(false);
      setError("Unsafe preview URL");
      return () => {
        cancelled = true;
      };
    }

    void fetch(safeUrl)
      .then((resp) => {
        if (!resp.ok) {
          throw new Error(`Failed to load preview (${resp.status})`);
        }
        return resp.text();
      })
      .then((text) => {
        if (!cancelled) {
          setContent(text.slice(0, maxChars));
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Preview unavailable");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [url, maxChars]);

  return (
    <div>
      <p className="metric-label">{title}</p>
      {loading && <p className="muted">Loading preview…</p>}
      {error && <div className="error-inline">{error}</div>}
      {!loading && !error && <pre className="preview-text">{content || "(empty text)"}</pre>}
    </div>
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

function CaptionsForm({
  onCreated,
  initialVideoId,
  projectId,
}: {
  onCreated: (job: Job) => void;
  initialVideoId?: string;
  projectId?: string;
}) {
  const [videoId, setVideoId] = useState(initialVideoId || "");
  const [sourceLang, setSourceLang] = useState("auto");
  const [backend, setBackend] = useState("faster_whisper");
  const [model, setModel] = useState("whisper-large-v3");
  const [qualityProfile, setQualityProfile] = useState("balanced");
  const [formats, setFormats] = useState<string[]>(["srt"]);
  const [diarizationBackend, setDiarizationBackend] = useState<"noop" | "speechbrain" | "pyannote">("noop");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const speakerLabelsEnabled = diarizationBackend !== "noop";

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
        project_id: projectId || undefined,
        options: {
          source_language: sourceLang || "auto",
          backend,
          model,
          subtitle_quality_profile: qualityProfile,
          formats,
          speaker_labels: speakerLabelsEnabled,
          diarization_backend: diarizationBackend,
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
      ...(projectId ? { project_id: projectId } : {}),
      options: {
        source_language: sourceLang || "auto",
        backend,
        model,
        subtitle_quality_profile: qualityProfile,
        formats,
        speaker_labels: speakerLabelsEnabled,
        diarization_backend: diarizationBackend,
      },
    };
    return `curl -sS -X POST \"${apiClient.baseUrl}/captions/jobs\" -H \"Content-Type: application/json\" -d '${JSON.stringify(payload)}'`;
  }, [videoId, sourceLang, backend, model, qualityProfile, formats, diarizationBackend, speakerLabelsEnabled, projectId]);

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
          <label className="field" title="Subtitle segmentation profile tuned for readability or high-impact edits.">
            <span>Subtitle quality profile</span>
            <select className="input" value={qualityProfile} onChange={(e) => setQualityProfile(e.target.value)}>
              <option value="balanced">balanced</option>
              <option value="readable">readable</option>
              <option value="high_impact">high_impact</option>
            </select>
          </label>
          <label
            className="field"
            title="Adds speaker labels (e.g. SPEAKER_01) using optional diarization. Requires extra worker deps; offline mode disables model downloads."
          >
            <span>Speaker labels</span>
            <select className="input" value={diarizationBackend} onChange={(e) => setDiarizationBackend(e.target.value as typeof diarizationBackend)}>
              <option value="noop">Off</option>
              <option value="speechbrain">On (speechbrain, token-free)</option>
              <option value="pyannote">On (pyannote, HF token)</option>
            </select>
          </label>
          <div className="field full">
            <p className="muted">{backendHelp}</p>
            {speakerLabelsEnabled && diarizationBackend === "pyannote" && (
              <p className="muted">
                Speaker labels via pyannote require a worker build that includes diarization deps (pyannote + torch) and a Hugging Face token
                (`HF_TOKEN`). Offline mode will skip diarization. If the worker can’t diarize, it will fall back without failing the job.
              </p>
            )}
            {speakerLabelsEnabled && diarizationBackend === "speechbrain" && (
              <p className="muted">
                Speaker labels via SpeechBrain are token-free, but still require heavy deps (speechbrain + torch + torchaudio) and may download
                models. Offline mode will skip diarization. If the worker can’t diarize, it will fall back without failing the job.
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

function TranslateForm({ onCreated, projectId }: { onCreated: (job: Job) => void; projectId?: string }) {
  const [subtitleId, setSubtitleId] = useState("");
  const [targetLang, setTargetLang] = useState("es");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const curlCommand = useMemo(() => {
    const payload = {
      subtitle_asset_id: subtitleId.trim() || "<SUBTITLE_ASSET_ID>",
      target_language: targetLang.trim() || "es",
      ...(projectId ? { project_id: projectId } : {}),
      options: notes ? { notes } : {},
    };
    return `curl -sS -X POST \"${apiClient.baseUrl}/subtitles/translate\" -H \"Content-Type: application/json\" -d '${JSON.stringify(payload)}'`;
  }, [subtitleId, targetLang, notes, projectId]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const job = await apiClient.createTranslateJob({
        subtitle_asset_id: subtitleId.trim(),
        target_language: targetLang.trim(),
        project_id: projectId || undefined,
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
  projectId,
}: {
  onAssetId: (id: string) => void;
  onPreview: (url: string | null) => void;
  projectId?: string;
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
      const asset = await apiClient.uploadAsset(file, "video", projectId);
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
  projectId,
}: {
  onAssetId: (id: string) => void;
  onPreview: (url: string | null) => void;
  projectId?: string;
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
      const asset = await apiClient.uploadAsset(file, "audio", projectId);
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
  projectId,
}: {
  onAssetId: (id: string) => void;
  onPreview: (url: string | null, name?: string | null) => void;
  label?: string;
  projectId?: string;
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
      const asset = await apiClient.uploadAsset(file, "subtitle", projectId);
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
  projectId,
}: {
  initialAssetId?: string;
  onAssetChosen: (asset: MediaAsset) => void;
  projectId?: string;
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
      const asset = await apiClient.uploadAsset(file, "subtitle", projectId);
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
  const savedOpenUrl = saved?.uri ? toSafeMediaUrl(apiClient.mediaUrl(saved.uri)) : null;

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
          {savedOpenUrl && (
            <div className="actions-row">
              <a className="btn btn-secondary" href={savedOpenUrl} target="_blank" rel="noreferrer">
                Open
              </a>
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

function SubtitleToolsForm({ onCreated, projectId }: { onCreated: (job: Job, bilingual: boolean) => void; projectId?: string }) {
  const [subtitleId, setSubtitleId] = useState("");
  const [targetLang, setTargetLang] = useState("es");
  const [bilingual, setBilingual] = useState(false);
  const [uploadPreview, setUploadPreview] = useState<string | null>(null);
  const [uploadName, setUploadName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const safeUploadPreview = toSafeMediaUrl(uploadPreview);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const job = await apiClient.translateSubtitleAsset({
        subtitle_asset_id: subtitleId.trim(),
        target_language: targetLang.trim(),
        bilingual,
        project_id: projectId || undefined,
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
        projectId={projectId}
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
      {safeUploadPreview && <TextPreview url={safeUploadPreview} title={`Uploaded subtitle preview ${uploadName ? `(${uploadName})` : ""}`} />}
      {error && <div className="error-inline">{error}</div>}
      <div className="actions-row">
        <Button type="submit" disabled={busy}>
          {busy ? "Submitting..." : "Translate subtitles"}
        </Button>
      </div>
    </form>
  );
}

function MergeAvForm({
  onCreated,
  initialVideoId,
  initialAudioId,
  projectId,
}: {
  onCreated: (job: Job) => void;
  initialVideoId?: string;
  initialAudioId?: string;
  projectId?: string;
}) {
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
      ...(projectId ? { project_id: projectId } : {}),
      offset,
      ducking,
      normalize,
    };
    return `curl -sS -X POST \"${apiClient.baseUrl}/utilities/merge-av\" -H \"Content-Type: application/json\" -d '${JSON.stringify(payload)}'`;
  }, [videoId, audioId, offset, ducking, normalize, projectId]);

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
        project_id: projectId || undefined,
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

function ShortsForm({ onCreated, projectId }: { onCreated: (job: Job) => void; projectId?: string }) {
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
      ...(projectId ? { project_id: projectId } : {}),
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
    projectId,
  ]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const job = await apiClient.createShortsJob({
        video_asset_id: videoId.trim(),
        project_id: projectId || undefined,
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
            <span>Timed subtitle asset (SRT/VTT) (optional)</span>
            <Input
              value={subtitleForScoringId}
              onChange={(e) => setSubtitleForScoringId(e.target.value)}
              placeholder="Subtitle asset id (SRT/VTT with timings)"
            />
            <p className="muted">
              If set, it’s used for <b>Groq scoring</b> <i>and</i> for slicing real per-clip subtitles when <b>Use subtitles</b> is enabled.
              Generate captions first, then paste the output subtitle asset id here.
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
	            Heads-up: generating many/long clips can take a while. For real per-clip subtitles, set a timed subtitle asset id (SRT/VTT) in Advanced selection.
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
		    const [editingClipId, setEditingClipId] = useState<string | null>(null);
		    const [recutClipId, setRecutClipId] = useState<string | null>(null);
        const [styleClipId, setStyleClipId] = useState<string | null>(null);
		    const [shortsEditError, setShortsEditError] = useState<string | null>(null);
        const [shortsStyleError, setShortsStyleError] = useState<string | null>(null);
        const [shortsStylePresetAll, setShortsStylePresetAll] = useState(PRESETS[0]?.name ?? "TikTok Bold");
        const [shortsStyleAllBusy, setShortsStyleAllBusy] = useState(false);
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
    const [retryingJobId, setRetryingJobId] = useState<string | null>(null);
		  const [jobsStatusFilter, setJobsStatusFilter] = useState<JobStatus | "">("");
		  const [jobsTypeFilter, setJobsTypeFilter] = useState("");
		  const [jobsDateFrom, setJobsDateFrom] = useState("");
  const [jobsDateTo, setJobsDateTo] = useState("");
    const [systemStatus, setSystemStatus] = useState<SystemStatusResponse | null>(null);
    const [systemLoading, setSystemLoading] = useState(false);
    const [systemError, setSystemError] = useState<string | null>(null);
    const [usageSummary, setUsageSummary] = useState<UsageSummary | null>(null);
    const [usageLoading, setUsageLoading] = useState(false);
    const [usageError, setUsageError] = useState<string | null>(null);
    const [usageFrom, setUsageFrom] = useState("");
    const [usageTo, setUsageTo] = useState("");
    const [projects, setProjects] = useState<Project[]>([]);
    const [projectsLoading, setProjectsLoading] = useState(false);
    const [projectsError, setProjectsError] = useState<string | null>(null);
    const [selectedProjectId, setSelectedProjectId] = useState<string>("");
    const [projectJobs, setProjectJobs] = useState<Job[]>([]);
    const [projectAssets, setProjectAssets] = useState<MediaAsset[]>([]);
    const [projectDataLoading, setProjectDataLoading] = useState(false);
    const [projectDataError, setProjectDataError] = useState<string | null>(null);
    const [newProjectName, setNewProjectName] = useState("");
    const [newProjectDescription, setNewProjectDescription] = useState("");
    const [projectCreateBusy, setProjectCreateBusy] = useState(false);
    const [shareSourceAssetId, setShareSourceAssetId] = useState("");
    const [projectSearch, setProjectSearch] = useState("");
    const [projectAssetKindFilter, setProjectAssetKindFilter] = useState("");
    const [selectedShareAssetIds, setSelectedShareAssetIds] = useState<string[]>([]);
    const [shareBusy, setShareBusy] = useState(false);
    const [shareLinks, setShareLinks] = useState<ProjectShareLink[]>([]);
    const [authEmail, setAuthEmail] = useState("");
    const [authPassword, setAuthPassword] = useState("");
    const [authDisplayName, setAuthDisplayName] = useState("");
    const [authOrgName, setAuthOrgName] = useState("");
    const [authBusy, setAuthBusy] = useState(false);
    const [authError, setAuthError] = useState<string | null>(null);
    const [authInfo, setAuthInfo] = useState<AuthMeResponse | null>(null);
    const [orgInfo, setOrgInfo] = useState<OrgContextResponse | null>(null);
    const [orgInvites, setOrgInvites] = useState<OrgInviteView[]>([]);
    const [inviteEmail, setInviteEmail] = useState("");
    const [inviteRole, setInviteRole] = useState("viewer");
    const [inviteExpiryDays, setInviteExpiryDays] = useState("7");
    const [inviteBusy, setInviteBusy] = useState(false);
    const [inviteError, setInviteError] = useState<string | null>(null);
    const [inviteResolveToken, setInviteResolveToken] = useState<string | null>(null);
    const [inviteResolveInfo, setInviteResolveInfo] = useState<OrgInviteResolveResponse | null>(null);
    const [inviteResolveError, setInviteResolveError] = useState<string | null>(null);
    const [inviteAcceptBusy, setInviteAcceptBusy] = useState(false);
    const [billingPlans, setBillingPlans] = useState<BillingPlan[]>([]);
    const [billingSubscription, setBillingSubscription] = useState<BillingSubscription | null>(null);
    const [billingUsage, setBillingUsage] = useState<BillingUsageSummary | null>(null);
    const [billingSeatUsage, setBillingSeatUsage] = useState<BillingSeatUsage | null>(null);
    const [billingSeatLimitDraft, setBillingSeatLimitDraft] = useState("1");
    const [billingLoading, setBillingLoading] = useState(false);
    const [billingError, setBillingError] = useState<string | null>(null);

  const [showQuickStart, setShowQuickStart] = useState(() => {
    try {
      return localStorage.getItem("reframe_quickstart_dismissed") !== "1";
    } catch {
      return true;
    }
  });

  const toSafeMediaHref = (uri: string | null | undefined): string | null => {
    if (!uri) return null;
    return toSafeMediaUrl(apiClient.mediaUrl(uri));
  };
  const outputAssetUrl = toSafeMediaHref(outputAsset?.uri);
  const subtitlePreviewUrl = toSafeMediaUrl(subtitlePreview);
  const safeUploadedPreview = toSafeMediaUrl(uploadedPreview);
  const safeMergeVideoPreview = toSafeMediaUrl(mergeVideoPreview);
  const safeMergeAudioPreview = toSafeMediaUrl(mergeAudioPreview);
  const usageMinutesPct = useMemo(() => {
    if (!usageSummary?.quota_job_minutes || !usageSummary.used_job_minutes) return 0;
    return Math.max(0, Math.min(100, (usageSummary.used_job_minutes / usageSummary.quota_job_minutes) * 100));
  }, [usageSummary]);
  const filteredProjects = useMemo(() => {
    const q = projectSearch.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter((project) => {
      const name = project.name?.toLowerCase() || "";
      const desc = project.description?.toLowerCase() || "";
      return name.includes(q) || desc.includes(q);
    });
  }, [projectSearch, projects]);
  const filteredProjectAssets = useMemo(() => {
    return projectAssets.filter((asset) => (projectAssetKindFilter ? asset.kind === projectAssetKindFilter : true));
  }, [projectAssets, projectAssetKindFilter]);
  const projectAssetKinds = useMemo(() => Array.from(new Set(projectAssets.map((asset) => asset.kind))).sort(), [projectAssets]);

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
        apiClient.listAssets({ kind: "video", limit: 25, project_id: selectedProjectId || undefined }),
        apiClient.listAssets({ kind: "subtitle", limit: 25, project_id: selectedProjectId || undefined }),
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
	  }, [active, selectedProjectId]);

		  const loadJobsPage = async () => {
		    setJobsPageLoading(true);
		    setJobsPageError(null);
		    try {
		      const data = await apiClient.listJobs({ project_id: selectedProjectId || undefined });
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

      const retryJobAndRefresh = async (job: Job) => {
        setJobsPageError(null);
        setRetryingJobId(job.id);
        try {
          const retried = await apiClient.retryJob(job.id, { idempotency_key: `retry-${job.id}-${Date.now()}` });
          setSelectedJob(retried);
          await loadJobsPage();
          refresh();
        } catch (err) {
          setJobsPageError(err instanceof Error ? err.message : "Failed to retry job");
        } finally {
          setRetryingJobId(null);
        }
      };

		  useEffect(() => {
		    if (active === "jobs") {
		      void loadJobsPage();
		    }
		  }, [active, selectedProjectId]);

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

    const loadUsageSummary = async () => {
      setUsageLoading(true);
      setUsageError(null);
      try {
        const summary = await apiClient.getUsageSummary({
          from: usageFrom || undefined,
          to: usageTo || undefined,
          project_id: selectedProjectId || undefined,
        });
        setUsageSummary(summary);
      } catch (err) {
        setUsageError(err instanceof Error ? err.message : "Failed to load usage summary");
      } finally {
        setUsageLoading(false);
      }
    };

    const loadProjects = async () => {
      setProjectsLoading(true);
      setProjectsError(null);
      try {
        const data = await apiClient.listProjects();
        setProjects(data);
        if (data.length === 0) {
          setSelectedProjectId("");
        } else if (!selectedProjectId || !data.some((p) => p.id === selectedProjectId)) {
          setSelectedProjectId(data[0]!.id);
        }
      } catch (err) {
        setProjectsError(err instanceof Error ? err.message : "Failed to load projects");
      } finally {
        setProjectsLoading(false);
      }
    };

    useEffect(() => {
      void loadProjects();
    }, []);

    const loadProjectData = async (projectId: string) => {
      if (!projectId) {
        setProjectJobs([]);
        setProjectAssets([]);
        return;
      }
      setProjectDataLoading(true);
      setProjectDataError(null);
      try {
        const [jobsData, assetsData] = await Promise.all([
          apiClient.listProjectJobs(projectId),
          apiClient.listProjectAssets(projectId),
        ]);
        setProjectJobs(jobsData);
        setProjectAssets(assetsData);
        if (!assetsData.some((asset) => asset.id === shareSourceAssetId)) {
          setShareSourceAssetId(assetsData[0]?.id || "");
        }
        setSelectedShareAssetIds((prev) => prev.filter((id) => assetsData.some((asset) => asset.id === id)));
      } catch (err) {
        setProjectDataError(err instanceof Error ? err.message : "Failed to load project data");
      } finally {
        setProjectDataLoading(false);
      }
    };

    useEffect(() => {
      if (active === "usage") {
        void loadUsageSummary();
      }
    }, [active, usageFrom, usageTo, selectedProjectId]);

    useEffect(() => {
      if (active === "projects") {
        void loadProjects();
      }
    }, [active]);

    useEffect(() => {
      if (active === "projects" && selectedProjectId) {
        void loadProjectData(selectedProjectId);
      }
    }, [active, selectedProjectId]);

    useEffect(() => {
      setSelectedShareAssetIds([]);
      setShareLinks([]);
    }, [selectedProjectId]);

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
    if (!job || ["completed", "failed", "cancelled"].includes(job.status)) return () => {};
    let cancelled = false;
    let timer: number | null = null;
    let delayMs = 2000;
    let lastStatus = job.status;
    let lastProgress = job.progress;
    let lastOutputAssetId = job.output_asset_id ?? null;
    let terminalConsistencyChecks = 0;

    const schedule = (ms: number) => {
      if (cancelled) return;
      timer = window.setTimeout(() => {
        void tick();
      }, ms);
    };

    const tick = async () => {
      if (cancelled) return;
      try {
        const refreshed = await apiClient.getJob(job.id);
        onUpdate(refreshed);

        if (job.job_type === "shorts" && refreshed.payload && "clip_assets" in (refreshed.payload as any)) {
          const resolveUri = (value: unknown): string | null => {
            if (!value || typeof value !== "string") return null;
            return toSafeMediaHref(value);
          };
          const defaultStylePreset =
            typeof (refreshed.payload as any).style_preset === "string" && (refreshed.payload as any).style_preset.trim()
              ? (refreshed.payload as any).style_preset.trim()
              : PRESETS[0]?.name ?? "TikTok Bold";
          const clips = ((refreshed.payload as any).clip_assets as any[]).map((c, i) => ({
            id: c.id || `${refreshed.id}-clip-${i + 1}`,
            asset_id: c.asset_id ?? null,
            subtitle_asset_id: c.subtitle_asset_id ?? null,
            thumbnail_asset_id: c.thumbnail_asset_id ?? null,
            styled_asset_id: c.styled_asset_id ?? null,
            styled_uri: resolveUri(c.styled_uri),
            style_preset: typeof c.style_preset === "string" && c.style_preset.trim() ? c.style_preset.trim() : defaultStylePreset,
            start: c.start ?? null,
            end: c.end ?? null,
            duration: c.duration ?? null,
            score: c.score ?? null,
            uri: resolveUri(c.uri ?? c.url),
            subtitle_uri: resolveUri(c.subtitle_uri),
            thumbnail_uri: resolveUri(c.thumbnail_uri),
          }));
          setShortsClips((prev) => {
            const byId = new Map(prev.map((clip) => [clip.id, clip]));
            return clips
              .filter(Boolean)
              .map((clip) => {
                const existing = byId.get(clip.id);
                return {
                  ...clip,
                  styled_asset_id: clip.styled_asset_id ?? existing?.styled_asset_id ?? null,
                  styled_uri: clip.styled_uri ?? existing?.styled_uri ?? null,
                  style_preset: existing?.style_preset ?? clip.style_preset ?? defaultStylePreset,
                };
              });
          });
        }

        if (onAsset && refreshed.output_asset_id && refreshed.output_asset_id !== lastOutputAssetId) {
          try {
            const asset = await apiClient.getAsset(refreshed.output_asset_id);
            onAsset(asset);
            lastOutputAssetId = refreshed.output_asset_id;
          } catch {
            onAsset(null);
          }
        }

        const terminal = ["completed", "failed", "cancelled"].includes(refreshed.status);
        if (terminal) {
          if (refreshed.status === "completed" && !refreshed.output_asset_id && terminalConsistencyChecks < 2) {
            terminalConsistencyChecks += 1;
            schedule(1500 * (terminalConsistencyChecks + 1));
            return;
          }
          return;
        }

        terminalConsistencyChecks = 0;
        const progressed = refreshed.status !== lastStatus || (refreshed.progress ?? 0) > (lastProgress ?? 0);
        delayMs = progressed ? 2000 : Math.min(15000, Math.round(delayMs * 1.5));
        lastStatus = refreshed.status;
        lastProgress = refreshed.progress ?? 0;
        schedule(delayMs);
      } catch {
        delayMs = Math.min(20000, Math.round(delayMs * 1.8));
        schedule(delayMs);
      }
    };

    schedule(0);
    return () => {
      cancelled = true;
      if (timer !== null) {
        clearTimeout(timer);
      }
    };
  };

  useEffect(() => {
    if (!shortsJob || ["completed", "failed", "cancelled"].includes(shortsJob.status)) {
      setShortsStatusPolling(false);
      return;
    }
    setShortsStatusPolling(true);
    return pollJob(shortsJob, setShortsJob, setShortsOutput);
  }, [shortsJob]);

  useEffect(() => {
    return pollJob(subtitleToolsJob, setSubtitleToolsJob, setSubtitleToolsOutput);
  }, [subtitleToolsJob]);

  useEffect(() => {
    return pollJob(mergeJob, setMergeJob, setMergeOutput);
  }, [mergeJob]);

  useEffect(() => {
    return pollJob(styleJob, setStyleJob, setStyleOutput);
  }, [styleJob]);

  useEffect(() => {
    return pollJob(captionJob, setCaptionJob, setCaptionOutput);
  }, [captionJob]);

  useEffect(() => {
    return pollJob(translateJob, setTranslateJob, setTranslateOutput);
  }, [translateJob]);

  useEffect(() => {
    if (captionOutput?.id) {
      setSubtitleAssetId(captionOutput.id);
      if (captionOutput.uri && captionOutput.mime_type?.includes("text")) {
        setSubtitlePreview(toSafeMediaHref(captionOutput.uri));
        const ext = captionOutput.uri.split(".").pop();
        setSubtitleFileName(ext ? `captions.${ext}` : "captions");
      }
    }
  }, [captionOutput]);

  useEffect(() => {
    if (translateOutput?.id) {
      setSubtitleAssetId(translateOutput.id);
      if (translateOutput.uri && translateOutput.mime_type?.includes("text")) {
        setSubtitlePreview(toSafeMediaHref(translateOutput.uri));
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
	    const job = await apiClient.createCaptionJob({
        video_asset_id: uploadedVideoId,
        project_id: selectedProjectId || undefined,
        options: {},
      });
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
			        const url = toSafeMediaHref(outputAsset.uri);
              if (!url) {
                throw new Error("Unsafe subtitle preview URL");
              }
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

		  const moveShortsClip = (clipId: string, delta: -1 | 1) => {
		    setShortsClips((prev) => {
		      const idx = prev.findIndex((c) => c.id === clipId);
		      if (idx < 0) return prev;
		      const nextIdx = idx + delta;
		      if (nextIdx < 0 || nextIdx >= prev.length) return prev;
		      const next = [...prev];
		      const [item] = next.splice(idx, 1);
		      next.splice(nextIdx, 0, item!);
		      return next;
		    });
		  };

			  const recutShortsClip = async (clip: ShortsClip) => {
			    setShortsEditError(null);
			    if (!uploadedVideoId) {
			      setShortsEditError("Upload a source video first.");
			      return;
		    }
		    const start = Number(clip.start ?? 0);
		    const end = Number(clip.end ?? start);
		    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
		      setShortsEditError("Start/end must be valid numbers and end must be greater than start.");
		      return;
		    }

		    setRecutClipId(clip.id);
		    try {
		      const job = await apiClient.createCutClipJob({
            video_asset_id: uploadedVideoId,
            project_id: selectedProjectId || undefined,
            start,
            end,
          });
		      const { job: finished, asset } = await waitForJobAsset(job.id);
		      if (!asset?.uri) throw new Error("Cut-clip job did not produce an output asset.");
		      const payload = (finished.payload || {}) as any;

			      setShortsClips((prev) =>
			        prev.map((c) =>
			          c.id === clip.id
			            ? {
			                ...c,
                      asset_id: asset.id,
			                uri: asset.uri,
                      styled_asset_id: null,
                      styled_uri: null,
                      thumbnail_asset_id: payload.thumbnail_asset_id ?? c.thumbnail_asset_id ?? null,
			                thumbnail_uri: payload.thumbnail_uri ?? c.thumbnail_uri,
			                duration: payload.duration ?? Math.max(0, end - start),
			              }
			            : c,
			        ),
			      );
		      refresh();
		    } catch (err) {
		      setShortsEditError(err instanceof Error ? err.message : "Failed to re-cut clip");
			    } finally {
			      setRecutClipId(null);
			    }
			  };

        const resolveStylePreset = (name: string | null | undefined) => {
          const presetName = String(name || "").trim();
          const preset = PRESETS.find((p) => p.name === presetName) ?? PRESETS[0];
          return { name: preset?.name ?? "TikTok Bold", style: (preset?.style ?? {}) as Record<string, unknown> };
        };

        const applyShortsStylePresetToAll = () => {
          setShortsClips((prev) => prev.map((c) => ({ ...c, style_preset: shortsStylePresetAll })));
        };

        const renderStyledSubtitlesForClip = async (clip: ShortsClip, previewSeconds?: number) => {
          setShortsStyleError(null);
          if (shortsJob && shortsJob.status !== "completed") {
            setShortsStyleError("Wait for the shorts job to finish before rendering styled subtitles.");
            return;
          }
          if (!clip.asset_id) {
            setShortsStyleError("Missing clip asset id (asset_id). Re-run the shorts job.");
            return;
          }
          if (!clip.subtitle_asset_id) {
            setShortsStyleError("This clip has no subtitle asset. Enable “Use subtitles” when generating shorts.");
            return;
          }

          const { style } = resolveStylePreset(clip.style_preset || shortsStylePresetAll);

          setStyleClipId(clip.id);
          try {
            const job = await apiClient.createStyledSubtitleJob({
              video_asset_id: clip.asset_id,
              subtitle_asset_id: clip.subtitle_asset_id,
              project_id: selectedProjectId || undefined,
              style,
              ...(previewSeconds ? { preview_seconds: previewSeconds } : {}),
            });
            refresh();
            const { job: finished, asset } = await waitForJobAsset(job.id);
            if (finished.status !== "completed") {
              throw new Error(finished.error || "Subtitle render failed");
            }
            if (!asset?.uri) {
              throw new Error("Subtitle render did not produce an output asset.");
            }

            setShortsClips((prev) =>
              prev.map((c) =>
                c.id === clip.id
                  ? {
                      ...c,
                      styled_asset_id: asset.id,
                      styled_uri: asset.uri,
                    }
                  : c,
              ),
            );
          } catch (err) {
            setShortsStyleError(err instanceof Error ? err.message : "Failed to render styled subtitles");
          } finally {
            setStyleClipId(null);
          }
        };

        const renderStyledSubtitlesForAllClips = async () => {
          setShortsStyleError(null);
          if (!shortsClips.length) return;
          if (shortsJob && shortsJob.status !== "completed") {
            setShortsStyleError("Wait for the shorts job to finish before rendering styled subtitles.");
            return;
          }

          setShortsStyleAllBusy(true);
          try {
            const clips = [...shortsClips];
            for (const clip of clips) {
              if (!clip.subtitle_asset_id) continue;
              await renderStyledSubtitlesForClip(clip);
            }
          } finally {
            setShortsStyleAllBusy(false);
            setStyleClipId(null);
          }
        };

        const createProject = async () => {
          const name = newProjectName.trim();
          if (!name) return;
          setProjectCreateBusy(true);
          setProjectsError(null);
          try {
            const created = await apiClient.createProject({
              name,
              description: newProjectDescription.trim() || undefined,
            });
            setNewProjectName("");
            setNewProjectDescription("");
            setProjects((prev) => [created, ...prev.filter((p) => p.id !== created.id)]);
            setSelectedProjectId(created.id);
            setShareLinks([]);
          } catch (err) {
            setProjectsError(err instanceof Error ? err.message : "Failed to create project");
          } finally {
            setProjectCreateBusy(false);
          }
        };

        const createShareLink = async () => {
          if (!selectedProjectId) return;
          const assetIds = selectedShareAssetIds.length ? selectedShareAssetIds : shareSourceAssetId ? [shareSourceAssetId] : [];
          if (!assetIds.length) return;
          setShareBusy(true);
          setProjectDataError(null);
          try {
            const response = await apiClient.createProjectShareLinks(selectedProjectId, {
              asset_ids: assetIds,
              expires_in_hours: 24,
            });
            setShareLinks(response.links);
          } catch (err) {
            setProjectDataError(err instanceof Error ? err.message : "Failed to generate share link");
          } finally {
            setShareBusy(false);
          }
        };

        const toggleShareAsset = (assetId: string) => {
          setSelectedShareAssetIds((prev) => (prev.includes(assetId) ? prev.filter((item) => item !== assetId) : [...prev, assetId]));
        };

        const persistTokens = (accessToken: string | null) => {
          apiClient.setAccessToken(accessToken);
          try {
            if (accessToken) {
              localStorage.setItem("reframe_access_token", accessToken);
            } else {
              localStorage.removeItem("reframe_access_token");
            }
          } catch {
            // ignore
          }
        };

        const loadOrgInvites = async (roleHint?: string) => {
          const normalizedRole = String(roleHint || orgInfo?.role || "").trim().toLowerCase();
          if (!apiClient.accessToken || !ORG_MANAGER_ROLES.includes(normalizedRole)) {
            setOrgInvites([]);
            return;
          }
          try {
            const invites = await apiClient.listOrgInvites();
            setOrgInvites(invites);
          } catch (err) {
            setInviteError(err instanceof Error ? err.message : "Failed to load invites");
          }
        };

        const loadAuthContext = async () => {
          try {
            const [me, org] = await Promise.all([apiClient.getMe(), apiClient.getOrgContext()]);
            setAuthInfo(me);
            setOrgInfo(org);
            setAuthError(null);
            await loadOrgInvites(org.role);
          } catch (err) {
            setAuthInfo(null);
            setOrgInfo(null);
            setOrgInvites([]);
            setAuthError(err instanceof Error ? err.message : "Failed to load account context");
          }
        };

        const registerAccount = async () => {
          setAuthBusy(true);
          setAuthError(null);
          try {
            const tokens = await apiClient.register({
              email: authEmail.trim(),
              password: authPassword,
              display_name: authDisplayName.trim() || undefined,
              organization_name: authOrgName.trim() || undefined,
            });
            persistTokens(tokens.access_token);
            await loadAuthContext();
          } catch (err) {
            setAuthError(err instanceof Error ? err.message : "Registration failed");
          } finally {
            setAuthBusy(false);
          }
        };

        const loginAccount = async () => {
          setAuthBusy(true);
          setAuthError(null);
          try {
            const tokens = await apiClient.login({
              email: authEmail.trim(),
              password: authPassword,
            });
            persistTokens(tokens.access_token);
            await loadAuthContext();
          } catch (err) {
            setAuthError(err instanceof Error ? err.message : "Login failed");
          } finally {
            setAuthBusy(false);
          }
        };

        const logoutAccount = async () => {
          setAuthBusy(true);
          setAuthError(null);
          try {
            await apiClient.logout();
          } catch {
            // ignore logout failures, clear local session anyway
          } finally {
            persistTokens(null);
            setAuthInfo(null);
            setOrgInfo(null);
            setOrgInvites([]);
            setAuthBusy(false);
          }
        };

        const createInvite = async () => {
          const email = inviteEmail.trim();
          const role = inviteRole.trim().toLowerCase();
          const expiresInDays = Math.max(1, Math.min(30, Number(inviteExpiryDays || "7")));
          if (!email) return;
          setInviteBusy(true);
          setInviteError(null);
          try {
            const created = await apiClient.createOrgInvite({
              email,
              role,
              expires_in_days: expiresInDays,
            });
            setOrgInvites((prev) => [created, ...prev.filter((invite) => invite.id !== created.id)]);
            setInviteEmail("");
          } catch (err) {
            setInviteError(err instanceof Error ? err.message : "Failed to create invite");
          } finally {
            setInviteBusy(false);
          }
        };

        const revokeInvite = async (inviteId: string) => {
          setInviteBusy(true);
          setInviteError(null);
          try {
            const updated = await apiClient.revokeOrgInvite(inviteId);
            setOrgInvites((prev) => prev.map((invite) => (invite.id === inviteId ? updated : invite)));
          } catch (err) {
            setInviteError(err instanceof Error ? err.message : "Failed to revoke invite");
          } finally {
            setInviteBusy(false);
          }
        };

        const updateMemberRole = async (userId: string, role: string) => {
          setInviteBusy(true);
          setInviteError(null);
          try {
            await apiClient.updateOrgMemberRole(userId, { role });
            await loadAuthContext();
          } catch (err) {
            setInviteError(err instanceof Error ? err.message : "Failed to update member role");
          } finally {
            setInviteBusy(false);
          }
        };

        const removeMember = async (userId: string) => {
          setInviteBusy(true);
          setInviteError(null);
          try {
            await apiClient.removeOrgMember(userId);
            await loadAuthContext();
          } catch (err) {
            setInviteError(err instanceof Error ? err.message : "Failed to remove member");
          } finally {
            setInviteBusy(false);
          }
        };

        const resolveInviteToken = async (token: string) => {
          const normalized = token.trim();
          if (!normalized) {
            setInviteResolveInfo(null);
            setInviteResolveError(null);
            return;
          }
          setInviteResolveError(null);
          try {
            const resolved = await apiClient.resolveOrgInvite(normalized);
            setInviteResolveInfo(resolved);
          } catch (err) {
            setInviteResolveInfo(null);
            setInviteResolveError(err instanceof Error ? err.message : "Failed to resolve invite");
          }
        };

        const acceptInvite = async () => {
          if (!inviteResolveToken) return;
          setInviteAcceptBusy(true);
          setInviteResolveError(null);
          try {
            const tokens = await apiClient.acceptOrgInvite({ token: inviteResolveToken });
            persistTokens(tokens.access_token);
            await loadAuthContext();
            setInviteResolveToken(null);
            setInviteResolveInfo(null);
          } catch (err) {
            setInviteResolveError(err instanceof Error ? err.message : "Failed to accept invite");
          } finally {
            setInviteAcceptBusy(false);
          }
        };

        const loadBillingData = async () => {
          setBillingLoading(true);
          setBillingError(null);
          try {
            const [plans, subscription, usage, seatUsage] = await Promise.all([
              apiClient.listBillingPlans(),
              apiClient.getBillingSubscription(),
              apiClient.getBillingUsageSummary(),
              apiClient.getBillingSeatUsage(),
            ]);
            setBillingPlans(plans);
            setBillingSubscription(subscription);
            setBillingUsage(usage);
            setBillingSeatUsage(seatUsage);
            setBillingSeatLimitDraft(String(seatUsage.seat_limit || 1));
          } catch (err) {
            setBillingError(err instanceof Error ? err.message : "Failed to load billing data");
          } finally {
            setBillingLoading(false);
          }
        };

        const updateSeatLimit = async () => {
          const parsed = Number(billingSeatLimitDraft);
          if (!Number.isFinite(parsed) || parsed < 1) {
            setBillingError("Seat limit must be at least 1");
            return;
          }
          setBillingLoading(true);
          setBillingError(null);
          try {
            const next = await apiClient.updateBillingSeatLimit({ seat_limit: Math.trunc(parsed) });
            setBillingSeatUsage(next);
            setBillingSeatLimitDraft(String(next.seat_limit));
          } catch (err) {
            setBillingError(err instanceof Error ? err.message : "Failed to update seat limit");
          } finally {
            setBillingLoading(false);
          }
        };

        useEffect(() => {
          try {
            const params = new URLSearchParams(window.location.search);
            const token = params.get("token");
            if (token) {
              setInviteResolveToken(token);
            }
            const existing = localStorage.getItem("reframe_access_token");
            if (existing) {
              apiClient.setAccessToken(existing);
              void loadAuthContext();
            }
          } catch {
            // ignore
          }
        }, []);

        useEffect(() => {
          if (active === "account" && apiClient.accessToken) {
            void loadAuthContext();
          }
        }, [active]);

        useEffect(() => {
          if (active === "account" && inviteResolveToken) {
            void resolveInviteToken(inviteResolveToken);
          }
        }, [active, inviteResolveToken]);

        useEffect(() => {
          if (active === "billing" && apiClient.accessToken) {
            void loadBillingData();
          }
        }, [active]);

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
            <label className="field" style={{ marginBottom: 0, minWidth: 220 }}>
              <span>Project scope</span>
              <select className="input" value={selectedProjectId} onChange={(e) => setSelectedProjectId(e.target.value)}>
                <option value="">All projects</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
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
                    {outputAssetUrl && (
                      <div className="actions-row">
                        <a className="btn btn-primary" href={outputAssetUrl} download>
                          Download
                        </a>
                      </div>
                    )}
                    {outputAssetUrl && outputAsset.mime_type?.includes("video") && (
                      <video className="preview" controls src={outputAssetUrl} />
                    )}
                    {outputAssetUrl && outputAsset.mime_type?.includes("text") && <TextPreview url={outputAssetUrl} title="Subtitle preview" />}
                  </div>
                )}
              </>
            )}
          </Card>
        </section>

	        {active === "shorts" && (
	          <section className="grid two-col">
            <Card title="Upload or link video">
              <UploadPanel
                projectId={selectedProjectId || undefined}
                onAssetId={(id) => setUploadedVideoId(id)}
                onPreview={(url) => setUploadedPreview(toSafeMediaUrl(url))}
              />
              {safeUploadedPreview && <video className="preview" controls src={safeUploadedPreview} />}
            </Card>
            <Card title="Shorts maker">
              <ShortsForm
                projectId={selectedProjectId || undefined}
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
		                    {toSafeMediaHref(shortsOutput?.uri) && (
		                      <a className="btn btn-primary" href={toSafeMediaHref(shortsOutput?.uri)!} download>
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
              {shortsStyleError && <div className="error-inline">{shortsStyleError}</div>}
              {shortsClips.length > 0 && (
                <div className="actions-row">
                  <label className="field" style={{ margin: 0, minWidth: 220 }}>
                    <span className="muted">Style preset (batch)</span>
                    <select className="input" value={shortsStylePresetAll} onChange={(e) => setShortsStylePresetAll(e.target.value)}>
                      {PRESETS.map((p) => (
                        <option key={p.name}>{p.name}</option>
                      ))}
                    </select>
                  </label>
                  <Button type="button" variant="ghost" onClick={applyShortsStylePresetToAll} disabled={shortsStyleAllBusy || styleClipId !== null}>
                    Apply to all
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => void renderStyledSubtitlesForAllClips()}
                    disabled={shortsStyleAllBusy || styleClipId !== null || shortsClips.every((c) => !c.subtitle_asset_id)}
                    title={shortsClips.some((c) => !c.subtitle_asset_id) ? "Some clips have no subtitle asset to render." : undefined}
                  >
                    {shortsStyleAllBusy ? "Rendering…" : "Render styled (all clips)"}
                  </Button>
                </div>
              )}
		            <div className="clip-grid">
		              {shortsClips.map((clip, idx) => (
		                <div key={clip.id} className="clip-card">
			                  <div className="clip-thumb">
		                    {toSafeMediaUrl(clip.thumbnail_uri) ? <img src={toSafeMediaUrl(clip.thumbnail_uri)!} alt="Clip thumbnail" /> : <div className="placeholder-thumb" />}
		                  </div>
	                  <p className="metric-value">{clip.duration ? `${clip.duration}s` : "?"}</p>
	                  <p className="muted">Score: {clip.score ?? "?"}</p>
		                  {clip.start != null && clip.end != null && (
		                    <p className="muted">
		                      Time: {formatCueTime(Number(clip.start))}–{formatCueTime(Number(clip.end))}
		                    </p>
		                  )}
                      {clip.subtitle_asset_id && (
                        <label className="field">
                          <span className="muted">Subtitle style</span>
                          <select
                            className="input"
                            value={clip.style_preset ?? shortsStylePresetAll}
                            onChange={(e) => {
                              const next = e.target.value;
                              setShortsClips((prev) => prev.map((c) => (c.id === clip.id ? { ...c, style_preset: next } : c)));
                            }}
                          >
                            {PRESETS.map((p) => (
                              <option key={p.name}>{p.name}</option>
                            ))}
                          </select>
                        </label>
                      )}
                      {(() => {
                        const clipVideoUrl = toSafeMediaUrl(clip.uri);
                        const clipStyledUrl = toSafeMediaUrl(clip.styled_uri);
                        const clipSubtitleUrl = toSafeMediaUrl(clip.subtitle_uri);
                        return (
                          <div className="actions-row">
                            {clipVideoUrl ? (
                              <a className="btn btn-secondary" href={clipVideoUrl} target="_blank" rel="noreferrer">
                                {clip.styled_uri ? "Download raw" : "Download video"}
                              </a>
                            ) : (
                              <Button variant="secondary" disabled>
                                Video not ready
                              </Button>
                            )}
                            {clipStyledUrl ? (
                              <a className="btn btn-ghost" href={clipStyledUrl} target="_blank" rel="noreferrer">
                                Download styled
                              </a>
                            ) : (
                              <Button variant="ghost" disabled>
                                No styled render
                              </Button>
                            )}
                            {clipSubtitleUrl ? (
                              <a className="btn btn-ghost" href={clipSubtitleUrl} target="_blank" rel="noreferrer">
                                Download subs
                              </a>
                            ) : (
                              <Button variant="ghost" disabled>
                                Subs not ready
                              </Button>
                            )}
                            <Button variant="ghost" onClick={() => setShortsClips((prev) => prev.filter((c) => c.id !== clip.id))}>
                              Remove
                            </Button>
                          </div>
                        );
                      })()}
                      {clip.subtitle_asset_id && (
                        <div className="actions-row">
                          <Button
                            type="button"
                            variant="ghost"
                            disabled={shortsStyleAllBusy || styleClipId !== null}
                            onClick={() => void renderStyledSubtitlesForClip(clip, 5)}
                            title="Render a quick preview (5 seconds)."
                          >
                            {styleClipId === clip.id ? "Rendering…" : "Preview 5s"}
                          </Button>
                          <Button
                            type="button"
                            variant="secondary"
                            disabled={shortsStyleAllBusy || styleClipId !== null}
                            onClick={() => void renderStyledSubtitlesForClip(clip)}
                            title="Render the full clip with burnt-in subtitles."
                          >
                            {styleClipId === clip.id ? "Rendering…" : "Render styled"}
                          </Button>
                        </div>
                      )}
		                  <div className="actions-row">
		                    <Button type="button" variant="ghost" disabled={idx === 0} onClick={() => moveShortsClip(clip.id, -1)}>
		                      Up
		                    </Button>
	                    <Button
	                      type="button"
	                      variant="ghost"
	                      disabled={idx === shortsClips.length - 1}
	                      onClick={() => moveShortsClip(clip.id, 1)}
	                    >
	                      Down
	                    </Button>
	                    <Button
	                      type="button"
	                      variant="ghost"
	                      onClick={() => {
	                        setShortsEditError(null);
	                        setEditingClipId((prev) => (prev === clip.id ? null : clip.id));
	                      }}
	                    >
	                      {editingClipId === clip.id ? "Close editor" : "Edit"}
	                    </Button>
	                  </div>

	                  {editingClipId === clip.id && (
	                    <>
	                      {shortsEditError && <div className="error-inline">{shortsEditError}</div>}
	                      <div className="form-grid">
	                        <label className="field">
	                          <span>Start (s)</span>
	                          <Input
	                            type="number"
	                            step="0.1"
	                            value={String(clip.start ?? 0)}
	                            onChange={(e) => {
	                              const nextStart = Number(e.target.value);
	                              setShortsClips((prev) => prev.map((c) => (c.id === clip.id ? { ...c, start: nextStart } : c)));
	                            }}
	                          />
	                        </label>
	                        <label className="field">
	                          <span>End (s)</span>
	                          <Input
	                            type="number"
	                            step="0.1"
	                            value={String(clip.end ?? 0)}
	                            onChange={(e) => {
	                              const nextEnd = Number(e.target.value);
	                              setShortsClips((prev) => prev.map((c) => (c.id === clip.id ? { ...c, end: nextEnd } : c)));
	                            }}
	                          />
	                        </label>
	                      </div>
	                      <div className="actions-row">
	                        <Button
	                          type="button"
	                          variant="secondary"
	                          disabled={recutClipId === clip.id}
	                          onClick={() => void recutShortsClip(clip)}
	                        >
	                          {recutClipId === clip.id ? "Re-cutting..." : "Re-cut clip"}
	                        </Button>
	                      </div>
	                    </>
	                  )}
	                </div>
	                ))}
	              </div>
	            </Card>
          </section>
        )}

        {active === "captions" && (
          <section className="grid two-col">
            <Card title="Upload video">
              <UploadPanel
                projectId={selectedProjectId || undefined}
                onAssetId={(id) => setUploadedVideoId(id)}
                onPreview={(url) => setUploadedPreview(toSafeMediaUrl(url))}
              />
              {safeUploadedPreview && <video className="preview" controls src={safeUploadedPreview} />}
            </Card>
            <Card title="Captions & Translate">
              <p className="muted">Create caption jobs with backend/model and format options.</p>
              <CaptionsForm onCreated={() => refresh()} initialVideoId={uploadedVideoId} projectId={selectedProjectId || undefined} />
            </Card>
            <Card title="Translate subtitles">
          <p className="muted">Submit translation jobs for existing subtitle assets.</p>
          <TranslateForm
            projectId={selectedProjectId || undefined}
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
	              {toSafeMediaHref(translateOutput?.uri) ? (
	                <div className="actions-row">
	                  <a className="btn btn-primary" href={toSafeMediaHref(translateOutput?.uri)!} download>
	                    Download translated subtitles
	                  </a>
	                  <Button variant="ghost" onClick={() => setSubtitlePreview(toSafeMediaHref(translateOutput?.uri))}>
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
		                      setUploadedPreview(toSafeMediaHref(asset?.uri));
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
		                        setSubtitlePreview(toSafeMediaHref(asset.uri));
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
                    projectId={selectedProjectId || undefined}
		                onAssetId={(id) => setSubtitleAssetId(id)}
		                onPreview={(url, name) => {
		                  setSubtitlePreview(toSafeMediaUrl(url));
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
                      const job = await apiClient.createCaptionJob({
                        video_asset_id: uploadedVideoId,
                        project_id: selectedProjectId || undefined,
                        options: {},
                      });
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
              <UploadPanel
                projectId={selectedProjectId || undefined}
                onAssetId={(id) => setUploadedVideoId(id)}
                onPreview={(url) => setUploadedPreview(toSafeMediaUrl(url))}
              />
              {safeUploadedPreview && <video className="preview" controls src={safeUploadedPreview} />}
	              {subtitlePreviewUrl && (
	                <div className="output-card">
                    <TextPreview url={subtitlePreviewUrl} title={`Subtitle preview ${subtitleFileName ? `(${subtitleFileName})` : ""}`} />
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
                  const job = await apiClient.createStyledSubtitleJob({
                    ...payload,
                    subtitle_asset_id: sid,
                    project_id: selectedProjectId || undefined,
                    preview_seconds: 5,
                  });
                  setStyleJob(job);
                  setStyleOutput(null);
                  refresh();
                  return job;
                }}
                onRender={async (payload) => {
                  const sid = await ensureSubtitleAssetForStyling();
                  const job = await apiClient.createStyledSubtitleJob({
                    ...payload,
                    subtitle_asset_id: sid,
                    project_id: selectedProjectId || undefined,
                  });
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
	                  {toSafeMediaHref(styleOutput?.uri) && (
	                    <div className="actions-row">
	                      <a className="btn btn-primary" href={toSafeMediaHref(styleOutput?.uri)!} download>
	                        {styleJob.payload && (styleJob.payload as any).preview_seconds ? "Download preview" : "Download render"}
	                      </a>
	                    </div>
	                  )}
		                  {toSafeMediaHref(styleOutput?.uri) && styleOutput.mime_type?.includes("video") && (
		                    <video className="preview" controls src={toSafeMediaHref(styleOutput?.uri)!} />
		                  )}
	                </div>
	              )}
		            </Card>
                <Card title="Subtitle editor">
	                  <SubtitleEditorCard
	                    initialAssetId={subtitleAssetId}
                      projectId={selectedProjectId || undefined}
	                    onAssetChosen={(asset) => {
	                      setSubtitleAssetId(asset.id);
	                      setSubtitlePreview(toSafeMediaHref(asset.uri));
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
                projectId={selectedProjectId || undefined}
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
	                    {toSafeMediaHref(subtitleToolsOutput?.uri) ? (
	                      <a className="btn btn-primary" href={toSafeMediaHref(subtitleToolsOutput?.uri)!} download>
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
              <UploadPanel
                projectId={selectedProjectId || undefined}
                onAssetId={(id) => setMergeVideoId(id)}
                onPreview={(url) => setMergeVideoPreview(toSafeMediaUrl(url))}
              />
              {safeMergeVideoPreview && <video className="preview" controls src={safeMergeVideoPreview} />}
              <AudioUploadPanel
                projectId={selectedProjectId || undefined}
                onAssetId={(id) => setMergeAudioId(id)}
                onPreview={(url) => setMergeAudioPreview(toSafeMediaUrl(url))}
              />
              {safeMergeAudioPreview && <audio controls src={safeMergeAudioPreview} />}
              <MergeAvForm
                projectId={selectedProjectId || undefined}
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
	                    {toSafeMediaHref(mergeOutput?.uri) ? (
	                      <a className="btn btn-primary" href={toSafeMediaHref(mergeOutput?.uri)!} download>
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
                    {selectedJob.error && (
                      <>
                        <p className="metric-label">Last error</p>
                        <pre className="code-block">{selectedJob.error}</pre>
                      </>
                    )}
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
			                    {toSafeExternalUrl(apiClient.jobBundleUrl(selectedJob.id)) && (
			                      <a className="btn btn-secondary" href={toSafeExternalUrl(apiClient.jobBundleUrl(selectedJob.id))!}>
			                        Download bundle
			                      </a>
			                    )}
                    {toSafeMediaHref(outputAsset?.uri) && (
                      <a className="btn btn-secondary" href={toSafeMediaHref(outputAsset?.uri)!} target="_blank" rel="noreferrer">
                        Open output
                      </a>
                    )}
                    <Button
                      type="button"
                      variant="secondary"
                      disabled={retryingJobId === selectedJob.id || !["failed", "cancelled"].includes(selectedJob.status)}
                      onClick={() => void retryJobAndRefresh(selectedJob)}
                    >
                      {retryingJobId === selectedJob.id ? "Retrying..." : "Retry job"}
                    </Button>
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
				                      {inputAsset?.kind === "video" && toSafeMediaHref(inputAsset?.uri) && (
				                        <video
				                          ref={jobVideoRef}
				                          className="video-preview"
				                          controls
				                          src={toSafeMediaHref(inputAsset?.uri)!}
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
		                          {toSafeMediaHref(inputAsset?.uri) && (
		                            <div className="actions-row">
		                              <a className="btn btn-ghost" href={toSafeMediaHref(inputAsset?.uri)!} target="_blank" rel="noreferrer">
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
		                          {outputAssetUrl && (
		                            <div className="actions-row">
		                              <a className="btn btn-primary" href={outputAssetUrl} download>
		                                Download
		                              </a>
		                              {outputAsset.mime_type?.includes("text") && (
		                                <Button
		                                  type="button"
		                                  variant="ghost"
		                                  onClick={async () => {
		                                    if (!outputAssetUrl) return;
		                                    try {
		                                      const resp = await fetch(outputAssetUrl);
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
		                          {outputAssetUrl && outputAsset.mime_type?.includes("video") && (
		                            <video className="preview" controls src={outputAssetUrl} />
		                          )}
		                          {outputAssetUrl && outputAsset.mime_type?.includes("text") && <TextPreview url={outputAssetUrl} title="Job output preview" />}
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

          {active === "usage" && (
            <section className="grid two-col">
              <Card title="Usage summary">
                <div className="form-grid">
                  <label className="field">
                    <span>From date</span>
                    <Input type="date" value={usageFrom} onChange={(e) => setUsageFrom(e.target.value)} />
                  </label>
                  <label className="field">
                    <span>To date</span>
                    <Input type="date" value={usageTo} onChange={(e) => setUsageTo(e.target.value)} />
                  </label>
                </div>
                <div className="actions-row">
                  <Button type="button" variant="ghost" onClick={() => void loadUsageSummary()} disabled={usageLoading}>
                    {usageLoading ? "Refreshing..." : "Refresh"}
                  </Button>
                </div>
                {usageError && <div className="error-inline">{usageError}</div>}
                {usageLoading && <Spinner label="Loading usage summary..." />}
                {usageSummary && (
                  <div className="snapshot">
                    <div>
                      <p className="metric-label">Plan</p>
                      <p className="metric-value">{usageSummary.plan_code || "n/a"}</p>
                    </div>
                    <div>
                      <p className="metric-label">Total jobs</p>
                      <p className="metric-value">{usageSummary.total_jobs}</p>
                    </div>
                    <div>
                      <p className="metric-label">Completed</p>
                      <p className="metric-value">{usageSummary.completed_jobs}</p>
                    </div>
                    <div>
                      <p className="metric-label">Running</p>
                      <p className="metric-value">{usageSummary.running_jobs}</p>
                    </div>
                    <div>
                      <p className="metric-label">Failed</p>
                      <p className="metric-value">{usageSummary.failed_jobs}</p>
                    </div>
                    <div>
                      <p className="metric-label">Generated assets</p>
                      <p className="metric-value">{usageSummary.output_assets_count}</p>
                    </div>
                    <div>
                      <p className="metric-label">Output duration</p>
                      <p className="metric-value">{usageSummary.output_duration_seconds.toFixed(2)}s</p>
                    </div>
                  </div>
                )}
                {usageSummary?.quota_job_minutes != null && (
                  <div className="output-card">
                    <p className="metric-label">Job minute quota</p>
                    <div className="progress-track">
                      <div className="progress-fill" style={{ width: `${usageMinutesPct}%` }} />
                    </div>
                    <p className="muted">
                      {(usageSummary.used_job_minutes || 0).toFixed(2)} / {usageSummary.quota_job_minutes} minutes
                    </p>
                    {usageSummary.max_concurrent_jobs != null && (
                      <p className="muted">Concurrent jobs cap: {usageSummary.max_concurrent_jobs}</p>
                    )}
                    {(usageSummary.overage_job_minutes || 0) > 0 && (
                      <p className="error-inline">Overage preview: {(usageSummary.overage_job_minutes || 0).toFixed(2)} minutes</p>
                    )}
                  </div>
                )}
              </Card>
              <Card title="By job type">
                {!usageSummary && <p className="muted">No summary loaded yet.</p>}
                {usageSummary && Object.keys(usageSummary.job_type_counts).length === 0 && <p className="muted">No jobs in selected range.</p>}
                {usageSummary && Object.entries(usageSummary.job_type_counts).length > 0 && (
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Job type</th>
                        <th>Count</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(usageSummary.job_type_counts)
                        .sort(([a], [b]) => a.localeCompare(b))
                        .map(([jobType, count]) => (
                          <tr key={jobType}>
                            <td>{jobType}</td>
                            <td>{count}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                )}
              </Card>
            </section>
          )}

          {active === "projects" && (
            <section className="grid two-col">
              <Card title="Projects">
                {projectsError && <div className="error-inline">{projectsError}</div>}
                {projectsLoading && <Spinner label="Loading projects..." />}
                <div className="form-grid">
                  <label className="field">
                    <span>Search projects</span>
                    <Input value={projectSearch} onChange={(e) => setProjectSearch(e.target.value)} placeholder="Filter by name/description" />
                  </label>
                  <label className="field">
                    <span>Project</span>
                    <select className="input" value={selectedProjectId} onChange={(e) => setSelectedProjectId(e.target.value)}>
                      <option value="">Select a project...</option>
                      {filteredProjects.map((project) => (
                        <option key={project.id} value={project.id}>
                          {project.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Project name</span>
                    <Input value={newProjectName} onChange={(e) => setNewProjectName(e.target.value)} />
                  </label>
                  <label className="field">
                    <span>Description</span>
                    <TextArea rows={3} value={newProjectDescription} onChange={(e) => setNewProjectDescription(e.target.value)} />
                  </label>
                </div>
                <div className="actions-row">
                  <Button type="button" variant="primary" onClick={() => void createProject()} disabled={projectCreateBusy || !newProjectName.trim()}>
                    {projectCreateBusy ? "Creating..." : "Create project"}
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => void loadProjects()} disabled={projectsLoading}>
                    {projectsLoading ? "Refreshing..." : "Refresh"}
                  </Button>
                </div>
              </Card>
              <Card title="Project assets & sharing">
                {!selectedProjectId && <p className="muted">Select a project to inspect jobs/assets.</p>}
                {projectDataError && <div className="error-inline">{projectDataError}</div>}
                {projectDataLoading && <Spinner label="Loading project data..." />}
                {selectedProjectId && !projectDataLoading && (
                  <>
                    <div className="snapshot">
                      <div>
                        <p className="metric-label">Jobs</p>
                        <p className="metric-value">{projectJobs.length}</p>
                      </div>
                      <div>
                        <p className="metric-label">Assets</p>
                        <p className="metric-value">{projectAssets.length}</p>
                      </div>
                    </div>
                    <label className="field">
                      <span>Share source asset</span>
                      <select className="input" value={shareSourceAssetId} onChange={(e) => setShareSourceAssetId(e.target.value)}>
                        <option value="">Select asset...</option>
                        {filteredProjectAssets.map((asset) => (
                          <option key={asset.id} value={asset.id}>
                            {asset.id} ({asset.kind})
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="form-grid">
                      <label className="field">
                        <span>Filter assets by kind</span>
                        <select className="input" value={projectAssetKindFilter} onChange={(e) => setProjectAssetKindFilter(e.target.value)}>
                          <option value="">All kinds</option>
                          {projectAssetKinds.map((kind) => (
                            <option key={kind} value={kind}>
                              {kind}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    {filteredProjectAssets.length > 0 && (
                      <div className="output-card">
                        <p className="metric-label">Bulk share asset selection</p>
                        <div className="actions-row">
                          <Button
                            type="button"
                            variant="ghost"
                            onClick={() => setSelectedShareAssetIds(filteredProjectAssets.map((asset) => asset.id))}
                          >
                            Select filtered
                          </Button>
                          <Button type="button" variant="ghost" onClick={() => setSelectedShareAssetIds([])}>
                            Clear selection
                          </Button>
                        </div>
                        <table className="table">
                          <thead>
                            <tr>
                              <th></th>
                              <th>Asset</th>
                              <th>Kind</th>
                            </tr>
                          </thead>
                          <tbody>
                            {filteredProjectAssets.map((asset) => (
                              <tr key={asset.id}>
                                <td>
                                  <input
                                    type="checkbox"
                                    checked={selectedShareAssetIds.includes(asset.id)}
                                    onChange={() => toggleShareAsset(asset.id)}
                                  />
                                </td>
                                <td className="mono">{asset.id}</td>
                                <td>{asset.kind}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                    <div className="actions-row">
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => void createShareLink()}
                        disabled={shareBusy || (selectedShareAssetIds.length === 0 && !shareSourceAssetId)}
                      >
                        {shareBusy ? "Generating..." : `Generate share link${selectedShareAssetIds.length ? "s" : ""}`}
                      </Button>
                    </div>
                    {shareLinks.length > 0 && (
                      <div className="output-card">
                        {shareLinks.map((link) => {
                          const safeLink = toSafeExternalUrl(link.url);
                          return (
                            <div key={link.asset_id}>
                              <p className="muted mono">{link.asset_id}</p>
                              {safeLink ? (
                                <a className="btn btn-secondary" href={safeLink} target="_blank" rel="noreferrer">
                                  {safeLink}
                                </a>
                              ) : (
                                <p className="muted">Generated link was rejected by URL policy.</p>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </>
                )}
              </Card>
            </section>
          )}

          {active === "account" && (
            <section className="grid two-col">
              <Card title="Account session">
                {authError && <div className="error-inline">{authError}</div>}
                {!authInfo && (
                  <>
                    <div className="form-grid">
                      <label className="field">
                        <span>Email</span>
                        <Input value={authEmail} onChange={(e) => setAuthEmail(e.target.value)} placeholder="you@example.com" />
                      </label>
                      <label className="field">
                        <span>Password</span>
                        <Input type="password" value={authPassword} onChange={(e) => setAuthPassword(e.target.value)} />
                      </label>
                      <label className="field">
                        <span>Display name (register)</span>
                        <Input value={authDisplayName} onChange={(e) => setAuthDisplayName(e.target.value)} />
                      </label>
                      <label className="field">
                        <span>Workspace name (register)</span>
                        <Input value={authOrgName} onChange={(e) => setAuthOrgName(e.target.value)} />
                      </label>
                    </div>
                    <div className="actions-row">
                      <Button type="button" variant="primary" disabled={authBusy || !authEmail || !authPassword} onClick={() => void loginAccount()}>
                        {authBusy ? "Working..." : "Login"}
                      </Button>
                      <Button type="button" variant="secondary" disabled={authBusy || !authEmail || !authPassword} onClick={() => void registerAccount()}>
                        {authBusy ? "Working..." : "Register"}
                      </Button>
                    </div>
                    <div className="actions-row">
                      <Button
                        type="button"
                        variant="ghost"
                        onClick={async () => {
                          try {
                            const data = await apiClient.oauthStart("google");
                            const url = toSafeExternalUrl(data.authorize_url);
                            if (url) {
                              window.location.href = url;
                            } else {
                              setAuthError("Unsafe OAuth redirect URL rejected.");
                            }
                          } catch (err) {
                            setAuthError(err instanceof Error ? err.message : "OAuth start failed");
                          }
                        }}
                      >
                        Continue with Google
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        onClick={async () => {
                          try {
                            const data = await apiClient.oauthStart("github");
                            const url = toSafeExternalUrl(data.authorize_url);
                            if (url) {
                              window.location.href = url;
                            } else {
                              setAuthError("Unsafe OAuth redirect URL rejected.");
                            }
                          } catch (err) {
                            setAuthError(err instanceof Error ? err.message : "OAuth start failed");
                          }
                        }}
                      >
                        Continue with GitHub
                      </Button>
                    </div>
                  </>
                )}
                {authInfo && (
                  <>
                    <div className="snapshot">
                      <div>
                        <p className="metric-label">User</p>
                        <p className="metric-value">{authInfo.email}</p>
                      </div>
                      <div>
                        <p className="metric-label">Role</p>
                        <p className="metric-value">{authInfo.role}</p>
                      </div>
                      <div>
                        <p className="metric-label">Workspace</p>
                        <p className="metric-value">{authInfo.org_name}</p>
                      </div>
                    </div>
                    <div className="actions-row">
                      <Button type="button" variant="ghost" onClick={() => void loadAuthContext()}>
                        Refresh account
                      </Button>
                      <Button type="button" variant="secondary" onClick={() => void logoutAccount()} disabled={authBusy}>
                        {authBusy ? "Signing out..." : "Logout"}
                      </Button>
                    </div>
                  </>
                )}
              </Card>
              <Card title="Organization">
                {!orgInfo && <p className="muted">Login first to view organization members.</p>}
                {orgInfo && (
                  <>
                    <p className="muted">
                      {orgInfo.org_name} ({orgInfo.slug})
                    </p>
                    {inviteResolveToken && (
                      <div className="output-card">
                        <p className="metric-label">Invite acceptance</p>
                        {!inviteResolveInfo && !inviteResolveError && <p className="muted">Resolving invite token...</p>}
                        {inviteResolveError && <div className="error-inline">{inviteResolveError}</div>}
                        {inviteResolveInfo && (
                          <>
                            <p className="muted">
                              Invite for <code>{inviteResolveInfo.email}</code> as <code>{inviteResolveInfo.role}</code>
                            </p>
                            <p className="muted">Expires: {formatTimestamp(inviteResolveInfo.expires_at)}</p>
                            <div className="actions-row">
                              <Button type="button" variant="primary" onClick={() => void acceptInvite()} disabled={inviteAcceptBusy || !apiClient.accessToken}>
                                {inviteAcceptBusy ? "Accepting..." : "Accept invite"}
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                onClick={() => {
                                  setInviteResolveToken(null);
                                  setInviteResolveInfo(null);
                                  setInviteResolveError(null);
                                }}
                              >
                                Dismiss
                              </Button>
                            </div>
                            {!apiClient.accessToken && <p className="muted">Log in first, then accept the invite.</p>}
                          </>
                        )}
                      </div>
                    )}
                    {(ORG_MANAGER_ROLES.includes(String(orgInfo.role || "").toLowerCase()) || !orgInfo.role) && (
                      <div className="output-card">
                        <p className="metric-label">Invite teammate</p>
                        {inviteError && <div className="error-inline">{inviteError}</div>}
                        <div className="form-grid">
                          <label className="field">
                            <span>Invite email</span>
                            <Input value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} placeholder="member@example.com" />
                          </label>
                          <label className="field">
                            <span>Invite role</span>
                            <select className="input" value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}>
                              {ORG_ROLE_OPTIONS.map((role) => (
                                <option key={role} value={role}>
                                  {role}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label className="field">
                            <span>Invite expiry (days)</span>
                            <Input
                              type="number"
                              min={1}
                              max={30}
                              value={inviteExpiryDays}
                              onChange={(e) => setInviteExpiryDays(e.target.value)}
                            />
                          </label>
                        </div>
                        <div className="actions-row">
                          <Button
                            type="button"
                            variant="primary"
                            disabled={inviteBusy || !inviteEmail.trim()}
                            onClick={() => void createInvite()}
                          >
                            {inviteBusy ? "Working..." : "Create invite"}
                          </Button>
                          <Button type="button" variant="ghost" disabled={inviteBusy} onClick={() => void loadOrgInvites(orgInfo.role)}>
                            Refresh invites
                          </Button>
                        </div>
                      </div>
                    )}
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Email</th>
                          <th>Role</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {orgInfo.members.map((member) => (
                          <tr key={member.user_id}>
                            <td>{member.email}</td>
                            <td>
                              {ORG_MANAGER_ROLES.includes(String(orgInfo.role || "").toLowerCase()) ? (
                                <select
                                  className="input"
                                  value={member.role}
                                  onChange={(e) => void updateMemberRole(member.user_id, e.target.value)}
                                  disabled={inviteBusy}
                                >
                                  {ORG_ROLE_OPTIONS.map((role) => (
                                    <option key={role} value={role}>
                                      {role}
                                    </option>
                                  ))}
                                </select>
                              ) : (
                                member.role
                              )}
                            </td>
                            <td>
                              {ORG_MANAGER_ROLES.includes(String(orgInfo.role || "").toLowerCase()) ? (
                                <Button type="button" variant="ghost" disabled={inviteBusy} onClick={() => void removeMember(member.user_id)}>
                                  Remove
                                </Button>
                              ) : (
                                <span className="muted">n/a</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="output-card">
                      <p className="metric-label">Invites</p>
                      {orgInvites.length === 0 && <p className="muted">No invites yet.</p>}
                      {orgInvites.length > 0 && (
                        <table className="table">
                          <thead>
                            <tr>
                              <th>Email</th>
                              <th>Role</th>
                              <th>Status</th>
                              <th>Invite link</th>
                              <th>Actions</th>
                            </tr>
                          </thead>
                          <tbody>
                            {orgInvites.map((invite) => {
                              const safeInviteUrl = toSafeExternalUrl(invite.invite_url || null);
                              return (
                                <tr key={invite.id}>
                                  <td>{invite.email}</td>
                                  <td>{invite.role}</td>
                                  <td>{invite.status}</td>
                                  <td>
                                    {safeInviteUrl ? (
                                      <p className="muted mono">{safeInviteUrl}</p>
                                    ) : (
                                      <span className="muted">n/a</span>
                                    )}
                                  </td>
                                  <td>
                                    <div className="actions-row">
                                      {safeInviteUrl && (
                                        <Button type="button" variant="ghost" onClick={() => void copyToClipboard(safeInviteUrl)}>
                                          Copy link
                                        </Button>
                                      )}
                                      {invite.status === "pending" && ORG_MANAGER_ROLES.includes(String(orgInfo.role || "").toLowerCase()) && (
                                        <Button type="button" variant="ghost" onClick={() => void revokeInvite(invite.id)} disabled={inviteBusy}>
                                          Revoke
                                        </Button>
                                      )}
                                    </div>
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      )}
                    </div>
                  </>
                )}
              </Card>
            </section>
          )}

          {active === "billing" && (
            <section className="grid two-col">
              <Card title="Billing status">
                {!apiClient.accessToken && <p className="muted">Login in Account tab to load billing data.</p>}
                {billingError && <div className="error-inline">{billingError}</div>}
                <div className="actions-row">
                  <Button type="button" variant="ghost" onClick={() => void loadBillingData()} disabled={!apiClient.accessToken || billingLoading}>
                    {billingLoading ? "Refreshing..." : "Refresh billing"}
                  </Button>
                </div>
                {billingSubscription && (
                  <div className="snapshot">
                    <div>
                      <p className="metric-label">Plan</p>
                      <p className="metric-value">{billingSubscription.plan_code}</p>
                    </div>
                    <div>
                      <p className="metric-label">Status</p>
                      <p className="metric-value">{billingSubscription.status}</p>
                    </div>
                    <div>
                      <p className="metric-label">Cancel at period end</p>
                      <p className="metric-value">{billingSubscription.cancel_at_period_end ? "Yes" : "No"}</p>
                    </div>
                  </div>
                )}
                {billingUsage && (
                  <div className="output-card">
                    <p className="metric-label">Usage & overage preview</p>
                    <p className="muted">
                      Minutes: {billingUsage.used_job_minutes.toFixed(2)} / {billingUsage.quota_job_minutes}
                    </p>
                    <p className="muted">
                      Storage: {billingUsage.used_storage_gb.toFixed(2)}GB / {billingUsage.quota_storage_gb}GB
                    </p>
                    <p className="muted">Estimated overage: ${(billingUsage.estimated_overage_cents / 100).toFixed(2)}</p>
                  </div>
                )}
                {billingSeatUsage && (
                  <div className="output-card">
                    <p className="metric-label">Seat usage</p>
                    <div className="snapshot">
                      <div>
                        <p className="metric-label">Active</p>
                        <p className="metric-value">{billingSeatUsage.active_members}</p>
                      </div>
                      <div>
                        <p className="metric-label">Pending</p>
                        <p className="metric-value">{billingSeatUsage.pending_invites}</p>
                      </div>
                      <div>
                        <p className="metric-label">Available</p>
                        <p className="metric-value">{billingSeatUsage.available_seats}</p>
                      </div>
                      <div>
                        <p className="metric-label">Limit</p>
                        <p className="metric-value">{billingSeatUsage.seat_limit}</p>
                      </div>
                    </div>
                    <label className="field">
                      <span>Seat limit</span>
                      <Input
                        type="number"
                        min={1}
                        value={billingSeatLimitDraft}
                        onChange={(e) => setBillingSeatLimitDraft(e.target.value)}
                        disabled={billingLoading}
                      />
                    </label>
                    <div className="actions-row">
                      <Button type="button" variant="secondary" disabled={billingLoading || !apiClient.accessToken} onClick={() => void updateSeatLimit()}>
                        {billingLoading ? "Updating..." : "Update seat limit"}
                      </Button>
                    </div>
                  </div>
                )}
              </Card>
              <Card title="Plans">
                {billingPlans.length === 0 && <p className="muted">No plans loaded yet.</p>}
                {billingPlans.length > 0 && (
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Plan</th>
                        <th>Concurrency</th>
                        <th>Minutes</th>
                        <th>Seats</th>
                      </tr>
                    </thead>
                    <tbody>
                      {billingPlans.map((plan) => (
                        <tr key={plan.code}>
                          <td>{plan.name}</td>
                          <td>{plan.max_concurrent_jobs}</td>
                          <td>{plan.monthly_job_minutes}</td>
                          <td>{plan.seat_limit}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                <p className="muted">Checkout/portal session APIs are available under `/billing/*` for hosted mode wiring.</p>
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
