"""add project model and links

Revision ID: 2024092603
Revises: 2024092602
Create Date: 2024-09-26 00:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2024092603"
down_revision = "2024092602"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    with op.batch_alter_table("mediaasset") as batch:
        batch.add_column(sa.Column("project_id", sa.String(length=36), nullable=True))
        batch.create_index("ix_mediaasset_project_id", ["project_id"], unique=False)

    with op.batch_alter_table("job") as batch:
        batch.add_column(sa.Column("project_id", sa.String(length=36), nullable=True))
        batch.create_index("ix_job_project_id", ["project_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("job") as batch:
        batch.drop_index("ix_job_project_id")
        batch.drop_column("project_id")

    with op.batch_alter_table("mediaasset") as batch:
        batch.drop_index("ix_mediaasset_project_id")
        batch.drop_column("project_id")

    op.drop_table("project")
