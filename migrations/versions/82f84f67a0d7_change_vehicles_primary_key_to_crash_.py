"""Change vehicles primary key to crash_unit_id

Revision ID: 82f84f67a0d7
Revises: aca31dbca7b1
Create Date: 2025-08-28 16:20:46.960351

"""
from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision = '82f84f67a0d7'
down_revision = 'aca31dbca7b1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # First, clear existing data from crash_vehicles to avoid constraint issues
    op.execute("DELETE FROM crash_vehicles")
    
    # Drop the old composite primary key constraint
    op.drop_constraint('pk_crash_vehicles', 'crash_vehicles', type_='primary')
    
    # Change crash_unit_id from regular column to primary key
    op.alter_column('crash_vehicles', 'crash_unit_id',
                   existing_type=sa.String(20),
                   nullable=False)
    
    # Create new primary key
    op.create_primary_key('pk_crash_vehicles', 'crash_vehicles', ['crash_unit_id'])
    
    # Add index for crash_record_id since it's now just a foreign key
    op.create_index('ix_crash_vehicles_crash_record_id', 'crash_vehicles', ['crash_record_id'], unique=False)


def downgrade() -> None:
    # Remove the new index
    op.drop_index('ix_crash_vehicles_crash_record_id', table_name='crash_vehicles')
    
    # Clear data to avoid constraint issues
    op.execute("DELETE FROM crash_vehicles")
    
    # Drop current primary key
    op.drop_constraint('pk_crash_vehicles', 'crash_vehicles', type_='primary')
    
    # Change crash_unit_id back to nullable
    op.alter_column('crash_vehicles', 'crash_unit_id',
                   existing_type=sa.String(20),
                   nullable=True)
    
    # Recreate the old composite primary key
    op.create_primary_key('pk_crash_vehicles', 'crash_vehicles', ['crash_record_id', 'unit_no'])