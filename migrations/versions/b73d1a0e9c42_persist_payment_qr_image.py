"""Persist the official PayWay PNG data URI for resuming existing payments.

Revision ID: b73d1a0e9c42
Revises: 800ccaedef30
"""
from alembic import op
import sqlalchemy as sa


revision = "b73d1a0e9c42"
down_revision = "800ccaedef30"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payments", sa.Column("qr_image", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("payments", "qr_image")
