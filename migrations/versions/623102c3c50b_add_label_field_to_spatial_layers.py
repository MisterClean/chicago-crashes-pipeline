"""add_label_field_to_spatial_layers

Revision ID: 623102c3c50b
Revises: fac198c28722
Create Date: 2026-01-02 20:40:50.850317

"""
from alembic import op
import sqlalchemy as sa
import geoalchemy2
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '623102c3c50b'
down_revision = 'fac198c28722'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if column already exists (idempotent migration)
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('spatial_layers')]

    if 'label_field' not in columns:
        op.add_column(
            'spatial_layers',
            sa.Column('label_field', sa.String(100), nullable=True)
        )


def downgrade() -> None:
    op.drop_column('spatial_layers', 'label_field')