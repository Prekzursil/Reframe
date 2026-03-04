import { render, screen, within } from "@testing-library/react";
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
  resolveOrgInvite: vi.fn(),
  acceptOrgInvite: vi.fn(),
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
  localStorage.removeItem("reframe_access_token");
  apiClientMock.accessToken = null;

  apiClientMock.listJobs.mockResolvedValue([]);
  apiClientMock.listAssets.mockResolvedValue([]);
  apiClientMock.listProjects.mockResolvedValue([]);
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
  apiClientMock.getSystemStatus.mockResolvedValue({
    api_version: "0.1.0",
    offline_mode: false,
    storage_backend: "LocalStorageBackend",
    broker_url: "redis://localhost:6379/0",
    result_backend: "redis://localhost:6379/0",
    worker: {
      ping_ok: true,
      workers: ["worker@local"],
      system_info: { ffmpeg: { present: true } },
    },
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
    members: [
      { user_id: "user-owner", email: "owner@team.test", display_name: "Owner", role: "owner" },
      { user_id: "user-editor", email: "editor@team.test", display_name: "Editor", role: "editor" },
    ],
  });
  apiClientMock.listOrgInvites.mockResolvedValue([
    {
      id: "invite-1",
      email: "new@team.test",
      role: "viewer",
      status: "pending",
      invite_url: "http://localhost:5173/invites/accept?token=tok_123",
      expires_at: "2030-01-01T00:00:00Z",
    },
  ]);

  apiClientMock.oauthStart.mockResolvedValue({ authorize_url: "javascript:alert(1)" });
  apiClientMock.resolveOrgInvite.mockResolvedValue({
    invite_id: "invite-1",
    org_id: "org-1",
    org_name: "Team Org",
    email: "new@team.test",
    role: "viewer",
    status: "pending",
    expires_at: "2030-01-01T00:00:00Z",
  });
  apiClientMock.acceptOrgInvite.mockResolvedValue({ access_token: "accepted-token", token_type: "bearer" });
  apiClientMock.login.mockResolvedValue({ access_token: "login-token", token_type: "bearer" });
  apiClientMock.register.mockResolvedValue({ access_token: "register-token", token_type: "bearer" });
  apiClientMock.logout.mockResolvedValue(undefined);
  apiClientMock.updateOrgMemberRole.mockResolvedValue({
    user_id: "user-editor",
    email: "editor@team.test",
    display_name: "Editor",
    role: "viewer",
  });
  apiClientMock.removeOrgMember.mockResolvedValue(undefined);
  apiClientMock.revokeOrgInvite.mockResolvedValue({ id: "invite-1", status: "revoked" });

  apiClientMock.listBillingPlans.mockResolvedValue([
    { code: "pro", name: "Pro", max_concurrent_jobs: 3, monthly_job_minutes: 1200, monthly_storage_gb: 50, seat_limit: 5, overage_per_minute_cents: 2 },
  ]);
  apiClientMock.getBillingSubscription.mockResolvedValue({
    org_id: "org-1",
    plan_code: "pro",
    status: "active",
    stripe_customer_id: "cus_1",
    stripe_subscription_id: "sub_1",
    cancel_at_period_end: false,
  });
  apiClientMock.getBillingUsageSummary.mockResolvedValue({
    org_id: "org-1",
    plan_code: "pro",
    used_job_minutes: 10,
    quota_job_minutes: 1200,
    used_storage_gb: 1,
    quota_storage_gb: 50,
    overage_job_minutes: 0,
    estimated_overage_cents: 0,
  });
  apiClientMock.getBillingSeatUsage.mockResolvedValue({
    org_id: "org-1",
    plan_code: "pro",
    active_members: 2,
    pending_invites: 1,
    seat_limit: 4,
    available_seats: 1,
  });
  apiClientMock.updateBillingSeatLimit.mockResolvedValue({
    org_id: "org-1",
    plan_code: "pro",
    active_members: 2,
    pending_invites: 1,
    seat_limit: 5,
    available_seats: 2,
  });
});

describe("account, billing, and diagnostics paths", () => {
  it("covers OAuth unsafe-redirect path", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Account" }));
    await user.click(screen.getByRole("button", { name: "Continue with Google" }));
    expect(apiClientMock.oauthStart).toHaveBeenCalledWith("google");
    expect(await screen.findByText(/Unsafe OAuth redirect URL rejected\./i)).toBeInTheDocument();
  });

  it("covers authenticated account management actions", async () => {
    const user = userEvent.setup();
    localStorage.setItem("reframe_access_token", "token");
    apiClientMock.accessToken = "token";

    render(<App />);

    await user.click(screen.getByRole("button", { name: "Account" }));
    await user.click(await screen.findByRole("button", { name: "Refresh account" }));
    expect(apiClientMock.getMe).toHaveBeenCalled();

    const roleSelectors = await screen.findAllByDisplayValue("editor");
    await user.selectOptions(roleSelectors[0], "viewer");
    expect(apiClientMock.updateOrgMemberRole).toHaveBeenCalledWith("user-editor", { role: "viewer" });

    await user.click(screen.getByRole("button", { name: "Revoke" }));
    expect(apiClientMock.revokeOrgInvite).toHaveBeenCalledWith("invite-1");

    const removeButtons = screen.getAllByRole("button", { name: "Remove" });
    await user.click(removeButtons[removeButtons.length - 1]);
    expect(apiClientMock.removeOrgMember).toHaveBeenCalledWith("user-editor");

    await user.click(screen.getByRole("button", { name: "Logout" }));
    expect(apiClientMock.logout).toHaveBeenCalled();
  }, 20000);

  it("covers invite token acceptance and auth actions", async () => {
    const user = userEvent.setup();
    localStorage.setItem("reframe_access_token", "token");
    apiClientMock.accessToken = "token";
    window.history.pushState({}, "", "/?token=tok_accept");

    render(<App />);

    await user.click(screen.getByRole("button", { name: "Account" }));
    expect(await screen.findByText(/Invite acceptance/i)).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Accept invite" }));
    expect(apiClientMock.acceptOrgInvite).toHaveBeenCalledWith({ token: "tok_accept" });

    await user.click(screen.getByRole("button", { name: "Logout" }));
    expect(apiClientMock.logout).toHaveBeenCalled();

    localStorage.removeItem("reframe_access_token");
    apiClientMock.accessToken = null;
    apiClientMock.oauthStart.mockRejectedValueOnce(new Error("oauth github failed"));

    await user.click(screen.getByRole("button", { name: "Continue with GitHub" }));
    expect(await screen.findByText(/oauth github failed/i)).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Email"));
    await user.type(screen.getByLabelText("Email"), "user@example.com");
    await user.clear(screen.getByLabelText("Password"));
    await user.type(screen.getByLabelText("Password"), "pass12345");
    await user.click(screen.getByRole("button", { name: "Register" }));
    expect(apiClientMock.register).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Logout" }));
    await user.click(screen.getByRole("button", { name: "Login" }));
    expect(apiClientMock.login).toHaveBeenCalled();
  }, 30000);
  it("covers billing and system refresh flows", async () => {
    const user = userEvent.setup();
    localStorage.setItem("reframe_access_token", "token");
    apiClientMock.accessToken = "token";

    render(<App />);

    await user.click(screen.getByRole("button", { name: "Billing" }));
    expect(await screen.findByText(/Billing status/i)).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Seat limit"));
    await user.type(screen.getByLabelText("Seat limit"), "5");
    await user.click(screen.getByRole("button", { name: "Update seat limit" }));
    expect(apiClientMock.updateBillingSeatLimit).toHaveBeenCalledWith({ seat_limit: 5 });

    const plansTable = await screen.findByRole("table");
    expect(within(plansTable).getByText("Pro")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "System" }));
    expect(await screen.findByText(/Ping: ok/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    expect(apiClientMock.getSystemStatus).toHaveBeenCalled();
  }, 20000);
});
