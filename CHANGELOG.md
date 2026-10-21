# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Replace the application backend, ingestion, scheduler, spatial processing, exports and recovery with Rust, DuckDB 2.0.0 and SQLite.
- Retain the Next.js dashboard and embed a safe administration UI with a shared proxy path.
- Consolidate background work into one backend owner and replica, with bounded SQL, queue, source, export and conversion resources.
- Add transactional publication receipts, preserved migration history and paired recovery snapshots.
- Revamp installation, configuration, API, security and contributor documentation for the Rust application.
- Run native tests on Linux/macOS and build the production backend/frontend images without workstation configuration.

### Removed

- Retired Python application, prototype, dependencies, tests and Alembic migrations. Earlier implementations remain in Git history.
- PostGIS/worker/tile-server development stack, generated Docusaurus site and stale application documentation.
- Bundled database files and workstation-specific notes from the publishable source tree.

## [1.0.0] - 2025-01-XX

### Added
- FastAPI REST API with health checks, sync controls, and spatial endpoints
- Admin portal for job orchestration and monitoring (vanilla JavaScript + Bootstrap 5)
- Automated ETL pipeline with batch processing and rate limiting
- Job scheduler with retries and execution history
- PostgreSQL/PostGIS database backend with spatial capabilities
- Data validation and sanitization pipeline
  - Geographic bounds checking for Chicago
  - Date parsing and normalization
  - Unicode handling and whitespace cleanup
- SODAClient for async data fetching from Chicago Open Data Portal
- Support for four primary datasets:
  - Traffic Crashes – Crashes
  - Traffic Crashes – People
  - Traffic Crashes – Vehicles
  - Traffic Crashes – Vision Zero Fatalities
- Spatial layer upload and management
  - GeoJSON and Shapefile support
  - PostGIS spatial queries
  - Admin portal spatial layers tab
- Database migrations with Alembic
- Structured JSON logging with configurable levels
- Docker Compose development environment
- Comprehensive test suite (1,535 lines, 7 test files)
  - pytest with async support
  - Database fixtures
  - API integration tests
  - Data validation tests
- Four specialized Claude AI agents:
  - Data Engineer Agent
  - Code Reviewer Agent
  - Frontend Developer Agent
  - Backend Architecture Agent
- Makefile automation for common tasks
- Command-line interface for ETL operations
- Configuration management with YAML + environment variables
- Connection pooling and bulk insert optimizations
- Progress tracking for long-running syncs
- Error handling with exponential backoff

### Technical Stack
- Python 3.11+
- FastAPI for REST API
- SQLAlchemy 2.0 with async support
- PostgreSQL 15 + PostGIS 3.3
- Redis 7 for caching
- Docker + Docker Compose
- Docusaurus 3 for documentation
- pytest for testing
- black, isort, flake8, mypy for code quality

### Architecture
- Clean separation of concerns (API → Services → Models → Database)
- Async-first implementation for performance
- Idempotent upserts with conflict handling
- Batch processing (50K record batches)
- Rate limiting (1000 requests/hour default)
- Spatial indexing with PostGIS

[Unreleased]: https://github.com/MisterClean/chicago-crashes-pipeline/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/MisterClean/chicago-crashes-pipeline/releases/tag/v1.0.0
