"""add lead round_count and template_id for AI multi-round chat

Revision ID: e6f7g8h9i0j1
Revises: e5f6g7h8i9j0
Create Date: 2026-08-18

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "e6f7g8h9i0j1"
down_revision = "e5f6g7h8i9j0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("round_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "leads",
        sa.Column("template_id", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("leads", "template_id")
    op.drop_column("leads", "round_count")
