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
    worker: { ping_ok: false, workers: [] },
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
  apiClientMock.createOrgInvite.mockResolvedValue({
    id: "invite-1",
    email: "editor@team.test",
    role: "editor",
    status: "pending",
    invite_url: "http://localhost:5173/invites/accept?token=tok_123",
    expires_at: "2030-01-01T00:00:00Z",
  });

  apiClientMock.listBillingPlans.mockResolvedValue([{ code: "pro", name: "Pro", max_concurrent_jobs: 3, monthly_job_minutes: 1200, monthly_storage_gb: 50, seat_limit: 5, overage_per_minute_cents: 2 }]);
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
    active_members: 1,
    pending_invites: 0,
    seat_limit: 3,
    available_seats: 2,
  });
  apiClientMock.updateBillingSeatLimit.mockResolvedValue({
    org_id: "org-1",
    plan_code: "pro",
    active_members: 1,
    pending_invites: 0,
    seat_limit: 4,
    available_seats: 3,
  });
});

describe("account + billing collaboration", () => {
  it("creates org invite from account workspace panel", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Account" }));

    await user.type(screen.getByLabelText("Invite email"), "editor@team.test");
    await user.selectOptions(screen.getByLabelText("Invite role"), "editor");
    await user.clear(screen.getByLabelText("Invite expiry (days)"));
    await user.type(screen.getByLabelText("Invite expiry (days)"), "10");
    await user.click(screen.getByRole("button", { name: "Create invite" }));

    expect(apiClientMock.createOrgInvite).toHaveBeenCalledWith({
      email: "editor@team.test",
      role: "editor",
      expires_in_days: 10,
    });
    expect(await screen.findByText(/invites\/accept\?token=tok_123/)).toBeInTheDocument();
  });

  it("loads seat usage and updates seat limit from billing page", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Billing" }));

    expect(await screen.findByText(/Seat usage/i)).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Seat limit"));
    await user.type(screen.getByLabelText("Seat limit"), "4");
    await user.click(screen.getByRole("button", { name: "Update seat limit" }));

    expect(apiClientMock.getBillingSeatUsage).toHaveBeenCalled();
    expect(apiClientMock.updateBillingSeatLimit).toHaveBeenCalledWith({ seat_limit: 4 });
  });
});
