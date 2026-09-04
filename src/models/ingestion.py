"""Committed source watermarks; advanced atomically with publication."""

from sqlalchemy import Column, DateTime, String

from src.models.base import Base


class IngestionCheckpoint(Base):
    __tablename__ = "ingestion_checkpoints"

    endpoint = Column(String(32), primary_key=True)
    source_updated_before = Column(DateTime(timezone=True), nullable=False)
