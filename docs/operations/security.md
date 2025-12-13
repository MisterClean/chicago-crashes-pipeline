---
title: Security Best Practices
sidebar_position: 4
description: Security considerations for production deployments
---

# Security Best Practices

This guide covers security considerations when deploying the Chicago Crash Data Pipeline in production environments.

## Environment Configuration

### 1. Secure Credentials

**Never use default credentials in production.**

Generate strong, unique passwords for all services:

```bash
# Generate secure passwords
openssl rand -base64 32

# Set in .env file
DB_PASSWORD=<generated-password>
POSTGRES_PASSWORD=<same-as-above>
CHICAGO_API_TOKEN=<your-api-token>
```

**Update docker-compose.yml** to use environment variables:

```yaml
postgres:
  environment:
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}  # From .env
    # Remove: POSTGRES_HOST_AUTH_METHOD: trust
```

**Best Practices:**
- Use different passwords for each environment (dev, staging, production)
- Store production credentials in a secrets manager (AWS Secrets Manager, HashiCorp Vault, etc.)
- Rotate passwords every 90 days
- Never commit `.env` files to version control
- Use strong passwords: 32+ characters, alphanumeric + symbols

### 2. CORS Configuration

Configure allowed origins explicitly in production:

```bash
# .env
CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

**Never use wildcards in production:**

```python
# BAD - Security vulnerability
allow_origins=["*"]
allow_credentials=True

# GOOD - Specific domains
allowed_origins = os.getenv("CORS_ORIGINS", "").split(",")
allow_origins=allowed_origins
allow_credentials=True
```

The application now uses environment-based CORS configuration in [src/api/main.py:82-97](../../src/api/main.py#L82-L97).

### 3. Database Security

**PostgreSQL Hardening:**

1. **Disable trust authentication:**
   ```yaml
   # docker-compose.yml - Remove this line:
   # POSTGRES_HOST_AUTH_METHOD: trust
   ```

2. **Use SSL/TLS connections:**
   ```python
   # Connection string with SSL
   DATABASE_URL=postgresql://user:pass@host:5432/db?sslmode=require
   ```

3. **Restrict network access:**
   ```yaml
   # docker-compose.yml
   postgres:
     networks:
       - backend  # Internal network only
   ```

4. **Configure connection limits:**
   ```yaml
   postgres:
     command: >
       -c max_connections=100
       -c shared_buffers=256MB
       -c effective_cache_size=1GB
   ```

5. **Enable query logging for auditing:**
   ```yaml
   postgres:
     command: >
       -c log_statement=mod
       -c log_duration=on
   ```

### 4. API Security

**Add Authentication to Admin Portal:**

The admin portal has no authentication by default. For production:

```python
# src/api/dependencies.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify API token."""
    token = credentials.credentials
    expected_token = os.getenv("API_TOKEN")

    if not expected_token or token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    return token
```

**Apply to protected routes:**

```python
# src/api/routers/jobs.py
from src.api.dependencies import verify_token

@router.post("/jobs", dependencies=[Depends(verify_token)])
async def create_job(...):
    ...
```

**Alternative authentication methods:**
- OAuth2 with JWT tokens
- API keys in headers
- Session-based authentication
- Integration with identity providers (Auth0, Okta, etc.)

See [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/) for implementation guides.

### 5. Rate Limiting

Implement rate limiting to prevent abuse:

**Option 1: Application-level (slowapi)**

```python
# src/api/main.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@router.get("/sync/status")
@limiter.limit("100/hour")
async def sync_status(request: Request):
    ...
```

**Option 2: Reverse proxy (nginx)**

```nginx
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

server {
    location /api/ {
        limit_req zone=api burst=20 nodelay;
        proxy_pass http://app:8000;
    }
}
```

### 6. HTTPS Configuration

**Always use HTTPS in production.** Run behind a reverse proxy:

**nginx example:**

```nginx
server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Caddy example (automatic HTTPS):**

```
yourdomain.com {
    reverse_proxy localhost:8000
}
```

### 7. Security Headers

Add security headers via reverse proxy or FastAPI middleware:

```python
# src/api/main.py
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware

# Force HTTPS
app.add_middleware(HTTPSRedirectMiddleware)

# Restrict allowed hosts
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["yourdomain.com", "www.yourdomain.com"]
)

# Add security headers
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response
```

## Production Deployment Checklist

Before deploying to production:

### Credentials
- [ ] All default passwords changed
- [ ] Strong, unique passwords generated (`openssl rand -base64 32`)
- [ ] Credentials stored in secrets manager
- [ ] `.env` file excluded from version control
- [ ] Different credentials for each environment

### Network Security
- [ ] HTTPS/TLS enabled
- [ ] Reverse proxy configured (nginx, Caddy, Traefik)
- [ ] Firewall rules restrict database access
- [ ] Docker networks properly isolated
- [ ] CORS configured with specific allowed origins

### Application Security
- [ ] Authentication added to admin portal
- [ ] API rate limiting implemented
- [ ] Security headers configured
- [ ] Trusted host middleware enabled
- [ ] Input validation on all endpoints

### Database Security
- [ ] PostgreSQL `trust` method disabled
- [ ] SSL/TLS for database connections
- [ ] Connection pooling limits configured
- [ ] Query logging enabled for auditing
- [ ] Regular backups configured

### Monitoring & Logging
- [ ] Structured logging enabled
- [ ] Log aggregation configured (ELK, Datadog, etc.)
- [ ] Error tracking (Sentry, Rollbar, etc.)
- [ ] Uptime monitoring
- [ ] Security event alerts

### Dependencies
- [ ] All dependencies updated
- [ ] `pip-audit` and `npm audit` passing
- [ ] Dependabot enabled for automated updates
- [ ] Security advisories subscribed

## Authentication Implementation Guide

### Option 1: API Key Authentication

Simple API key-based authentication:

```python
# src/api/dependencies.py
from fastapi import Header, HTTPException

async def verify_api_key(x_api_key: str = Header(...)):
    """Verify API key from header."""
    expected_key = os.getenv("API_KEY")
    if x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

# Apply to routes
@router.post("/jobs", dependencies=[Depends(verify_api_key)])
async def create_job(...):
    ...
```

Usage:
```bash
curl -H "X-API-Key: your-secret-key" http://localhost:8000/jobs
```

### Option 2: JWT Token Authentication

More secure token-based authentication:

```python
# src/api/auth.py
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# Apply to routes
@router.get("/jobs", dependencies=[Depends(get_current_user)])
async def list_jobs(...):
    ...
```

### Option 3: OAuth2 with External Provider

Integrate with Auth0, Google, GitHub, etc.:

```python
from authlib.integrations.starlette_client import OAuth

oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)
```

## Monitoring & Alerting

### Log Aggregation

Integrate with log aggregation services:

**ELK Stack:**
```python
# src/utils/logging.py
import logging
from pythonjsonlogger import jsonlogger

logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter()
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
```

**Datadog:**
```python
from ddtrace import tracer
from ddtrace.contrib.fastapi import patch

patch()
```

### Security Event Monitoring

Monitor for:
- Failed authentication attempts
- Unusual API access patterns
- Database connection failures
- High error rates
- Slow query performance
- Unauthorized access attempts

**Example alert configuration:**
```yaml
# alertmanager.yml
routes:
  - match:
      severity: critical
    receiver: 'pagerduty'
  - match:
      severity: warning
    receiver: 'email'
```

## Data Protection

### Sensitive Data Handling

The Chicago crash data is public, but implement best practices:

1. **Data masking for PII:**
   ```python
   def mask_sensitive_fields(record):
       if 'license_plate' in record:
           record['license_plate'] = '***' + record['license_plate'][-3:]
       return record
   ```

2. **Encryption at rest:**
   - Use encrypted database volumes
   - Encrypt backups
   - Use AWS KMS, Azure Key Vault, or similar

3. **Encryption in transit:**
   - HTTPS for all API communication
   - SSL/TLS for database connections
   - VPN for admin access

### Compliance

Consider data protection regulations:
- **GDPR** (if serving EU users)
- **CCPA** (if serving California users)
- **HIPAA** (if handling health data)

## Incident Response

### Security Incident Procedure

1. **Detection:** Monitor logs and alerts
2. **Containment:** Isolate affected systems
3. **Investigation:** Analyze logs and determine scope
4. **Remediation:** Patch vulnerabilities, rotate credentials
5. **Recovery:** Restore from backups if needed
6. **Post-mortem:** Document lessons learned

### Security Contacts

- **Vulnerability Reports:** the.michael.mclean@gmail.com
- **Security Policy:** [SECURITY.md](../../SECURITY.md)

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [PostgreSQL Security](https://www.postgresql.org/docs/current/security.html)
- [Docker Security](https://docs.docker.com/engine/security/)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)
