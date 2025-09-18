# Development Guide

This guide covers development setup, coding standards, and contribution guidelines for the Chicago Crash Data Pipeline.

## Development Environment Setup

### Prerequisites

- Python 3.11+ (recommended: 3.13)
- PostgreSQL 15+ with PostGIS extension
- Git
- Make (optional, for convenience commands)

### Quick Start

1. **Clone the repository**
   ```bash
   git clone https://github.com/MisterClean/chicago-crashes-pipeline.git
   cd chicago-crashes-pipeline
   ```

2. **Set up virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up database**
   ```bash
   # Install PostgreSQL and PostGIS
   # Create database and enable PostGIS extension
   createdb chicago_crashes
   psql -d chicago_crashes -c "CREATE EXTENSION postgis;"
   ```

5. **Configure environment**
   ```bash
   cp .env.example .env
   # Update .env with your database credentials or use the provided defaults
   ```

6. **Run tests**
   ```bash
   python -m pytest tests/ -v
   ```

7. **Start development server**
   ```bash
   uvicorn src.api.main:app --reload
   ```

## Project Structure

```
lakeview-crashes/
├── src/                    # Main source code
│   ├── api/               # FastAPI application
│   │   ├── main.py        # App entry point
│   │   ├── routers/       # API route handlers
│   │   └── dependencies/  # Dependency injection
│   ├── models/            # SQLAlchemy models
│   ├── etl/              # Data processing pipeline
│   ├── validators/       # Data validation and sanitization
│   ├── spatial/          # Spatial data handling
│   └── utils/            # Shared utilities
├── tests/                # Test suite
├── config/               # Configuration files
├── data/                # Data storage (gitignored)
├── docs/                # Documentation
└── requirements.txt     # Python dependencies
```

## Development Workflow

### 1. Feature Development

1. **Create feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make changes**
   - Follow coding standards (see below)
   - Add tests for new functionality
   - Update documentation as needed

3. **Run tests**
   ```bash
   python -m pytest tests/ -v
   ```

4. **Commit changes**
   ```bash
   git add .
   git commit -m "feat: your feature description"
   ```

5. **Push and create PR**
   ```bash
   git push origin feature/your-feature-name
   ```

### 2. Bug Fixes

Follow the same process but use `fix/` prefix for branch names and `fix:` for commit messages.

### 3. Testing

Always run the full test suite before committing:

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_soda_client.py -v

# Run with coverage
python -m pytest tests/ --cov=src --cov-report=html
```

## Coding Standards

### Python Style

- **PEP 8**: Follow Python's official style guide
- **Line length**: Maximum 88 characters (Black formatter standard)
- **Imports**: Group imports (standard library, third-party, local)
- **Type hints**: Use type hints for all function parameters and returns

### Naming Conventions

- **Functions/variables**: `snake_case`
- **Classes**: `PascalCase`
- **Constants**: `UPPER_SNAKE_CASE`
- **Files/modules**: `snake_case.py`

### Code Organization

```python
"""Module docstring describing purpose."""
import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import pandas as pd
from sqlalchemy import Column, String

from utils.config import settings
from utils.logging import get_logger

logger = get_logger(__name__)

class DataProcessor:
    """Class for processing crash data."""
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize processor with configuration."""
        self.config = config
    
    async def process_data(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process raw data records.
        
        Args:
            records: List of raw data records
            
        Returns:
            List of processed records
            
        Raises:
            ProcessingError: If processing fails
        """
        # Implementation here
        pass
```

### Documentation Standards

- **Docstrings**: Use Google-style docstrings
- **Comments**: Explain "why", not "what"
- **Type hints**: Always include for public APIs
- **README updates**: Update when adding new features

## Database Guidelines

### Schema Changes

1. **Create migration scripts** using Alembic
2. **Test migrations** on development data
3. **Document changes** in migration comments
4. **Consider backwards compatibility**

### Query Optimization

- **Use indexes** for frequently queried columns
- **Avoid N+1 queries** with proper joins/eager loading
- **Use EXPLAIN ANALYZE** to optimize slow queries
- **Consider spatial indexes** for geographic data

## API Development

### FastAPI Best Practices

- **Use dependency injection** for shared resources
- **Validate input** with Pydantic models
- **Handle errors gracefully** with proper HTTP status codes
- **Document endpoints** with docstrings and examples
- **Use async/await** for I/O operations

### Example Endpoint

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_database_session

router = APIRouter()

class CreateRecordRequest(BaseModel):
    """Request model for creating records."""
    name: str
    value: int

@router.post("/records", response_model=RecordResponse)
async def create_record(
    request: CreateRecordRequest,
    db_session = Depends(get_database_session)
) -> RecordResponse:
    """Create a new record.
    
    Args:
        request: Record creation request
        db_session: Database session
        
    Returns:
        Created record information
        
    Raises:
        HTTPException: If creation fails
    """
    try:
        # Implementation
        pass
    except Exception as e:
        logger.error("Failed to create record", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")
```

## Testing Guidelines

### Test Structure

```python
"""Test module for data processing."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from etl.processor import DataProcessor

class TestDataProcessor:
    """Test data processing functionality."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance for testing."""
        return DataProcessor({"batch_size": 100})
    
    @pytest.mark.asyncio
    async def test_process_valid_data(self, processor):
        """Test processing valid data records."""
        # Test implementation
        pass
    
    @pytest.mark.asyncio  
    async def test_process_invalid_data_raises_error(self, processor):
        """Test that invalid data raises appropriate error."""
        # Test implementation
        pass
```

### Testing Best Practices

- **One assertion per test** when possible
- **Use descriptive test names** that explain what's being tested
- **Mock external dependencies** (databases, APIs, etc.)
- **Test both success and error cases**
- **Use fixtures** for common test setup

## Configuration Management

### Environment-Specific Settings

```yaml
# config/settings.yaml
database:
  host: localhost
  port: 5432
  database: chicago_crashes
  username: ${DB_USERNAME:-postgres}
  password: ${DB_PASSWORD:-}

api:
  token: ${SODA_API_TOKEN:-}
  rate_limit: 1000
```

### Configuration Guidelines

- **Use environment variables** for sensitive data
- **Provide defaults** for development
- **Validate configuration** on startup
- **Document required settings**

## Debugging

### Common Issues

1. **Database connection errors**
   - Check PostgreSQL is running
   - Verify connection credentials
   - Ensure PostGIS extension is installed

2. **Import errors**
   - Check virtual environment is activated
   - Verify all dependencies are installed
   - Check Python path configuration

3. **API errors**
   - Check Chicago Open Data Portal status
   - Verify API endpoints in configuration
   - Check rate limiting settings

### Debug Tools

```python
# Add to any module for debugging
import logging
logging.basicConfig(level=logging.DEBUG)

# Use pdb for interactive debugging  
import pdb; pdb.set_trace()

# Use rich for better print debugging
from rich import print
print(data)
```

## Performance Guidelines

### Database Optimization

- **Batch operations** for large datasets
- **Use connection pooling** for concurrent access
- **Index frequently queried columns**
- **Monitor query performance**

### API Optimization

- **Use async operations** for I/O
- **Implement caching** for expensive operations
- **Monitor response times**
- **Use connection pooling** for external APIs

### Memory Management

- **Process data in chunks** for large datasets
- **Use generators** instead of loading all data
- **Monitor memory usage** during development
- **Clean up resources** properly

## Troubleshooting

### Development Server Issues

```bash
# Check if port is in use
lsof -i :8000

# Clear Python cache
find . -type d -name "__pycache__" -delete

# Reinstall dependencies
pip freeze > temp_requirements.txt
pip uninstall -r temp_requirements.txt -y
pip install -r requirements.txt
```

### Database Issues

```bash
# Check PostgreSQL status
pg_ctl status

# Reset database
dropdb chicago_crashes
createdb chicago_crashes
psql -d chicago_crashes -c "CREATE EXTENSION postgis;"
```

### Testing Issues

```bash
# Clear test cache
python -m pytest --cache-clear

# Run tests with verbose output
python -m pytest tests/ -v -s

# Run specific test
python -m pytest tests/test_soda_client.py::TestSODAClient::test_fetch_records -v
```

## Contributing

### Pull Request Process

1. **Fork the repository**
2. **Create feature branch** from main
3. **Make changes** following coding standards
4. **Add/update tests** for new functionality
5. **Update documentation** as needed
6. **Run full test suite**
7. **Create pull request** with clear description

### Commit Messages

Use conventional commit format:

```
type(scope): description

feat(api): add new endpoint for crash validation
fix(etl): resolve pagination issue in SODA client
docs(readme): update installation instructions
test(validation): add tests for geographic bounds checking
```

### Code Review Guidelines

- **Review for correctness** and edge cases
- **Check test coverage** for new features
- **Verify documentation** is updated
- **Ensure coding standards** are followed
- **Test locally** before approving

## Release Process

1. **Update version** in relevant files
2. **Update CHANGELOG** with release notes
3. **Create release branch** from main
4. **Run full test suite**
5. **Create GitHub release** with tags
6. **Deploy to production** environment

This development guide ensures consistent, high-quality contributions to the Chicago Crash Data Pipeline project.
