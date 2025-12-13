"""FastAPI application for Chicago crash data pipeline monitoring and control."""
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.dependencies import sync_state
from src.api.routers import health, jobs, spatial, spatial_layers, sync, validation
from src.services.job_scheduler import start_job_scheduler, stop_job_scheduler
from src.utils.config import settings
from src.utils.logging import get_logger, setup_logging

# Setup logging
setup_logging("api", settings.logging.level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting Chicago Crash Data Pipeline API")

    # Initialize database tables
    try:
        # Import models to register all tables with Base.metadata
        from src import models  # noqa: F401 - This imports all models including jobs
        from src.models.base import Base, engine

        logger.info("Creating database tables...")
        Base.metadata.create_all(engine)
        logger.info(
            "Database tables created successfully (including job management tables)"
        )
    except Exception as e:
        logger.error("Failed to create database tables", error=str(e))
        # Continue startup even if table creation fails

    # Initialize startup tasks
    sync_state["started_at"] = datetime.now()

    # Initialize default jobs
    try:
        from src.services.job_service import JobService

        job_service = JobService()
        created_jobs = job_service.initialize_default_jobs()
        if created_jobs:
            logger.info(f"Initialized {len(created_jobs)} default jobs")
    except Exception as e:
        logger.error("Failed to initialize default jobs", error=str(e))

    # Start job scheduler
    try:
        await start_job_scheduler()
        logger.info("Job scheduler started successfully")
    except Exception as e:
        logger.error("Failed to start job scheduler", error=str(e))

    logger.info("API started successfully", startup_time=datetime.now())

    yield

    # Cleanup tasks
    logger.info("Shutting down Chicago Crash Data Pipeline API")

    # Stop job scheduler
    try:
        await stop_job_scheduler()
        logger.info("Job scheduler stopped successfully")
    except Exception as e:
        logger.error("Failed to stop job scheduler", error=str(e))


# Create FastAPI app
app = FastAPI(
    title="Chicago Crash Data Pipeline",
    description="REST API for monitoring and controlling the Chicago traffic crash data pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware - configure allowed origins via environment variable
# For local development, defaults to localhost origins
# For production, set CORS_ORIGINS environment variable to comma-separated list of allowed domains
# WARNING: Never use "*" (wildcard) in production with allow_credentials=True - this is a security vulnerability
allowed_origins = os.getenv(
    "CORS_ORIGINS", "http://localhost:3000,http://localhost:8000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Mount static assets
static_root = os.path.join(os.path.dirname(__file__), "..", "static")

admin_path = os.path.join(static_root, "admin")
app.mount(
    "/admin",
    StaticFiles(directory=admin_path, html=True, check_dir=False),
    name="admin",
)
if not os.path.isdir(admin_path):  # pragma: no cover - warning for missing dev assets
    logger.warning("Admin static assets not found", path=admin_path)

docs_path = os.path.join(static_root, "documentation")
app.mount(
    "/documentation",
    StaticFiles(directory=docs_path, html=True, check_dir=False),
    name="documentation",
)
if not os.path.isdir(docs_path):  # pragma: no cover - warning for missing docs bundle
    logger.warning("Documentation static assets not found", path=docs_path)

# Include routers
app.include_router(health.router)
app.include_router(sync.router)
app.include_router(validation.router)
app.include_router(jobs.router)
app.include_router(spatial.router)
app.include_router(spatial_layers.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level=settings.logging.level.lower(),
    )
