"""add_sort_type_to_spatial_layers

Revision ID: 3fe06b6f51ad
Revises: 623102c3c50b
Create Date: 2026-01-05 07:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '3fe06b6f51ad'
down_revision = '623102c3c50b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if column already exists (idempotent migration)
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('spatial_layers')]

    if 'sort_type' not in columns:
        op.add_column(
            'spatial_layers',
            sa.Column(
                'sort_type',
                sa.String(20),
                nullable=False,
                server_default='alphabetic'
            )
        )


def downgrade() -> None:
    op.drop_column('spatial_layers', 'sort_type')
