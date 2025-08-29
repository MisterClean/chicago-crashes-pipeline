"""Add missing fields and fix field sizes for people and vehicles tables

Revision ID: aca31dbca7b1
Revises: 2ddf301db7de
Create Date: 2025-08-28 16:16:24.479760

"""
from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision = 'aca31dbca7b1'
down_revision = '2ddf301db7de'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add missing fields to crash_people table
    op.add_column('crash_people', sa.Column('crash_date', sa.DateTime(), nullable=True))
    op.add_column('crash_people', sa.Column('vehicle_id', sa.String(length=20), nullable=True))
    op.add_column('crash_people', sa.Column('driver_action', sa.String(length=100), nullable=True))
    op.add_column('crash_people', sa.Column('driver_vision', sa.String(length=50), nullable=True))
    
    # Extend field sizes in crash_people table
    op.alter_column('crash_people', 'ems_unit', type_=sa.String(50))
    op.alter_column('crash_people', 'drivers_license_class', type_=sa.String(50))
    op.alter_column('crash_people', 'bac_result', type_=sa.String(50))
    
    # Add missing fields to crash_vehicles table
    op.add_column('crash_vehicles', sa.Column('crash_date', sa.DateTime(), nullable=True))
    op.add_column('crash_vehicles', sa.Column('crash_unit_id', sa.String(length=20), nullable=True))
    op.add_column('crash_vehicles', sa.Column('area_01_i', sa.String(length=1), nullable=True))
    op.add_column('crash_vehicles', sa.Column('area_11_i', sa.String(length=1), nullable=True))
    op.add_column('crash_vehicles', sa.Column('area_12_i', sa.String(length=1), nullable=True))
    
    # Extend field sizes in crash_vehicles table
    op.alter_column('crash_vehicles', 'make', type_=sa.String(100))
    op.alter_column('crash_vehicles', 'model', type_=sa.String(100))
    op.alter_column('crash_vehicles', 'vehicle_type', type_=sa.String(100))
    op.alter_column('crash_vehicles', 'travel_direction', type_=sa.String(10))
    
    # Add new indexes
    op.create_index('ix_vehicles_crash_unit_id', 'crash_vehicles', ['crash_unit_id'], unique=False)


def downgrade() -> None:
    # Remove indexes
    op.drop_index('ix_vehicles_crash_unit_id', table_name='crash_vehicles')
    
    # Revert field sizes in crash_vehicles table
    op.alter_column('crash_vehicles', 'travel_direction', type_=sa.String(5))
    op.alter_column('crash_vehicles', 'vehicle_type', type_=sa.String(50))
    op.alter_column('crash_vehicles', 'model', type_=sa.String(50))
    op.alter_column('crash_vehicles', 'make', type_=sa.String(50))
    
    # Remove fields from crash_vehicles table
    op.drop_column('crash_vehicles', 'area_12_i')
    op.drop_column('crash_vehicles', 'area_11_i')
    op.drop_column('crash_vehicles', 'area_01_i')
    op.drop_column('crash_vehicles', 'crash_unit_id')
    op.drop_column('crash_vehicles', 'crash_date')
    
    # Revert field sizes in crash_people table
    op.alter_column('crash_people', 'bac_result', type_=sa.String(20))
    op.alter_column('crash_people', 'drivers_license_class', type_=sa.String(20))
    op.alter_column('crash_people', 'ems_unit', type_=sa.String(20))
    
    # Remove fields from crash_people table
    op.drop_column('crash_people', 'driver_vision')
    op.drop_column('crash_people', 'driver_action')
    op.drop_column('crash_people', 'vehicle_id')
    op.drop_column('crash_people', 'crash_date')