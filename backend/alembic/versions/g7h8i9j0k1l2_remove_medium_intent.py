"""remove medium intent classification

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa


revision = "g7h8i9j0k1l2"
down_revision = "f6g7h8i9j0k1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE leads SET intent_level = 'invalid' "
        "WHERE intent_level NOT IN ('high', 'invalid')"
    )
    op.create_check_constraint(
        "ck_leads_intent_level",
        "leads",
        "intent_level IN ('high', 'invalid')",
    )
    op.drop_column("daily_stats", "medium_intent")


def downgrade() -> None:
    op.add_column(
        "daily_stats",
        sa.Column("medium_intent", sa.Integer(), nullable=False, server_default="0"),
    )
    op.drop_constraint("ck_leads_intent_level", "leads", type_="check")
