"""S3-compatible artifact storage with explicit export-only configuration."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExportSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EXPORT_", extra="ignore")

    endpoint: str = ""
    bucket: str = ""
    access_key_id: str = ""
    secret_access_key: SecretStr = SecretStr("")
    region: str = "auto"
    lease_seconds: int = Field(180, ge=30)
    timeout_seconds: int = Field(1800, ge=30)
    retention_hours: int = Field(24, ge=1)
    max_attempts: int = Field(3, ge=1, le=10)
    max_pending: int = Field(100, ge=1)
    max_concurrent: int = Field(1, ge=1)
    max_rows: int = Field(5_000_000, ge=1)
    max_bytes: int = Field(2_000_000_000, ge=1024)

    def configured(self) -> bool:
        return bool(
            self.endpoint
            and self.bucket
            and self.access_key_id
            and self.secret_access_key.get_secret_value()
        )


class ObjectStorage:
    def __init__(self, settings: ExportSettings) -> None:
        if not settings.configured():
            raise ValueError("Export object storage is not configured")
        # Optional feature: importing the API must not require the storage SDK.
        import boto3
        from botocore.config import Config

        self.bucket = settings.bucket
        self.client: Any = boto3.client(
            "s3",
            endpoint_url=settings.endpoint,
            region_name=settings.region,
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.secret_access_key.get_secret_value(),
            config=Config(
                signature_version="s3v4",
                connect_timeout=10,
                read_timeout=60,
                retries={"max_attempts": 3},
                s3={"addressing_style": "virtual"},
            ),
        )

    def upload(self, path: Path, key: str, filename: str, sha256: str) -> None:
        self.client.upload_file(
            str(path),
            self.bucket,
            key,
            ExtraArgs={
                "ContentType": "application/zip"
                if filename.endswith(".zip")
                else "text/csv",
                "ContentDisposition": f'attachment; filename="{filename}"',
                "Metadata": {"sha256": sha256},
            },
        )
        metadata = self.client.head_object(Bucket=self.bucket, Key=key)
        if (
            metadata["ContentLength"] != path.stat().st_size
            or metadata.get("Metadata", {}).get("sha256") != sha256
        ):
            raise RuntimeError("Uploaded export verification failed")

    def signed_download(self, key: str, *, expires_seconds: int = 300) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def cleanup_orphans(
        self, before: datetime, retain_key: Callable[[str], bool]
    ) -> int:
        """Bounded-memory sweep also removes artifacts orphaned by killed workers."""
        removed = 0
        pages = self.client.get_paginator("list_objects_v2")
        for page in pages.paginate(Bucket=self.bucket, Prefix="exports/"):
            for item in page.get("Contents", []):
                if item["LastModified"] < before and not retain_key(item["Key"]):
                    self.delete(item["Key"])
                    removed += 1
        return removed
