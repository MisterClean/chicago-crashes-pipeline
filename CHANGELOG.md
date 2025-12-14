# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial open source release preparation
- Comprehensive Docusaurus documentation site with 20+ guides
- GitHub Actions workflows for CI/CD (tests, linting, security scans, Docker builds)
- Security best practices guide in docs/operations/security.md
- Enhanced testing documentation with mocking patterns and integration test examples
- Configuration validation with security warnings
- Issue and pull request templates for GitHub
- CONTRIBUTING.md with contributor guidelines
- SECURITY.md with vulnerability reporting process
- README badges for build status and code quality

### Changed
- CORS configuration now uses environment variables (no more wildcards by default)
- Docker Compose credentials use environment variables instead of hardcoded values
- README documentation links updated to match actual file structure
- All documentation sanitized to remove user-specific paths
- Enhanced .env.example with comprehensive security warnings and examples

### Security
- Removed hardcoded database credentials from docker-compose.yml
- Fixed wildcard CORS configuration to use specific allowed origins
- Added configuration validation that blocks insecure production deployments
- Enhanced password requirements and security warnings
- Documented security best practices for production deployments

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
