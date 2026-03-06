import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  baseUrl: "http://localhost:8000/api/v1",
  accessToken: null as string | null,
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
  listPublishProviders: vi.fn(),
  listPublishConnections: vi.fn(),
  listPublishJobs: vi.fn(),
  startPublishConnection: vi.fn(),
  completePublishConnection: vi.fn(),
  revokePublishConnection: vi.fn(),
  createPublishJob: vi.fn(),
  retryPublishJob: vi.fn(),
  deleteJob: vi.fn(),
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
  mediaUrl: (uri: string) => (uri.startsWith("http") ? uri : `http://localhost:8000${uri}`),
  jobBundleUrl: (jobId: string) => `http://localhost:8000/api/v1/jobs/${jobId}/bundle`,
}));

vi.mock("./api/client", () => ({ apiClient: apiClientMock }));

import App from "./App";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.setItem("reframe_access_token", "token");
  apiClientMock.accessToken = "token";

  apiClientMock.listJobs.mockResolvedValue([]);
  apiClientMock.listAssets.mockResolvedValue([]);
  apiClientMock.getAsset.mockResolvedValue({ id: "asset-1", kind: "video", uri: "/media/tmp/video.mp4", mime_type: "video/mp4" });
  apiClientMock.getJob.mockResolvedValue({ id: "job-1", job_type: "captions", status: "queued", progress: 0, payload: {} });

  apiClientMock.getSystemStatus.mockResolvedValue({
    api_version: "0.1.0",
    offline_mode: false,
    storage_backend: "LocalStorageBackend",
    broker_url: "memory://",
    result_backend: "cache+memory://",
    worker: { ping_ok: true, workers: ["worker@local"], system_info: { ffmpeg: { present: true } } },
  });

  apiClientMock.getUsageSummary.mockResolvedValue({
    total_jobs: 1,
    queued_jobs: 0,
    running_jobs: 0,
    completed_jobs: 1,
    failed_jobs: 0,
    cancelled_jobs: 0,
    job_type_counts: { captions: 1 },
    output_assets_count: 1,
    output_duration_seconds: 12,
    generated_bytes: 10,
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
    projected_status: "ok",
  });

  apiClientMock.getMe.mockResolvedValue({
    user_id: "user-1",
    email: "owner@test.dev",
    display_name: "Owner",
    org_id: "org-1",
    org_name: "Org",
    role: "owner",
  });
  apiClientMock.getOrgContext.mockResolvedValue({
    org_id: "org-1",
    org_name: "Org",
    slug: "org",
    role: "owner",
    members: [],
  });
  apiClientMock.listOrgInvites.mockResolvedValue([]);

  apiClientMock.listProjects.mockResolvedValue([{ id: "proj-1", name: "Proj", description: "d" }]);
  apiClientMock.listProjectJobs.mockResolvedValue([]);
  apiClientMock.listProjectAssets.mockResolvedValue([]);
  apiClientMock.listProjectMembers.mockResolvedValue([]);
  apiClientMock.listProjectComments.mockResolvedValue([]);
  apiClientMock.listProjectActivity.mockResolvedValue([]);

  apiClientMock.listPublishProviders.mockResolvedValue([]);
  apiClientMock.listPublishConnections.mockResolvedValue([]);
  apiClientMock.listPublishJobs.mockResolvedValue([]);

  apiClientMock.listBillingPlans.mockResolvedValue([]);
  apiClientMock.getBillingSubscription.mockResolvedValue({ plan_code: "free", status: "active", seat_limit: 1 });
  apiClientMock.getBillingUsageSummary.mockResolvedValue({
    period_start: "2026-03-01",
    period_end: "2026-03-31",
    quota_job_minutes: 100,
    used_job_minutes: 1,
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
});

describe("App failure-path matrix", () => {
  it("covers jobs delete/retry error branches and filters invalid dates", async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, "confirm");

    apiClientMock.listJobs
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        {
          id: "job-bad-date",
          job_type: "captions",
          status: "failed",
          progress: 0,
          created_at: "not-a-date",
          input_asset_id: "asset-in",
          output_asset_id: null,
          payload: {},
        },
        {
          id: "job-good",
          job_type: "captions",
          status: "completed",
          progress: 1,
          created_at: "2026-03-03T10:00:00Z",
          input_asset_id: "asset-in",
          output_asset_id: "asset-out",
          payload: {},
        },
      ]);

    apiClientMock.getJob.mockResolvedValueOnce({
      id: "job-good",
      job_type: "captions",
      status: "failed",
      progress: 0,
      created_at: "2026-03-03T10:00:00Z",
      input_asset_id: "asset-in",
      output_asset_id: null,
      payload: {},
    });

    apiClientMock.deleteJob.mockRejectedValueOnce(new Error("delete failed"));
    apiClientMock.retryJob.mockRejectedValueOnce(new Error("retry failed"));

    render(<App />);

    await user.click(screen.getByRole("button", { name: "Jobs" }));

    const table = await screen.findByRole("table");
    expect(within(table).getByText("job-bad-date")).toBeInTheDocument();
    expect(within(table).getByText("job-good")).toBeInTheDocument();

    const row = within(table).getByText("job-good").closest("tr") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "View" }));

    confirmSpy.mockReturnValueOnce(false);
    await user.click(screen.getByRole("button", { name: "Delete job" }));
    expect(apiClientMock.deleteJob).not.toHaveBeenCalled();

    confirmSpy.mockReturnValueOnce(true);
    await user.click(screen.getByRole("button", { name: "Delete job" }));
    expect(await screen.findByText("delete failed")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry job" }));
    expect(await screen.findByText("retry failed")).toBeInTheDocument();
  }, 20000);

  it("covers system, usage, and projects error branches", async () => {
    const user = userEvent.setup();

    apiClientMock.getSystemStatus.mockRejectedValueOnce(new Error("system failed"));
    apiClientMock.getUsageSummary.mockRejectedValueOnce(new Error("usage failed"));
    apiClientMock.listProjects.mockResolvedValueOnce([{ id: "proj-1", name: "Proj", description: null }]);
    apiClientMock.listProjectJobs.mockRejectedValueOnce(new Error("project jobs failed"));

    render(<App />);

    await user.click(screen.getByRole("button", { name: "System" }));
    expect(await screen.findByText("system failed")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Usage" }));
    expect(await screen.findByText("usage failed")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Soft limit (cents)"));
    await user.type(screen.getByLabelText("Soft limit (cents)"), "-1");
    await user.click(screen.getByRole("button", { name: "Save budget policy" }));
    expect(await screen.findByText(/Soft limit must be a non-negative number/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Projects" }));
    expect(await screen.findByText("project jobs failed")).toBeInTheDocument();
  }, 20000);

  it("covers quick-start localStorage fallback", async () => {
    const user = userEvent.setup();
    const getItemSpy = vi.spyOn(Storage.prototype, "getItem").mockImplementationOnce(() => {
      throw new Error("storage blocked");
    });

    render(<App />);

    expect(await screen.findByText(/Quick start/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss" }));

    getItemSpy.mockRestore();
  }, 20000);
});