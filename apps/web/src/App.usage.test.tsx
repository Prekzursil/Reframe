import { render, screen } from "@testing-library/react";
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
  getBudgetPolicy: vi.fn(),
  updateBudgetPolicy: vi.fn(),
  listProjects: vi.fn(),
  createProject: vi.fn(),
  listProjectJobs: vi.fn(),
  listProjectAssets: vi.fn(),
  createProjectShareLinks: vi.fn(),
  retryJob: vi.fn(),
  register: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  getMe: vi.fn(),
  getOrgContext: vi.fn(),
  oauthStart: vi.fn(),
  listBillingPlans: vi.fn(),
  getBillingSubscription: vi.fn(),
  getBillingUsageSummary: vi.fn(),
  initAssetUpload: vi.fn(),
  completeAssetUpload: vi.fn(),
  uploadAsset: vi.fn(),
  jobBundleUrl: (jobId: string) => `http://localhost:8000/api/v1/jobs/${jobId}/bundle`,
  mediaUrl: (uri: string) => (uri.startsWith("http") ? uri : `http://localhost:8000${uri}`),
}));

vi.mock("./api/client", () => ({ apiClient: apiClientMock }));

import App from "./App";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.removeItem("reframe_access_token");
  apiClientMock.accessToken = null;
  apiClientMock.listJobs.mockResolvedValue([]);
  apiClientMock.listAssets.mockResolvedValue([]);
  apiClientMock.getUsageSummary.mockResolvedValue({
    total_jobs: 12,
    queued_jobs: 2,
    running_jobs: 3,
    completed_jobs: 6,
    failed_jobs: 1,
    cancelled_jobs: 0,
    job_type_counts: { captions: 5, shorts: 4, merge_av: 3 },
    output_assets_count: 8,
    output_duration_seconds: 122.5,
    generated_bytes: 1000,
    from_date: null,
    to_date: null,
  });
  apiClientMock.getBudgetPolicy.mockResolvedValue({
    org_id: "00000000-0000-0000-0000-000000000001",
    monthly_soft_limit_cents: 500,
    monthly_hard_limit_cents: 800,
    enforce_hard_limit: true,
    current_month_estimated_cost_cents: 640,
    projected_status: "soft_limit_exceeded",
    updated_at: "2026-03-02T00:00:00Z",
  });
  apiClientMock.updateBudgetPolicy.mockImplementation(async (payload: Record<string, unknown>) => ({
    org_id: "00000000-0000-0000-0000-000000000001",
    monthly_soft_limit_cents: payload.monthly_soft_limit_cents,
    monthly_hard_limit_cents: payload.monthly_hard_limit_cents,
    enforce_hard_limit: Boolean(payload.enforce_hard_limit),
    current_month_estimated_cost_cents: 640,
    projected_status: "soft_limit_exceeded",
    updated_at: "2026-03-02T00:00:00Z",
  }));
  apiClientMock.listProjects.mockResolvedValue([]);
  apiClientMock.getSystemStatus.mockResolvedValue({
    api_version: "0.1.0",
    offline_mode: false,
    storage_backend: "LocalStorageBackend",
    broker_url: "redis://localhost:6379/0",
    result_backend: "redis://localhost:6379/0",
    worker: { ping_ok: false, workers: [] },
  });
});

describe("usage page", () => {
  it("loads usage summary and renders key metrics", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Usage" }));

    expect(await screen.findByText("12")).toBeInTheDocument();
    expect(screen.getByText("8")).toBeInTheDocument();
    expect(screen.getByText(/122.50s/)).toBeInTheDocument();
    expect(apiClientMock.getUsageSummary).toHaveBeenCalled();
    expect(apiClientMock.getBudgetPolicy).toHaveBeenCalled();
  });

  it("updates budget policy from usage page controls", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Usage" }));
    await screen.findByText("Budget policy");

    const hardLimitInput = screen.getByLabelText("Hard limit (cents)");
    await user.clear(hardLimitInput);
    await user.type(hardLimitInput, "1200");
    await user.click(screen.getByRole("button", { name: "Save budget policy" }));

    expect(apiClientMock.updateBudgetPolicy).toHaveBeenCalledWith({
      monthly_soft_limit_cents: 500,
      monthly_hard_limit_cents: 1200,
      enforce_hard_limit: true,
    });
  });
});
