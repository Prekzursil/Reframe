import { useEffect, useMemo, useState } from "react";
import "./styles.css";
import { apiClient, type Job, type JobStatus } from "./api/client";
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

function useLiveJobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const data = await apiClient.listJobs();
        if (!cancelled) setJobs(data.slice(0, 5));
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load jobs");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return { jobs, loading, error };
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

function AppShell() {
  const [active, setActive] = useState(NAV_ITEMS[0].id);
  const [theme, setTheme] = useState<"light" | "dark">("dark");
  const [showSettings, setShowSettings] = useState(false);
  const { jobs, loading, error } = useLiveJobs();

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
                <div key={job.id} className="job-row">
                  <div>
                    <p className="metric-label">{job.job_type}</p>
                    <p className="metric-value">{job.id}</p>
                  </div>
                  <JobStatusPill status={job.status} />
                </div>
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
        </section>

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
