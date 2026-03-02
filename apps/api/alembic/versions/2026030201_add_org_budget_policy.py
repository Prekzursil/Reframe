"""add org budget policy

Revision ID: 2026030201
Revises: 2026030101
Create Date: 2026-03-02 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2026030201"
down_revision = "2026030101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orgbudgetpolicy",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("monthly_soft_limit_cents", sa.Integer(), nullable=True),
        sa.Column("monthly_hard_limit_cents", sa.Integer(), nullable=True),
        sa.Column("enforce_hard_limit", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["user.id"]),
        sa.UniqueConstraint("org_id", name="uq_org_budget_policy_org"),
    )
    op.create_index("ix_orgbudgetpolicy_id", "orgbudgetpolicy", ["id"], unique=False)
    op.create_index("ix_orgbudgetpolicy_org_id", "orgbudgetpolicy", ["org_id"], unique=False)
    op.create_index("ix_orgbudgetpolicy_updated_by_user_id", "orgbudgetpolicy", ["updated_by_user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("orgbudgetpolicy")
