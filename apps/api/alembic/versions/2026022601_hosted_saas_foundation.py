"""hosted saas foundation

Revision ID: 2026022601
Revises: 2024092603
Create Date: 2026-02-26 20:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2026022601"
down_revision = "2024092603"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("tier", sa.String(length=64), nullable=False, server_default=sa.text("'free'")),
        sa.Column("seat_limit", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_organization_id", "organization", ["id"], unique=False)
    op.create_index("ix_organization_slug", "organization", ["slug"], unique=True)

    op.create_table(
        "user",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_id", "user", ["id"], unique=False)
    op.create_index("ix_user_email", "user", ["email"], unique=True)

    op.create_table(
        "orgmembership",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False, server_default=sa.text("'owner'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.UniqueConstraint("org_id", "user_id", name="uq_org_membership_org_user"),
    )
    op.create_index("ix_orgmembership_id", "orgmembership", ["id"], unique=False)
    op.create_index("ix_orgmembership_org_id", "orgmembership", ["org_id"], unique=False)
    op.create_index("ix_orgmembership_user_id", "orgmembership", ["user_id"], unique=False)

    op.create_table(
        "oauthaccount",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.UniqueConstraint("provider", "provider_subject", name="uq_oauth_provider_subject"),
    )
    op.create_index("ix_oauthaccount_id", "oauthaccount", ["id"], unique=False)
    op.create_index("ix_oauthaccount_user_id", "oauthaccount", ["user_id"], unique=False)
    op.create_index("ix_oauthaccount_provider", "oauthaccount", ["provider"], unique=False)

    op.create_table(
        "plan",
        sa.Column("code", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("max_concurrent_jobs", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("monthly_job_minutes", sa.Integer(), nullable=False, server_default=sa.text("120")),
        sa.Column("monthly_storage_gb", sa.Integer(), nullable=False, server_default=sa.text("2")),
        sa.Column("seat_limit", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("overage_per_minute_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_plan_code", "plan", ["code"], unique=False)

    op.create_table(
        "subscription",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("plan_code", sa.String(length=64), nullable=False, server_default=sa.text("'free'")),
        sa.Column("status", sa.String(length=64), nullable=False, server_default=sa.text("'active'")),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("current_period_start", sa.DateTime(), nullable=True),
        sa.Column("current_period_end", sa.DateTime(), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["plan_code"], ["plan.code"]),
    )
    op.create_index("ix_subscription_id", "subscription", ["id"], unique=False)
    op.create_index("ix_subscription_org_id", "subscription", ["org_id"], unique=True)
    op.create_index("ix_subscription_stripe_customer_id", "subscription", ["stripe_customer_id"], unique=False)
    op.create_index("ix_subscription_stripe_subscription_id", "subscription", ["stripe_subscription_id"], unique=False)

    op.create_table(
        "invoicesnapshot",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), nullable=True),
        sa.Column("stripe_invoice_id", sa.String(length=255), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("currency", sa.String(length=16), nullable=False, server_default=sa.text("'usd'")),
        sa.Column("status", sa.String(length=64), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("period_start", sa.DateTime(), nullable=True),
        sa.Column("period_end", sa.DateTime(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscription.id"]),
    )
    op.create_index("ix_invoicesnapshot_id", "invoicesnapshot", ["id"], unique=False)
    op.create_index("ix_invoicesnapshot_org_id", "invoicesnapshot", ["org_id"], unique=False)
    op.create_index("ix_invoicesnapshot_subscription_id", "invoicesnapshot", ["subscription_id"], unique=False)
    op.create_index("ix_invoicesnapshot_stripe_invoice_id", "invoicesnapshot", ["stripe_invoice_id"], unique=False)

    op.create_table(
        "usageevent",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
    )
    op.create_index("ix_usageevent_id", "usageevent", ["id"], unique=False)
    op.create_index("ix_usageevent_org_id", "usageevent", ["org_id"], unique=False)
    op.create_index("ix_usageevent_user_id", "usageevent", ["user_id"], unique=False)
    op.create_index("ix_usageevent_job_id", "usageevent", ["job_id"], unique=False)
    op.create_index("ix_usageevent_metric", "usageevent", ["metric"], unique=False)

    op.create_table(
        "usageaggregate",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.DateTime(), nullable=False),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.UniqueConstraint("org_id", "metric", "period_start", "period_end", name="uq_usage_aggregate_bucket"),
    )
    op.create_index("ix_usageaggregate_id", "usageaggregate", ["id"], unique=False)
    op.create_index("ix_usageaggregate_org_id", "usageaggregate", ["org_id"], unique=False)
    op.create_index("ix_usageaggregate_metric", "usageaggregate", ["metric"], unique=False)
    op.create_index("ix_usageaggregate_period_start", "usageaggregate", ["period_start"], unique=False)
    op.create_index("ix_usageaggregate_period_end", "usageaggregate", ["period_end"], unique=False)

    with op.batch_alter_table("project") as batch:
        batch.add_column(sa.Column("org_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("owner_user_id", sa.String(length=36), nullable=True))
        batch.create_index("ix_project_org_id", ["org_id"], unique=False)
        batch.create_index("ix_project_owner_user_id", ["owner_user_id"], unique=False)

    with op.batch_alter_table("mediaasset") as batch:
        batch.add_column(sa.Column("org_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("owner_user_id", sa.String(length=36), nullable=True))
        batch.create_index("ix_mediaasset_org_id", ["org_id"], unique=False)
        batch.create_index("ix_mediaasset_owner_user_id", ["owner_user_id"], unique=False)

    with op.batch_alter_table("job") as batch:
        batch.add_column(sa.Column("task_id", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("org_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("owner_user_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
        batch.create_index("ix_job_task_id", ["task_id"], unique=False)
        batch.create_index("ix_job_org_id", ["org_id"], unique=False)
        batch.create_index("ix_job_owner_user_id", ["owner_user_id"], unique=False)
        batch.create_index("ix_job_idempotency_key", ["idempotency_key"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("job") as batch:
        batch.drop_index("ix_job_idempotency_key")
        batch.drop_index("ix_job_owner_user_id")
        batch.drop_index("ix_job_org_id")
        batch.drop_index("ix_job_task_id")
        batch.drop_column("idempotency_key")
        batch.drop_column("owner_user_id")
        batch.drop_column("org_id")
        batch.drop_column("task_id")

    with op.batch_alter_table("mediaasset") as batch:
        batch.drop_index("ix_mediaasset_owner_user_id")
        batch.drop_index("ix_mediaasset_org_id")
        batch.drop_column("owner_user_id")
        batch.drop_column("org_id")

    with op.batch_alter_table("project") as batch:
        batch.drop_index("ix_project_owner_user_id")
        batch.drop_index("ix_project_org_id")
        batch.drop_column("owner_user_id")
        batch.drop_column("org_id")

    op.drop_table("usageaggregate")
    op.drop_table("usageevent")
    op.drop_table("invoicesnapshot")
    op.drop_table("subscription")
    op.drop_table("plan")
    op.drop_table("oauthaccount")
    op.drop_table("orgmembership")
    op.drop_table("user")
    op.drop_table("organization")
