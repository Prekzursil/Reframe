import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  baseUrl: "http://localhost:8000/api/v1",
  fetcher: vi.fn(),
  createCaptionJob: vi.fn(),
  createTranslateJob: vi.fn(),
  uploadAsset: vi.fn(),
  translateSubtitleAsset: vi.fn(),
  mergeAv: vi.fn(),
  createShortsJob: vi.fn(),
  mediaUrl: (uri: string) => (uri.startsWith("http") ? uri : `http://localhost:8000${uri}`),
}));

vi.mock("./api/client", () => ({ apiClient: apiClientMock }));

import {
  AudioUploadPanel,
  CaptionsForm,
  copyToClipboard,
  CopyCommandButton,
  JobStatusPill,
  MergeAvForm,
  ShortsForm,
  StyleEditor,
  SubtitleEditorCard,
  SubtitleToolsForm,
  SubtitleUpload,
  TextPreview,
  TranslateForm,
  UploadPanel,
} from "./App";

function makeJob(id: string, jobType = "captions") {
  return {
    id,
    job_type: jobType,
    status: "queued",
    progress: 0,
    payload: {},
  };
}

describe("App component coverage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiClientMock.createCaptionJob.mockResolvedValue(makeJob("job-cap", "captions"));
    apiClientMock.createTranslateJob.mockResolvedValue(makeJob("job-tr", "translate"));
    apiClientMock.translateSubtitleAsset.mockResolvedValue(makeJob("job-sub", "subtitle_translate"));
    apiClientMock.mergeAv.mockResolvedValue(makeJob("job-merge", "merge_av"));
    apiClientMock.createShortsJob.mockResolvedValue(makeJob("job-shorts", "shorts"));
    apiClientMock.uploadAsset.mockResolvedValue({ id: "asset-1", uri: "/media/asset-1.srt" });
    apiClientMock.fetcher.mockResolvedValue({
      ok: true,
      text: async () => "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
    });
    vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      text: async () => "preview content",
    } as Response);
  });

  it("covers clipboard helper success and fallback paths", async () => {
    expect(await copyToClipboard("hello")).toBe(true);

    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValueOnce(new Error("denied"));
    const execSpy = vi.fn(() => true);
    Object.defineProperty(document, "execCommand", { value: execSpy, configurable: true });

    expect(await copyToClipboard("fallback")).toBe(true);
    expect(execSpy).toHaveBeenCalledWith("copy");
  });

  it("renders copy button and text preview states", async () => {
    const user = userEvent.setup();
    render(<CopyCommandButton command="curl test" label="Copy" />);
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();

    render(<TextPreview url="/media/file.txt" title="Preview" />);
    expect(await screen.findByText("preview content")).toBeInTheDocument();

    render(<TextPreview url="javascript:alert(1)" title="Unsafe" />);
    expect(await screen.findByText("Unsafe preview URL")).toBeInTheDocument();
  });

  it("renders all job status pills", () => {
    const statuses = ["queued", "running", "completed", "failed", "cancelled"] as const;
    statuses.forEach((status) => {
      render(<JobStatusPill status={status} />);
      expect(screen.getByText(status)).toBeInTheDocument();
    });
  });

  it("submits caption form with advanced diarization variants and handles errors", async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();
    render(<CaptionsForm onCreated={onCreated} initialVideoId="video-1" projectId="proj-1" />);

    await user.selectOptions(screen.getByLabelText("Backend"), "noop");
    expect(screen.getByText(/No transcription runs/)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Speaker labels"), "pyannote");
    expect(screen.getByText(/HF_TOKEN/)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Speaker labels"), "speechbrain");
    expect(screen.getByText(/SpeechBrain/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create caption job" }));

    expect(apiClientMock.createCaptionJob).toHaveBeenCalled();
    expect(onCreated).toHaveBeenCalled();

    apiClientMock.createCaptionJob.mockRejectedValueOnce(new Error("caption fail"));
    await user.click(screen.getByRole("button", { name: "Create caption job" }));
    expect(await screen.findByText("caption fail")).toBeInTheDocument();
  });

  it("submits translate form success and failure", async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();
    render(<TranslateForm onCreated={onCreated} projectId="proj-2" />);

    await user.type(screen.getByLabelText("Subtitle asset ID"), "sub-1");
    await user.clear(screen.getByLabelText("Target language"));
    await user.type(screen.getByLabelText("Target language"), "fr");
    await user.type(screen.getByLabelText("Notes / instructions"), "note");
    await user.click(screen.getByRole("button", { name: "Request translation" }));

    expect(apiClientMock.createTranslateJob).toHaveBeenCalled();
    expect(onCreated).toHaveBeenCalled();

    apiClientMock.createTranslateJob.mockRejectedValueOnce(new Error("translate fail"));
    await user.click(screen.getByRole("button", { name: "Request translation" }));
    expect(await screen.findByText("translate fail")).toBeInTheDocument();
  });

  it("handles upload panel video/audio/subtitle success and errors", async () => {
    const onAssetId = vi.fn();
    const onPreview = vi.fn();

    const { container: videoContainer } = render(<UploadPanel onAssetId={onAssetId} onPreview={onPreview} projectId="proj" />);
    const videoInput = videoContainer.querySelector('input[type="file"]') as HTMLInputElement;
    const videoFile = new File(["video"], "clip.mp4", { type: "video/mp4" });
    fireEvent.change(videoInput, { target: { files: [videoFile] } });

    await waitFor(() => expect(apiClientMock.uploadAsset).toHaveBeenCalledWith(videoFile, "video", "proj"));
    expect(onAssetId).toHaveBeenCalledWith("asset-1");

    apiClientMock.uploadAsset.mockRejectedValueOnce(new Error("upload fail"));
    fireEvent.change(videoInput, { target: { files: [videoFile] } });
    expect(await screen.findByText("upload fail")).toBeInTheDocument();

    const { container: audioContainer } = render(<AudioUploadPanel onAssetId={onAssetId} onPreview={onPreview} projectId="proj" />);
    const audioInput = audioContainer.querySelector('input[type="file"]') as HTMLInputElement;
    const audioFile = new File(["audio"], "track.mp3", { type: "audio/mpeg" });
    fireEvent.change(audioInput, { target: { files: [audioFile] } });
    await waitFor(() => expect(apiClientMock.uploadAsset).toHaveBeenCalledWith(audioFile, "audio", "proj"));

    const subtitlePreview = vi.fn();
    const { container: subtitleContainer } = render(
      <SubtitleUpload onAssetId={onAssetId} onPreview={subtitlePreview} label="Upload subtitles" projectId="proj" />,
    );
    const subtitleInput = subtitleContainer.querySelector('input[type="file"]') as HTMLInputElement;
    const subtitleFile = new File(["1\n00:00:00,000 --> 00:00:01,000\nhi"], "sub.srt", { type: "text/plain" });
    fireEvent.change(subtitleInput, { target: { files: [subtitleFile] } });
    await waitFor(() => expect(apiClientMock.uploadAsset).toHaveBeenCalledWith(subtitleFile, "subtitle", "proj"));
    expect(subtitlePreview).toHaveBeenCalled();
  });

  it("covers subtitle editor load/shift/cues/save flows", async () => {
    const user = userEvent.setup();
    const onAssetChosen = vi.fn();

    render(<SubtitleEditorCard initialAssetId="sub-asset-1" onAssetChosen={onAssetChosen} projectId="proj-3" />);

    await user.click(screen.getByRole("button", { name: "Load" }));
    expect(await screen.findByDisplayValue(/hello/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cue table" }));
    expect(await screen.findByText(/Cue table mode/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add cue" }));
    await user.click(screen.getByRole("button", { name: "Sort cues" }));

    await user.click(screen.getAllByRole("button", { name: "Remove" })[0]!);
    await user.click(screen.getByText("Raw text").closest("button") as HTMLButtonElement);

    await user.clear(screen.getByLabelText("Shift timings (seconds)"));
    await user.type(screen.getByLabelText("Shift timings (seconds)"), "1.5");
    await user.click(screen.getByRole("button", { name: "Apply shift" }));

    await user.click(screen.getByRole("button", { name: "Save as new subtitle asset" }));
    expect(onAssetChosen).toHaveBeenCalled();
    expect(await screen.findByText("Saved subtitle asset")).toBeInTheDocument();

    apiClientMock.fetcher.mockResolvedValueOnce({
      ok: false,
      statusText: "bad",
      text: async () => "download fail",
    });
    await user.click(screen.getByRole("button", { name: "Load" }));
    expect(await screen.findByText("download fail")).toBeInTheDocument();
  });

  it("submits subtitle tools, merge, shorts, and style actions with error handling", async () => {
    const user = userEvent.setup();

    const subtitleCreated = vi.fn();
    render(<SubtitleToolsForm onCreated={subtitleCreated} projectId="p1" />);
    await user.type(screen.getByLabelText("Subtitle asset ID"), "sub-200");
    await user.selectOptions(screen.getByLabelText("Target language"), "de");
    await user.click(screen.getAllByRole("checkbox")[0]!);
    await user.click(screen.getByRole("button", { name: "Translate subtitles" }));
    expect(apiClientMock.translateSubtitleAsset).toHaveBeenCalled();
    expect(subtitleCreated).toHaveBeenCalled();

    apiClientMock.translateSubtitleAsset.mockRejectedValueOnce(new Error("subtitle translate fail"));
    await user.click(screen.getByRole("button", { name: "Translate subtitles" }));
    expect(await screen.findByText("subtitle translate fail")).toBeInTheDocument();

    const mergeCreated = vi.fn();
    render(<MergeAvForm onCreated={mergeCreated} initialVideoId="v1" initialAudioId="a1" projectId="p2" />);
    await user.click(screen.getByRole("button", { name: "Merge audio/video" }));
    expect(apiClientMock.mergeAv).toHaveBeenCalled();
    expect(mergeCreated).toHaveBeenCalled();

    apiClientMock.mergeAv.mockRejectedValueOnce(new Error("merge fail"));
    await user.click(screen.getByRole("button", { name: "Merge audio/video" }));
    expect(await screen.findByText("merge fail")).toBeInTheDocument();

    const shortsCreated = vi.fn();
    render(<ShortsForm onCreated={shortsCreated} projectId="p3" />);
    await user.type(screen.getByLabelText("Video asset ID or URL"), "vid-33");
    await user.click(screen.getByRole("checkbox", { name: /Attach styled subtitles/i }));
    await user.click(screen.getByRole("checkbox", { name: /Prefer non-silent segments \(experimental\)/i }));
    await user.type(screen.getByLabelText(/Timed subtitle asset \(SRT\/VTT\)/i), "sub-300");
    await user.click(screen.getByRole("checkbox", { name: /Use Groq \(requires GROQ_API_KEY on the worker\)/i }));
    await user.type(screen.getByLabelText("Prompt to guide selection"), "highlight energetic moments");
    await user.click(screen.getByRole("button", { name: "Create shorts job" }));
    expect(apiClientMock.createShortsJob).toHaveBeenCalled();
    expect(shortsCreated).toHaveBeenCalled();

    apiClientMock.createShortsJob.mockRejectedValueOnce(new Error("shorts fail"));
    await user.click(screen.getByRole("button", { name: "Create shorts job" }));
    expect(await screen.findByText("shorts fail")).toBeInTheDocument();

    const previewSpy = vi.fn().mockResolvedValue(makeJob("preview", "style"));
    const renderSpy = vi.fn().mockResolvedValue(makeJob("render", "style"));
    const onJobCreated = vi.fn();
    render(
      <StyleEditor
        onPreview={previewSpy}
        onRender={renderSpy}
        onJobCreated={onJobCreated}
        videoId="vid-style"
        subtitleId="sub-style"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Preview 5s" }));
    await user.click(screen.getByRole("button", { name: "Render full video" }));
    expect(previewSpy).toHaveBeenCalled();
    expect(renderSpy).toHaveBeenCalled();
    expect(onJobCreated).toHaveBeenCalled();

    const failedPreview = vi.fn().mockRejectedValue(new Error("preview fail"));
    render(<StyleEditor onPreview={failedPreview} onRender={renderSpy} videoId="vid-style" subtitleId="sub-style" />);
    await user.click(screen.getAllByRole("button", { name: "Preview 5s" }).at(-1)!);
    expect(await screen.findByText("preview fail")).toBeInTheDocument();
  });
});



