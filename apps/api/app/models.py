from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

FK_MEDIA_ASSET_ID = "mediaasset.id"
FK_PROJECT_ID = "project.id"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Organization(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    name: str
    slug: str = Field(index=True, unique=True)
    tier: str = Field(default="free")
    seat_limit: int = Field(default=1)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class User(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    email: str = Field(index=True, unique=True)
    password_hash: Optional[str] = Field(default=None)
    display_name: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class OrgMembership(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_org_membership_org_user"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    role: str = Field(default="owner")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class OAuthAccount(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("provider", "provider_subject", name="uq_oauth_provider_subject"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    provider: str = Field(index=True)
    provider_subject: str
    email: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Plan(SQLModel, table=True):
    code: str = Field(primary_key=True, index=True)
    name: str
    max_concurrent_jobs: int = Field(default=1)
    monthly_job_minutes: int = Field(default=120)
    monthly_storage_gb: int = Field(default=2)
    seat_limit: int = Field(default=1)
    overage_per_minute_cents: int = Field(default=0)
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Subscription(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True, unique=True)
    plan_code: str = Field(foreign_key="plan.code", default="free")
    status: str = Field(default="active")
    stripe_customer_id: Optional[str] = Field(default=None, index=True)
    stripe_subscription_id: Optional[str] = Field(default=None, index=True)
    current_period_start: Optional[datetime] = Field(default=None)
    current_period_end: Optional[datetime] = Field(default=None)
    cancel_at_period_end: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class InvoiceSnapshot(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    subscription_id: Optional[UUID] = Field(default=None, foreign_key="subscription.id", index=True)
    stripe_invoice_id: Optional[str] = Field(default=None, index=True)
    amount_cents: int = Field(default=0)
    currency: str = Field(default="usd")
    status: str = Field(default="draft")
    period_start: Optional[datetime] = Field(default=None)
    period_end: Optional[datetime] = Field(default=None)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class UsageEvent(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    job_id: Optional[UUID] = Field(default=None, foreign_key="job.id", index=True)
    metric: str = Field(index=True)
    quantity: float = Field(default=0.0)
    details: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class UsageAggregate(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("org_id", "metric", "period_start", "period_end", name="uq_usage_aggregate_bucket"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    metric: str = Field(index=True)
    period_start: datetime = Field(default_factory=utcnow, index=True)
    period_end: datetime = Field(default_factory=utcnow, index=True)
    quantity: float = Field(default=0.0)
    updated_at: datetime = Field(default_factory=utcnow)


class ApiKey(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("org_id", "key_hash", name="uq_apikey_org_key_hash"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    created_by_user_id: UUID = Field(foreign_key="user.id", index=True)
    name: str
    key_prefix: str = Field(index=True)
    key_hash: str
    scopes: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    last_used_at: Optional[datetime] = Field(default=None)
    revoked_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AuditEvent(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    actor_user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    event_type: str = Field(index=True)
    entity_type: Optional[str] = Field(default=None, index=True)
    entity_id: Optional[str] = Field(default=None, index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class WorkflowRunStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class WorkflowStepStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class WorkflowTemplate(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    name: str
    description: Optional[str] = Field(default=None)
    steps: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    active: bool = Field(default=True)
    org_id: Optional[UUID] = Field(default=None, foreign_key="organization.id", index=True)
    owner_user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WorkflowRun(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    template_id: UUID = Field(foreign_key="workflowtemplate.id", index=True)
    task_id: Optional[str] = Field(default=None, index=True)
    status: WorkflowRunStatus = Field(default=WorkflowRunStatus.queued, index=True)
    input_asset_id: Optional[UUID] = Field(default=None, foreign_key=FK_MEDIA_ASSET_ID, index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    project_id: Optional[UUID] = Field(default=None, foreign_key=FK_PROJECT_ID, index=True)
    org_id: Optional[UUID] = Field(default=None, foreign_key="organization.id", index=True)
    owner_user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WorkflowRunStep(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("run_id", "order_index", name="uq_workflow_run_step_order"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    run_id: UUID = Field(foreign_key="workflowrun.id", index=True)
    order_index: int = Field(default=0, index=True)
    step_type: str = Field(index=True)
    status: WorkflowStepStatus = Field(default=WorkflowStepStatus.queued, index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class UsageLedgerEntry(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    job_id: Optional[UUID] = Field(default=None, foreign_key="job.id", index=True)
    metric: str = Field(index=True)
    unit: str = Field(default="count")
    quantity: float = Field(default=0.0)
    estimated_cost_cents: int = Field(default=0)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class OrgBudgetPolicy(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("org_id", name="uq_org_budget_policy_org"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    monthly_soft_limit_cents: Optional[int] = Field(default=None)
    monthly_hard_limit_cents: Optional[int] = Field(default=None)
    enforce_hard_limit: bool = Field(default=False)
    updated_by_user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SsoConnection(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("org_id", name="uq_sso_connection_org"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    provider: str = Field(default="okta", index=True)
    enabled: bool = Field(default=False)
    issuer_url: Optional[str] = Field(default=None)
    client_id: Optional[str] = Field(default=None)
    client_secret_ref: Optional[str] = Field(default=None)
    audience: Optional[str] = Field(default=None)
    default_role: str = Field(default="viewer")
    jit_enabled: bool = Field(default=True)
    allow_email_link: bool = Field(default=True)
    config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ScimToken(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("org_id", "token_hash", name="uq_scim_token_org_hash"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    created_by_user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    token_hint: str = Field(index=True)
    token_hash: str
    scopes: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    last_used_at: Optional[datetime] = Field(default=None)
    revoked_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ScimIdentity(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("org_id", "provider", "external_id", "resource_type", name="uq_scim_identity_external"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    provider: str = Field(default="okta", index=True)
    external_id: str = Field(index=True)
    resource_type: str = Field(default="user", index=True)
    email: Optional[str] = Field(default=None, index=True)
    group_name: Optional[str] = Field(default=None, index=True)
    active: bool = Field(default=True)
    attributes: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class RoleMapping(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("org_id", "provider", "external_value", name="uq_role_mapping_external"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    provider: str = Field(default="okta", index=True)
    external_value: str = Field(index=True)
    role: str = Field(default="viewer")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProjectMembership(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_membership_project_user"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    project_id: UUID = Field(foreign_key=FK_PROJECT_ID, index=True)
    org_id: Optional[UUID] = Field(default=None, foreign_key="organization.id", index=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    role: str = Field(default="viewer", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProjectComment(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    project_id: UUID = Field(foreign_key=FK_PROJECT_ID, index=True)
    org_id: Optional[UUID] = Field(default=None, foreign_key="organization.id", index=True)
    author_user_id: UUID = Field(foreign_key="user.id", index=True)
    parent_comment_id: Optional[UUID] = Field(default=None, foreign_key="projectcomment.id", index=True)
    body: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProjectApprovalRequest(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    project_id: UUID = Field(foreign_key=FK_PROJECT_ID, index=True)
    org_id: Optional[UUID] = Field(default=None, foreign_key="organization.id", index=True)
    requested_by_user_id: UUID = Field(foreign_key="user.id", index=True)
    status: str = Field(default="pending", index=True)
    summary: Optional[str] = Field(default=None)
    resolved_by_user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    resolved_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProjectActivityEvent(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    project_id: UUID = Field(foreign_key=FK_PROJECT_ID, index=True)
    org_id: Optional[UUID] = Field(default=None, foreign_key="organization.id", index=True)
    actor_user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    event_type: str = Field(index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class PublishConnection(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    provider: str = Field(index=True)
    account_label: Optional[str] = Field(default=None)
    external_account_id: Optional[str] = Field(default=None, index=True)
    token_ref: Optional[str] = Field(default=None)
    refresh_token_ref: Optional[str] = Field(default=None)
    connection_meta: dict = Field(default_factory=dict, sa_column=Column(JSON))
    revoked_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class PublishJob(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    provider: str = Field(index=True)
    connection_id: UUID = Field(foreign_key="publishconnection.id", index=True)
    asset_id: UUID = Field(foreign_key=FK_MEDIA_ASSET_ID, index=True)
    status: str = Field(default="queued", index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    retry_count: int = Field(default=0)
    error: Optional[str] = Field(default=None)
    external_post_id: Optional[str] = Field(default=None)
    published_url: Optional[str] = Field(default=None)
    task_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AutomationRunEvent(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: Optional[UUID] = Field(default=None, foreign_key="organization.id", index=True)
    workflow_run_id: Optional[UUID] = Field(default=None, foreign_key="workflowrun.id", index=True)
    publish_job_id: Optional[UUID] = Field(default=None, foreign_key="publishjob.id", index=True)
    step_name: str = Field(index=True)
    status: str = Field(index=True)
    message: Optional[str] = Field(default=None)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class MediaAsset(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    kind: str = Field(description="Type of asset, e.g., video, audio, subtitle")
    uri: Optional[str] = Field(default=None, description="Storage URI or path for the asset")
    mime_type: Optional[str] = Field(default=None)
    duration: Optional[float] = Field(default=None, description="Duration in seconds if known")
    project_id: Optional[UUID] = Field(default=None, foreign_key=FK_PROJECT_ID, index=True)
    org_id: Optional[UUID] = Field(default=None, foreign_key="organization.id", index=True)
    owner_user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class OrgRole(str, Enum):
    owner = "owner"
    admin = "admin"
    editor = "editor"
    viewer = "viewer"


class InviteStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"
    expired = "expired"


class Job(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    job_type: str = Field(description="Pipeline type, e.g., transcribe, translate, shorts")
    task_id: Optional[str] = Field(default=None, index=True, description="Celery task id for execution tracking")
    status: JobStatus = Field(default=JobStatus.queued, index=True)
    progress: float = Field(default=0.0, description="0-1.0 progress fraction")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON), description="Options or parameters for the job")

    input_asset_id: Optional[UUID] = Field(default=None, foreign_key=FK_MEDIA_ASSET_ID)
    output_asset_id: Optional[UUID] = Field(default=None, foreign_key=FK_MEDIA_ASSET_ID)
    project_id: Optional[UUID] = Field(default=None, foreign_key=FK_PROJECT_ID, index=True)
    org_id: Optional[UUID] = Field(default=None, foreign_key="organization.id", index=True)
    owner_user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    idempotency_key: Optional[str] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SubtitleStylePreset(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    name: str
    description: Optional[str] = Field(default=None)
    style: dict = Field(default_factory=dict, sa_column=Column(JSON), description="Serialized style payload")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Project(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    name: str
    description: Optional[str] = Field(default=None)
    org_id: Optional[UUID] = Field(default=None, foreign_key="organization.id", index=True)
    owner_user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class OrgInvite(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_org_invite_token_hash"),
        UniqueConstraint("org_id", "email", "status", name="uq_org_invite_org_email_status"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    org_id: UUID = Field(foreign_key="organization.id", index=True)
    email: str = Field(index=True)
    role: str = Field(default="viewer")
    token_hash: str = Field(index=True)
    status: InviteStatus = Field(default=InviteStatus.pending, index=True)
    invited_by_user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    accepted_by_user_id: Optional[UUID] = Field(default=None, foreign_key="user.id", index=True)
    expires_at: datetime = Field(default_factory=utcnow, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
