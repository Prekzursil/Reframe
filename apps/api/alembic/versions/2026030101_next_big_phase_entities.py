"""next big phase entities

Revision ID: 2026030101
Revises: 2026022602
Create Date: 2026-03-01 03:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2026030101"
down_revision = "2026022602"
branch_labels = None
depends_on = None

FK_ORGANIZATION_ID = "organization.id"
FK_USER_ID = "user.id"


def upgrade() -> None:
    op.create_table(
        "apikey",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], [FK_ORGANIZATION_ID]),
        sa.ForeignKeyConstraint(["created_by_user_id"], [FK_USER_ID]),
        sa.UniqueConstraint("org_id", "key_hash", name="uq_apikey_org_key_hash"),
    )
    op.create_index("ix_apikey_id", "apikey", ["id"], unique=False)
    op.create_index("ix_apikey_org_id", "apikey", ["org_id"], unique=False)
    op.create_index("ix_apikey_created_by_user_id", "apikey", ["created_by_user_id"], unique=False)
    op.create_index("ix_apikey_key_prefix", "apikey", ["key_prefix"], unique=False)

    op.create_table(
        "auditevent",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=True),
        sa.Column("entity_id", sa.String(length=255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], [FK_ORGANIZATION_ID]),
        sa.ForeignKeyConstraint(["actor_user_id"], [FK_USER_ID]),
    )
    op.create_index("ix_auditevent_id", "auditevent", ["id"], unique=False)
    op.create_index("ix_auditevent_org_id", "auditevent", ["org_id"], unique=False)
    op.create_index("ix_auditevent_actor_user_id", "auditevent", ["actor_user_id"], unique=False)
    op.create_index("ix_auditevent_event_type", "auditevent", ["event_type"], unique=False)
    op.create_index("ix_auditevent_entity_type", "auditevent", ["entity_type"], unique=False)
    op.create_index("ix_auditevent_entity_id", "auditevent", ["entity_id"], unique=False)
    op.create_index("ix_auditevent_created_at", "auditevent", ["created_at"], unique=False)

    op.create_table(
        "workflowtemplate",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("org_id", sa.String(length=36), nullable=True),
        sa.Column("owner_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], [FK_ORGANIZATION_ID]),
        sa.ForeignKeyConstraint(["owner_user_id"], [FK_USER_ID]),
    )
    op.create_index("ix_workflowtemplate_id", "workflowtemplate", ["id"], unique=False)
    op.create_index("ix_workflowtemplate_org_id", "workflowtemplate", ["org_id"], unique=False)
    op.create_index("ix_workflowtemplate_owner_user_id", "workflowtemplate", ["owner_user_id"], unique=False)

    op.create_table(
        "workflowrun",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("template_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("input_asset_id", sa.String(length=36), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("org_id", sa.String(length=36), nullable=True),
        sa.Column("owner_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["workflowtemplate.id"]),
        sa.ForeignKeyConstraint(["input_asset_id"], ["mediaasset.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["org_id"], [FK_ORGANIZATION_ID]),
        sa.ForeignKeyConstraint(["owner_user_id"], [FK_USER_ID]),
    )
    op.create_index("ix_workflowrun_id", "workflowrun", ["id"], unique=False)
    op.create_index("ix_workflowrun_template_id", "workflowrun", ["template_id"], unique=False)
    op.create_index("ix_workflowrun_task_id", "workflowrun", ["task_id"], unique=False)
    op.create_index("ix_workflowrun_status", "workflowrun", ["status"], unique=False)
    op.create_index("ix_workflowrun_org_id", "workflowrun", ["org_id"], unique=False)
    op.create_index("ix_workflowrun_owner_user_id", "workflowrun", ["owner_user_id"], unique=False)

    op.create_table(
        "workflowrunstep",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("step_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["workflowrun.id"]),
        sa.UniqueConstraint("run_id", "order_index", name="uq_workflow_run_step_order"),
    )
    op.create_index("ix_workflowrunstep_id", "workflowrunstep", ["id"], unique=False)
    op.create_index("ix_workflowrunstep_run_id", "workflowrunstep", ["run_id"], unique=False)
    op.create_index("ix_workflowrunstep_order_index", "workflowrunstep", ["order_index"], unique=False)
    op.create_index("ix_workflowrunstep_step_type", "workflowrunstep", ["step_type"], unique=False)
    op.create_index("ix_workflowrunstep_status", "workflowrunstep", ["status"], unique=False)

    op.create_table(
        "usageledgerentry",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False, server_default=sa.text("'count'")),
        sa.Column("quantity", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("estimated_cost_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], [FK_ORGANIZATION_ID]),
        sa.ForeignKeyConstraint(["user_id"], [FK_USER_ID]),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
    )
    op.create_index("ix_usageledgerentry_id", "usageledgerentry", ["id"], unique=False)
    op.create_index("ix_usageledgerentry_org_id", "usageledgerentry", ["org_id"], unique=False)
    op.create_index("ix_usageledgerentry_user_id", "usageledgerentry", ["user_id"], unique=False)
    op.create_index("ix_usageledgerentry_job_id", "usageledgerentry", ["job_id"], unique=False)
    op.create_index("ix_usageledgerentry_metric", "usageledgerentry", ["metric"], unique=False)
    op.create_index("ix_usageledgerentry_created_at", "usageledgerentry", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("usageledgerentry")
    op.drop_table("workflowrunstep")
    op.drop_table("workflowrun")
    op.drop_table("workflowtemplate")
    op.drop_table("auditevent")
    op.drop_table("apikey")
