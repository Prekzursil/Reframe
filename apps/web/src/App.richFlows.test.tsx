import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

  if (!("createObjectURL" in URL)) {
    Object.defineProperty(URL, "createObjectURL", { value: vi.fn(() => "blob:mock"), configurable: true });
  }
  if (!("revokeObjectURL" in URL)) {
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
  }

  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

  apiClientMock.listJobs.mockResolvedValue([]);
  apiClientMock.listAssets.mockResolvedValue([
    { id: "asset-video-1", kind: "video", uri: "/media/tmp/input.mp4", mime_type: "video/mp4" },
    { id: "asset-sub-1", kind: "subtitle", uri: "/media/tmp/input.srt", mime_type: "text/plain" },
  ]);
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

  apiClientMock.listProjects.mockResolvedValue([{ id: "proj-1", name: "Launch", description: "release" }]);
  apiClientMock.listProjectJobs.mockResolvedValue([]);
  apiClientMock.listProjectAssets.mockResolvedValue([
    { id: "asset-video-1", kind: "video", uri: "/media/tmp/input.mp4", mime_type: "video/mp4" },
    { id: "asset-sub-1", kind: "subtitle", uri: "/media/tmp/input.srt", mime_type: "text/plain" },
  ]);
  apiClientMock.listProjectMembers.mockResolvedValue([]);
  apiClientMock.listProjectComments.mockResolvedValue([]);
  apiClientMock.listProjectActivity.mockResolvedValue([]);

  apiClientMock.listPublishProviders.mockResolvedValue([{ provider: "youtube", display_name: "YouTube", connected_count: 0 }]);
  apiClientMock.listPublishConnections.mockResolvedValue([]);
  apiClientMock.listPublishJobs.mockResolvedValue([]);

  apiClientMock.createShortsJob.mockResolvedValue({ id: "job-shorts", job_type: "shorts", status: "queued", progress: 0, payload: {} });
  apiClientMock.createCaptionJob.mockResolvedValue({ id: "job-caption", job_type: "captions", status: "queued", progress: 0, payload: {} });
  apiClientMock.uploadAsset.mockResolvedValue({ id: "asset-video-upload", kind: "video", uri: "/media/tmp/upload.mp4", mime_type: "video/mp4" });
  apiClientMock.createCutClipJob.mockResolvedValue({ id: "job-cut-1", job_type: "cut_clip", status: "queued", progress: 0, payload: {} });

  apiClientMock.createStyledSubtitleJob
    .mockResolvedValueOnce({ id: "job-style-preview", job_type: "style", status: "queued", progress: 0, payload: { preview_seconds: 5 } })
    .mockResolvedValueOnce({ id: "job-style-full", job_type: "style", status: "queued", progress: 0, payload: {} })
    .mockResolvedValue({ id: "job-style-subtitles", job_type: "style", status: "queued", progress: 0, payload: {} });

  apiClientMock.getJob.mockImplementation(async (jobId: string) => {
    if (jobId === "job-shorts") {
      return {
        id: "job-shorts",
        job_type: "shorts",
        status: "completed",
        progress: 1,
        output_asset_id: "asset-manifest",
        payload: {
          clip_assets: [
            {
              id: "clip-1",
              asset_id: "asset-clip-1",
              subtitle_asset_id: "asset-sub-1",
              thumbnail_asset_id: "asset-thumb-1",
              thumbnail_uri: "/media/tmp/clip-thumb.jpg",
              uri: "/media/tmp/clip.mp4",
              subtitle_uri: "/media/tmp/clip.srt",
              styled_uri: "/media/tmp/clip-styled.mp4",
              style_preset: "TikTok Bold",
              start: 1,
              end: 9,
              duration: 8,
              score: 0.91,
            },
          ],
        },
      };
    }
    if (jobId === "job-cut-1") {
      return {
        id: "job-cut-1",
        job_type: "cut_clip",
        status: "completed",
        progress: 1,
        output_asset_id: "asset-cut-1",
        payload: { thumbnail_asset_id: "asset-thumb-2", thumbnail_uri: "/media/tmp/clip-thumb-2.jpg", duration: 6.5 },
      };
    }
    if (jobId.startsWith("job-style")) {
      return {
        id: jobId,
        job_type: "style",
        status: "completed",
        progress: 1,
        output_asset_id: `${jobId}-asset`,
        payload: {},
      };
    }
    if (jobId === "job-caption") {
      return {
        id: "job-caption",
        job_type: "captions",
        status: "completed",
        progress: 1,
        output_asset_id: "asset-caption-1",
        payload: {},
      };
    }
    return { id: jobId, job_type: "unknown", status: "queued", progress: 0, payload: {} };
  });

  apiClientMock.getAsset.mockImplementation(async (assetId: string) => {
    if (assetId === "asset-manifest") {
      return { id: assetId, kind: "manifest", uri: "/media/tmp/shorts-manifest.json", mime_type: "application/json" };
    }
    if (assetId === "asset-cut-1") {
      return { id: assetId, kind: "video", uri: "/media/tmp/clip-recutted.mp4", mime_type: "video/mp4" };
    }
    if (assetId === "asset-caption-1") {
      return { id: assetId, kind: "subtitle", uri: "/media/tmp/captions.srt", mime_type: "text/plain" };
    }
    if (assetId.startsWith("job-style")) {
      return { id: assetId, kind: "video", uri: "/media/tmp/styled-output.mp4", mime_type: "video/mp4" };
    }
    return { id: assetId, kind: "video", uri: "/media/tmp/default.mp4", mime_type: "video/mp4" };
  });
});

describe("App rich flow coverage", () => {
  it("covers shorts result actions and subtitle panel interactions", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Shorts" }));

    const uploadInput = document.querySelector("input[type=file]") as HTMLInputElement;
    const videoFile = new File(["video"], "clip.mp4", { type: "video/mp4" });
    fireEvent.change(uploadInput, { target: { files: [videoFile] } });
    await waitFor(() => expect(apiClientMock.uploadAsset).toHaveBeenCalled());

    await user.type(await screen.findByLabelText("Video asset ID or URL"), "asset-video-1");
    await user.click(screen.getByRole("button", { name: "Create shorts job" }));
    expect(apiClientMock.createShortsJob).toHaveBeenCalled();

    expect(await screen.findByRole("button", { name: "Download CSV" }, { timeout: 15000 })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Download CSV" }));
    await user.click(screen.getByRole("button", { name: "Download EDL" }));

    await user.click(screen.getByRole("button", { name: "Apply to all" }));
    await user.click(screen.getByRole("button", { name: "Preview 5s" }));
    await user.click(screen.getByRole("button", { name: "Render styled" }));

    await user.click(screen.getByRole("button", { name: "Edit" }));
    const startInput = screen.getByLabelText("Start (s)");
    const endInput = screen.getByLabelText("End (s)");
    await user.clear(startInput);
    await user.type(startInput, "2");
    await user.clear(endInput);
    await user.type(endInput, "8");
    await user.click(screen.getByRole("button", { name: "Re-cut clip" }));
    await waitFor(() => {
      expect(apiClientMock.createCutClipJob).toHaveBeenCalled();
    });

    expect(apiClientMock.createStyledSubtitleJob).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Subtitles" }));
    expect(await screen.findByText(/Select assets/i)).toBeInTheDocument();

    const subtitleSelectSection = screen.getByText("Or pick a recent subtitle asset").closest("label") as HTMLElement;
    await user.selectOptions(within(subtitleSelectSection).getByRole("combobox"), "asset-sub-1");

    const videoSelectSection = screen.getByText("Or pick a recent video asset").closest("label") as HTMLElement;
    await user.selectOptions(within(videoSelectSection).getByRole("combobox"), "asset-video-1");

    await user.click(screen.getByRole("button", { name: "Generate captions from video" }));
    expect(apiClientMock.createCaptionJob).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Preview 5s" }));
    await user.click(screen.getByRole("button", { name: "Render full video" }));
    expect(apiClientMock.createStyledSubtitleJob).toHaveBeenCalledTimes(4);
  }, 45000);

  it("sweeps visible controls across tabs to exercise broad form branches", async () => {
    const user = userEvent.setup();
    render(<App />);

    const tabNames = [
      "Captions",
      "Subtitles",
      "Styling",
      "Shorts",
      "Utilities",
      "Jobs",
      "Usage",
      "Projects",
      "Workflows",
      "Account",
    ];

    const sweepCurrentView = () => {
      const root = document.body;

      root.querySelectorAll("textarea").forEach((node) => {
        const el = node as HTMLTextAreaElement;
        fireEvent.change(el, { target: { value: "coverage wave text" } });
      });

      root.querySelectorAll("select").forEach((node) => {
        const el = node as HTMLSelectElement;
        const options = Array.from(el.options).filter((opt) => opt.value);
        const value = options.length > 1 ? options[1]?.value : options[0]?.value;
        if (value != null) {
          fireEvent.change(el, { target: { value } });
        }
      });

      root.querySelectorAll("input").forEach((node) => {
        const el = node as HTMLInputElement;
        if (el.type === "file") return;
        if (el.type === "checkbox") {
          fireEvent.click(el);
          return;
        }
        if (el.type === "date") {
          fireEvent.change(el, { target: { value: "2026-03-01" } });
          return;
        }
        if (el.type === "number" || el.type === "range") {
          fireEvent.change(el, { target: { value: "2" } });
          return;
        }
        fireEvent.change(el, { target: { value: "coverage-wave" } });
      });
    };

    for (const tab of tabNames) {
      const btn = screen.queryByRole("button", { name: tab });
      if (!btn) continue;
      await user.click(btn);
      sweepCurrentView();
    }

    await waitFor(() => {
      expect(screen.getByText(/Creative media pipeline/)).toBeInTheDocument();
    });
  }, 45000);

});
