"""Base model configuration for SQLAlchemy."""
from datetime import datetime
from typing import Any

from importlib import import_module
from pathlib import Path

from sqlalchemy import Column, DateTime, MetaData, create_engine, text
from sqlalchemy.ext.declarative import as_declarative, declared_attr
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

from src.utils.config import settings
from src.utils.logging import get_logger


logger = get_logger(__name__)


def _create_engine_with_fallback():
    url = settings.database.url
    kwargs = {
        "pool_size": getattr(settings.database, "pool_size", 10),
        "max_overflow": getattr(settings.database, "max_overflow", 20),
        "echo": False,
    }

    try:
        engine = create_engine(url, **kwargs)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return engine
    except Exception as exc:  # pragma: no cover - fallback path
        logger.warning("Primary database unavailable, falling back to SQLite", error=str(exc))
        fallback_path = Path("data")
        fallback_path.mkdir(parents=True, exist_ok=True)
        fallback_url = f"sqlite:///{fallback_path / 'chicago_crashes.db'}"
        sqlite_engine = create_engine(
            fallback_url,
            connect_args={"check_same_thread": False},
        )
        return sqlite_engine

# Create engine with connection pooling
engine = _create_engine_with_fallback()

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Define naming convention for constraints
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s", 
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

metadata = MetaData(naming_convention=convention)


@as_declarative(metadata=metadata)
class Base:
    """Base class for all models."""
    
    id: Any
    __name__: str
    
    # Generate table name from class name
    @declared_attr
    def __tablename__(cls) -> str:
        return cls.__name__.lower()


class TimestampMixin:
    """Mixin for created_at and updated_at timestamps."""
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)


def get_db():
    """Dependency for getting database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


try:  # pragma: no cover - executed at import time
    for module_path in (
        "src.models.crashes",
        "src.models.jobs",
        "src.models.spatial",
    ):
        import_module(module_path)
    Base.metadata.create_all(engine)
except Exception as exc:  # pragma: no cover - log but ignore during import
    logger.warning("Metadata initialization failed", error=str(exc))
