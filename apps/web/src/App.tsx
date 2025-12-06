import { useEffect, useMemo, useState } from "react";
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
  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const file = files[0];
    const objectUrl = URL.createObjectURL(file);
    const pseudoId = `local-${file.name}-${Date.now()}`;
    onPreview(objectUrl);
    onAssetId(pseudoId);
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
      onClick={() => document.getElementById("video-upload-input")?.click()}
    >
      <input
        id="video-upload-input"
        type="file"
        accept="video/*"
        style={{ display: "none" }}
        onChange={(e) => handleFiles(e.target.files)}
      />
      <p className="metric-value">Upload a video</p>
      <p className="muted">Drop a file here or click to select. Generates a local asset id for forms.</p>
    </div>
  );
}

function AppShell() {
  const [active, setActive] = useState(NAV_ITEMS[1].id);
  const [theme, setTheme] = useState<"light" | "dark">("dark");
  const [showSettings, setShowSettings] = useState(false);
  const { jobs, loading, error, refresh } = useLiveJobs();
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [outputAsset, setOutputAsset] = useState<MediaAsset | null>(null);
  const [assetError, setAssetError] = useState<string | null>(null);
  const [assetLoading, setAssetLoading] = useState(false);
  const [uploadedVideoId, setUploadedVideoId] = useState<string>("");
  const [uploadedPreview, setUploadedPreview] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

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
              <TranslateForm onCreated={() => refresh()} />
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
