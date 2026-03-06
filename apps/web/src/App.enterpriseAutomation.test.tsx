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
  jobBundleUrl: (jobId: string) => `http://localhost:8000/api/v1/jobs/${jobId}/bundle`,
  mediaUrl: (uri: string) => (uri.startsWith("http") ? uri : `http://localhost:8000${uri}`),
}));

vi.mock("./api/client", () => ({ apiClient: apiClientMock }));

import App from "./App";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.setItem("reframe_access_token", "test-token");
  apiClientMock.accessToken = "test-token";

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

  apiClientMock.getMe.mockResolvedValue({
    user_id: "user-owner",
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
    members: [{ user_id: "user-owner", email: "owner@team.test", display_name: "Owner", role: "owner" }],
  });
  apiClientMock.listOrgInvites.mockResolvedValue([]);

  apiClientMock.getOrgSsoConfig.mockResolvedValue({
    org_id: "org-1",
    provider: "okta",
    enabled: true,
    issuer_url: "https://example.okta.com/oauth2/default",
    client_id: "okta-client",
    audience: "api://default",
    default_role: "viewer",
    jit_enabled: true,
    allow_email_link: true,
    config: {},
    updated_at: "2030-01-01T00:00:00Z",
  });
  apiClientMock.updateOrgSsoConfig.mockResolvedValue({
    org_id: "org-1",
    provider: "okta",
    enabled: true,
    issuer_url: "https://example.okta.com/oauth2/default",
    client_id: "okta-client",
    audience: "api://default",
    default_role: "viewer",
    jit_enabled: true,
    allow_email_link: true,
    config: {},
    updated_at: "2030-01-02T00:00:00Z",
  });
  apiClientMock.createScimToken.mockResolvedValue({
    id: "scim-token-1",
    org_id: "org-1",
    token_hint: "rscim_12...ab",
    scopes: ["users:read", "users:write"],
    created_at: "2030-01-01T00:00:00Z",
    token: "rscim_secret_once",
  });

  apiClientMock.listProjects.mockResolvedValue([{ id: "proj-1", name: "Launch", description: "release" }]);
  apiClientMock.listProjectJobs.mockResolvedValue([]);
  apiClientMock.listProjectAssets.mockResolvedValue([{ id: "asset-1", kind: "video", uri: "/media/tmp/clip.mp4", mime_type: "video/mp4" }]);

  apiClientMock.listProjectMembers.mockResolvedValue([{ user_id: "user-owner", email: "owner@team.test", display_name: "Owner", role: "owner", added_at: "2030-01-01T00:00:00Z" }]);
  apiClientMock.listProjectComments.mockResolvedValue([]);
  apiClientMock.listProjectActivity.mockResolvedValue([]);
  apiClientMock.addProjectMember.mockResolvedValue({ user_id: "user-editor", email: "editor@team.test", display_name: "Editor", role: "editor", added_at: "2030-01-01T00:00:00Z" });
  apiClientMock.createProjectComment.mockResolvedValue({
    id: "comment-1",
    project_id: "proj-1",
    author_user_id: "user-owner",
    author_email: "owner@team.test",
    body: "Ship it",
    created_at: "2030-01-01T00:00:00Z",
    updated_at: "2030-01-01T00:00:00Z",
  });
  apiClientMock.requestProjectApproval.mockResolvedValue({
    id: "approval-1",
    project_id: "proj-1",
    status: "pending",
    summary: "Final review",
    requested_by_user_id: "user-owner",
    created_at: "2030-01-01T00:00:00Z",
    updated_at: "2030-01-01T00:00:00Z",
  });

  apiClientMock.listPublishProviders.mockResolvedValue([
    { provider: "youtube", display_name: "YouTube", connected_count: 1 },
    { provider: "tiktok", display_name: "TikTok", connected_count: 0 },
    { provider: "instagram", display_name: "Instagram", connected_count: 0 },
    { provider: "facebook", display_name: "Facebook", connected_count: 0 },
  ]);
  apiClientMock.listPublishConnections.mockResolvedValue([
    { id: "conn-1", provider: "youtube", account_label: "Main channel", external_account_id: "yt-1", created_at: "2030-01-01T00:00:00Z", updated_at: "2030-01-01T00:00:00Z" },
  ]);
  apiClientMock.listPublishJobs.mockResolvedValue([]);
  apiClientMock.startPublishConnection.mockResolvedValue({
    provider: "youtube",
    state: "state-1",
    authorize_url: "https://example.com/oauth",
    redirect_uri: "http://localhost:8000/api/v1/publish/youtube/connect/callback",
  });
  apiClientMock.completePublishConnection.mockResolvedValue({
    id: "conn-1",
    provider: "youtube",
    account_label: "Main channel",
    external_account_id: "yt-1",
    created_at: "2030-01-01T00:00:00Z",
    updated_at: "2030-01-01T00:00:00Z",
  });
  apiClientMock.createPublishJob.mockResolvedValue({
    id: "publish-job-1",
    provider: "youtube",
    connection_id: "conn-1",
    asset_id: "asset-1",
    status: "queued",
    retry_count: 0,
    payload: {},
    created_at: "2030-01-01T00:00:00Z",
    updated_at: "2030-01-01T00:00:00Z",
  });
});

describe("enterprise automation surfaces", () => {
  it("saves SSO config and creates a SCIM token from account security panel", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Account" }));

    expect(await screen.findByText(/Enterprise security \(Okta \+ SCIM\)/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save SSO config" }));
    expect(apiClientMock.updateOrgSsoConfig).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Create SCIM token" }));
    expect(apiClientMock.createScimToken).toHaveBeenCalledWith("org-1");
    expect(await screen.findByText(/rscim_secret_once/)).toBeInTheDocument();

    apiClientMock.revokeScimToken.mockResolvedValueOnce({
      id: "scim-token-1",
      org_id: "org-1",
      token_hint: "rscim_12...ab",
      scopes: ["users:read", "users:write"],
      created_at: "2030-01-01T00:00:00Z",
      revoked_at: "2030-01-01T01:00:00Z",
    });
    await user.click(screen.getByRole("button", { name: "Revoke" }));
    expect(apiClientMock.revokeScimToken).toHaveBeenCalledWith("org-1", "scim-token-1");
  });

  it("adds collaboration member and creates publish job from projects tab", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Projects" }));

    await user.clear(await screen.findByLabelText("Member email"));
    await user.type(screen.getByLabelText("Member email"), "editor@team.test");
    await user.selectOptions(screen.getByLabelText("Role"), "editor");
    await user.click(screen.getByRole("button", { name: "Add project member" }));
    expect(apiClientMock.addProjectMember).toHaveBeenCalledWith("proj-1", {
      email: "editor@team.test",
      role: "editor",
    });

    await user.type(screen.getByLabelText("Title"), "Launch cut");
    await user.click(screen.getByRole("button", { name: "Create publish job" }));

    expect(apiClientMock.createPublishJob).toHaveBeenCalledWith(
      expect.objectContaining({
        provider: "youtube",
        connection_id: "conn-1",
        asset_id: "asset-1",
        title: "Launch cut",
      }),
    );
  }, 15000);
  it("covers share links, collaboration resolution, and publish retry flows", async () => {
    const user = userEvent.setup();

    apiClientMock.listProjectAssets.mockResolvedValueOnce([
      { id: "asset-1", kind: "video", uri: "/media/tmp/clip.mp4", mime_type: "video/mp4" },
      { id: "asset-2", kind: "audio", uri: "/media/tmp/clip.mp3", mime_type: "audio/mpeg" },
    ]);
    apiClientMock.createProjectShareLinks.mockResolvedValueOnce([
      { project_id: "proj-1", asset_id: "asset-1", url: "https://example.com/share/asset-1", expires_at: "2030-01-02T00:00:00Z" },
      { project_id: "proj-1", asset_id: "asset-2", url: "javascript:alert(1)", expires_at: "2030-01-02T00:00:00Z" },
    ]);
    apiClientMock.listProjectComments.mockResolvedValue([
      {
        id: "comment-1",
        project_id: "proj-1",
        author_user_id: "user-owner",
        author_email: "owner@team.test",
        body: "Needs tweaks",
        created_at: "2030-01-01T00:00:00Z",
        updated_at: "2030-01-01T00:00:00Z",
      },
    ]);
    apiClientMock.listProjectActivity.mockResolvedValue([
      {
        id: "evt-1",
        project_id: "proj-1",
        actor_user_id: "user-owner",
        event_type: "project.approval_requested",
        payload: { approval_id: "approval-1", summary: "Ship review", requested_by_user_id: "user-owner" },
        created_at: "2030-01-01T00:00:00Z",
      },
    ]);
    apiClientMock.approveProjectApproval.mockResolvedValue({
      id: "approval-1",
      project_id: "proj-1",
      status: "approved",
      summary: "Ship review",
      requested_by_user_id: "user-owner",
      resolved_by_user_id: "user-owner",
      resolved_at: "2030-01-01T01:00:00Z",
      created_at: "2030-01-01T00:00:00Z",
      updated_at: "2030-01-01T01:00:00Z",
    });
    apiClientMock.deleteProjectComment.mockResolvedValue(undefined);
    apiClientMock.revokePublishConnection.mockResolvedValue(undefined);
    apiClientMock.listPublishJobs.mockResolvedValue([
      {
        id: "publish-job-failed",
        provider: "youtube",
        connection_id: "conn-1",
        asset_id: "asset-1",
        status: "failed",
        retry_count: 1,
        payload: {},
        published_url: "https://youtube.com/watch?v=abc",
        created_at: "2030-01-01T00:00:00Z",
        updated_at: "2030-01-01T00:00:00Z",
      },
    ]);
    apiClientMock.retryPublishJob.mockResolvedValue({
      id: "publish-job-failed",
      provider: "youtube",
      connection_id: "conn-1",
      asset_id: "asset-1",
      status: "queued",
      retry_count: 2,
      payload: {},
      created_at: "2030-01-01T00:00:00Z",
      updated_at: "2030-01-01T00:02:00Z",
    });

    render(<App />);

    await user.click(screen.getByRole("button", { name: "Projects" }));

    await user.click(await screen.findByRole("button", { name: "Select filtered" }));
    await user.click(screen.getByRole("button", { name: /Generate share links/i }));
    expect(apiClientMock.createProjectShareLinks).toHaveBeenCalled();
    expect(await screen.findByText("https://example.com/share/asset-1")).toBeInTheDocument();
    expect(await screen.findByText(/Generated link was rejected by URL policy\./i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(apiClientMock.deleteProjectComment).toHaveBeenCalledWith("proj-1", "comment-1");

    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(apiClientMock.approveProjectApproval).toHaveBeenCalledWith("proj-1", "approval-1");

    await user.click(screen.getByRole("button", { name: "Use" }));
    await user.click(screen.getByRole("button", { name: "Revoke" }));
    expect(apiClientMock.revokePublishConnection).toHaveBeenCalledWith("youtube", "conn-1");

    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(apiClientMock.retryPublishJob).toHaveBeenCalledWith("publish-job-failed");
  }, 30000);
});
