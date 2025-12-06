import { useEffect, useMemo, useRef, useState } from "react";
import "./styles.css";
import { apiClient, type Job, type JobStatus, type MediaAsset } from "./api/client";
import { Button, Card, Chip, Input, TextArea } from "./components/ui";
import { Spinner } from "./components/Spinner";
import { SettingsModal } from "./components/SettingsModal";
import { ErrorBoundary } from "./components/ErrorBoundary";

const NAV_ITEMS = [
  { id: "shorts", label: "Shorts" },
  { id: "captions", label: "Captions" },
  { id: "subtitles", label: "Subtitles" },
  { id: "utilities", label: "Utilities" },
  { id: "jobs", label: "Jobs" },
];

const PRESETS = [
  { name: "TikTok Bold", accent: "var(--accent-coral)", desc: "High contrast with warm highlight" },
  { name: "Clean Slate", accent: "var(--accent-mint)", desc: "Minimalist white/gray with subtle shadow" },
  { name: "Night Runner", accent: "var(--accent-blue)", desc: "Dark base with electric cyan highlight" },
];

const OUTPUT_FORMATS = ["srt", "vtt", "ass"];
const BACKENDS = ["whisper", "faster_whisper", "whisper_cpp"];
const FONTS = ["Inter", "Space Grotesk", "Montserrat", "Open Sans"];
const ASPECTS = ["9:16", "16:9", "1:1"];
const LANGS = ["en", "es", "fr", "de", "it", "pt", "ja", "ko", "zh"];

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
  const [backend, setBackend] = useState(BACKENDS[0]);
  const [model, setModel] = useState("whisper-large-v3");
  const [formats, setFormats] = useState<string[]>(["srt"]);
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
        options: { source_language: sourceLang || "auto", backend, model, formats },
      });
      onCreated(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create caption job");
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
        <span>Source language</span>
        <Input value={sourceLang} onChange={(e) => setSourceLang(e.target.value)} placeholder="auto" />
      </label>
      <label className="field">
        <span>Backend</span>
        <select className="input" value={backend} onChange={(e) => setBackend(e.target.value)}>
          {BACKENDS.map((b) => (
            <option key={b} value={b}>
              {b}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Model</span>
        <Input value={model} onChange={(e) => setModel(e.target.value)} />
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
      {error && <div className="error-inline">{error}</div>}
      <div className="actions-row">
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
  const [stylePreset, setStylePreset] = useState("TikTok Bold");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      </label>
      {error && <div className="error-inline">{error}</div>}
      <div className="actions-row">
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
  const [outputAsset, setOutputAsset] = useState<MediaAsset | null>(null);
  const [assetError, setAssetError] = useState<string | null>(null);
  const [assetLoading, setAssetLoading] = useState(false);
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
    { id: string; duration: number; score: number; uri?: string | null; subtitle_uri?: string | null; thumbnail_uri?: string | null }[]
  >([]);
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

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const pollJob = (job: Job | null, onUpdate: (j: Job) => void, onAsset?: (a: MediaAsset | null) => void) => {
    if (!job || ["completed", "failed", "cancelled"].includes(job.status)) return null;
    return setInterval(async () => {
      try {
        const refreshed = await apiClient.getJob(job.id);
        onUpdate(refreshed);
        if (job.job_type === "shorts" && refreshed.payload && "clip_assets" in (refreshed.payload as any)) {
          const clips = ((refreshed.payload as any).clip_assets as any[]).map((c, i) => ({
            id: c.id || `${refreshed.id}-clip-${i + 1}`,
            duration: c.duration ?? null,
            score: c.score ?? null,
            uri: c.uri ?? c.url ?? null,
            subtitle_uri: c.subtitle_uri ?? null,
            thumbnail_uri: c.thumbnail_uri ?? null,
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
        setSubtitlePreview(captionOutput.uri);
        setSubtitleFileName("captions.srt");
      }
    }
  }, [captionOutput]);

  useEffect(() => {
    if (translateOutput?.id) {
      setSubtitleAssetId(translateOutput.id);
      if (translateOutput.uri && translateOutput.mime_type?.includes("text")) {
        setSubtitlePreview(translateOutput.uri);
        setSubtitleFileName("translated.srt");
      }
    }
  }, [translateOutput]);

  const waitForJobAsset = async (jobId: string, timeoutMs = 60000) => {
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
                <button key={job.id} className="job-row selectable" onClick={async () => {
                  setSelectedJob(job);
                  setOutputAsset(null);
                  setAssetError(null);
                  if (job.output_asset_id) {
                    setAssetLoading(true);
                    try {
                      const asset = await apiClient.getAsset(job.output_asset_id);
                      setOutputAsset(asset);
                    } catch (err) {
                      setAssetError(err instanceof Error ? err.message : "Failed to fetch asset");
                    } finally {
                      setAssetLoading(false);
                    }
                  }
                }}>
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
                        <a className="btn btn-primary" href={outputAsset.uri} download>
                          Download
                        </a>
                      </div>
                    )}
                    {outputAsset.uri && outputAsset.mime_type?.includes("video") && (
                      <video className="preview" controls src={outputAsset.uri} />
                    )}
                    {outputAsset.uri && outputAsset.mime_type?.includes("text") && (
                      <iframe className="preview-text" src={outputAsset.uri} title="subtitle-preview" />
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
                {shortsOutput && shortsOutput.uri && (
                  <div className="actions-row">
                    <a className="btn btn-primary" href={shortsOutput.uri} download>
                      Download compiled shorts
                      </a>
                    </div>
                  )}
                </div>
              ) : (
                <p className="muted">Create a shorts job to view progress.</p>
              )}
            </Card>
            <Card title="Results">
              {shortsClips.length === 0 && <p className="muted">No clips yet.</p>}
              <div className="clip-grid">
                {shortsClips.map((clip) => (
                  <div key={clip.id} className="clip-card">
                    <div className="clip-thumb">
                      {clip.thumbnail_uri ? <img src={clip.thumbnail_uri} alt="Clip thumbnail" /> : <div className="placeholder-thumb" />}
                    </div>
                    <p className="metric-value">{clip.duration ? `${clip.duration}s` : "?"}</p>
                    <p className="muted">Score: {clip.score ?? "?"}</p>
                    <div className="actions-row">
                      <Button variant="secondary" disabled={!clip.uri} onClick={() => clip.uri && window.open(clip.uri, "_blank")}>
                        Download video
                      </Button>
                      <Button variant="ghost" disabled={!clip.subtitle_uri} onClick={() => clip.subtitle_uri && window.open(clip.subtitle_uri, "_blank")}>
                        Download subs
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
                  <a className="btn btn-primary" href={translateOutput.uri} download>
                    Download translated subtitles
                  </a>
                  <Button variant="ghost" onClick={() => setSubtitlePreview(translateOutput.uri || null)}>
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
                <span>Subtitle asset ID</span>
                <Input value={subtitleAssetId} onChange={(e) => setSubtitleAssetId(e.target.value)} />
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
                      <a className="btn btn-primary" href={styleOutput.uri} download>
                        Download preview
                      </a>
                    </div>
                  )}
                </div>
              )}
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
                  <div className="actions-row">
                    {subtitleToolsOutput?.uri ? (
                      <a className="btn btn-primary" href={subtitleToolsOutput.uri} download>
                        Download translated subtitles
                      </a>
                    ) : (
                      <Button variant="secondary" disabled>
                        Download when ready
                      </Button>
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
                  <div className="actions-row">
                    {mergeOutput?.uri ? (
                      <a className="btn btn-primary" href={mergeOutput.uri} download>
                        Download merged output
                      </a>
                    ) : (
                      <Button variant="secondary" disabled>
                        Download merged output when ready
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </Card>
          </section>
        )}

        {active !== "captions" && (
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
