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

describe("jobs page", () => {
  it("filters jobs and shows output download link in detail view", async () => {
    const user = userEvent.setup();

    const jobs = [
      {
        id: "job-1",
        job_type: "captions",
        status: "completed",
        progress: 1,
        input_asset_id: "asset-in-1",
        output_asset_id: "asset-out-1",
        created_at: "2026-02-03T12:00:00Z",
      },
      {
        id: "job-2",
        job_type: "shorts",
        status: "failed",
        progress: 0.2,
        input_asset_id: "asset-in-2",
        output_asset_id: null,
        created_at: "2026-02-01T12:00:00Z",
      },
    ];

    apiClientMock.listJobs.mockResolvedValue(jobs);
    apiClientMock.getJob.mockImplementation(async (jobId: string) => jobs.find((j) => j.id === jobId));
    apiClientMock.getAsset.mockImplementation(async (assetId: string) => {
      if (assetId === "asset-out-1") return { id: "asset-out-1", kind: "subtitle", uri: "/media/tmp/out.srt", mime_type: "text/srt" };
      return { id: assetId, kind: "video", uri: "/media/tmp/in.mp4", mime_type: "video/mp4" };
    });

    render(<App />);

    await user.click(screen.getByRole("button", { name: "Jobs" }));

    const statusSelect = screen.getByLabelText("Status");
    await user.selectOptions(statusSelect, "completed");

    const table = await screen.findByRole("table");
    expect(within(table).getByText("job-1")).toBeInTheDocument();
    expect(within(table).queryByText("job-2")).not.toBeInTheDocument();

    const jobRow = within(table).getByText("job-1").closest("tr");
    expect(jobRow).toBeTruthy();
    await user.click(within(jobRow!).getByRole("button", { name: "View" }));

    const jobDetailCard = screen.getByRole("heading", { name: "Job detail" }).closest(".card") as HTMLElement | null;
    expect(jobDetailCard).toBeTruthy();

    const download = await within(jobDetailCard!).findByRole("link", { name: "Download" });
    expect(download).toHaveAttribute("href", "http://localhost:8000/media/tmp/out.srt");
  });
});
