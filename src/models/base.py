"""Base model configuration for SQLAlchemy with PostGIS support."""
from typing import Any

from geoalchemy2 import Geometry  # noqa: F401 - exported for model modules
from sqlalchemy import Column, DateTime, MetaData, create_engine
from sqlalchemy.ext.declarative import as_declarative, declared_attr
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

from src.utils.config import settings

engine = create_engine(
    settings.database.url,
    pool_size=getattr(settings.database, "pool_size", 10),
    max_overflow=getattr(settings.database, "max_overflow", 20),
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=convention)


@as_declarative(metadata=metadata)
class Base:
    """Base class for all models."""

    id: Any
    __name__: str

    @declared_attr
    def __tablename__(cls) -> str:
        return cls.__name__.lower()


class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


def get_db():
    """Dependency for getting database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
