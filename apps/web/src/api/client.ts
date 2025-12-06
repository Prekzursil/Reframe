export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface Job {
  id: string;
  job_type: string;
  status: JobStatus;
  progress: number;
  payload?: Record<string, unknown>;
  input_asset_id?: string | null;
  output_asset_id?: string | null;
}

export interface CaptionJobRequest {
  video_asset_id: string;
  options?: Record<string, unknown>;
}

export interface TranslateJobRequest {
  subtitle_asset_id: string;
  target_language: string;
  options?: Record<string, unknown>;
}

export interface StyledSubtitleJobRequest {
  video_asset_id: string;
  subtitle_asset_id: string;
  style: Record<string, unknown>;
  preview_seconds?: number;
}

export interface ShortsJobRequest {
  video_asset_id: string;
  options?: Record<string, unknown>;
}

export interface MediaAsset {
  id: string;
  kind: string;
  uri?: string | null;
  mime_type?: string | null;
  duration?: number | null;
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

  listJobs() {
    return this.request<Job[]>("/jobs");
  }

  getJob(jobId: string) {
    return this.request<Job>(`/jobs/${jobId}`);
  }

  getAsset(assetId: string) {
    return this.request<MediaAsset>(`/assets/${assetId}`);
  }

  createCaptionJob(payload: CaptionJobRequest) {
    return this.request<Job>("/captions/jobs", { method: "POST", body: JSON.stringify(payload) });
  }

  createTranslateJob(payload: TranslateJobRequest) {
    return this.request<Job>("/subtitles/translate", { method: "POST", body: JSON.stringify(payload) });
  }

  createStyledSubtitleJob(payload: StyledSubtitleJobRequest) {
    // Placeholder endpoint; adjust to backend path once available.
    return this.request<Job>("/subtitles/style", { method: "POST", body: JSON.stringify(payload) });
  }

  createShortsJob(payload: ShortsJobRequest) {
    return this.request<Job>("/shorts/jobs", { method: "POST", body: JSON.stringify(payload) });
  }
}

export const apiClient = new ApiClient();
