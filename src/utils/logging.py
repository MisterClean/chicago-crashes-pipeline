"""Logging configuration for the Chicago crash data pipeline."""
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

import structlog

from .config import settings


def setup_logging(
    service_name: str,
    log_level: Optional[str] = None,
    log_file: Optional[str] = None
) -> None:
    """Configure structured logging for the application.
    
    Args:
        service_name: Name of the service/component
        log_level: Logging level (overrides config)
        log_file: Log file path (overrides config)
    """
    # Use provided values or fall back to settings
    level = log_level or settings.logging.level
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer() if settings.logging.format == "json"
            else structlog.dev.ConsoleRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper())
    )
    
    # Get logger for this service
    logger = logging.getLogger(service_name)
    logger.setLevel(getattr(logging, level.upper()))
    
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper()))
    logger.addHandler(console_handler)
    
    # Add file handler if specified
    if log_file:
        _add_file_handler(logger, log_file, level)


def _add_file_handler(logger: logging.Logger, log_file: str, level: str) -> None:
    """Add rotating file handler to logger.
    
    Args:
        logger: Logger instance
        log_file: Path to log file
        level: Logging level
    """
    # Ensure log directory exists
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=settings.logging.max_bytes,
        backupCount=settings.logging.backup_count
    )
    
    file_handler.setLevel(getattr(logging, level.upper()))
    
    # Set formatter based on config
    if settings.logging.format == "json":
        formatter = logging.Formatter('%(message)s')
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.
    
    Args:
        name: Logger name
        
    Returns:
        Structured logger instance
    """
    return structlog.get_logger(name)