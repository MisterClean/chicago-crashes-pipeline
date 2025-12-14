"""restore_geoalchemy_geometry_columns

Revision ID: fac198c28722
Revises: 82f4b7a922c1
Create Date: 2025-09-17 22:06:23.111988

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from geoalchemy2 import types as ga_types


# revision identifiers, used by Alembic.
revision = 'fac198c28722'
down_revision = '82f4b7a922c1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    def is_geometry_column(table_name: str, column_name: str) -> bool:
        """Check if column is already a PostGIS geometry type.

        PostGIS geometry columns appear in information_schema with:
        - data_type = 'USER-DEFINED'
        - udt_name = 'geometry'
        """
        conn = op.get_bind()
        result = conn.execute(text("""
            SELECT data_type, udt_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table
              AND column_name = :column
        """), {"table": table_name, "column": column_name})
        row = result.fetchone()
        if row is None:
            return False
        return row[0] == 'USER-DEFINED' and row[1] == 'geometry'

    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # Crashes geometry back to POINT
    op.execute("DROP INDEX IF EXISTS ix_crashes_geometry")
    op.execute("DROP INDEX IF EXISTS ix_crashes_geometry_gix")
    if not is_geometry_column("crashes", "geometry"):
        op.alter_column(
            "crashes",
            "geometry",
            type_=ga_types.Geometry(geometry_type="POINT", srid=4326),
            postgresql_using=(
                "CASE WHEN geometry IS NULL OR geometry = '' "
                "THEN NULL ELSE ST_SetSRID(ST_GeomFromText(geometry), 4326) END"
            ),
        )
    op.create_index(
        "ix_crashes_geometry_gix",
        "crashes",
        ["geometry"],
        postgresql_using="gist",
    )

    # Vision Zero fatalities geometry back to POINT
    op.execute("DROP INDEX IF EXISTS ix_vision_zero_fatalities_geometry")
    op.execute("DROP INDEX IF EXISTS ix_vision_zero_fatalities_geometry_gix")
    if not is_geometry_column("vision_zero_fatalities", "geometry"):
        op.alter_column(
            "vision_zero_fatalities",
            "geometry",
            type_=ga_types.Geometry(geometry_type="POINT", srid=4326),
            postgresql_using=(
                "CASE WHEN geometry IS NULL OR geometry = '' "
                "THEN NULL ELSE ST_SetSRID(ST_GeomFromText(geometry), 4326) END"
            ),
        )
    op.create_index(
        "ix_vision_zero_fatalities_geometry_gix",
        "vision_zero_fatalities",
        ["geometry"],
        postgresql_using="gist",
    )

    # Spatial layer features geometry + jsonb properties
    op.execute("ALTER TABLE spatial_layer_features DROP COLUMN IF EXISTS geom")
    op.alter_column(
        "spatial_layer_features",
        "properties",
        type_=postgresql.JSONB(),
        postgresql_using="properties::jsonb",
    )
    op.execute("DROP INDEX IF EXISTS ix_spatial_layer_features_geometry_gix")
    if not is_geometry_column("spatial_layer_features", "geometry"):
        op.alter_column(
            "spatial_layer_features",
            "geometry",
            type_=ga_types.Geometry(geometry_type="GEOMETRY", srid=4326),
            postgresql_using="CASE WHEN geometry IS NULL THEN NULL ELSE ST_SetSRID(ST_GeomFromGeoJSON(geometry::text), 4326) END",
        )
    op.create_index(
        "ix_spatial_layer_features_geometry_gix",
        "spatial_layer_features",
        ["geometry"],
        postgresql_using="gist",
    )

    # Replace geometry columns for static boundary tables
    for table in (
        "wards",
        "community_areas",
        "census_tracts",
        "police_beats",
        "house_districts",
        "senate_districts",
    ):
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_geometry")
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_geometry")
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_geometry_gix")
        if not is_geometry_column(table, "geometry"):
            op.alter_column(
                table,
                "geometry",
                type_=ga_types.Geometry(geometry_type="MULTIPOLYGON", srid=4326),
                postgresql_using=(
                    "CASE WHEN geometry IS NULL OR geometry = '' "
                    "THEN NULL ELSE ST_SetSRID(ST_GeomFromText(geometry), 4326) END"
                ),
            )
        op.create_index(
            f"ix_{table}_geometry_gix",
            table,
            ["geometry"],
            postgresql_using="gist",
        )


def downgrade() -> None:
    # Downgrade spatial boundary tables back to text geometries
    for table in (
        "senate_districts",
        "house_districts",
        "police_beats",
        "census_tracts",
        "community_areas",
        "wards",
    ):
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_geometry_gix")
        op.alter_column(
            table,
            "geometry",
            type_=sa.Text(),
            postgresql_using="CASE WHEN geometry IS NULL THEN NULL ELSE ST_AsText(geometry) END",
        )
        op.create_index(f"ix_{table}_geometry", table, ["geometry"])

    # Spatial layer features revert
    op.execute("DROP INDEX IF EXISTS ix_spatial_layer_features_geometry_gix")
    op.alter_column(
        "spatial_layer_features",
        "geometry",
        type_=sa.JSON(),
        postgresql_using="CASE WHEN geometry IS NULL THEN NULL ELSE ST_AsGeoJSON(geometry)::json END",
    )
    op.alter_column(
        "spatial_layer_features",
        "properties",
        type_=sa.JSON(),
        postgresql_using="properties::json",
    )

    # Vision zero fatalities back to varchar + original index
    op.execute("DROP INDEX IF EXISTS ix_vision_zero_fatalities_geometry_gix")
    op.alter_column(
        "vision_zero_fatalities",
        "geometry",
        type_=sa.String(length=100),
        postgresql_using="CASE WHEN geometry IS NULL THEN NULL ELSE ST_AsText(geometry) END",
    )
    op.create_index("ix_vision_zero_fatalities_geometry", "vision_zero_fatalities", ["geometry"])

    # Crashes back to varchar + original index
    op.execute("DROP INDEX IF EXISTS ix_crashes_geometry_gix")
    op.alter_column(
        "crashes",
        "geometry",
        type_=sa.String(length=100),
        postgresql_using="CASE WHEN geometry IS NULL THEN NULL ELSE ST_AsText(geometry) END",
    )
    op.create_index("ix_crashes_geometry", "crashes", ["geometry"])
