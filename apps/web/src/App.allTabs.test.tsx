import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  baseUrl: "http://localhost:8000/api/v1",
  accessToken: "token" as string | null,
  setAccessToken: vi.fn(),
  listJobs: vi.fn(),
  getJob: vi.fn(),
  getAsset: vi.fn(),
  listAssets: vi.fn(),
  createCaptionJob: vi.fn(),
  createTranslateJob: vi.fn(),
  createStyledSubtitleJob: vi.fn(),
  createShortsJob: vi.fn(),
  translateSubtitleAsset: vi.fn(),
  mergeAv: vi.fn(),
  createCutClipJob: vi.fn(),
  getSystemStatus: vi.fn(),
  getUsageSummary: vi.fn(),
  getUsageCosts: vi.fn(),
  getBudgetPolicy: vi.fn(),
  updateBudgetPolicy: vi.fn(),
  listProjects: vi.fn(),
  createProject: vi.fn(),
  listProjectJobs: vi.fn(),
  listProjectAssets: vi.fn(),
  createProjectShareLinks: vi.fn(),
  listProjectMembers: vi.fn(),
  addProjectMember: vi.fn(),
  updateProjectMemberRole: vi.fn(),
  removeProjectMember: vi.fn(),
  listProjectComments: vi.fn(),
  createProjectComment: vi.fn(),
  deleteProjectComment: vi.fn(),
  requestProjectApproval: vi.fn(),
  approveProjectApproval: vi.fn(),
  rejectProjectApproval: vi.fn(),
  listProjectActivity: vi.fn(),
  retryJob: vi.fn(),
  register: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  getMe: vi.fn(),
  getOrgContext: vi.fn(),
  createOrgInvite: vi.fn(),
  listOrgInvites: vi.fn(),
  revokeOrgInvite: vi.fn(),
  updateOrgMemberRole: vi.fn(),
  removeOrgMember: vi.fn(),
  oauthStart: vi.fn(),
  listBillingPlans: vi.fn(),
  getBillingSubscription: vi.fn(),
  getBillingUsageSummary: vi.fn(),
  getBillingSeatUsage: vi.fn(),
  updateBillingSeatLimit: vi.fn(),
  initAssetUpload: vi.fn(),
  completeAssetUpload: vi.fn(),
  uploadAsset: vi.fn(),
  getOrgSsoConfig: vi.fn(),
  updateOrgSsoConfig: vi.fn(),
  createScimToken: vi.fn(),
  revokeScimToken: vi.fn(),
  startOktaSso: vi.fn(),
  listPublishProviders: vi.fn(),
  listPublishConnections: vi.fn(),
  listPublishJobs: vi.fn(),
  startPublishConnection: vi.fn(),
  completePublishConnection: vi.fn(),
  revokePublishConnection: vi.fn(),
  createPublishJob: vi.fn(),
  retryPublishJob: vi.fn(),
  jobBundleUrl: (jobId: string) => `http://localhost:8000/api/v1/jobs/${jobId}/bundle`,
  mediaUrl: (uri: string) => (uri.startsWith("http") ? uri : `http://localhost:8000${uri}`),
}));

vi.mock("./api/client", () => ({ apiClient: apiClientMock }));

import App from "./App";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.setItem("reframe_access_token", "token");
  apiClientMock.accessToken = "token";

  apiClientMock.listJobs.mockResolvedValue([]);
  apiClientMock.listAssets.mockResolvedValue([]);
  apiClientMock.getSystemStatus.mockResolvedValue({
    api_version: "0.1.0",
    offline_mode: false,
    storage_backend: "LocalStorageBackend",
    broker_url: "memory://",
    result_backend: "cache+memory://",
    worker: { ping_ok: true, workers: ["local-queue"], system_info: { ffmpeg: { present: true, version: "6.1" } } },
  });
  apiClientMock.getUsageSummary.mockResolvedValue({
    total_jobs: 0,
    queued_jobs: 0,
    running_jobs: 0,
    completed_jobs: 0,
    failed_jobs: 0,
    cancelled_jobs: 0,
    job_type_counts: {},
    output_assets_count: 0,
    output_duration_seconds: 0,
    generated_bytes: 0,
  });
  apiClientMock.getUsageCosts.mockResolvedValue({
    currency: "USD",
    total_estimated_cost_cents: 0,
    entries_count: 0,
    by_metric: {},
    by_metric_cost_cents: {},
  });
  apiClientMock.getBudgetPolicy.mockResolvedValue({
    org_id: "org-1",
    monthly_soft_limit_cents: null,
    monthly_hard_limit_cents: null,
    enforce_hard_limit: false,
    current_month_estimated_cost_cents: 0,
    projected_status: "on_track",
  });

  apiClientMock.getMe.mockResolvedValue({
    user_id: "user-1",
    email: "owner@team.test",
    display_name: "Owner",
    org_id: "org-1",
    org_name: "Team Org",
    role: "owner",
  });
  apiClientMock.getOrgContext.mockResolvedValue({
    org_id: "org-1",
    org_name: "Team Org",
    slug: "team-org",
    role: "owner",
    members: [{ user_id: "user-1", email: "owner@team.test", display_name: "Owner", role: "owner" }],
  });
  apiClientMock.listOrgInvites.mockResolvedValue([]);

  apiClientMock.getOrgSsoConfig.mockResolvedValue({
    org_id: "org-1",
    provider: "okta",
    enabled: false,
    issuer_url: "https://example.okta.com/oauth2/default",
    client_id: "okta-client",
    audience: "api://default",
    default_role: "viewer",
    jit_enabled: true,
    allow_email_link: true,
    config: {},
  });

  apiClientMock.listProjects.mockResolvedValue([{ id: "proj-1", name: "Launch", description: "release" }]);
  apiClientMock.listProjectJobs.mockResolvedValue([]);
  apiClientMock.listProjectAssets.mockResolvedValue([{ id: "asset-1", kind: "video", uri: "/media/tmp/clip.mp4", mime_type: "video/mp4" }]);
  apiClientMock.listProjectMembers.mockResolvedValue([]);
  apiClientMock.listProjectComments.mockResolvedValue([]);
  apiClientMock.listProjectActivity.mockResolvedValue([]);

  apiClientMock.listPublishProviders.mockResolvedValue([{ provider: "youtube", display_name: "YouTube", connected_count: 0 }]);
  apiClientMock.listPublishConnections.mockResolvedValue([]);
  apiClientMock.listPublishJobs.mockResolvedValue([]);

  apiClientMock.listBillingPlans.mockResolvedValue([{ code: "starter", name: "Starter", monthly_price_cents: 0 }]);
  apiClientMock.getBillingSubscription.mockResolvedValue({ plan_code: "starter", status: "active", seat_limit: 1 });
  apiClientMock.getBillingUsageSummary.mockResolvedValue({
    period_start: "2026-03-01",
    period_end: "2026-03-31",
    quota_job_minutes: 100,
    used_job_minutes: 0,
    overage_job_minutes: 0,
    used_storage_gb: 0,
    quota_storage_gb: 5,
    estimated_overage_cents: 0,
    estimated_cost_cents: 0,
  });
  apiClientMock.getBillingSeatUsage.mockResolvedValue({
    seat_limit: 1,
    active_members: 1,
    available_seats: 0,
    pending_invites: 0,
  });

  apiClientMock.uploadAsset.mockResolvedValue({ id: "asset-upload", kind: "video", uri: "/media/tmp/upload.mp4", mime_type: "video/mp4" });
  apiClientMock.createCaptionJob.mockResolvedValue({ id: "job-caption", job_type: "captions", status: "queued", progress: 0, payload: {} });
  apiClientMock.createTranslateJob.mockResolvedValue({ id: "job-translate", job_type: "translate", status: "queued", progress: 0, payload: {} });
  apiClientMock.createShortsJob.mockResolvedValue({ id: "job-shorts", job_type: "shorts", status: "queued", progress: 0, payload: {} });
  apiClientMock.translateSubtitleAsset.mockResolvedValue({ id: "job-translate-asset", job_type: "translate_subtitle", status: "queued", progress: 0, payload: {} });
  apiClientMock.mergeAv.mockResolvedValue({ id: "job-merge", job_type: "merge", status: "queued", progress: 0, payload: {} });
  apiClientMock.createStyledSubtitleJob.mockResolvedValue({ id: "job-style", job_type: "style", status: "queued", progress: 0, payload: {} });
});

describe("app tab coverage smoke", () => {
  it("navigates every major tab and renders key product surfaces", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Shorts" }));
    expect(await screen.findByText(/Upload or link video/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Captions" }));
    expect(await screen.findByText(/Captions & Translate/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Subtitles" }));
    expect(await screen.findByText(/Subtitle editor/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Utilities" }));
    expect(await screen.findByText(/Merge audio\/video/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Jobs" }));
    expect(await screen.findByText(/Recent jobs/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Usage" }));
    expect(await screen.findByText(/Usage summary/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Projects" }));
    expect(await screen.findByRole("heading", { name: "Projects" })).toBeInTheDocument();
    expect(await screen.findByText(/Publish automation/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Account" }));
    expect(await screen.findByText(/Account session/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Billing" }));
    expect(await screen.findByText(/Billing status/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "System" }));
    expect(await screen.findByText(/System health/i)).toBeInTheDocument();
  }, 20000);
});


