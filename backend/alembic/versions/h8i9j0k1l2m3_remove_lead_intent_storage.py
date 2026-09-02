"""remove lead intent storage

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa


revision = "h8i9j0k1l2m3"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    invalid_leads = "SELECT id FROM leads WHERE intent_level = 'invalid'"
    op.execute(f"DELETE FROM chat_messages WHERE lead_id IN ({invalid_leads})")
    op.execute(f"DELETE FROM lead_followups WHERE lead_id IN ({invalid_leads})")
    op.execute(f"DELETE FROM dm_queue WHERE lead_id IN ({invalid_leads})")
    op.execute("DELETE FROM leads WHERE intent_level = 'invalid'")
    op.drop_constraint("ck_leads_intent_level", "leads", type_="check")
    op.drop_column("leads", "intent_level")


def downgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("intent_level", sa.String(length=20), nullable=False, server_default="high"),
    )
    op.create_check_constraint(
        "ck_leads_intent_level",
        "leads",
        "intent_level IN ('high', 'invalid')",
    )
