"""add org invites

Revision ID: 2026022602
Revises: 2026022601
Create Date: 2026-02-26 23:50:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2026022602"
down_revision = "2026022601"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orginvite",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False, server_default=sa.text("'viewer'")),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("invited_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("accepted_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["user.id"]),
        sa.UniqueConstraint("token_hash", name="uq_org_invite_token_hash"),
        sa.UniqueConstraint("org_id", "email", "status", name="uq_org_invite_org_email_status"),
    )
    op.create_index("ix_orginvite_id", "orginvite", ["id"], unique=False)
    op.create_index("ix_orginvite_org_id", "orginvite", ["org_id"], unique=False)
    op.create_index("ix_orginvite_email", "orginvite", ["email"], unique=False)
    op.create_index("ix_orginvite_token_hash", "orginvite", ["token_hash"], unique=False)
    op.create_index("ix_orginvite_status", "orginvite", ["status"], unique=False)
    op.create_index("ix_orginvite_invited_by_user_id", "orginvite", ["invited_by_user_id"], unique=False)
    op.create_index("ix_orginvite_accepted_by_user_id", "orginvite", ["accepted_by_user_id"], unique=False)
    op.create_index("ix_orginvite_expires_at", "orginvite", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_table("orginvite")
