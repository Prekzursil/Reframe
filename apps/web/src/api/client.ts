export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface Job {
  id: string;
  job_type: string;
  status: JobStatus;
  progress: number;
  payload?: Record<string, unknown>;
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
}

export const apiClient = new ApiClient();
