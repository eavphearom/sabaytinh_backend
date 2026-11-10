"""Fix stock movement balance constraint

Revision ID: af67540f8dff
Revises: d1fcc90276c4
Create Date: 2026-11-09 18:32:59.307203

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'af67540f8dff'
down_revision = 'd1fcc90276c4'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass


def upgrade():
    op.drop_constraint(
        "chk_stock_movement_balance",
        "stock_movements",
        type_="check"
    )

    op.create_check_constraint(
        "chk_stock_movement_balance",
        "stock_movements",
        """
        (type = 'IN'
         AND qty_after = qty_before + base_qty_change)
        OR
        (type = 'OUT'
         AND qty_after = qty_before - base_qty_change)
        """
    )


def downgrade():
    op.drop_constraint(
        "chk_stock_movement_balance",
        "stock_movements",
        type_="check"
    )

    op.create_check_constraint(
        "chk_stock_movement_balance",
        "stock_movements",
        """
        (type = 'IN'
         AND qty_after = qty_before + qty_change)
        OR
        (type = 'OUT'
         AND qty_after = qty_before - qty_change)
        """
    )

