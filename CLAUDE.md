# Chicago Traffic Crash Data Pipeline - Claude AI Assistant Guide

This document provides essential information for Claude AI to work effectively with the Chicago Traffic Crash Data Pipeline project.

## Quick Start Checklist

Before any work, ensure the environment is ready:

```bash
# 1. Get to project root
cd chicago-crashes-pipeline  # Or: cd $(git rev-parse --show-toplevel)

# 2. Check/start PostgreSQL 
docker ps | grep postgres || (cd docker && docker-compose up -d postgres && sleep 15)

# 3. Activate virtual environment
source venv/bin/activate

# 4. Verify setup
python3 -c "import sys; sys.path.append('src'); from utils.config import settings; print('✓ Ready')"
```

## Common Issues & Quick Fixes

### PostgreSQL Connection Refused
- **Fix**: `cd docker && docker-compose up -d postgres && sleep 15`

### Module Import Errors
- **Fix**: `cd <project-root> && source venv/bin/activate` (run from project root directory)
- **For scripts**: Always add `sys.path.append('src')` before project imports

### F-String Syntax Errors in Bash
- **Fix**: Use `.format()` or simple concatenation instead of complex f-strings in bash commands

## Project Structure

```
src/
├── api/                 # FastAPI application & routers
├── models/              # SQLAlchemy ORM models (crashes.py, jobs.py)
├── etl/                 # Data pipeline (soda_client.py)
├── validators/          # Data sanitization (data_sanitizer.py)
├── services/            # Business logic (job_service.py, database_service.py)
└── utils/               # Config & logging
```

## Key Technologies

- **Python 3.11+** with FastAPI, SQLAlchemy 2.0, PostgreSQL+PostGIS
- **Database**: 4 main tables (crashes, crash_people, crash_vehicles, vision_zero_fatalities)
- **API**: REST endpoints at http://localhost:8000, admin portal at /admin
- **Data Sources**: Chicago Open Data Portal SODA APIs
- **Frontend**: Next.js 15 dashboard at http://localhost:3001 (dev) or http://localhost (production)

## Frontend Development

The public dashboard is built with Next.js 15 (App Router) and lives in `frontend/`.

### Frontend Quick Start
```bash
cd frontend
npm install
npm run dev  # Dashboard at http://localhost:3001/dashboard
```

### Frontend Structure
```
frontend/
├── app/
│   ├── dashboard/
│   │   ├── page.tsx           # Server component (data fetching)
│   │   └── components/        # MetricCards, TrendCharts, CrashMap, FilterPanel
│   ├── layout.tsx             # Root layout with nav
│   └── page.tsx               # Landing page
├── lib/
│   ├── api.ts                 # Backend API client
│   └── mapStyles.ts           # Map configuration
├── Dockerfile                 # Production build
└── package.json
```

### Frontend Technologies
- **Next.js 15**: App Router, Server Components, TypeScript
- **react-map-gl + MapLibre**: Interactive maps (no Mapbox token needed)
- **Recharts**: Trend charts and visualizations
- **Tailwind CSS**: Styling

### Key Frontend Files
- `frontend/lib/api.ts` - API client with SSR-aware URL handling
- `frontend/app/dashboard/page.tsx` - Main dashboard (server component)
- `frontend/app/dashboard/components/CrashMap.tsx` - Interactive map

### Full Stack Docker Deployment
```bash
# Download Chicago basemap (one-time)
./docker/tiles/download-basemap.sh

# Start everything
docker-compose -f docker/docker-compose.fullstack.yml up -d

# Services:
# - http://localhost       - Dashboard (nginx -> frontend)
# - http://localhost/api   - Backend API (nginx -> FastAPI)
# - http://localhost/tiles - Vector tiles (nginx -> Martin)
```

## Essential Patterns

### Database Queries
```python
import sys
sys.path.append('src')
from sqlalchemy import create_engine, text
from utils.config import settings

engine = create_engine(settings.database.url)
with engine.connect() as conn:
    result = conn.execute(text("SELECT COUNT(*) FROM crashes"))
```

### Data Sanitization
```python
from validators.data_sanitizer import DataSanitizer
sanitizer = DataSanitizer()
clean_data = sanitizer.sanitize_crash_record(raw_record)
```

### Configuration Access
```python
from utils.config import settings
print(settings.database.url)
print(settings.api.endpoints['crashes'])
```

## ast-grep for Code Search

Use `sg` for syntax-aware searches instead of grep:

```bash
# Find models
sg run -l python -p 'class $_($Base): $$$' src/models/

# Find API routes  
sg run -l python -p '@router.$_("$_")' src/api/routers/

# Find async functions
sg run -l python -p 'async def $_($_): $$$' src/

# Find config usage
sg run -l python -p 'settings.$_' src/
```

## Data Analysis Setup

For database analysis tasks:
```bash
# Run from project root directory
source venv/bin/activate
docker ps | grep postgres || (cd docker && docker-compose up -d postgres && sleep 15)

python3 -c "
import sys
sys.path.append('src')
from sqlalchemy import create_engine, text
from utils.config import settings
engine = create_engine(settings.database.url)
# Ready for queries
"
```

## API Development

Start the API server:
```bash
cd src && uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Verify it's working:
```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/sync/counts
```

### Spatial Layer Management

- **Purpose**: Upload administrative boundaries (e.g., Senate Districts, Schools) and make them queryable in PostGIS for spatial joins with crash data.
- **Upload via API**:
  ```bash
  # GeoJSON FeatureCollection
  curl -F "name=Zip Districts" \
       -F "file=@data/districts.geojson" \
       http://localhost:8000/spatial/layers

  # Zipped ESRI Shapefile (.shp/.shx/.dbf/.prj required)
  curl -F "name=Zip Districts" \
       -F "file=@data/districts.zip" \
       http://localhost:8000/spatial/layers

  # With label_field to specify display name field
  curl -F "name=Chicago Schools" \
       -F "file=@data/schools.zip" \
       -F "label_field=SCHOOL_NM" \
       http://localhost:8000/spatial/layers
  ```
- **Label Field Configuration**: Each layer can have a `label_field` that specifies which property to use for display names in the location report dropdown. If not set, the system uses heuristics to detect common name fields (`name`, `*_nm`, `desc`, `district`, etc.).
- **Field Preview**: Before uploading, you can preview available fields:
  ```bash
  curl -F "file=@data/schools.zip" \
       http://localhost:8000/spatial/layers/preview-fields
  # Returns: {"fields": [{"name": "SCHOOL_NM", "sample_values": ["Lincoln Elementary"], "suggested": true}], "recommended_field": "SCHOOL_NM"}
  ```
- **Validation**: The service rejects archives missing required shapefile components, disallows path traversal, and converts shapefiles to GeoJSON through `ogr2ogr` before inserting features.
- **Admin Portal**: `/admin` now has a **Spatial Layers** tab to upload, review sample attributes, configure label fields, replace data, or delete layers without leaving the UI. When uploading a file, the portal auto-detects available fields and recommends a label field.
- **Storage**: Layer metadata lives in `spatial_layers` (including `label_field`); individual geometries are stored in `spatial_layer_features` with a GiST index for spatial queries.

## Key Database Tables

- **crashes**: Main crash records (`crash_record_id`, `crash_date`, `latitude`, `longitude`)
- **crash_people**: Person-level data (`person_type`, `age`, `injury_classification`) 
- **crash_vehicles**: Vehicle data (`vehicle_year`, `make`, `model`)
- **vision_zero_fatalities**: Curated fatality records

## Nuclear Reset (If Everything Breaks)

```bash
# Run from project root directory
pkill -f uvicorn || true
cd docker && docker-compose down && docker-compose up -d postgres && sleep 15
cd .. && source venv/bin/activate
python3 -c "import sys; sys.path.append('src'); from utils.config import settings; print('✓ Reset complete')"
```

## Development Guidelines

1. **Always work from project root**: All commands should be run from the repository root directory
2. **Use virtual environment**: `source venv/bin/activate`
3. **Add src to path**: `sys.path.append('src')` in Python scripts
4. **Follow existing patterns**: Check similar code before writing new features
5. **Use structured logging**: `from utils.logging import get_logger`
6. **Handle database connections properly**: Use SQLAlchemy sessions correctly

## Data Engineer Agent

For specialized data pipeline and database tasks, you can work with the **Data Engineer Agent** - a specialized assistant with deep expertise in this specific pipeline.

### Agent Specializations

The Data Engineer Agent excels at:

- **ETL Pipeline Optimization**: Batch sizes, streaming patterns, rate limiting, async performance
- **PostgreSQL/PostGIS Query Tuning**: Index design, spatial queries, EXPLAIN ANALYZE, connection pooling
- **Data Validation & Sanitization**: Field-level cleaning, geographic bounds validation, null handling
- **Job Orchestration**: Scheduling patterns, execution tracking, retry strategies
- **Database Schema Design**: SQLAlchemy models, migrations, relationships, indexes
- **Async Python Patterns**: httpx streaming, asyncio, rate limiting, retry with backoff
- **Spatial Data Operations**: PostGIS geometry, GeoJSON processing, spatial joins

### When to Use the Data Engineer Agent

Invoke the Data Engineer Agent for:

- Adding new data sources to the pipeline
- Debugging data quality issues (invalid coordinates, missing fields, sanitization failures)
- Optimizing slow queries or ETL performance
- Designing database schemas and migrations
- Troubleshooting sync failures (API errors, timeouts, rate limits)
- Creating or modifying job schedules
- Analyzing spatial query performance
- Implementing data transformations

### Agent Knowledge

The agent has deep familiarity with:

- **Architecture Flow**: SODA API → SODAClient → DataSanitizer → DatabaseService → PostGIS
- **Key Services**: SyncService (ETL), JobService (scheduling), DatabaseService (upserts)
- **Database Schema**: crashes, crash_people, crash_vehicles, vision_zero_fatalities
- **Optimization Settings**: 50K batch size, Chicago geographic bounds, rate limits
- **Code Patterns**: Idempotent upserts, async streaming, structured logging
- **File Locations**: All service, model, validator, and ETL code paths

### Example Tasks

```bash
# Optimize ETL performance
"The crash sync is taking too long. Can you optimize it?"

# Debug data quality
"Some crashes have coordinates outside Chicago. Why is this happening?"

# Add new data source
"Add traffic signals data from SODA endpoint abc-123.json"

# Analyze slow query
"This spatial query finding crashes near schools is timing out"

# Create scheduled job
"Create a job that syncs only crashes from the last 7 days, running daily at 2 AM"
```

### Documentation

- **Agent Configuration**: [.claude/agents/data-engineer.md](.claude/agents/data-engineer.md)
- **Usage Examples**: [docs/agents/data-engineer-examples.md](docs/agents/data-engineer-examples.md)

The Data Engineer Agent understands this pipeline's architecture, patterns, and quirks better than a general AI assistant, making it ideal for complex data engineering tasks.

## Code Reviewer Agent

For pull request reviews, security audits, and code quality checks, you can work with the **Code Reviewer Agent** - a specialized assistant focused on maintaining high code standards.

### Agent Specializations

The Code Reviewer Agent excels at:

- **Pull Request Reviews**: Comprehensive reviews checking tests, types, security, performance, architecture
- **Test Coverage Analysis**: Identify untested code paths, suggest pytest fixtures, improve coverage
- **Code Quality Checks**: flake8, mypy, black, isort compliance, type hint validation
- **Security Audits**: SQL injection, XSS, CSRF, secrets in code, OWASP Top 10 vulnerabilities
- **Performance Analysis**: N+1 queries, missing indexes, async patterns, batch processing
- **Documentation Review**: Docstring completeness, type annotations, inline comments

### When to Use the Code Reviewer Agent

Invoke the Code Reviewer Agent for:

- Reviewing pull requests before merge
- Conducting security audits of new features
- Analyzing test coverage gaps
- Identifying performance bottlenecks
- Validating type safety across codebase
- Ensuring code quality standards compliance

### Documentation

- **Agent Configuration**: [.claude/agents/code-reviewer.md](.claude/agents/code-reviewer.md)
- **Usage Examples**: [docs/agents/code-reviewer-examples.md](docs/agents/code-reviewer-examples.md)

## Frontend Developer Agent

For admin portal features and documentation site updates, you can work with the **Frontend Developer Agent** - a specialized assistant for building intuitive user interfaces.

### Agent Specializations

The Frontend Developer Agent excels at:

- **Admin Portal Development**: Vanilla JavaScript + Bootstrap 5, glass-morphism UI, API integration
- **Responsive Design**: Mobile-first layouts, touch-friendly UI, cross-browser compatibility
- **Real-Time Features**: Polling, WebSocket integration, live data streaming
- **Docusaurus Documentation**: React 18, TypeScript, MDX, custom themes
- **Performance Optimization**: Parallel loading, caching, lazy loading, skeleton screens
- **Accessibility**: ARIA labels, keyboard navigation, screen reader support

### When to Use the Frontend Developer Agent

Invoke the Frontend Developer Agent for:

- Adding new features to admin portal (tabs, modals, charts)
- Fixing responsive design issues on mobile/tablet
- Implementing real-time updates (WebSocket, polling)
- Creating new Docusaurus documentation pages
- Optimizing frontend loading performance
- Debugging API integration issues

### Documentation

- **Agent Configuration**: [.claude/agents/frontend-developer.md](.claude/agents/frontend-developer.md)
- **Usage Examples**: [docs/agents/frontend-developer-examples.md](docs/agents/frontend-developer-examples.md)

## Backend Architecture Agent

For API design, service layers, and database optimization, you can work with the **Backend Architecture Agent** - a specialized assistant for scalable backend systems.

### Agent Specializations

The Backend Architecture Agent excels at:

- **API Design**: FastAPI routers, dependency injection, Pydantic models, OpenAPI documentation
- **Service Layer Architecture**: Business logic encapsulation, SOLID principles, clean architecture
- **Database Optimization**: Query tuning, EXPLAIN ANALYZE, indexes, connection pooling
- **Async Python Patterns**: asyncio, streaming, concurrency control, thread pools
- **Spatial Queries**: PostGIS geometry, SRID transformations, spatial indexes
- **Background Tasks**: Job scheduling, async execution, error handling

### When to Use the Backend Architecture Agent

Invoke the Backend Architecture Agent for:

- Designing new API endpoints (Router → Service → Model → Database)
- Optimizing slow database queries with indexes and query rewriting
- Adding background tasks and job scheduling
- Creating database migrations with Alembic
- Implementing async patterns and concurrency control
- Designing service layer for complex business logic
- Reviewing architecture and scalability

### Documentation

- **Agent Configuration**: [.claude/agents/backend-architecture.md](.claude/agents/backend-architecture.md)
- **Usage Examples**: [docs/agents/backend-architecture-examples.md](docs/agents/backend-architecture-examples.md)

## Feature Planning Skill

For complex feature requests requiring structured planning, the **Feature Planning Skill** (`/feature-planning`) provides a systematic workflow to break down requests into actionable implementation plans.

### Skill Capabilities

The Feature Planning Skill provides:

- **Requirements Clarification**: Asks targeted questions about problem domain, users, constraints, and success metrics
- **Codebase Exploration**: Analyzes existing patterns and architecture to inform design decisions
- **Component Identification**: Breaks features into database, backend, frontend, testing, and documentation tasks
- **Implementation Planning**: Creates sequential task lists with file references, descriptions, and dependencies
- **User Review**: Confirms plans before execution to ensure alignment

### When to Use

Invoke `/feature-planning` when:

- Requesting new features ("add user authentication", "build dashboard")
- Asking for enhancements ("improve performance", "add export functionality")
- Describing complex multi-step changes
- Explicitly requesting planning ("plan how to implement X")
- Providing vague requirements that need clarification

### Planning Workflow

1. **Understand Requirements**: Clarifying questions and codebase exploration
2. **Analyze & Design**: Component identification, architecture decisions, dependency checking
3. **Create Plan**: Discrete, sequential tasks with file paths and specific implementation details
4. **Review with User**: Confirmation and adjustments before proceeding
5. **Execute**: Sequential implementation with testing and verification

### Example Usage

```bash
# Request feature planning
"I want to add user authentication to the admin portal"

# The skill will:
# 1. Ask about auth requirements (OAuth, JWT, session-based?)
# 2. Explore existing code patterns in src/api/
# 3. Design auth flow matching project architecture
# 4. Create plan with tasks for models, API endpoints, frontend, tests
# 5. Get your approval before implementation
```

### Best Practices

- **Specific References**: Plans include file paths with line numbers (`src/utils/auth.py:45`)
- **Follow Patterns**: Adheres to existing code patterns from CLAUDE.md and codebase
- **Atomic Tasks**: Each task is focused and independently testable
- **Architectural Thinking**: Considers edge cases, security, performance upfront
- **Clear Communication**: Explains decisions, trade-offs, and assumptions

### Documentation

- **Skill Configuration**: [.claude/skills/feature-planning/SKILL.md](.claude/skills/feature-planning/SKILL.md)
