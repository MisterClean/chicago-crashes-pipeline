# Security Policy

## Supported Versions

We release patches for security vulnerabilities for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 1.x.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them via email to: **the.michael.mclean@gmail.com**

You should receive a response within 48 hours. If the issue is confirmed, we will:
1. Work on a fix and release it as soon as possible
2. Credit you in the security advisory (unless you prefer to remain anonymous)
3. Publish a security advisory on GitHub

## Security Best Practices

When deploying this application:

### 1. Never Use Default Credentials in Production

```bash
# BAD - Default credentials
POSTGRES_PASSWORD=postgres
DB_PASSWORD=postgres

# GOOD - Strong, unique passwords
POSTGRES_PASSWORD=$(openssl rand -base64 32)
DB_PASSWORD=$(openssl rand -base64 32)
```

Change all default passwords in:
- `docker-compose.yml` (use environment variables)
- `.env` file (never commit this to git)
- Database connection strings

### 2. Configure CORS Properly

```bash
# BAD - Wildcard with credentials
CORS_ORIGINS=*

# GOOD - Specific domains
CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

**Never use `allow_origins=["*"]` with `allow_credentials=True`** - this is a critical security vulnerability.

Review the CORS configuration in [src/api/main.py](src/api/main.py#L82-L97).

### 3. Secure API Tokens

- Store Chicago Data Portal API tokens in environment variables only
- Never commit API tokens to version control
- Rotate tokens periodically
- Use different tokens for different environments

### 4. Database Security

**PostgreSQL Configuration:**
```yaml
# docker-compose.yml
postgres:
  environment:
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}  # From environment
    # REMOVE: POSTGRES_HOST_AUTH_METHOD: trust
```

**Best Practices:**
- Use PostgreSQL authentication (not "trust" method)
- Configure PostgreSQL to only accept connections from trusted hosts
- Keep PostgreSQL and PostGIS updated
- Use SSL/TLS for database connections in production
- Implement connection pooling limits

### 5. Network Security

**Production Deployment:**
- Run behind a reverse proxy (nginx, traefik, Caddy)
- Use HTTPS/TLS for all external communication
- Implement rate limiting at the proxy level
- Use firewall rules to restrict database access
- Enable Docker network isolation

### 6. Environment Variables

**Secure Handling:**
```bash
# Generate strong passwords
openssl rand -base64 32

# Set in environment (not in code)
export POSTGRES_PASSWORD="your-generated-password"
export DB_PASSWORD="your-generated-password"
export CHICAGO_API_TOKEN="your-api-token"
```

**Never:**
- Commit `.env` files to version control
- Log environment variables or connection strings
- Share credentials via email or chat
- Use the same credentials across environments

## Known Security Considerations

### Admin Portal Authentication

**API Key Authentication is now available!** The admin portal and protected API endpoints can be secured using API key authentication.

**To enable API key authentication:**

1. Generate a secure API key:
   ```bash
   openssl rand -base64 32
   ```

2. Set the `API_KEY` environment variable:
   ```bash
   # Railway/Production
   API_KEY=your-generated-key-here

   # Local development (.env file)
   API_KEY=your-generated-key-here
   ```

3. The admin portal will automatically prompt for the API key on first visit
4. The key is stored in the browser session (cleared when tab closes)

**Protected endpoints (require API key when `API_KEY` is set):**
- `/sync/trigger` - Trigger data synchronization
- `/sync/test` - Test data source connectivity
- `/jobs/*` - Job management CRUD operations
- `/spatial/layers` - Spatial layer uploads and management
- `/dashboard/location-report/export` - Data export functionality

**Public endpoints (no authentication required):**
- `/health` - Health check
- `/dashboard/stats` - Dashboard statistics
- `/dashboard/trends/*` - Trend data
- `/dashboard/crashes/geojson` - Crash map data
- `/places/*` - Geographic place data

**Frontend/Server-Side Requests:**
The frontend Next.js application includes the API key in server-side requests automatically when `API_KEY` is set in the environment.

### API Endpoints

API endpoints are protected by API key authentication when the `API_KEY` environment variable is set. For production:
- Set `API_KEY` to a strong, unique value (32+ characters)
- Include `X-API-Key` header in all requests to protected endpoints
- Implement rate limiting at the reverse proxy level
- Log all access attempts (automatic with API key middleware)
- Monitor for suspicious activity (unauthorized access attempts are logged)

### Data Exposure

This application processes public Chicago traffic crash data. However:
- Some fields may contain personally identifiable information (PII)
- Review data before exposing via public APIs
- Implement data masking for sensitive fields
- Comply with data protection regulations (GDPR, CCPA, etc.)

## Dependencies

We monitor dependencies for known vulnerabilities using:

### Python Dependencies
```bash
pip install pip-audit
pip-audit
```

### Node.js Dependencies
```bash
npm audit
npm audit fix  # Apply automatic fixes
```

### Docker Images
We use official images and monitor for security updates:
- `postgis/postgis:15-3.3`
- `redis:7-alpine`
- `python:3.11-slim` (in Dockerfile)

### Automated Updates

**Recommended:**
- Enable Dependabot on GitHub for automated dependency updates
- Review and test security patches promptly
- Subscribe to security advisories for critical dependencies

## Security Checklist for Production

Before deploying to production, verify:

- [ ] All default passwords changed to strong, unique values
- [ ] CORS configured with specific allowed origins (no wildcards)
- [ ] API tokens stored in environment variables only
- [ ] `.env` file excluded from version control (in `.gitignore`)
- [ ] PostgreSQL `trust` authentication method disabled
- [ ] HTTPS/TLS enabled for all external connections
- [ ] Reverse proxy configured with rate limiting
- [ ] Database connections use SSL/TLS
- [ ] **API_KEY set to protect admin portal and sensitive endpoints**
- [ ] Firewall rules restrict database access
- [ ] All dependencies updated to latest secure versions
- [ ] Logging and monitoring enabled
- [ ] Backup strategy implemented
- [ ] Security headers configured (CSP, HSTS, etc.)

## Additional Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [PostgreSQL Security](https://www.postgresql.org/docs/current/security.html)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)

## Contact

For security concerns, contact: **the.michael.mclean@gmail.com**

For general support, open an issue on GitHub.
