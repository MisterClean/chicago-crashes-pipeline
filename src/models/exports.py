"""Durable export queue; artifacts live in object storage, never in the API process."""

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text

from src.models.base import Base


class ExportJob(Base):
    __tablename__ = "export_jobs"

    id = Column(String(36), primary_key=True)
    status = Column(String(16), nullable=False, index=True)
    request = Column(JSON, nullable=False)
    request_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    lease_until = Column(DateTime(timezone=True))
    lease_token = Column(String(36))
    attempts = Column(Integer, nullable=False, default=0)
    object_key = Column(Text)
    filename = Column(Text)
    manifest = Column(JSON)
    error = Column(Text)
