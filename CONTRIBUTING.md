# Contributing to Chicago Crash Data Pipeline

Thank you for your interest in contributing! We welcome contributions that improve data quality, stability, and documentation.

## Quick Links

- [Full Contributing Guide](docs/development/contributing.md) - Detailed guidelines and workflow
- [Security Policy](SECURITY.md) - Reporting vulnerabilities
- [Development Setup](docs/getting-started/quickstart.md) - Get started developing

## Quick Start for Contributors

1. **Fork the repository**
   ```bash
   # Click "Fork" on GitHub, then clone your fork
   git clone https://github.com/YOUR-USERNAME/chicago-crashes-pipeline.git
   cd chicago-crashes-pipeline
   ```

2. **Set up development environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   make dev-install
   ```

3. **Start the development stack**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   make docker-up
   make migrate
   ```

4. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   # Or: fix/bug-description, docs/update-readme, etc.
   ```

5. **Make your changes**
   - Follow existing code patterns and style
   - Add tests for new functionality
   - Update documentation as needed

6. **Run tests and linters**
   ```bash
   make test    # Run test suite
   make lint    # Run flake8 and mypy
   make format  # Run black and isort
   ```

7. **Commit your changes**
   ```bash
   git add .
   git commit -m "Add feature: description of changes"
   ```

8. **Push and create a pull request**
   ```bash
   git push origin feature/your-feature-name
   # Then open a PR on GitHub
   ```

## Pull Request Checklist

Before submitting a PR, ensure:

- [ ] Tests pass (`make test`)
- [ ] Linters pass (`make lint`)
- [ ] Code is formatted (`make format`)
- [ ] Documentation updated (if applicable)
- [ ] Commit messages are clear and descriptive
- [ ] PR description explains the change
- [ ] No merge conflicts with main branch

## Development Guidelines

### Code Style

We follow Python best practices:
- **Ruff** for linting and code formatting (88 character line length)
- **mypy** for type checking
- **PEP 8** style guide

Run all formatters and linters:
```bash
make format  # Auto-format code and fix linting issues
make lint    # Check for issues
```

To run checks manually:
```bash
ruff check src tests           # Lint code
ruff format src tests          # Format code
ruff check --fix src tests     # Auto-fix linting issues
mypy src/utils src/etl src/validators  # Type check
```

### Testing

- Write tests for all new functionality
- Use pytest fixtures from `tests/conftest.py`
- Aim for >80% code coverage
- Test both success and error paths

Run tests:
```bash
make test                    # All tests
pytest tests/test_file.py    # Specific file
pytest -v -k test_name       # Specific test
```

### Commit Messages

Write clear, descriptive commit messages:

**Good:**
```
Add validation for crash coordinates

- Check lat/lon are within Chicago bounds
- Add tests for edge cases
- Update documentation
```

**Bad:**
```
fix bug
updated files
changes
```

### Documentation

Update documentation when:
- Adding new features
- Changing APIs or configuration
- Fixing significant bugs
- Modifying deployment processes

Documentation locations:
- User guides: `docs/user-guides/`
- Development: `docs/development/`
- Operations: `docs/operations/`
- API docs: `docs/user-guides/api-reference.md`

## Types of Contributions

### Bug Reports

Found a bug? Open an issue with:
- Clear description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python version, etc.)
- Relevant logs or error messages

### Feature Requests

Have an idea? Open an issue with:
- Description of the feature
- Use case and benefits
- Proposed implementation (if applicable)
- Examples or mockups

### Code Contributions

We welcome:
- Bug fixes
- New features
- Performance improvements
- Test coverage improvements
- Documentation updates
- Code refactoring

### Documentation Contributions

Help improve:
- README and setup guides
- API documentation
- Code comments and docstrings
- Troubleshooting guides
- Architecture diagrams

## Code Review Process

1. **Automated checks run** on all PRs (tests, linting)
2. **Maintainers review** within 3-5 business days
3. **Address feedback** and update PR
4. **Approval and merge** once checks pass and changes are approved

## Getting Help

Need assistance?
- Check [Troubleshooting Guide](docs/operations/troubleshooting.md)
- Review [Documentation](http://localhost:8000/documentation/)
- Open an issue for bugs or feature requests
- Ask questions in pull request comments

## Project Structure

Understanding the codebase:

```
chicago-crashes-pipeline/
├── src/
│   ├── api/          # FastAPI application and routers
│   ├── etl/          # Data extraction and loading
│   ├── models/       # SQLAlchemy database models
│   ├── services/     # Business logic layer
│   ├── validators/   # Data validation and sanitization
│   ├── spatial/      # Geographic data processing
│   └── utils/        # Configuration and logging
├── tests/            # Test suite
├── migrations/       # Alembic database migrations
├── docs/             # Docusaurus documentation
├── docker/           # Docker configuration
└── config/           # Application configuration
```

## Key Technologies

Familiarize yourself with:
- **Python 3.11+** - Primary language
- **FastAPI** - Web framework
- **SQLAlchemy 2.0** - Database ORM
- **PostgreSQL + PostGIS** - Database with spatial extensions
- **pytest** - Testing framework
- **Docker** - Containerization
- **Alembic** - Database migrations

## Running the Full Development Workflow

Complete development cycle:

```bash
# 1. Start services
make docker-up

# 2. Run migrations
make migrate

# 3. Make code changes
# ... edit files ...

# 4. Format code
make format

# 5. Run tests
make test

# 6. Check linting
make lint

# 7. Start API server
make serve

# 8. Test manually
curl http://localhost:8000/health

# 9. Build documentation
cd docs && npm run build

# 10. Clean up
make docker-down
```

## Questions?

For questions or discussions:
- Open an issue for public discussion
- Review existing issues and PRs
- Check the [full contributing guide](docs/development/contributing.md)

Thank you for contributing to the Chicago Crash Data Pipeline!
