FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    libpq-dev \
    libgdal-dev \
    gdal-bin \
    libproj-dev \
    libgeos-dev \
    libspatialindex-dev \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/
COPY migrations/ ./migrations/
COPY alembic.ini .

# Create logs directory
RUN mkdir -p logs

# Expose port
EXPOSE 8000

# Default command
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]