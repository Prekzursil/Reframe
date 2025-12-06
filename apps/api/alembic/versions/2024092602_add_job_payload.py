"""add job payload

Revision ID: 2024092602
Revises: 2024092601
Create Date: 2024-09-26 00:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2024092602"
down_revision = "2024092601"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job",
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("job", "payload")
