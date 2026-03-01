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
  idempotency_key?: string;
}

export interface TranslateJobRequest {
  subtitle_asset_id: string;
  target_language: string;
  options?: Record<string, unknown>;
  project_id?: string;
  idempotency_key?: string;
}

export interface StyledSubtitleJobRequest {
  video_asset_id: string;
  subtitle_asset_id: string;
  style: Record<string, unknown>;
  preview_seconds?: number;
  project_id?: string;
  idempotency_key?: string;
}

export interface ShortsJobRequest {
  video_asset_id: string;
  max_clips?: number;
  min_duration?: number;
  max_duration?: number;
  aspect_ratio?: string;
  options?: Record<string, unknown>;
  project_id?: string;
  idempotency_key?: string;
}

export interface SubtitleToolsRequest {
  subtitle_asset_id: string;
  target_language: string;
  bilingual?: boolean;
  project_id?: string;
  idempotency_key?: string;
}

export interface MergeAvRequest {
  video_asset_id: string;
  audio_asset_id: string;
  offset?: number;
  ducking?: boolean;
  normalize?: boolean;
  project_id?: string;
  idempotency_key?: string;
}

export interface CutClipRequest {
  video_asset_id: string;
  start: number;
  end: number;
  options?: Record<string, unknown>;
  project_id?: string;
  idempotency_key?: string;
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
  plan_code?: string | null;
  quota_job_minutes?: number | null;
  used_job_minutes?: number | null;
  overage_job_minutes?: number | null;
  max_concurrent_jobs?: number | null;
  from_date?: string | null;
  to_date?: string | null;
}

export interface UsageCostSummary {
  currency: string;
  total_estimated_cost_cents: number;
  entries_count: number;
  by_metric: Record<string, number>;
  by_metric_cost_cents: Record<string, number>;
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

export interface UploadInitRequest {
  filename: string;
  mime_type: string;
  kind?: string;
  size_bytes?: number;
  project_id?: string | null;
}

export interface UploadInitResponse {
  upload_id: string;
  asset_id?: string | null;
  upload_url: string;
  method: string;
  headers: Record<string, string>;
  form_fields: Record<string, string>;
  expires_at: string;
  strategy: string;
}

export interface UploadCompleteRequest {
  upload_id: string;
  asset_id: string;
}

export interface UploadCompleteResponse {
  upload_id: string;
  asset_id: string;
  status?: string;
}

export interface MultipartUploadInitRequest {
  kind?: string;
  filename: string;
  mime_type?: string;
  project_id?: string | null;
}

export interface MultipartUploadInitResponse {
  upload_id: string;
  asset_id: string;
  strategy: string;
  expires_at: string;
  part_size_bytes: number;
}

export interface MultipartUploadPartResponse {
  upload_id: string;
  part_number: number;
  upload_url: string;
  method: string;
  headers: Record<string, string>;
  expires_at: string;
}

export interface MultipartUploadCompleteRequest {
  parts: Array<{ part_number: number; etag: string }>;
}

export interface MultipartUploadAbortResponse {
  upload_id: string;
  status: string;
}

export interface AuthTokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user_id: string;
  org_id: string;
  role: string;
}

export interface AuthMeResponse {
  user_id: string;
  email: string;
  display_name?: string | null;
  org_id: string;
  org_name: string;
  role: string;
}

export interface OAuthStartResponse {
  provider: string;
  authorize_url: string;
  state: string;
}

export interface OrgMemberView {
  user_id: string;
  email: string;
  display_name?: string | null;
  role: string;
}

export interface OrgContextResponse {
  org_id: string;
  org_name: string;
  slug: string;
  role: string;
  members: OrgMemberView[];
}

export interface OrgView {
  org_id: string;
  name: string;
  slug: string;
  role: string;
  seat_limit: number;
  tier: string;
}

export interface OrgInviteView {
  id: string;
  org_id: string;
  email: string;
  role: string;
  status: string;
  expires_at: string;
  invite_url?: string | null;
}

export interface ApiKeyView {
  id: string;
  org_id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  created_at: string;
  last_used_at?: string | null;
  revoked_at?: string | null;
  secret?: string | null;
}

export interface AuditEventView {
  id: string;
  org_id: string;
  actor_user_id?: string | null;
  event_type: string;
  entity_type?: string | null;
  entity_id?: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface OrgInviteResolveResponse {
  org_id: string;
  org_name: string;
  email: string;
  role: string;
  status: string;
  expires_at: string;
}

export interface WorkflowTemplateView {
  id: string;
  name: string;
  description?: string | null;
  steps: Array<Record<string, unknown>>;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkflowRunStepView {
  id: string;
  order_index: number;
  step_type: string;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface WorkflowRunView {
  id: string;
  template_id: string;
  task_id?: string | null;
  status: string;
  input_asset_id?: string | null;
  payload: Record<string, unknown>;
  project_id?: string | null;
  created_at: string;
  updated_at: string;
  steps: WorkflowRunStepView[];
}

export interface BillingPlan {
  code: string;
  name: string;
  max_concurrent_jobs: number;
  monthly_job_minutes: number;
  monthly_storage_gb: number;
  seat_limit: number;
  overage_per_minute_cents: number;
}

export interface BillingSubscription {
  org_id: string;
  plan_code: string;
  status: string;
  stripe_customer_id?: string | null;
  stripe_subscription_id?: string | null;
  current_period_start?: string | null;
  current_period_end?: string | null;
  cancel_at_period_end: boolean;
}

export interface BillingUsageSummary {
  org_id: string;
  plan_code: string;
  used_job_minutes: number;
  quota_job_minutes: number;
  used_storage_gb: number;
  quota_storage_gb: number;
  overage_job_minutes: number;
  estimated_overage_cents: number;
}

export interface BillingSessionResponse {
  id: string;
  url: string;
}

export interface BillingSeatUsage {
  org_id: string;
  plan_code: string;
  active_members: number;
  pending_invites: number;
  seat_limit: number;
  available_seats: number;
}

export interface BillingMetric {
  metric: string;
  unit: string;
  description: string;
  included_in_plan: boolean;
}

export interface BillingCostModel {
  currency: string;
  billable_metrics: BillingMetric[];
  plans: BillingPlan[];
  notes: string[];
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
  accessToken: string | null;

  constructor(options?: ApiClientOptions) {
    const env = (import.meta as unknown as { env?: Record<string, string> }).env || {};
    this.baseUrl = options?.baseUrl || env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";
    this.fetcher = options?.fetcher || fetch;
    this.accessToken = null;
  }

  setAccessToken(token: string | null | undefined) {
    this.accessToken = token || null;
  }

  async request<T>(path: string, init?: RequestInit): Promise<T> {
    const headers = new Headers(init?.headers || {});
    if (!headers.has("Content-Type") && !(init?.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }
    if (this.accessToken && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${this.accessToken}`);
    }
    const resp = await this.fetcher(`${this.baseUrl}${path}`, {
      headers,
      ...init,
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      const message = (body as any)?.message || resp.statusText || "Request failed";
      throw new Error(message);
    }
    if (resp.status === 204) {
      return undefined as T;
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
    return this.request<Job>("/captions/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
      headers: payload.idempotency_key ? { "Idempotency-Key": payload.idempotency_key } : undefined,
    });
  }

  createTranslateJob(payload: TranslateJobRequest) {
    return this.request<Job>("/subtitles/translate", {
      method: "POST",
      body: JSON.stringify(payload),
      headers: payload.idempotency_key ? { "Idempotency-Key": payload.idempotency_key } : undefined,
    });
  }

  createStyledSubtitleJob(payload: StyledSubtitleJobRequest) {
    return this.request<Job>("/subtitles/style", {
      method: "POST",
      body: JSON.stringify(payload),
      headers: payload.idempotency_key ? { "Idempotency-Key": payload.idempotency_key } : undefined,
    });
  }

  createShortsJob(payload: ShortsJobRequest) {
    return this.request<Job>("/shorts/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
      headers: payload.idempotency_key ? { "Idempotency-Key": payload.idempotency_key } : undefined,
    });
  }

  translateSubtitleAsset(payload: SubtitleToolsRequest) {
    return this.request<Job>("/utilities/translate-subtitle", {
      method: "POST",
      body: JSON.stringify(payload),
      headers: payload.idempotency_key ? { "Idempotency-Key": payload.idempotency_key } : undefined,
    });
  }

  mergeAv(payload: MergeAvRequest) {
    return this.request<Job>("/utilities/merge-av", {
      method: "POST",
      body: JSON.stringify(payload),
      headers: payload.idempotency_key ? { "Idempotency-Key": payload.idempotency_key } : undefined,
    });
  }

  createCutClipJob(payload: CutClipRequest) {
    return this.request<Job>("/utilities/cut-clip", {
      method: "POST",
      body: JSON.stringify(payload),
      headers: payload.idempotency_key ? { "Idempotency-Key": payload.idempotency_key } : undefined,
    });
  }

  retryJob(jobId: string, params?: { idempotency_key?: string }) {
    return this.request<Job>(`/jobs/${jobId}/retry`, {
      method: "POST",
      headers: params?.idempotency_key ? { "Idempotency-Key": params.idempotency_key } : undefined,
    });
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
    const querySuffix = query ? `?${query}` : "";
    return this.request<UsageSummary>(`/usage/summary${querySuffix}`);
  }

  getUsageCosts(params?: { from?: string; to?: string; project_id?: string }) {
    const search = new URLSearchParams();
    if (params?.from) search.set("from", params.from);
    if (params?.to) search.set("to", params.to);
    if (params?.project_id) search.set("project_id", params.project_id);
    const query = search.toString();
    const querySuffix = query ? `?${query}` : "";
    return this.request<UsageCostSummary>(`/usage/costs${querySuffix}`);
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

  initAssetUpload(payload: UploadInitRequest) {
    return this.request<UploadInitResponse>("/assets/upload-init", { method: "POST", body: JSON.stringify(payload) });
  }

  completeAssetUpload(payload: UploadCompleteRequest) {
    return this.request<UploadCompleteResponse>("/assets/upload-complete", { method: "POST", body: JSON.stringify(payload) });
  }

  initMultipartAssetUpload(payload: MultipartUploadInitRequest) {
    return this.request<MultipartUploadInitResponse>("/assets/upload-multipart/init", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  signMultipartUploadPart(uploadId: string, partNumber: number) {
    return this.request<MultipartUploadPartResponse>(`/assets/upload-multipart/${uploadId}/parts/${partNumber}`, { method: "POST" });
  }

  completeMultipartUpload(uploadId: string, payload: MultipartUploadCompleteRequest) {
    return this.request<UploadCompleteResponse>(`/assets/upload-multipart/${uploadId}/complete`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  abortMultipartUpload(uploadId: string) {
    return this.request<MultipartUploadAbortResponse>(`/assets/upload-multipart/${uploadId}/abort`, { method: "POST" });
  }

  register(payload: { email: string; password: string; display_name?: string; organization_name?: string }) {
    return this.request<AuthTokenResponse>("/auth/register", { method: "POST", body: JSON.stringify(payload) });
  }

  login(payload: { email: string; password: string }) {
    return this.request<AuthTokenResponse>("/auth/login", { method: "POST", body: JSON.stringify(payload) });
  }

  refreshToken(refresh_token: string) {
    return this.request<AuthTokenResponse>("/auth/refresh", { method: "POST", body: JSON.stringify({ refresh_token }) });
  }

  logout() {
    return this.request<void>("/auth/logout", { method: "POST" });
  }

  getMe() {
    return this.request<AuthMeResponse>("/auth/me");
  }

  oauthStart(provider: "google" | "github", redirectTo?: string) {
    const search = new URLSearchParams();
    if (redirectTo) search.set("redirect_to", redirectTo);
    const query = search.toString();
    return this.request<OAuthStartResponse>(`/auth/oauth/${provider}/start${query ? `?${query}` : ""}`);
  }

  getOrgContext() {
    return this.request<OrgContextResponse>("/orgs/me");
  }

  listOrgs() {
    return this.request<OrgView[]>("/orgs");
  }

  createOrg(payload: { name: string; slug?: string; seat_limit?: number }) {
    return this.request<OrgView>("/orgs", { method: "POST", body: JSON.stringify(payload) });
  }

  listOrgInvites() {
    return this.request<OrgInviteView[]>("/orgs/invites");
  }

  createOrgInvite(payload: { email: string; role: string; expires_in_days: number }) {
    return this.request<OrgInviteView>("/orgs/invites", { method: "POST", body: JSON.stringify(payload) });
  }

  revokeOrgInvite(inviteId: string) {
    return this.request<OrgInviteView>(`/orgs/invites/${inviteId}/revoke`, { method: "POST" });
  }

  resolveOrgInvite(token: string) {
    const query = new URLSearchParams({ token }).toString();
    return this.request<OrgInviteResolveResponse>(`/orgs/invites/resolve?${query}`);
  }

  acceptOrgInvite(payload: { token: string }) {
    return this.request<AuthTokenResponse>("/orgs/invites/accept", { method: "POST", body: JSON.stringify(payload) });
  }

  updateOrgMemberRole(userId: string, payload: { role: string }) {
    return this.request<OrgMemberView>(`/orgs/members/${userId}/role`, { method: "PATCH", body: JSON.stringify(payload) });
  }

  addOrgMember(orgId: string, payload: { email: string; role?: string }) {
    return this.request<OrgMemberView>(`/orgs/${orgId}/members`, { method: "POST", body: JSON.stringify(payload) });
  }

  async removeOrgMemberFromOrg(orgId: string, userId: string): Promise<void> {
    const resp = await this.fetcher(`${this.baseUrl}/orgs/${orgId}/members/${userId}`, {
      method: "DELETE",
      headers: this.accessToken ? { Authorization: `Bearer ${this.accessToken}` } : undefined,
    });
    if (!resp.ok) {
      const body = await resp.text().catch(() => resp.statusText);
      throw new Error(body || "Failed to remove org member");
    }
  }

  async removeOrgMember(userId: string): Promise<void> {
    const resp = await this.fetcher(`${this.baseUrl}/orgs/members/${userId}`, {
      method: "DELETE",
      headers: this.accessToken ? { Authorization: `Bearer ${this.accessToken}` } : undefined,
    });
    if (!resp.ok) {
      const body = await resp.text().catch(() => resp.statusText);
      throw new Error(body || "Failed to remove member");
    }
  }

  listAuditEvents(limit = 50) {
    return this.request<AuditEventView[]>(`/audit-events?limit=${encodeURIComponent(String(limit))}`);
  }

  listApiKeys(orgId: string) {
    return this.request<ApiKeyView[]>(`/orgs/${orgId}/api-keys`);
  }

  createApiKey(orgId: string, payload: { name: string; scopes?: string[] }) {
    return this.request<ApiKeyView>(`/orgs/${orgId}/api-keys`, { method: "POST", body: JSON.stringify(payload) });
  }

  async revokeApiKey(orgId: string, keyId: string): Promise<void> {
    const resp = await this.fetcher(`${this.baseUrl}/orgs/${orgId}/api-keys/${keyId}`, {
      method: "DELETE",
      headers: this.accessToken ? { Authorization: `Bearer ${this.accessToken}` } : undefined,
    });
    if (!resp.ok) {
      const body = await resp.text().catch(() => resp.statusText);
      throw new Error(body || "Failed to revoke api key");
    }
  }

  createWorkflowTemplate(payload: { name: string; description?: string; steps: Array<Record<string, unknown>>; active?: boolean }) {
    return this.request<WorkflowTemplateView>("/workflows/templates", { method: "POST", body: JSON.stringify(payload) });
  }

  listWorkflowTemplates(includeInactive = false) {
    const query = includeInactive ? "?include_inactive=true" : "";
    return this.request<WorkflowTemplateView[]>(`/workflows/templates${query}`);
  }

  createWorkflowRun(payload: { template_id: string; video_asset_id: string; options?: Record<string, unknown>; project_id?: string }) {
    return this.request<WorkflowRunView>("/workflows/runs", { method: "POST", body: JSON.stringify(payload) });
  }

  getWorkflowRun(runId: string) {
    return this.request<WorkflowRunView>(`/workflows/runs/${runId}`);
  }

  cancelWorkflowRun(runId: string) {
    return this.request<WorkflowRunView>(`/workflows/runs/${runId}/cancel`, { method: "POST" });
  }

  listBillingPlans() {
    return this.request<BillingPlan[]>("/billing/plans");
  }

  getBillingSubscription() {
    return this.request<BillingSubscription>("/billing/subscription");
  }

  getBillingUsageSummary() {
    return this.request<BillingUsageSummary>("/billing/usage-summary");
  }

  getBillingSeatUsage() {
    return this.request<BillingSeatUsage>("/billing/seat-usage");
  }

  getBillingCostModel() {
    return this.request<BillingCostModel>("/billing/cost-model");
  }

  createBillingCheckoutSession(payload: { plan_code: string; seat_limit?: number; success_url?: string; cancel_url?: string }) {
    return this.request<BillingSessionResponse>("/billing/checkout-session", { method: "POST", body: JSON.stringify(payload) });
  }

  updateBillingSeatLimit(payload: { seat_limit: number }) {
    return this.request<BillingSeatUsage>("/billing/seat-limit", { method: "PATCH", body: JSON.stringify(payload) });
  }

  createBillingPortalSession(payload?: { return_url?: string }) {
    return this.request<BillingSessionResponse>("/billing/portal-session", {
      method: "POST",
      body: JSON.stringify(payload || {}),
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
    const mimeType =
      file.type ||
      (kind === "video" ? "video/mp4" : kind === "audio" ? "audio/mpeg" : "text/plain");
    const init = await this.initAssetUpload({
      filename: file.name,
      mime_type: mimeType,
      kind,
      size_bytes: file.size,
      project_id: projectId || null,
    });

    const uploadMethod = (init.method || "POST").toUpperCase();
    const uploadHeaders = new Headers(init.headers || {});

    if (uploadMethod === "POST") {
      const form = new FormData();
      Object.entries(init.form_fields || {}).forEach(([k, v]) => form.append(k, v));
      form.append("file", file);
      const localUploadUrl = init.upload_url || `${this.baseUrl}/assets/upload`;
      const shouldAttachAuth = localUploadUrl.includes("/api/v1/");
      if (shouldAttachAuth && this.accessToken) {
        uploadHeaders.set("Authorization", `Bearer ${this.accessToken}`);
      }
      const resp = await this.fetcher(localUploadUrl, {
        method: "POST",
        headers: uploadHeaders,
        body: form,
      });
      if (!resp.ok) {
        const msg = await resp.text().catch(() => resp.statusText);
        throw new Error(msg || "Upload failed");
      }
      const asset = (await resp.json()) as MediaAsset;
      await this.completeAssetUpload({ upload_id: init.upload_id, asset_id: asset.id });
      return asset;
    }

    if (uploadMethod === "PUT") {
      if (!uploadHeaders.has("Content-Type") && file.type) {
        uploadHeaders.set("Content-Type", file.type);
      }
      const resp = await this.fetcher(init.upload_url, {
        method: "PUT",
        headers: uploadHeaders,
        body: file,
      });
      if (!resp.ok) {
        const msg = await resp.text().catch(() => resp.statusText);
        throw new Error(msg || "Upload failed");
      }
      if (!init.asset_id) {
        throw new Error("Upload session missing asset_id");
      }
      await this.completeAssetUpload({ upload_id: init.upload_id, asset_id: init.asset_id });
      return this.getAsset(init.asset_id);
    }

    throw new Error(`Unsupported upload method: ${uploadMethod}`);
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
