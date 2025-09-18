---
title: Development Environment
sidebar_position: 1
description: Set up tooling and workflows for contributing to the pipeline.
---

## Requirements

- Python **3.11** (the codebase targets 3.11 locally and in Docker)
- PostgreSQL **15** with PostGIS if running services outside Docker
- Redis **7** (Docker or local)
- Node.js **18+** if you plan to work on the Docusaurus documentation site

## Setup Steps

```bash
git clone https://github.com/MisterClean/chicago-crashes-pipeline.git
cd chicago-crashes-pipeline
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt  # optional, for extra tooling
cp .env.example .env
```

Use `make dev-install` to install the project in editable mode along with base dependencies.

## Project Layout

```
chicago-crashes-pipeline/
├── src/
│   ├── api/                 # FastAPI app, routers, dependencies
│   ├── cli/                 # Command-line entry points
│   ├── etl/                 # SODA client and ingestion helpers
│   ├── models/              # SQLAlchemy models
│   ├── services/            # Business logic (sync, jobs, spatial layers)
│   ├── static/admin/        # Admin portal assets
│   ├── utils/               # Config, logging, helpers
│   └── validators/          # Data sanitisation and validation rules
├── config/config.yaml       # Application configuration defaults
├── docker/                  # Dockerfile, Compose stack, init SQL
├── docs/                    # Docusaurus documentation content
├── tests/                   # Pytest suite
└── Makefile                 # Convenience commands
```

## Useful Make Targets

| Target | Action |
| --- | --- |
| `make test` | Run pytest with coverage report |
| `make lint` | Run flake8 + mypy |
| `make format` | Apply Black and isort |
| `make sync` | Execute a rolling delta sync via CLI |
| `make load-shapefiles` | Import shapefiles listed in `config/config.yaml` |
| `make serve` | Launch the API with auto-reload |

## Code Style

- Format with **Black** (`black src tests`) and **isort** for imports.
- Follow **PEP 8** plus type hints on public functions.
- Prefer dependency injection via FastAPI routers to keep modules testable.
- Use structured logging (`get_logger(__name__)`) with contextual keyword arguments.

## Testing

```bash
# Run full suite
pytest tests -v

# Focus on a single module
pytest tests/api/test_sync_router.py -k "trigger"
```

Integration tests expect a PostgreSQL instance. For isolated runs, leverage pytest fixtures under `tests/conftest.py` that spin up temporary databases using SQLAlchemy.

## Pre-Commit / CI

Set up a pre-commit hook to mirror CI checks:

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

CI pipelines should run `make lint`, `make test`, and the Docusaurus build (`npm run build`) to catch issues early.
