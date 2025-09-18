---
title: Testing & Quality
sidebar_position: 2
description: Testing strategy, fixtures, and coverage expectations.
---

## Testing Strategy

The project uses [pytest](https://docs.pytest.org/) for unit and integration tests with SQLAlchemy-backed fixtures.

| Layer | Examples | Notes |
| --- | --- | --- |
| Pure functions | Validators, utilities | Aim for deterministic, side-effect free tests |
| Service layer | `SyncService`, `JobService` | Mock external dependencies (SODA API, Redis) using pytest fixtures |
| API routers | FastAPI `TestClient` assertions | Validate status codes, schemas, and background task behaviour |

## Fixtures

Key fixtures live in `tests/conftest.py`:

- `session` / `db_engine` – create isolated in-memory or temporary PostgreSQL databases.
- `test_client` – FastAPI client with dependency overrides for external services.
- `soda_responses` – stubbed SODA API payloads for deterministic sync tests.

Reuse these fixtures to avoid brittle setup code in individual tests.

## Coverage Targets

- Maintain **80%+** line coverage for critical modules (`src/services`, `src/api/routers`, `src/validators`).
- Ensure each new feature includes corresponding tests. For regressions, add tests that fail without the fix.

## Running Tests

```bash
# Base run
pytest tests -v

# With coverage report
pytest tests --cov=src --cov-report=term-missing

# Run a single test case
pytest tests/services/test_job_service.py::test_create_job
```

## Test Data

Large fixtures (crash samples, people, vehicles) reside in `tests/fixtures/`. Keep them small and anonymised. For new datasets, prefer synthesised JSON snippets rather than copying full records.

## Linting & Type Checking

```bash
flake8 src tests
mypy src
```

CI should fail on lint violations or type errors. When type stubs are missing for third-party libraries, annotate `# type: ignore[import]` and leave a TODO to replace with proper typing later.

## Testing the Admin Portal

- Use Playwright or Cypress for end-to-end smoke tests if UI coverage is required.
- For quick manual tests, run `npm install && npm run start` inside the docs site to preview documentation changes alongside the API.

Document notable edge cases uncovered during testing so they can be promoted to automated coverage.
