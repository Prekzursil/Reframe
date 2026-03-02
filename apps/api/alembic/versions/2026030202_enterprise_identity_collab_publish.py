"""enterprise identity collaboration and publish entities

Revision ID: 2026030202
Revises: 2026030201
Create Date: 2026-03-02 21:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2026030202"
down_revision = "2026030201"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ssoconnection",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default=sa.text("'okta'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("issuer_url", sa.Text(), nullable=True),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("client_secret_ref", sa.Text(), nullable=True),
        sa.Column("audience", sa.Text(), nullable=True),
        sa.Column("default_role", sa.String(length=32), nullable=False, server_default=sa.text("'viewer'")),
        sa.Column("jit_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("allow_email_link", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.UniqueConstraint("org_id", name="uq_sso_connection_org"),
    )
    op.create_index("ix_ssoconnection_id", "ssoconnection", ["id"], unique=False)
    op.create_index("ix_ssoconnection_org_id", "ssoconnection", ["org_id"], unique=False)
    op.create_index("ix_ssoconnection_provider", "ssoconnection", ["provider"], unique=False)

    op.create_table(
        "scimtoken",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("token_hint", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
        sa.UniqueConstraint("org_id", "token_hash", name="uq_scim_token_org_hash"),
    )
    op.create_index("ix_scimtoken_id", "scimtoken", ["id"], unique=False)
    op.create_index("ix_scimtoken_org_id", "scimtoken", ["org_id"], unique=False)
    op.create_index("ix_scimtoken_created_by_user_id", "scimtoken", ["created_by_user_id"], unique=False)
    op.create_index("ix_scimtoken_token_hint", "scimtoken", ["token_hint"], unique=False)

    op.create_table(
        "scimidentity",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default=sa.text("'okta'")),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False, server_default=sa.text("'user'")),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("group_name", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("attributes", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.UniqueConstraint("org_id", "provider", "external_id", "resource_type", name="uq_scim_identity_external"),
    )
    op.create_index("ix_scimidentity_id", "scimidentity", ["id"], unique=False)
    op.create_index("ix_scimidentity_org_id", "scimidentity", ["org_id"], unique=False)
    op.create_index("ix_scimidentity_user_id", "scimidentity", ["user_id"], unique=False)
    op.create_index("ix_scimidentity_provider", "scimidentity", ["provider"], unique=False)
    op.create_index("ix_scimidentity_external_id", "scimidentity", ["external_id"], unique=False)
    op.create_index("ix_scimidentity_resource_type", "scimidentity", ["resource_type"], unique=False)
    op.create_index("ix_scimidentity_email", "scimidentity", ["email"], unique=False)
    op.create_index("ix_scimidentity_group_name", "scimidentity", ["group_name"], unique=False)

    op.create_table(
        "rolemapping",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default=sa.text("'okta'")),
        sa.Column("external_value", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default=sa.text("'viewer'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.UniqueConstraint("org_id", "provider", "external_value", name="uq_role_mapping_external"),
    )
    op.create_index("ix_rolemapping_id", "rolemapping", ["id"], unique=False)
    op.create_index("ix_rolemapping_org_id", "rolemapping", ["org_id"], unique=False)
    op.create_index("ix_rolemapping_provider", "rolemapping", ["provider"], unique=False)
    op.create_index("ix_rolemapping_external_value", "rolemapping", ["external_value"], unique=False)

    op.create_table(
        "projectmembership",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default=sa.text("'viewer'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_membership_project_user"),
    )
    op.create_index("ix_projectmembership_id", "projectmembership", ["id"], unique=False)
    op.create_index("ix_projectmembership_project_id", "projectmembership", ["project_id"], unique=False)
    op.create_index("ix_projectmembership_org_id", "projectmembership", ["org_id"], unique=False)
    op.create_index("ix_projectmembership_user_id", "projectmembership", ["user_id"], unique=False)
    op.create_index("ix_projectmembership_role", "projectmembership", ["role"], unique=False)

    op.create_table(
        "projectcomment",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=True),
        sa.Column("author_user_id", sa.String(length=36), nullable=False),
        sa.Column("parent_comment_id", sa.String(length=36), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["author_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["parent_comment_id"], ["projectcomment.id"]),
    )
    op.create_index("ix_projectcomment_id", "projectcomment", ["id"], unique=False)
    op.create_index("ix_projectcomment_project_id", "projectcomment", ["project_id"], unique=False)
    op.create_index("ix_projectcomment_org_id", "projectcomment", ["org_id"], unique=False)
    op.create_index("ix_projectcomment_author_user_id", "projectcomment", ["author_user_id"], unique=False)
    op.create_index("ix_projectcomment_parent_comment_id", "projectcomment", ["parent_comment_id"], unique=False)

    op.create_table(
        "projectapprovalrequest",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=True),
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("resolved_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["user.id"]),
    )
    op.create_index("ix_projectapprovalrequest_id", "projectapprovalrequest", ["id"], unique=False)
    op.create_index("ix_projectapprovalrequest_project_id", "projectapprovalrequest", ["project_id"], unique=False)
    op.create_index("ix_projectapprovalrequest_org_id", "projectapprovalrequest", ["org_id"], unique=False)
    op.create_index("ix_projectapprovalrequest_requested_by_user_id", "projectapprovalrequest", ["requested_by_user_id"], unique=False)
    op.create_index("ix_projectapprovalrequest_resolved_by_user_id", "projectapprovalrequest", ["resolved_by_user_id"], unique=False)
    op.create_index("ix_projectapprovalrequest_status", "projectapprovalrequest", ["status"], unique=False)

    op.create_table(
        "projectactivityevent",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=True),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"]),
    )
    op.create_index("ix_projectactivityevent_id", "projectactivityevent", ["id"], unique=False)
    op.create_index("ix_projectactivityevent_project_id", "projectactivityevent", ["project_id"], unique=False)
    op.create_index("ix_projectactivityevent_org_id", "projectactivityevent", ["org_id"], unique=False)
    op.create_index("ix_projectactivityevent_actor_user_id", "projectactivityevent", ["actor_user_id"], unique=False)
    op.create_index("ix_projectactivityevent_event_type", "projectactivityevent", ["event_type"], unique=False)
    op.create_index("ix_projectactivityevent_created_at", "projectactivityevent", ["created_at"], unique=False)

    op.create_table(
        "publishconnection",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("account_label", sa.Text(), nullable=True),
        sa.Column("external_account_id", sa.Text(), nullable=True),
        sa.Column("token_ref", sa.Text(), nullable=True),
        sa.Column("refresh_token_ref", sa.Text(), nullable=True),
        sa.Column("connection_meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
    )
    op.create_index("ix_publishconnection_id", "publishconnection", ["id"], unique=False)
    op.create_index("ix_publishconnection_org_id", "publishconnection", ["org_id"], unique=False)
    op.create_index("ix_publishconnection_user_id", "publishconnection", ["user_id"], unique=False)
    op.create_index("ix_publishconnection_provider", "publishconnection", ["provider"], unique=False)
    op.create_index("ix_publishconnection_external_account_id", "publishconnection", ["external_account_id"], unique=False)

    op.create_table(
        "publishjob",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("external_post_id", sa.Text(), nullable=True),
        sa.Column("published_url", sa.Text(), nullable=True),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["connection_id"], ["publishconnection.id"]),
        sa.ForeignKeyConstraint(["asset_id"], ["mediaasset.id"]),
    )
    op.create_index("ix_publishjob_id", "publishjob", ["id"], unique=False)
    op.create_index("ix_publishjob_org_id", "publishjob", ["org_id"], unique=False)
    op.create_index("ix_publishjob_user_id", "publishjob", ["user_id"], unique=False)
    op.create_index("ix_publishjob_provider", "publishjob", ["provider"], unique=False)
    op.create_index("ix_publishjob_connection_id", "publishjob", ["connection_id"], unique=False)
    op.create_index("ix_publishjob_asset_id", "publishjob", ["asset_id"], unique=False)
    op.create_index("ix_publishjob_status", "publishjob", ["status"], unique=False)
    op.create_index("ix_publishjob_task_id", "publishjob", ["task_id"], unique=False)

    op.create_table(
        "automationrunevent",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=True),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("publish_job_id", sa.String(length=36), nullable=True),
        sa.Column("step_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflowrun.id"]),
        sa.ForeignKeyConstraint(["publish_job_id"], ["publishjob.id"]),
    )
    op.create_index("ix_automationrunevent_id", "automationrunevent", ["id"], unique=False)
    op.create_index("ix_automationrunevent_org_id", "automationrunevent", ["org_id"], unique=False)
    op.create_index("ix_automationrunevent_workflow_run_id", "automationrunevent", ["workflow_run_id"], unique=False)
    op.create_index("ix_automationrunevent_publish_job_id", "automationrunevent", ["publish_job_id"], unique=False)
    op.create_index("ix_automationrunevent_step_name", "automationrunevent", ["step_name"], unique=False)
    op.create_index("ix_automationrunevent_status", "automationrunevent", ["status"], unique=False)
    op.create_index("ix_automationrunevent_created_at", "automationrunevent", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("automationrunevent")
    op.drop_table("publishjob")
    op.drop_table("publishconnection")
    op.drop_table("projectactivityevent")
    op.drop_table("projectapprovalrequest")
    op.drop_table("projectcomment")
    op.drop_table("projectmembership")
    op.drop_table("rolemapping")
    op.drop_table("scimidentity")
    op.drop_table("scimtoken")
    op.drop_table("ssoconnection")
