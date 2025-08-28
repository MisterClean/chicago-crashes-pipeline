"""FastAPI application for Chicago crash data pipeline monitoring and control."""
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from utils.config import settings
from utils.logging import get_logger, setup_logging
from api.routers import sync, health, validation, spatial
from api.dependencies import sync_state

# Setup logging
setup_logging("api", settings.logging.level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting Chicago Crash Data Pipeline API")
    
    # Initialize database tables
    try:
        from models.base import Base, engine
        logger.info("Creating database tables...")
        Base.metadata.create_all(engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error("Failed to create database tables", error=str(e))
        # Continue startup even if table creation fails
    
    # Initialize startup tasks
    sync_state["started_at"] = datetime.now()
    logger.info("API started successfully", startup_time=datetime.now())
    
    yield
    
    # Cleanup tasks
    logger.info("Shutting down Chicago Crash Data Pipeline API")


# Create FastAPI app
app = FastAPI(
    title="Chicago Crash Data Pipeline",
    description="REST API for monitoring and controlling the Chicago traffic crash data pipeline",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(sync.router)
app.include_router(validation.router)
app.include_router(spatial.router)


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level=settings.logging.level.lower()
    )