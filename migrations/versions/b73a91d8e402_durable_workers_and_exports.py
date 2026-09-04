"""Add durable execution leases, export queue and ingestion watermarks.

Revision ID: b73a91d8e402
Revises: 3fe06b6f51ad
"""

import sqlalchemy as sa
from alembic import op

revision = "b73a91d8e402"
down_revision = "3fe06b6f51ad"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    # Earlier releases created job tables during API startup, outside Alembic.
    # Include their frozen schema here so a fresh migration-only install works.
    if "scheduled_jobs" not in tables:
        op.create_table(
            "scheduled_jobs",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("job_type", sa.String(50), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("config", sa.JSON()),
            sa.Column("recurrence_type", sa.String(50), nullable=False),
            sa.Column("cron_expression", sa.String(100)),
            sa.Column("next_run", sa.DateTime()),
            sa.Column("last_run", sa.DateTime()),
            sa.Column("timeout_minutes", sa.Integer()),
            sa.Column("max_retries", sa.Integer()),
            sa.Column("retry_delay_minutes", sa.Integer()),
            sa.Column("created_by", sa.String(100)),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if "job_executions" not in tables:
        op.create_table(
            "job_executions",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("execution_id", sa.String(128), nullable=False, unique=True),
            sa.Column(
                "job_id",
                sa.BigInteger(),
                sa.ForeignKey("scheduled_jobs.id"),
                nullable=False,
            ),
            sa.Column("status", sa.String(50), nullable=False),
            sa.Column("started_at", sa.DateTime()),
            sa.Column("completed_at", sa.DateTime()),
            sa.Column("duration_seconds", sa.Integer()),
            sa.Column("records_processed", sa.Integer()),
            sa.Column("records_inserted", sa.Integer()),
            sa.Column("records_updated", sa.Integer()),
            sa.Column("records_skipped", sa.Integer()),
            sa.Column("error_message", sa.Text()),
            sa.Column("error_details", sa.JSON()),
            sa.Column("retry_count", sa.Integer()),
            sa.Column("execution_context", sa.JSON()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    columns = {c["name"] for c in sa.inspect(bind).get_columns("job_executions")}
    for column in (
        sa.Column("lease_owner", sa.String(128)),
        sa.Column("lease_expires_at", sa.DateTime()),
        sa.Column("available_at", sa.DateTime()),
    ):
        if column.name not in columns:
            op.add_column("job_executions", column)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_executions_lease_expires_at "
        "ON job_executions (lease_expires_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_executions_available_at "
        "ON job_executions (available_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_executions_job_status "
        "ON job_executions (job_id, status)"
    )

    if "ingestion_checkpoints" not in tables:
        op.create_table(
            "ingestion_checkpoints",
            sa.Column("endpoint", sa.String(32), primary_key=True),
            sa.Column(
                "source_updated_before", sa.DateTime(timezone=True), nullable=False
            ),
        )
    if "export_jobs" not in tables:
        op.create_table(
            "export_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("request", sa.JSON(), nullable=False),
            sa.Column("request_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("lease_until", sa.DateTime(timezone=True)),
            sa.Column("lease_token", sa.String(36)),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("object_key", sa.Text()),
            sa.Column("filename", sa.Text()),
            sa.Column("manifest", sa.JSON()),
            sa.Column("error", sa.Text()),
        )
        op.create_index("ix_export_jobs_status", "export_jobs", ["status"])
        op.create_index("ix_export_jobs_expires_at", "export_jobs", ["expires_at"])


def downgrade() -> None:
    op.drop_table("export_jobs")
    op.drop_table("ingestion_checkpoints")
    op.drop_index("ix_job_executions_lease_expires_at", table_name="job_executions")
    op.drop_index("ix_job_executions_available_at", table_name="job_executions")
    op.drop_column("job_executions", "lease_owner")
    op.drop_column("job_executions", "lease_expires_at")
    op.drop_column("job_executions", "available_at")
