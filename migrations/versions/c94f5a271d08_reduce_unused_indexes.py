"""Remove unused coordinate indexes and vacuum frequently updated fact tables.

Revision ID: c94f5a271d08
Revises: b73a91d8e402
"""

from alembic import op

revision = "c94f5a271d08"
down_revision = "b73a91d8e402"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Spatial predicates use the retained geometry GiST index. These standalone
    # B-tree indexes had zero production scans and consumed 85 MiB at rollout.
    with op.get_context().autocommit_block():
        for name in ("ix_crashes_latitude", "ix_crashes_longitude"):
            op.drop_index(
                name, table_name="crashes", if_exists=True, postgresql_concurrently=True
            )
    for table in ("crashes", "crash_people", "crash_vehicles"):
        op.execute(
            f"ALTER TABLE {table} SET ("
            "autovacuum_vacuum_scale_factor = 0.02, "
            "autovacuum_vacuum_threshold = 5000, "
            "autovacuum_analyze_scale_factor = 0.01)"
        )


def downgrade() -> None:
    for table in ("crashes", "crash_people", "crash_vehicles"):
        op.execute(
            f"ALTER TABLE {table} RESET ("
            "autovacuum_vacuum_scale_factor, "
            "autovacuum_vacuum_threshold, "
            "autovacuum_analyze_scale_factor)"
        )
    with op.get_context().autocommit_block():
        for column in ("latitude", "longitude"):
            op.create_index(
                f"ix_crashes_{column}",
                "crashes",
                [column],
                postgresql_concurrently=True,
            )
