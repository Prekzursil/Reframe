import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "./client";

function okJson(body: unknown, status = 200) {
  return {
    ok: true,
    status,
    statusText: "OK",
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

function failJson(message: string, status = 400, statusText = "Bad Request") {
  return {
    ok: false,
    status,
    statusText,
    json: async () => ({ message }),
    text: async () => message,
  } as unknown as Response;
}

describe("ApiClient", () => {
  const fetcher = vi.fn();
  let client: ApiClient;

  beforeEach(() => {
    fetcher.mockReset();
    client = new ApiClient({ baseUrl: "http://localhost:8000/api/v1", fetcher: fetcher as unknown as typeof fetch });
  });

  it("handles request headers, auth, errors, and 204 responses", async () => {
    fetcher.mockResolvedValueOnce(okJson({ ok: true }));
    await client.request("/jobs");

    const [url1, init1] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(url1).toBe("http://localhost:8000/api/v1/jobs");
    expect(new Headers(init1.headers).get("Content-Type")).toBe("application/json");

    client.setAccessToken("abc");
    fetcher.mockResolvedValueOnce(okJson({ ok: true }));
    await client.request("/auth/me");
    const [, init2] = fetcher.mock.calls[1] as [string, RequestInit];
    expect(new Headers(init2.headers).get("Authorization")).toBe("Bearer abc");

    fetcher.mockResolvedValueOnce({ ok: true, status: 204, statusText: "No Content", json: async () => ({}) } as unknown as Response);
    await expect(client.request<void>("/auth/logout", { method: "POST" })).resolves.toBeUndefined();

    fetcher.mockResolvedValueOnce(failJson("custom fail"));
    await expect(client.request("/bad")).rejects.toThrow("custom fail");

    fetcher.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Server Error",
      json: async () => {
        throw new Error("bad json");
      },
      text: async () => "",
    } as unknown as Response);
    await expect(client.request("/bad2")).rejects.toThrow("Server Error");
  });

  it("executes high-surface request wrappers", async () => {
    const requestSpy = vi.spyOn(client, "request").mockResolvedValue({} as never);

    await client.listJobs({ status: "running", project_id: "p1" });
    await client.listJobs();
    await client.getJob("job-1");
    await client.getAsset("asset-1");
    await client.listAssets({ kind: "video", limit: 10, project_id: "p1" });
    await client.listAssets();

    await client.createCaptionJob({ video_asset_id: "v", idempotency_key: "k" });
    await client.createCaptionJob({ video_asset_id: "v" });
    await client.createTranslateJob({ subtitle_asset_id: "s", target_language: "fr", idempotency_key: "k" });
    await client.createTranslateJob({ subtitle_asset_id: "s", target_language: "fr" });
    await client.createStyledSubtitleJob({ video_asset_id: "v", subtitle_asset_id: "s", style: {}, idempotency_key: "k" });
    await client.createStyledSubtitleJob({ video_asset_id: "v", subtitle_asset_id: "s", style: {} });
    await client.createShortsJob({ video_asset_id: "v", idempotency_key: "k" });
    await client.createShortsJob({ video_asset_id: "v" });
    await client.translateSubtitleAsset({ subtitle_asset_id: "s", target_language: "es", idempotency_key: "k" });
    await client.translateSubtitleAsset({ subtitle_asset_id: "s", target_language: "es" });
    await client.mergeAv({ video_asset_id: "v", audio_asset_id: "a", idempotency_key: "k" });
    await client.mergeAv({ video_asset_id: "v", audio_asset_id: "a" });
    await client.createCutClipJob({ video_asset_id: "v", start: 0, end: 1, idempotency_key: "k" });
    await client.createCutClipJob({ video_asset_id: "v", start: 0, end: 1 });
    await client.retryJob("job-1", { idempotency_key: "k" });
    await client.retryJob("job-1");

    await client.getSystemStatus();
    await client.getUsageSummary({ from: "2026-01-01", to: "2026-02-01", project_id: "p1" });
    await client.getUsageSummary();
    await client.getUsageCosts({ from: "2026-01-01", to: "2026-02-01", project_id: "p1" });
    await client.getUsageCosts();
    await client.getBudgetPolicy();
    await client.updateBudgetPolicy({ enforce_hard_limit: true });

    await client.listProjects();
    await client.createProject({ name: "n" });
    await client.getProject("p1");
    await client.listProjectJobs("p1");
    await client.listProjectAssets("p1", { kind: "video", limit: 10 });
    await client.listProjectAssets("p1");
    await client.listProjectMembers("p1");
    await client.addProjectMember("p1", { email: "a@b.com", role: "editor" });
    await client.updateProjectMemberRole("p1", "u1", { role: "viewer" });
    await client.listProjectComments("p1");
    await client.createProjectComment("p1", { body: "hi" });
    await client.requestProjectApproval("p1", { summary: "ok" });
    await client.requestProjectApproval("p1");
    await client.approveProjectApproval("p1", "a1");
    await client.rejectProjectApproval("p1", "a1");
    await client.listProjectActivity("p1", 25);
    await client.createProjectShareLinks("p1", { asset_ids: ["a1"] });

    await client.initAssetUpload({ filename: "f", mime_type: "video/mp4" });
    await client.completeAssetUpload({ upload_id: "u1", asset_id: "a1" });
    await client.initMultipartAssetUpload({ filename: "f" });
    await client.signMultipartUploadPart("u1", 1);
    await client.completeMultipartUpload("u1", { parts: [{ part_number: 1, etag: "x" }] });
    await client.abortMultipartUpload("u1");

    await client.register({ email: "a@b.com", password: "pw" });
    await client.login({ email: "a@b.com", password: "pw" });
    await client.refreshToken("rt");
    await client.logout();
    await client.getMe();
    await client.oauthStart("google", "http://localhost/cb");
    await client.oauthStart("github");

    await client.getOrgContext();
    await client.listOrgs();
    await client.createOrg({ name: "org" });
    await client.getOrgSsoConfig("org-1");
    await client.updateOrgSsoConfig("org-1", { enabled: true });
    await client.createScimToken("org-1", { scopes: ["Users"] });
    await client.createScimToken("org-1");
    await client.startOktaSso("http://localhost/cb");
    await client.startOktaSso();
    await client.completeOktaSso({ state: "s", code: "c", email: "a@b.com", sub: "sub", groups: "admins" });
    await client.completeOktaSso({ state: "s" });

    await client.listOrgInvites();
    await client.createOrgInvite({ email: "x@y.com", role: "editor", expires_in_days: 7 });
    await client.revokeOrgInvite("inv-1");
    await client.resolveOrgInvite("tok");
    await client.acceptOrgInvite({ token: "tok" });
    await client.updateOrgMemberRole("u1", { role: "owner" });
    await client.addOrgMember("org-1", { email: "m@x.com" });

    await client.listAuditEvents();
    await client.listApiKeys("org-1");
    await client.createApiKey("org-1", { name: "k" });

    await client.createWorkflowTemplate({ name: "wf", steps: [] });
    await client.listWorkflowTemplates(true);
    await client.listWorkflowTemplates(false);
    await client.createWorkflowRun({ template_id: "t1", video_asset_id: "a1" });
    await client.getWorkflowRun("r1");
    await client.cancelWorkflowRun("r1");

    await client.listPublishProviders();
    await client.listPublishConnections("youtube");
    await client.startPublishConnection("youtube", "http://localhost/cb");
    await client.startPublishConnection("tiktok");
    await client.completePublishConnection("youtube", {
      state: "s",
      code: "code",
      refresh_token: "r",
      account_id: "acct",
      account_label: "label",
    });
    await client.completePublishConnection("facebook", { state: "s" });
    await client.createPublishJob({ provider: "youtube", connection_id: "c", asset_id: "a" });
    await client.listPublishJobs({ provider: "youtube", status: "queued" });
    await client.listPublishJobs();
    await client.getPublishJob("p1");
    await client.retryPublishJob("p1");

    await client.listBillingPlans();
    await client.getBillingSubscription();
    await client.getBillingUsageSummary();
    await client.getBillingSeatUsage();
    await client.getBillingCostModel();
    await client.createBillingCheckoutSession({ plan_code: "starter" });
    await client.updateBillingSeatLimit({ seat_limit: 8 });
    await client.createBillingPortalSession({ return_url: "http://localhost" });
    await client.createBillingPortalSession();

    expect(requestSpy).toHaveBeenCalled();
  });

  it("covers direct delete/revoke method success and failures", async () => {
    client.setAccessToken("abc");

    fetcher.mockResolvedValue(okJson({}, 200));
    await client.removeProjectMember("p1", "u1");
    await client.deleteProjectComment("p1", "c1");
    await client.revokeScimToken("org-1", "tok-1");
    await client.removeOrgMemberFromOrg("org-1", "u1");
    await client.removeOrgMember("u1");
    await client.revokeApiKey("org-1", "k1");
    await client.revokePublishConnection("youtube", "pc1");
    await client.deleteJob("job-1", { deleteAssets: true });
    await client.deleteJob("job-2");
    await client.deleteAsset("asset-1");

    fetcher.mockResolvedValueOnce({ ok: false, status: 500, statusText: "", text: async () => "", json: async () => ({}) } as unknown as Response);
    await expect(client.removeProjectMember("p1", "u1")).rejects.toThrow("Failed to remove project member");

    fetcher.mockResolvedValueOnce({ ok: false, status: 500, statusText: "oops", text: async () => { throw new Error("x"); }, json: async () => ({}) } as unknown as Response);
    await expect(client.deleteProjectComment("p1", "c1")).rejects.toThrow("oops");
  });

  it("covers uploadAsset POST, PUT, and unsupported method paths", async () => {
    client.setAccessToken("token");
    const file = new File(["video"], "clip.mp4", { type: "video/mp4" });

    vi.spyOn(client, "initAssetUpload").mockResolvedValueOnce({
      upload_id: "u1",
      asset_id: null,
      upload_url: "http://localhost:8000/api/v1/assets/upload",
      method: "POST",
      headers: {},
      form_fields: { acl: "private" },
      expires_at: "2026-03-04T00:00:00Z",
      strategy: "presigned_post",
    });
    vi.spyOn(client, "completeAssetUpload").mockResolvedValue({ upload_id: "u1", asset_id: "a1" });

    fetcher.mockResolvedValueOnce(okJson({ id: "a1", kind: "video" }));
    const postAsset = await client.uploadAsset(file, "video");
    expect(postAsset.id).toBe("a1");

    vi.spyOn(client, "initAssetUpload").mockResolvedValueOnce({
      upload_id: "u2",
      asset_id: "a2",
      upload_url: "https://storage.example/upload",
      method: "PUT",
      headers: {},
      form_fields: {},
      expires_at: "2026-03-04T00:00:00Z",
      strategy: "presigned_put",
    });
    vi.spyOn(client, "getAsset").mockResolvedValue({ id: "a2", kind: "video" } as never);
    fetcher.mockResolvedValueOnce(okJson({}, 200));
    const putAsset = await client.uploadAsset(file, "video");
    expect(putAsset.id).toBe("a2");

    vi.spyOn(client, "initAssetUpload").mockResolvedValueOnce({
      upload_id: "u3",
      asset_id: "a3",
      upload_url: "https://storage.example/upload",
      method: "PATCH",
      headers: {},
      form_fields: {},
      expires_at: "2026-03-04T00:00:00Z",
      strategy: "unsupported",
    });
    await expect(client.uploadAsset(file, "video")).rejects.toThrow("Unsupported upload method: PATCH");

    expect(client.mediaUrl("https://cdn.example/file.mp4")).toBe("https://cdn.example/file.mp4");
    expect(client.mediaUrl("/media/out.mp4")).toContain("/media/out.mp4");

    const malformed = new ApiClient({ baseUrl: "bad-url", fetcher: fetcher as unknown as typeof fetch });
    expect(malformed.mediaUrl("/asset")).toContain("/asset");
    expect(client.jobBundleUrl("job-1")).toBe("http://localhost:8000/api/v1/jobs/job-1/bundle");
  });
});

