# Deployment Guide

This guide covers deployment strategies and configurations for the Chicago Crash Data Pipeline in production environments.

## Overview

The Chicago Crash Data Pipeline can be deployed using several methods:

1. **Docker Compose** (Recommended for development/small production)
2. **Kubernetes** (Recommended for large-scale production)
3. **Traditional VM/Server** deployment
4. **Cloud Platform Services** (AWS, Google Cloud, Azure)

## Prerequisites

### System Requirements

- **CPU**: 2+ cores (4+ recommended for production)
- **RAM**: 4GB minimum (8GB+ recommended)
- **Storage**: 100GB+ for data storage (depends on dataset size)
- **Network**: Reliable internet connection for SODA API access

### Software Requirements

- **Docker** 20.10+
- **Docker Compose** 1.29+
- **PostgreSQL** 15+ with PostGIS
- **Python** 3.11+ (if not using Docker)

## Docker Deployment (Recommended)

### 1. Production Docker Compose

Create a production-ready `docker-compose.prod.yml`:

```yaml
version: '3.8'

services:
  db:
    image: postgis/postgis:15-3.3
    restart: unless-stopped
    environment:
      POSTGRES_DB: chicago_crashes
      POSTGRES_USER: ${DB_USERNAME}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USERNAME}"]
      interval: 30s
      timeout: 10s
      retries: 3

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 30s
      timeout: 10s
      retries: 3

  api:
    build: .
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://${DB_USERNAME}:${DB_PASSWORD}@db:5432/chicago_crashes
      - REDIS_URL=redis://redis:6379
      - API_TOKEN=${SODA_API_TOKEN}
      - LOG_LEVEL=INFO
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  nginx:
    image: nginx:alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - api

volumes:
  postgres_data:
  redis_data:
```

### 2. Production Dockerfile

```dockerfile
FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    libpq-dev \
    libgeos-dev \
    libproj-dev \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Create non-root user
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### 3. Environment Configuration

Create `.env` file for production:

```bash
# Database Configuration
DB_USERNAME=crash_user
DB_PASSWORD=secure_password_here
DATABASE_URL=postgresql://crash_user:secure_password_here@db:5432/chicago_crashes

# API Configuration
SODA_API_TOKEN=your_chicago_open_data_token
API_HOST=0.0.0.0
API_PORT=8000

# Security
SECRET_KEY=your_secret_key_here
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Performance
WORKER_COUNT=4
MAX_CONNECTIONS=100
```

### 4. Deployment Commands

```bash
# Build and start services
docker-compose -f docker-compose.prod.yml up -d --build

# Check service status
docker-compose -f docker-compose.prod.yml ps

# View logs
docker-compose -f docker-compose.prod.yml logs -f api

# Run database migrations
docker-compose -f docker-compose.prod.yml exec api alembic upgrade head

# Scale API service
docker-compose -f docker-compose.prod.yml up -d --scale api=3
```

## Kubernetes Deployment

### 1. Namespace and ConfigMap

```yaml
# k8s/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: chicago-crashes

---
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: crash-pipeline-config
  namespace: chicago-crashes
data:
  LOG_LEVEL: "INFO"
  API_HOST: "0.0.0.0"
  API_PORT: "8000"
  WORKER_COUNT: "4"
```

### 2. Database Deployment

```yaml
# k8s/postgres.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: chicago-crashes
spec:
  serviceName: postgres-service
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgis/postgis:15-3.3
        env:
        - name: POSTGRES_DB
          value: "chicago_crashes"
        - name: POSTGRES_USER
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: username
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: password
        ports:
        - containerPort: 5432
        volumeMounts:
        - name: postgres-storage
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: postgres-storage
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 100Gi

---
apiVersion: v1
kind: Service
metadata:
  name: postgres-service
  namespace: chicago-crashes
spec:
  selector:
    app: postgres
  ports:
  - port: 5432
    targetPort: 5432
```

### 3. API Deployment

```yaml
# k8s/api.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: crash-api
  namespace: chicago-crashes
spec:
  replicas: 3
  selector:
    matchLabels:
      app: crash-api
  template:
    metadata:
      labels:
        app: crash-api
    spec:
      containers:
      - name: api
        image: your-registry/chicago-crashes:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: url
        - name: SODA_API_TOKEN
          valueFrom:
            secretKeyRef:
              name: api-secret
              key: token
        envFrom:
        - configMapRef:
            name: crash-pipeline-config
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"

---
apiVersion: v1
kind: Service
metadata:
  name: crash-api-service
  namespace: chicago-crashes
spec:
  selector:
    app: crash-api
  ports:
  - port: 80
    targetPort: 8000
  type: ClusterIP
```

### 4. Ingress Configuration

```yaml
# k8s/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: crash-api-ingress
  namespace: chicago-crashes
  annotations:
    kubernetes.io/ingress.class: nginx
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/rate-limit: "100"
spec:
  tls:
  - hosts:
    - api.yourdomain.com
    secretName: api-tls-secret
  rules:
  - host: api.yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: crash-api-service
            port:
              number: 80
```

## Cloud Platform Deployments

### AWS Deployment

#### Using ECS with Fargate

```yaml
# aws/task-definition.yaml
{
  "family": "chicago-crashes",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "1024",
  "memory": "2048",
  "executionRoleArn": "arn:aws:iam::account:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::account:role/ecsTaskRole",
  "containerDefinitions": [
    {
      "name": "api",
      "image": "your-account.dkr.ecr.region.amazonaws.com/chicago-crashes:latest",
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {
          "name": "LOG_LEVEL",
          "value": "INFO"
        }
      ],
      "secrets": [
        {
          "name": "DATABASE_URL",
          "valueFrom": "arn:aws:ssm:region:account:parameter/chicago-crashes/database-url"
        },
        {
          "name": "SODA_API_TOKEN",
          "valueFrom": "arn:aws:ssm:region:account:parameter/chicago-crashes/api-token"
        }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/chicago-crashes",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      },
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"],
        "interval": 30,
        "timeout": 10,
        "retries": 3,
        "startPeriod": 60
      }
    }
  ]
}
```

#### RDS Database Setup

```bash
# Create RDS PostgreSQL instance with PostGIS
aws rds create-db-instance \
    --db-instance-identifier chicago-crashes-db \
    --db-instance-class db.t3.medium \
    --engine postgres \
    --engine-version 15.4 \
    --allocated-storage 100 \
    --storage-type gp2 \
    --db-name chicago_crashes \
    --master-username crashuser \
    --master-user-password your-secure-password \
    --vpc-security-group-ids sg-xxxxxxxxx \
    --db-subnet-group-name your-db-subnet-group \
    --publicly-accessible false \
    --storage-encrypted

# Install PostGIS extension after creation
psql -h your-rds-endpoint -U crashuser -d chicago_crashes -c "CREATE EXTENSION postgis;"
```

### Google Cloud Platform

#### Using Cloud Run

```yaml
# gcp/cloudrun.yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: chicago-crashes-api
  annotations:
    run.googleapis.com/ingress: all
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/maxScale: "10"
        run.googleapis.com/cpu-throttling: "false"
    spec:
      containerConcurrency: 80
      containers:
      - image: gcr.io/your-project/chicago-crashes:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              key: database-url
              name: db-secret
        - name: SODA_API_TOKEN
          valueFrom:
            secretKeyRef:
              key: api-token
              name: api-secret
        resources:
          limits:
            cpu: "2"
            memory: "4Gi"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
```

## Post-Deployment Verification

### 1. Service Health Checks

After deployment, verify all services are running:

```bash
# Check API health
curl http://localhost:8000/health

# Check database connectivity
curl http://localhost:8000/sync/status

# Verify admin portal
curl http://localhost:8000/admin/
```

### 2. Admin Portal Access

The admin portal is automatically available at:
- **Development**: http://localhost:8000/admin
- **Production**: https://yourdomain.com/admin

**Features available:**
- Job management and scheduling
- Real-time execution monitoring
- Database administration
- System health dashboard

**Security considerations:**
- In production, restrict admin portal access via firewall rules
- Consider implementing authentication for admin portal access
- Use HTTPS for production deployments

### 3. Default Job Initialization

The system automatically creates four default jobs:
- Full Data Refresh (disabled by default)
- Last 30 Days - Crashes (enabled, daily)
- Last 30 Days - People (enabled, daily)  
- Last 6 Months - Fatalities (enabled, weekly)

Monitor job status via the admin portal or API endpoints.

## Security Configuration

### 1. Admin Portal Security

**Development:**
- Admin portal accessible without authentication
- Suitable for local development and testing

**Production Recommendations:**
- Implement reverse proxy with authentication
- Restrict access to admin portal via IP whitelist
- Use HTTPS/TLS encryption
- Regular security audits

### 2. SSL/TLS Setup

```nginx
# nginx.conf
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;

    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req zone=api burst=20 nodelay;
}
```

### 2. Environment Security

```bash
# Production environment variables
export DATABASE_URL="postgresql://user:password@host:5432/dbname"
export SODA_API_TOKEN="your_token_here"
export SECRET_KEY="your_secret_key"
export ALLOWED_HOSTS="yourdomain.com"
export DEBUG="false"
export LOG_LEVEL="INFO"

# File permissions
chmod 600 .env
chmod 700 config/
```

## Monitoring and Logging

### 1. Application Monitoring

```python
# Add to src/api/main.py for monitoring
from prometheus_client import Counter, Histogram, generate_latest
import time

REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint'])
REQUEST_DURATION = Histogram('http_request_duration_seconds', 'HTTP request duration')

@app.middleware("http")
async def monitor_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    
    REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path).inc()
    REQUEST_DURATION.observe(duration)
    
    return response

@app.get("/metrics")
async def get_metrics():
    return Response(generate_latest(), media_type="text/plain")
```

### 2. Log Configuration

```yaml
# docker-compose.prod.yml - Add logging
services:
  api:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### 3. Health Checks

```python
# Enhanced health check endpoint
@app.get("/health")
async def health_check():
    checks = {
        "database": await check_database_health(),
        "soda_api": await check_soda_api_health(),
        "disk_space": check_disk_space(),
        "memory": check_memory_usage()
    }
    
    status = "healthy" if all(checks.values()) else "unhealthy"
    return {
        "status": status,
        "timestamp": datetime.utcnow(),
        "checks": checks
    }
```

## Backup and Recovery

### 1. Database Backup

```bash
# Automated backup script
#!/bin/bash
BACKUP_DIR="/backups"
DB_NAME="chicago_crashes"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup
pg_dump -h localhost -U crashuser -d $DB_NAME | gzip > "$BACKUP_DIR/backup_$DATE.sql.gz"

# Keep only last 7 days of backups
find $BACKUP_DIR -name "backup_*.sql.gz" -mtime +7 -delete

# Upload to S3 (optional)
aws s3 cp "$BACKUP_DIR/backup_$DATE.sql.gz" s3://your-backup-bucket/database/
```

### 2. Application Data Backup

```bash
# Backup configuration and logs
tar -czf "app_backup_$(date +%Y%m%d).tar.gz" config/ logs/ data/shapefiles/
```

## Performance Optimization

### 1. Database Optimization

```sql
-- Create indexes for performance
CREATE INDEX CONCURRENTLY idx_crashes_date ON crashes(crash_date);
CREATE INDEX CONCURRENTLY idx_crashes_location ON crashes USING GIST(geometry);
CREATE INDEX CONCURRENTLY idx_people_crash_id ON people(crash_record_id);
CREATE INDEX CONCURRENTLY idx_vehicles_crash_id ON vehicles(crash_record_id);

-- Update table statistics
ANALYZE crashes;
ANALYZE people;
ANALYZE vehicles;
```

### 2. Application Optimization

```python
# Connection pooling configuration
from sqlalchemy.pool import QueuePool

engine = create_async_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,
    max_overflow=0,
    pool_pre_ping=True,
    pool_recycle=300
)
```

## Troubleshooting

### Common Issues

1. **Database Connection Issues**
   ```bash
   # Check database connectivity
   docker-compose exec api pg_isready -h db -p 5432
   ```

2. **Memory Issues**
   ```bash
   # Monitor memory usage
   docker stats
   
   # Increase memory limits in docker-compose.yml
   deploy:
     resources:
       limits:
         memory: 2G
   ```

3. **Performance Issues**
   ```bash
   # Check database query performance
   docker-compose exec db psql -U crashuser -d chicago_crashes -c "SELECT * FROM pg_stat_activity;"
   ```

### Debugging Production Issues

```bash
# View application logs
docker-compose -f docker-compose.prod.yml logs -f --tail=100 api

# Access container shell
docker-compose -f docker-compose.prod.yml exec api bash

# Check database status
docker-compose -f docker-compose.prod.yml exec db pg_stat_activity

# Monitor resource usage
docker-compose -f docker-compose.prod.yml exec api top
```

This deployment guide provides comprehensive instructions for deploying the Chicago Crash Data Pipeline in various production environments with proper security, monitoring, and maintenance procedures.