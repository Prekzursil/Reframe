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
  apiClientMock.listProjects.mockResolvedValue([]);
});

describe("frontend forms", () => {
  it("submits a captions job with selected options", async () => {
    const user = userEvent.setup();
    apiClientMock.createCaptionJob.mockResolvedValue({
      id: "job-1",
      job_type: "captions",
      status: "queued",
      progress: 0,
      payload: {},
    });

    render(<App />);

    await user.click(screen.getByRole("button", { name: "Captions" }));

    await user.clear(screen.getByLabelText("Video asset ID"));
    await user.type(screen.getByLabelText("Video asset ID"), "video-123");

    await user.click(screen.getByRole("checkbox", { name: "VTT" }));
    await user.click(screen.getByRole("checkbox", { name: "ASS" }));

    await user.click(screen.getByRole("button", { name: "Create caption job" }));

    expect(apiClientMock.createCaptionJob).toHaveBeenCalledWith({
      video_asset_id: "video-123",
      project_id: undefined,
      options: {
        source_language: "auto",
        backend: "faster_whisper",
        model: "whisper-large-v3",
        subtitle_quality_profile: "balanced",
        formats: ["srt", "vtt", "ass"],
        speaker_labels: false,
        diarization_backend: "noop",
      },
    });
  });
});
