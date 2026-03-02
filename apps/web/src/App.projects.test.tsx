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
  apiClientMock.getSystemStatus.mockResolvedValue({
    api_version: "0.1.0",
    offline_mode: false,
    storage_backend: "LocalStorageBackend",
    broker_url: "redis://localhost:6379/0",
    result_backend: "redis://localhost:6379/0",
    worker: { ping_ok: false, workers: [] },
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
    from_date: null,
    to_date: null,
  });

  apiClientMock.listProjects.mockResolvedValue([{ id: "proj-1", name: "Existing", description: null }]);
  apiClientMock.listProjectJobs.mockResolvedValue([]);
  apiClientMock.listProjectAssets.mockResolvedValue([
    { id: "asset-1", kind: "subtitle", uri: "/media/tmp/captions.srt", mime_type: "text/plain" },
  ]);
  apiClientMock.createProject.mockResolvedValue({ id: "proj-2", name: "Campaign B", description: "desc" });
  apiClientMock.createProjectShareLinks.mockResolvedValue({
    links: [{ asset_id: "asset-1", url: "http://localhost:8000/api/v1/share/assets/asset-1?token=t", expires_at: "2030-01-01T00:00:00Z" }],
  });
});

describe("projects page", () => {
  it("creates a project and generates a share link", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Projects" }));

    await user.type(screen.getByLabelText("Project name"), "Campaign B");
    await user.type(screen.getByLabelText("Description"), "desc");
    await user.click(screen.getByRole("button", { name: "Create project" }));

    expect(apiClientMock.createProject).toHaveBeenCalledWith({ name: "Campaign B", description: "desc" });

    await user.selectOptions(screen.getByLabelText("Share source asset"), "asset-1");
    await user.click(screen.getByRole("button", { name: "Generate share link" }));

    expect(apiClientMock.createProjectShareLinks).toHaveBeenCalled();
    expect(await screen.findByText(/share\/assets\/asset-1/)).toBeInTheDocument();
  }, 15000);
});
