"""Retain payment renewal lineage and gateway closure evidence.

Revision ID: d42e9f01a673
Revises: b73d1a0e9c42
"""
from alembic import op
import sqlalchemy as sa

revision = "d42e9f01a673"
down_revision = "b73d1a0e9c42"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payments", sa.Column("replaces_payment_id", sa.BigInteger(), nullable=True))
    op.add_column("payments", sa.Column("close_accepted_at", sa.DateTime(), nullable=True))
    op.add_column("payments", sa.Column("closure_verified_at", sa.DateTime(), nullable=True))
    op.create_foreign_key("fk_payments_replaces", "payments", "payments", ["replaces_payment_id"], ["id"])
    op.create_unique_constraint("uq_payments_replaces", "payments", ["replaces_payment_id"])


def downgrade():
    op.drop_constraint("uq_payments_replaces", "payments", type_="unique")
    op.drop_constraint("fk_payments_replaces", "payments", type_="foreignkey")
    op.drop_column("payments", "closure_verified_at")
    op.drop_column("payments", "close_accepted_at")
    op.drop_column("payments", "replaces_payment_id")
