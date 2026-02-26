export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface Job {
  id: string;
  job_type: string;
  status: JobStatus;
  progress: number;
  error?: string | null;
  payload?: Record<string, unknown>;
  input_asset_id?: string | null;
  output_asset_id?: string | null;
  project_id?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface CaptionJobRequest {
  video_asset_id: string;
  options?: Record<string, unknown>;
  project_id?: string;
}

export interface TranslateJobRequest {
  subtitle_asset_id: string;
  target_language: string;
  options?: Record<string, unknown>;
  project_id?: string;
}

export interface StyledSubtitleJobRequest {
  video_asset_id: string;
  subtitle_asset_id: string;
  style: Record<string, unknown>;
  preview_seconds?: number;
  project_id?: string;
}

export interface ShortsJobRequest {
  video_asset_id: string;
  max_clips?: number;
  min_duration?: number;
  max_duration?: number;
  aspect_ratio?: string;
  options?: Record<string, unknown>;
  project_id?: string;
}

export interface SubtitleToolsRequest {
  subtitle_asset_id: string;
  target_language: string;
  bilingual?: boolean;
  project_id?: string;
}

export interface MergeAvRequest {
  video_asset_id: string;
  audio_asset_id: string;
  offset?: number;
  ducking?: boolean;
  normalize?: boolean;
  project_id?: string;
}

export interface CutClipRequest {
  video_asset_id: string;
  start: number;
  end: number;
  options?: Record<string, unknown>;
  project_id?: string;
}

export interface MediaAsset {
  id: string;
  kind: string;
  uri?: string | null;
  mime_type?: string | null;
  duration?: number | null;
  project_id?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface UsageSummary {
  total_jobs: number;
  queued_jobs: number;
  running_jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  cancelled_jobs: number;
  job_type_counts: Record<string, number>;
  output_assets_count: number;
  output_duration_seconds: number;
  generated_bytes: number;
  from_date?: string | null;
  to_date?: string | null;
}

export interface Project {
  id: string;
  name: string;
  description?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface ProjectShareLink {
  asset_id: string;
  url: string;
  expires_at: string;
}

export interface ProjectShareLinksResponse {
  links: ProjectShareLink[];
}

export interface WorkerDiagnostics {
  ping_ok: boolean;
  workers: string[];
  system_info?: Record<string, unknown> | null;
  error?: string | null;
}

export interface SystemStatusResponse {
  api_version: string;
  offline_mode: boolean;
  storage_backend: string;
  broker_url: string;
  result_backend: string;
  worker: WorkerDiagnostics;
}

interface ApiClientOptions {
  baseUrl?: string;
  fetcher?: typeof fetch;
}

export class ApiClient {
  baseUrl: string;
  fetcher: typeof fetch;

  constructor(options?: ApiClientOptions) {
    const env = (import.meta as unknown as { env?: Record<string, string> }).env || {};
    this.baseUrl = options?.baseUrl || env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";
    this.fetcher = options?.fetcher || fetch;
  }

  async request<T>(path: string, init?: RequestInit): Promise<T> {
    const resp = await this.fetcher(`${this.baseUrl}${path}`, {
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
      ...init,
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      const message = (body as any)?.message || resp.statusText || "Request failed";
      throw new Error(message);
    }
    return (await resp.json()) as T;
  }

  listJobs(params?: { status?: JobStatus; project_id?: string }) {
    const search = new URLSearchParams();
    if (params?.status) search.set("status_filter", params.status);
    if (params?.project_id) search.set("project_id", params.project_id);
    const query = search.toString();
    return this.request<Job[]>(`/jobs${query ? `?${query}` : ""}`);
  }

  getJob(jobId: string) {
    return this.request<Job>(`/jobs/${jobId}`);
  }

  getAsset(assetId: string) {
    return this.request<MediaAsset>(`/assets/${assetId}`);
  }

  listAssets(params?: { kind?: string; limit?: number; project_id?: string }) {
    const search = new URLSearchParams();
    if (params?.kind) search.set("kind", params.kind);
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.project_id) search.set("project_id", params.project_id);
    const query = search.toString();
    return this.request<MediaAsset[]>(`/assets${query ? `?${query}` : ""}`);
  }

  createCaptionJob(payload: CaptionJobRequest) {
    return this.request<Job>("/captions/jobs", { method: "POST", body: JSON.stringify(payload) });
  }

  createTranslateJob(payload: TranslateJobRequest) {
    return this.request<Job>("/subtitles/translate", { method: "POST", body: JSON.stringify(payload) });
  }

  createStyledSubtitleJob(payload: StyledSubtitleJobRequest) {
    return this.request<Job>("/subtitles/style", { method: "POST", body: JSON.stringify(payload) });
  }

  createShortsJob(payload: ShortsJobRequest) {
    return this.request<Job>("/shorts/jobs", { method: "POST", body: JSON.stringify(payload) });
  }

  translateSubtitleAsset(payload: SubtitleToolsRequest) {
    return this.request<Job>("/utilities/translate-subtitle", { method: "POST", body: JSON.stringify(payload) });
  }

  mergeAv(payload: MergeAvRequest) {
    return this.request<Job>("/utilities/merge-av", { method: "POST", body: JSON.stringify(payload) });
  }

  createCutClipJob(payload: CutClipRequest) {
    return this.request<Job>("/utilities/cut-clip", { method: "POST", body: JSON.stringify(payload) });
  }

  getSystemStatus() {
    return this.request<SystemStatusResponse>("/system/status");
  }

  getUsageSummary(params?: { from?: string; to?: string; project_id?: string }) {
    const search = new URLSearchParams();
    if (params?.from) search.set("from", params.from);
    if (params?.to) search.set("to", params.to);
    if (params?.project_id) search.set("project_id", params.project_id);
    const query = search.toString();
    return this.request<UsageSummary>(`/usage/summary${query ? `?${query}` : ""}`);
  }

  listProjects() {
    return this.request<Project[]>("/projects");
  }

  createProject(payload: { name: string; description?: string | null }) {
    return this.request<Project>("/projects", { method: "POST", body: JSON.stringify(payload) });
  }

  getProject(projectId: string) {
    return this.request<Project>(`/projects/${projectId}`);
  }

  listProjectJobs(projectId: string) {
    return this.request<Job[]>(`/projects/${projectId}/jobs`);
  }

  listProjectAssets(projectId: string, params?: { kind?: string; limit?: number }) {
    const search = new URLSearchParams();
    if (params?.kind) search.set("kind", params.kind);
    if (params?.limit) search.set("limit", String(params.limit));
    const query = search.toString();
    return this.request<MediaAsset[]>(`/projects/${projectId}/assets${query ? `?${query}` : ""}`);
  }

  createProjectShareLinks(projectId: string, payload: { asset_ids: string[]; expires_in_hours?: number }) {
    return this.request<ProjectShareLinksResponse>(`/projects/${projectId}/share-links`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async deleteJob(jobId: string, options?: { deleteAssets?: boolean }): Promise<void> {
    const search = new URLSearchParams();
    if (options?.deleteAssets) search.set("delete_assets", "true");
    const query = search.toString();
    const resp = await this.fetcher(`${this.baseUrl}/jobs/${jobId}${query ? `?${query}` : ""}`, { method: "DELETE" });
    if (!resp.ok) {
      const msg = await resp.text().catch(() => resp.statusText);
      throw new Error(msg || "Delete job failed");
    }
  }

  async deleteAsset(assetId: string): Promise<void> {
    const resp = await this.fetcher(`${this.baseUrl}/assets/${assetId}`, { method: "DELETE" });
    if (!resp.ok) {
      const msg = await resp.text().catch(() => resp.statusText);
      throw new Error(msg || "Delete asset failed");
    }
  }

  async uploadAsset(file: File, kind = "video", projectId?: string): Promise<MediaAsset> {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    if (projectId) form.append("project_id", projectId);
    const resp = await this.fetcher(`${this.baseUrl}/assets/upload`, {
      method: "POST",
      body: form,
    });
    if (!resp.ok) {
      const msg = await resp.text().catch(() => resp.statusText);
      throw new Error(msg || "Upload failed");
    }
    return (await resp.json()) as MediaAsset;
  }

  mediaUrl(uri: string): string {
    if (/^https?:\/\//i.test(uri)) return uri;
    const base = (() => {
      try {
        return new URL(this.baseUrl);
      } catch {
        return new URL(this.baseUrl, window.location.origin);
      }
    })();
    return new URL(uri, base.origin).toString();
  }

  jobBundleUrl(jobId: string): string {
    return `${this.baseUrl}/jobs/${jobId}/bundle`;
  }
}

export const apiClient = new ApiClient();
