import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  baseUrl: "http://localhost:8000/api/v1",
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
  uploadAsset: vi.fn(),
  mediaUrl: (uri: string) => (uri.startsWith("http") ? uri : `http://localhost:8000${uri}`),
}));

vi.mock("./api/client", () => ({ apiClient: apiClientMock }));

import App from "./App";

beforeEach(() => {
  vi.clearAllMocks();
  apiClientMock.listJobs.mockResolvedValue([]);
  apiClientMock.listAssets.mockResolvedValue([]);
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
      options: {
        source_language: "auto",
        backend: "noop",
        model: "whisper-large-v3",
        formats: ["srt", "vtt", "ass"],
      },
    });
  });
});
