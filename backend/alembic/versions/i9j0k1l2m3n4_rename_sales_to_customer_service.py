"""rename sales role to customer_service

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-08-27
"""
from alembic import op


revision = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET role = 'customer_service' WHERE role = 'sales'")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'sales' WHERE role = 'customer_service'")
