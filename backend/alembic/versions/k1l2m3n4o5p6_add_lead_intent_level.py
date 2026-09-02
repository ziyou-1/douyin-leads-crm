"""add lead intent_level (high/medium tiering by response latency)

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-08-29
"""
from alembic import op
import sqlalchemy as sa


revision = "k1l2m3n4o5p6"
down_revision = "j0k1l2m3n4o5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("intent_level", sa.String(length=20), nullable=False, server_default="high"),
    )
    op.create_check_constraint(
        "ck_leads_intent_level",
        "leads",
        "intent_level IN ('high', 'medium')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_leads_intent_level", "leads", type_="check")
    op.drop_column("leads", "intent_level")
