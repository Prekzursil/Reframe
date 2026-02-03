import { render, screen, within } from "@testing-library/react";
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
  apiClientMock.listAssets.mockResolvedValue([]);
});

describe("minimal e2e flow", () => {
  it("upload → caption job → download from Jobs", async () => {
    const user = userEvent.setup();

    const jobs: any[] = [];

    apiClientMock.listJobs.mockImplementation(async () => jobs);

    apiClientMock.uploadAsset.mockResolvedValue({
      id: "video-1",
      kind: "video",
      uri: "/media/tmp/video.mp4",
      mime_type: "video/mp4",
    });

    apiClientMock.createCaptionJob.mockImplementation(async (payload: any) => {
      const job = {
        id: "job-1",
        job_type: "captions",
        status: "completed",
        progress: 1,
        payload: payload.options || {},
        input_asset_id: payload.video_asset_id,
        output_asset_id: "subtitle-1",
        created_at: "2026-02-03T12:00:00Z",
      };
      jobs.push(job);
      return job;
    });

    apiClientMock.getJob.mockImplementation(async (jobId: string) => jobs.find((j) => j.id === jobId));

    apiClientMock.getAsset.mockImplementation(async (assetId: string) => {
      if (assetId === "subtitle-1") {
        return {
          id: "subtitle-1",
          kind: "subtitle",
          uri: "/media/tmp/captions.srt",
          mime_type: "text/srt",
        };
      }
      return {
        id: assetId,
        kind: "video",
        uri: "/media/tmp/video.mp4",
        mime_type: "video/mp4",
      };
    });

    render(<App />);

    await user.click(screen.getByRole("button", { name: "Captions" }));

    const uploadLabel = screen.getByText("Upload a video");
    const dropzone = uploadLabel.closest("div");
    expect(dropzone).toBeTruthy();

    const fileInput = dropzone!.querySelector('input[type=\"file\"]') as HTMLInputElement | null;
    expect(fileInput).toBeTruthy();

    const file = new File([new Uint8Array([1, 2, 3])], "sample.mp4", { type: "video/mp4" });
    await user.upload(fileInput!, file);

    expect(screen.getByLabelText("Video asset ID")).toHaveValue("video-1");

    await user.click(screen.getByRole("button", { name: "Create caption job" }));

    await user.click(screen.getByRole("button", { name: "Jobs" }));

    const table = await screen.findByRole("table");
    expect(within(table).getByText("job-1")).toBeInTheDocument();

    const row = within(table).getByText("job-1").closest("tr");
    expect(row).toBeTruthy();
    await user.click(within(row!).getByRole("button", { name: "View" }));

    const jobDetailCard = screen.getByRole("heading", { name: "Job detail" }).closest(".card") as HTMLElement | null;
    expect(jobDetailCard).toBeTruthy();

    const download = await within(jobDetailCard!).findByRole("link", { name: "Download" });
    expect(download).toHaveAttribute("href", "http://localhost:8000/media/tmp/captions.srt");
  });
});
