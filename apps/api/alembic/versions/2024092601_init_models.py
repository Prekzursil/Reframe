"""init models

Revision ID: 2024092601
Revises: 
Create Date: 2024-09-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2024092601"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mediaasset",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("kind", sa.String(length=255), nullable=False),
        sa.Column("uri", sa.String(length=1024), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "job",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("job_type", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("progress", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("input_asset_id", sa.String(length=36), sa.ForeignKey("mediaasset.id"), nullable=True),
        sa.Column("output_asset_id", sa.String(length=36), sa.ForeignKey("mediaasset.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "subtitlestylepreset",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("style", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("subtitlestylepreset")
    op.drop_table("job")
    op.drop_table("mediaasset")
