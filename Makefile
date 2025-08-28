.PHONY: help install dev-install test lint format clean docker-build docker-up docker-down migrate seed-data

# Default target
help:
	@echo "Available commands:"
	@echo "  install      Install production dependencies"
	@echo "  dev-install  Install development dependencies"
	@echo "  test         Run tests"
	@echo "  lint         Run linting"
	@echo "  format       Format code"
	@echo "  clean        Clean up build artifacts"
	@echo "  docker-build Build Docker containers"
	@echo "  docker-up    Start development environment"
	@echo "  docker-down  Stop development environment"
	@echo "  migrate      Run database migrations"
	@echo "  seed-data    Load initial/sample data"

# Installation
install:
	pip install -r requirements.txt

dev-install:
	pip install -r requirements.txt
	pip install -e .

# Testing and quality
test:
	pytest tests/ -v --cov=src --cov-report=html

lint:
	flake8 src tests
	mypy src

format:
	black src tests
	isort src tests

# Cleanup
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	rm -rf .coverage htmlcov/ .pytest_cache/ .mypy_cache/

# Docker commands
docker-build:
	docker-compose -f docker/docker-compose.yml build

docker-up:
	docker-compose -f docker/docker-compose.yml up -d

docker-down:
	docker-compose -f docker/docker-compose.yml down

# Database commands
migrate:
	alembic upgrade head

migrate-create:
	alembic revision --autogenerate -m "$(MESSAGE)"

# ETL commands
initial-load:
	python -m src.etl.initial_load --start-date $(START_DATE)

sync:
	python -m src.etl.sync

# API commands
serve:
	uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

serve-prod:
	uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --workers 4

# Spatial data
load-shapefiles:
	python -m src.spatial.loader --directory data/shapefiles