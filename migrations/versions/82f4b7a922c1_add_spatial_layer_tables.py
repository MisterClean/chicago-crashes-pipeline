"""add spatial layer tables

Revision ID: 82f4b7a922c1
Revises: ed02a9fe1714
Create Date: 2025-09-15 21:38:08.582603

"""
from alembic import op
import sqlalchemy as sa
import geoalchemy2
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '82f4b7a922c1'
down_revision = 'ed02a9fe1714'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'spatial_layers',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(length=150), nullable=False, unique=True),
        sa.Column('slug', sa.String(length=160), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('geometry_type', sa.String(length=64), nullable=False),
        sa.Column('srid', sa.Integer(), nullable=False, server_default='4326'),
        sa.Column('feature_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('original_filename', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )

    op.create_table(
        'spatial_layer_features',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('layer_id', sa.Integer(), nullable=False),
        sa.Column('properties', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('geometry', geoalchemy2.types.Geometry(geometry_type='GEOMETRY', srid=4326), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['layer_id'], ['spatial_layers.id'], ondelete='CASCADE'),
    )

    op.create_index('ix_spatial_layer_features_layer_id', 'spatial_layer_features', ['layer_id'])
    op.create_index(
        'ix_spatial_layer_features_geometry',
        'spatial_layer_features',
        ['geometry'],
        postgresql_using='gist'
    )


def downgrade() -> None:
    op.drop_index('ix_spatial_layer_features_geometry', table_name='spatial_layer_features')
    op.drop_index('ix_spatial_layer_features_layer_id', table_name='spatial_layer_features')
    op.drop_table('spatial_layer_features')
    op.drop_table('spatial_layers')
