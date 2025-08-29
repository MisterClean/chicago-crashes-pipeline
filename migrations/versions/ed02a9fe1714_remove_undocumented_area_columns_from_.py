"""Remove undocumented area columns from vehicles table

Revision ID: ed02a9fe1714
Revises: 82f84f67a0d7
Create Date: 2025-08-28 16:27:38.707415

"""
from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision = 'ed02a9fe1714'
down_revision = '82f84f67a0d7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove undocumented area columns from crash_vehicles table
    op.drop_column('crash_vehicles', 'area_01_i')
    op.drop_column('crash_vehicles', 'area_11_i')
    op.drop_column('crash_vehicles', 'area_12_i')


def downgrade() -> None:
    # Re-add the area columns if needed
    op.add_column('crash_vehicles', sa.Column('area_01_i', sa.String(length=1), nullable=True))
    op.add_column('crash_vehicles', sa.Column('area_11_i', sa.String(length=1), nullable=True))
    op.add_column('crash_vehicles', sa.Column('area_12_i', sa.String(length=1), nullable=True))