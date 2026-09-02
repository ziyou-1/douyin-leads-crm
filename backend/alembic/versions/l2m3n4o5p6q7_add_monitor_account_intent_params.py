"""add monitor_accounts ai_freshness_min and high_intent_min (per-account intent tiering)

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-08-29
"""
from alembic import op
import sqlalchemy as sa


revision = "l2m3n4o5p6q7"
down_revision = "k1l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "monitor_accounts",
        sa.Column("ai_freshness_min", sa.Integer(), nullable=False, server_default="20"),
    )
    op.add_column(
        "monitor_accounts",
        sa.Column("high_intent_min", sa.Integer(), nullable=False, server_default="8"),
    )


def downgrade() -> None:
    op.drop_column("monitor_accounts", "high_intent_min")
    op.drop_column("monitor_accounts", "ai_freshness_min")
