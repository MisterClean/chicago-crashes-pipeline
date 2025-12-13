# Frontend Developer Agent - Usage Examples

This document provides real-world examples of using the **Frontend Developer Agent** for the Chicago Traffic Crash Data Pipeline project.

---

## Example 1: Add "Crash Analytics" Tab to Admin Portal

### User Request
> "Can you add a new tab to the admin portal that shows crash statistics by hour of day and day of week?"

### Agent Workflow

**Step 1: Plan the feature**
- New tab in admin portal navigation
- Two chart visualizations (hourly distribution, weekly distribution)
- API endpoint to fetch aggregated data
- Responsive design for mobile/tablet/desktop

**Step 2: Implement HTML structure**

```html
<!-- src/static/admin/index.html -->

<!-- Add to tab navigation (line ~85) -->
<ul class="nav nav-pills modern-tabs" role="tablist">
    <li class="nav-item">
        <button class="nav-link active" data-bs-toggle="tab" data-bs-target="#dashboard">Dashboard</button>
    </li>
    <!-- ... existing tabs ... -->
    <li class="nav-item">
        <button class="nav-link" data-bs-toggle="tab" data-bs-target="#analytics">
            Analytics
        </button>
    </li>
</ul>

<!-- Add to tab content (line ~250) -->
<div class="tab-pane fade" id="analytics" role="tabpanel">
    <div class="surface p-4 mb-4">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h2 class="section-title mb-0">Crash Analytics</h2>
            <button class="btn btn-outline-primary" onclick="loadAnalytics()">
                <i class="bi bi-arrow-clockwise"></i> Refresh
            </button>
        </div>

        <!-- Loading state -->
        <div id="analytics-loading" class="text-center py-5">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            <p class="text-muted mt-3">Loading analytics...</p>
        </div>

        <!-- Content (hidden initially) -->
        <div id="analytics-content" style="display: none;">
            <div class="row">
                <div class="col-lg-6 mb-4">
                    <div class="surface p-3">
                        <h3 class="chart-title">Crashes by Hour of Day</h3>
                        <div id="hourly-chart" class="chart-container"></div>
                    </div>
                </div>
                <div class="col-lg-6 mb-4">
                    <div class="surface p-3">
                        <h3 class="chart-title">Crashes by Day of Week</h3>
                        <div id="weekly-chart" class="chart-container"></div>
                    </div>
                </div>
            </div>

            <div class="surface p-3">
                <h3 class="chart-title">Key Insights</h3>
                <div id="insights-container" class="insights-grid"></div>
            </div>
        </div>
    </div>
</div>
```

**Step 3: Implement JavaScript logic**

```javascript
// src/static/admin/app.js

// Add to global state (line ~15)
let analyticsData = null;
let analyticsLoaded = false;

// Add to event listeners setup (line ~85)
document.querySelector('[data-bs-target="#analytics"]').addEventListener('shown.bs.tab', function() {
    if (!analyticsLoaded) {
        loadAnalytics();
    }
});

// Add analytics functions
async function loadAnalytics() {
    const loadingEl = document.getElementById('analytics-loading');
    const contentEl = document.getElementById('analytics-content');

    try {
        // Show loading state
        loadingEl.style.display = 'block';
        contentEl.style.display = 'none';

        // Fetch analytics data from backend
        const data = await apiRequest('/analytics/crashes/temporal');

        analyticsData = data;
        analyticsLoaded = true;

        // Render charts and insights
        renderHourlyChart(data.hourly_distribution);
        renderWeeklyChart(data.weekly_distribution);
        renderInsights(data.insights);

        // Show content, hide loading
        loadingEl.style.display = 'none';
        contentEl.style.display = 'block';

    } catch (error) {
        console.error('Failed to load analytics:', error);
        showToast('Error', 'Failed to load analytics data', 'danger');
        loadingEl.style.display = 'none';
    }
}

function renderHourlyChart(hourlyData) {
    const container = document.getElementById('hourly-chart');

    // Find peak hour
    const maxCrashes = Math.max(...hourlyData.map(d => d.count));

    const barsHtml = hourlyData.map(hour => {
        const percentage = (hour.count / maxCrashes) * 100;
        return `
            <div class="chart-bar-container">
                <div class="chart-bar-label">${hour.hour}:00</div>
                <div class="chart-bar-wrapper">
                    <div class="chart-bar" style="width: ${percentage}%;" data-count="${hour.count}">
                        <span class="chart-bar-value">${hour.count.toLocaleString()}</span>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = `<div class="horizontal-bar-chart">${barsHtml}</div>`;
}

function renderWeeklyChart(weeklyData) {
    const container = document.getElementById('weekly-chart');

    const daysOfWeek = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    const maxCrashes = Math.max(...weeklyData.map(d => d.count));

    const barsHtml = weeklyData.map((day, index) => {
        const percentage = (day.count / maxCrashes) * 100;
        const dayName = daysOfWeek[index];
        return `
            <div class="chart-bar-container">
                <div class="chart-bar-label">${dayName}</div>
                <div class="chart-bar-wrapper">
                    <div class="chart-bar chart-bar-primary" style="width: ${percentage}%;">
                        <span class="chart-bar-value">${day.count.toLocaleString()}</span>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = `<div class="horizontal-bar-chart">${barsHtml}</div>`;
}

function renderInsights(insights) {
    const container = document.getElementById('insights-container');

    const insightsHtml = insights.map(insight => {
        const iconClass = {
            'peak_hour': 'bi-clock',
            'peak_day': 'bi-calendar-week',
            'quietest_time': 'bi-moon',
            'trend': 'bi-graph-up'
        }[insight.type] || 'bi-info-circle';

        return `
            <div class="insight-card">
                <div class="insight-icon">
                    <i class="bi ${iconClass}"></i>
                </div>
                <div class="insight-content">
                    <h4 class="insight-title">${escapeHtml(insight.title)}</h4>
                    <p class="insight-description">${escapeHtml(insight.description)}</p>
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = insightsHtml;
}
```

**Step 4: Add CSS styling**

```css
/* src/static/admin/styles.css */

/* Analytics tab styling */
.chart-container {
    min-height: 400px;
    padding: 1rem;
}

.chart-title {
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 1.5rem;
}

/* Horizontal bar charts */
.horizontal-bar-chart {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
}

.chart-bar-container {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.chart-bar-label {
    min-width: 80px;
    font-weight: 500;
    color: var(--text-muted);
    font-size: 0.875rem;
}

.chart-bar-wrapper {
    flex: 1;
    background: rgba(0, 0, 0, 0.05);
    border-radius: 8px;
    overflow: hidden;
    height: 32px;
}

.chart-bar {
    height: 100%;
    background: var(--brand-gradient);
    display: flex;
    align-items: center;
    justify-content: flex-end;
    padding-right: 0.75rem;
    transition: width 0.6s ease;
    position: relative;
}

.chart-bar-primary {
    background: linear-gradient(90deg, #4f46e5 0%, #0ea5e9 100%);
}

.chart-bar-value {
    color: white;
    font-weight: 600;
    font-size: 0.75rem;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
}

/* Insights grid */
.insights-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 1.5rem;
    margin-top: 1rem;
}

.insight-card {
    display: flex;
    gap: 1rem;
    padding: 1.5rem;
    background: linear-gradient(135deg, rgba(79, 70, 229, 0.05) 0%, rgba(14, 165, 233, 0.05) 100%);
    border-radius: 12px;
    border: 1px solid rgba(79, 70, 229, 0.1);
}

.insight-icon {
    flex-shrink: 0;
    width: 48px;
    height: 48px;
    border-radius: 12px;
    background: var(--brand-gradient);
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 1.5rem;
}

.insight-content {
    flex: 1;
}

.insight-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 0.5rem;
}

.insight-description {
    font-size: 0.875rem;
    color: var(--text-muted);
    margin: 0;
}

/* Responsive adjustments */
@media (max-width: 992px) {
    .chart-bar-label {
        min-width: 60px;
        font-size: 0.75rem;
    }

    .chart-title {
        font-size: 1.125rem;
    }
}

@media (max-width: 768px) {
    .insights-grid {
        grid-template-columns: 1fr;
    }

    .chart-container {
        min-height: 300px;
    }

    .chart-bar-value {
        font-size: 0.625rem;
    }
}
```

**Step 5: Backend API endpoint (reference for testing)**

```python
# src/api/routers/analytics.py (NEW FILE)
from fastapi import APIRouter, Depends
from sqlalchemy import func, extract
from sqlalchemy.orm import Session
from src.models.crashes import Crash
from src.models.base import get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.get("/crashes/temporal")
async def get_temporal_analytics(db: Session = Depends(get_db)):
    """Get crash analytics by hour of day and day of week."""

    # Hourly distribution
    hourly = db.query(
        extract('hour', Crash.crash_date).label('hour'),
        func.count(Crash.crash_record_id).label('count')
    ).group_by('hour').order_by('hour').all()

    # Weekly distribution
    weekly = db.query(
        extract('dow', Crash.crash_date).label('day'),  # 0=Sunday, 6=Saturday
        func.count(Crash.crash_record_id).label('count')
    ).group_by('day').order_by('day').all()

    # Calculate insights
    peak_hour = max(hourly, key=lambda x: x.count)
    peak_day = max(weekly, key=lambda x: x.count)

    return {
        "hourly_distribution": [{"hour": h.hour, "count": h.count} for h in hourly],
        "weekly_distribution": [{"day": d.day, "count": d.count} for d in weekly],
        "insights": [
            {
                "type": "peak_hour",
                "title": f"Peak Hour: {peak_hour.hour}:00",
                "description": f"{peak_hour.count:,} crashes occur during this hour on average"
            },
            {
                "type": "peak_day",
                "title": f"Peak Day: {['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'][peak_day.day]}",
                "description": f"{peak_day.count:,} crashes occur on this day of the week"
            }
        ]
    }
```

### Expected Outcome

**Result**: New Analytics tab with:
- ✅ Two horizontal bar charts showing temporal patterns
- ✅ Insights cards with key findings
- ✅ Loading state while fetching data
- ✅ Responsive design (mobile/tablet/desktop)
- ✅ XSS protection (escapeHtml on all user content)
- ✅ Error handling with toast notifications

**Screenshots**:
- Desktop: Full-width charts side-by-side
- Tablet: Stacked charts
- Mobile: Single-column layout with smaller fonts

---

## Example 2: Implement WebSocket for Live Execution Updates

### User Request
> "The current polling for job execution logs is inefficient. Can you replace it with WebSockets for real-time streaming?"

### Agent Workflow

**Step 1: Design WebSocket architecture**
- Backend: WebSocket endpoint `/ws/executions/{execution_id}`
- Frontend: WebSocket client with reconnection logic
- Message format: JSON with log entries
- Graceful fallback to polling if WebSocket fails

**Step 2: Implement WebSocket client**

```javascript
// src/static/admin/app.js

class ExecutionLogStream {
    constructor(executionId, onMessage, onError) {
        this.executionId = executionId;
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 2000;  // 2 seconds
        this.onMessage = onMessage;
        this.onError = onError;
        this.intentionallyClosed = false;
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/executions/${this.executionId}`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('[WebSocket] Connected to execution stream');
            this.reconnectAttempts = 0;
            this.updateConnectionStatus('connected');
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleMessage(data);
            } catch (error) {
                console.error('[WebSocket] Failed to parse message:', error);
            }
        };

        this.ws.onerror = (error) => {
            console.error('[WebSocket] Error:', error);
            this.updateConnectionStatus('error');
            if (this.onError) {
                this.onError(error);
            }
        };

        this.ws.onclose = (event) => {
            console.log('[WebSocket] Connection closed:', event.code, event.reason);
            this.updateConnectionStatus('disconnected');

            if (!this.intentionallyClosed && this.reconnectAttempts < this.maxReconnectAttempts) {
                this.reconnect();
            } else if (this.reconnectAttempts >= this.maxReconnectAttempts) {
                console.warn('[WebSocket] Max reconnection attempts reached, falling back to polling');
                this.fallbackToPolling();
            }
        };
    }

    reconnect() {
        this.reconnectAttempts++;
        const delay = this.reconnectDelay * this.reconnectAttempts;

        console.log(`[WebSocket] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

        this.updateConnectionStatus('reconnecting');

        setTimeout(() => {
            this.connect();
        }, delay);
    }

    handleMessage(data) {
        switch (data.type) {
            case 'log':
                this.appendLog(data.log);
                break;
            case 'status':
                this.updateExecutionStatus(data.status);
                break;
            case 'complete':
                this.handleExecutionComplete(data);
                break;
            default:
                console.warn('[WebSocket] Unknown message type:', data.type);
        }

        if (this.onMessage) {
            this.onMessage(data);
        }
    }

    appendLog(logEntry) {
        const logContainer = document.getElementById('execution-log-stream');
        if (!logContainer) return;

        const timestamp = new Date(logEntry.timestamp).toLocaleTimeString('en-US', {
            hour12: false,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            fractionalSecondDigits: 3
        });

        const levelClass = {
            'DEBUG': 'log-debug',
            'INFO': 'log-info',
            'WARNING': 'log-warning',
            'ERROR': 'log-error',
            'CRITICAL': 'log-critical'
        }[logEntry.level] || 'log-info';

        const logHtml = `
            <div class="execution-log-entry ${levelClass}">
                <span class="log-timestamp">${timestamp}</span>
                <span class="log-level">${escapeHtml(logEntry.level)}</span>
                <span class="log-message">${escapeHtml(logEntry.message)}</span>
                ${logEntry.context ? `<span class="log-context">${escapeHtml(JSON.stringify(logEntry.context))}</span>` : ''}
            </div>
        `;

        logContainer.insertAdjacentHTML('beforeend', logHtml);

        // Auto-scroll to bottom
        logContainer.scrollTop = logContainer.scrollHeight;

        // Highlight new entries briefly
        const newEntry = logContainer.lastElementChild;
        newEntry.classList.add('log-entry-new');
        setTimeout(() => newEntry.classList.remove('log-entry-new'), 2000);
    }

    updateExecutionStatus(status) {
        const statusBadge = document.getElementById('execution-status-badge');
        if (!statusBadge) return;

        const statusConfig = {
            'pending': { class: 'bg-secondary', text: 'Pending' },
            'running': { class: 'bg-primary', text: 'Running', icon: '<span class="spinner-border spinner-border-sm me-1"></span>' },
            'completed': { class: 'bg-success', text: 'Completed', icon: '<i class="bi bi-check-circle me-1"></i>' },
            'failed': { class: 'bg-danger', text: 'Failed', icon: '<i class="bi bi-x-circle me-1"></i>' }
        }[status.status] || { class: 'bg-secondary', text: status.status };

        statusBadge.className = `badge ${statusConfig.class}`;
        statusBadge.innerHTML = `${statusConfig.icon || ''}${statusConfig.text}`;

        // Update metrics
        if (status.records_processed) {
            document.getElementById('records-processed').textContent = status.records_processed.toLocaleString();
        }
        if (status.records_inserted) {
            document.getElementById('records-inserted').textContent = status.records_inserted.toLocaleString();
        }
        if (status.records_updated) {
            document.getElementById('records-updated').textContent = status.records_updated.toLocaleString();
        }
    }

    handleExecutionComplete(data) {
        console.log('[WebSocket] Execution completed:', data);
        showToast('Execution Complete', `Job completed with status: ${data.status.status}`,
                  data.status.status === 'completed' ? 'success' : 'danger');

        // Stop polling if was fallback
        stopExecutionPolling();
    }

    updateConnectionStatus(status) {
        const indicator = document.getElementById('ws-connection-indicator');
        if (!indicator) return;

        const statusConfig = {
            'connected': { class: 'text-success', icon: 'bi-circle-fill', text: 'Live' },
            'reconnecting': { class: 'text-warning', icon: 'bi-arrow-repeat', text: 'Reconnecting...' },
            'disconnected': { class: 'text-danger', icon: 'bi-circle', text: 'Disconnected' },
            'error': { class: 'text-danger', icon: 'bi-exclamation-circle', text: 'Error' }
        }[status];

        indicator.className = `connection-indicator ${statusConfig.class}`;
        indicator.innerHTML = `<i class="bi ${statusConfig.icon} me-1"></i>${statusConfig.text}`;
    }

    fallbackToPolling() {
        console.log('[WebSocket] Falling back to polling');
        showToast('Connection Lost', 'Switching to polling for updates', 'warning');

        // Start traditional polling
        startExecutionPolling(this.executionId);
    }

    disconnect() {
        this.intentionallyClosed = true;
        if (this.ws) {
            this.ws.close();
        }
    }
}

// Global WebSocket instance
let executionStream = null;

// Modified function to use WebSocket
function viewExecutionDetails(executionId) {
    // Stop any existing stream
    if (executionStream) {
        executionStream.disconnect();
    }

    // Load execution details
    loadExecutionDetail(executionId);

    // Start WebSocket stream
    executionStream = new ExecutionLogStream(
        executionId,
        (data) => {
            // Optional: Handle additional message types
        },
        (error) => {
            console.error('WebSocket error:', error);
        }
    );
    executionStream.connect();

    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('executionDetailModal'));
    modal.show();

    // Cleanup on modal close
    document.getElementById('executionDetailModal').addEventListener('hidden.bs.modal', function() {
        if (executionStream) {
            executionStream.disconnect();
            executionStream = null;
        }
    }, { once: true });
}
```

**Step 3: Add connection indicator to HTML**

```html
<!-- src/static/admin/index.html -->

<!-- In execution detail modal header -->
<div class="modal-header">
    <h5 class="modal-title">Execution Details</h5>
    <div class="d-flex align-items-center gap-3">
        <span id="ws-connection-indicator" class="connection-indicator">
            <i class="bi bi-circle-fill"></i> Connecting...
        </span>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
    </div>
</div>
```

**Step 4: Add WebSocket-specific styles**

```css
/* src/static/admin/styles.css */

/* Connection indicator */
.connection-indicator {
    display: inline-flex;
    align-items: center;
    font-size: 0.875rem;
    font-weight: 500;
    padding: 0.25rem 0.75rem;
    border-radius: 12px;
    background: rgba(0, 0, 0, 0.05);
}

.connection-indicator i {
    font-size: 0.625rem;
}

/* Log entry animations */
.execution-log-entry {
    transition: background-color 0.3s ease;
}

.log-entry-new {
    background-color: rgba(79, 70, 229, 0.1);
    animation: highlight-fade 2s ease;
}

@keyframes highlight-fade {
    0% {
        background-color: rgba(79, 70, 229, 0.2);
    }
    100% {
        background-color: transparent;
    }
}

/* Log levels with distinct colors */
.log-debug { color: #64748b; }
.log-info { color: #0ea5e9; }
.log-warning { color: #f59e0b; }
.log-error { color: #ef4444; }
.log-critical {
    color: #dc2626;
    font-weight: 600;
    background: rgba(220, 38, 38, 0.1);
}
```

### Expected Outcome

**Result**: Real-time execution log streaming with:
- ✅ WebSocket connection with auto-reconnect
- ✅ Live log appending (no page refresh)
- ✅ Connection status indicator
- ✅ Graceful fallback to polling if WebSocket fails
- ✅ Auto-scroll to latest logs
- ✅ Visual highlight for new log entries
- ✅ Proper cleanup on modal close

**Performance Improvement**:
- Before: HTTP request every 5 seconds (even with no new logs)
- After: Real-time push only when new logs appear
- Bandwidth saved: ~90% reduction

---

## Example 3: Fix Mobile Responsive Issues in Modal Forms

### User Request
> "The job creation modal is unusable on mobile. The form fields are too small and the buttons are cut off."

### Agent Workflow

**Step 1: Identify issues via Chrome DevTools**

```bash
# Use Chrome DevTools Device Emulation
1. Open Chrome DevTools (F12)
2. Toggle device toolbar (Ctrl+Shift+M)
3. Select "iPhone 12 Pro" (390×844)
4. Navigate to admin portal
5. Click "Create Job"
6. Observe issues:
   - Input fields too small (hard to tap)
   - Select dropdowns don't open properly
   - Buttons overflow modal width
   - iOS keyboard covers form fields
```

**Step 2: Fix CSS for mobile**

```css
/* src/static/admin/styles.css */

/* ===== MOBILE RESPONSIVE FIXES ===== */

/* Larger tap targets for mobile (44×44px minimum per iOS HIG) */
@media (max-width: 768px) {
    /* Form inputs */
    .form-control,
    .form-select {
        font-size: 16px;  /* Prevent iOS zoom on focus */
        min-height: 44px;
        padding: 0.75rem;
    }

    .form-label {
        font-size: 0.875rem;
        font-weight: 600;
        margin-bottom: 0.5rem;
    }

    /* Checkboxes and radios */
    .form-check-input {
        width: 24px;
        height: 24px;
        margin-top: 0;
    }

    .form-check-label {
        font-size: 0.875rem;
        padding-left: 0.5rem;
    }

    /* Buttons */
    .btn {
        min-height: 44px;
        font-size: 1rem;
        padding: 0.75rem 1.5rem;
    }

    /* Modal adjustments */
    .modal-dialog {
        margin: 0.5rem;
        max-width: calc(100% - 1rem);
    }

    .modal-body {
        max-height: calc(100vh - 200px);  /* Prevent modal from exceeding viewport */
        overflow-y: auto;
        -webkit-overflow-scrolling: touch;  /* Smooth scrolling on iOS */
    }

    .modal-footer {
        flex-direction: column;  /* Stack buttons vertically */
        gap: 0.5rem;
    }

    .modal-footer .btn {
        width: 100%;  /* Full-width buttons */
        margin: 0;
    }

    /* Action buttons in tables */
    .action-buttons {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }

    .action-buttons .btn {
        width: 100%;
    }
}

/* Small mobile (iPhone SE, etc.) */
@media (max-width: 576px) {
    .modal-title {
        font-size: 1.125rem;
    }

    .form-control,
    .form-select {
        font-size: 14px;  /* Slightly smaller to fit more content */
    }

    /* Reduce modal padding on very small screens */
    .modal-body {
        padding: 1rem;
    }
}

/* Fix iOS-specific issues */
@supports (-webkit-touch-callout: none) {
    /* Fix for iOS safe area (notch) */
    .modal-dialog {
        margin-top: env(safe-area-inset-top, 0.5rem);
        margin-bottom: env(safe-area-inset-bottom, 0.5rem);
    }

    /* Prevent rubber-band scrolling from showing background */
    .modal {
        overscroll-behavior: contain;
    }

    /* Fix for iOS keyboard covering inputs */
    .modal-open .modal {
        padding-bottom: 0 !important;
    }
}
```

**Step 3: Add JavaScript for keyboard handling**

```javascript
// src/static/admin/app.js

// Fix iOS keyboard covering form fields
function setupMobileKeyboardFix() {
    if (!('ontouchstart' in window)) return;  // Only on touch devices

    const modal = document.querySelector('.modal');
    if (!modal) return;

    // When input is focused, scroll it into view
    modal.addEventListener('focus', function(e) {
        if (e.target.matches('input, select, textarea')) {
            setTimeout(() => {
                e.target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center'
                });
            }, 300);  // Wait for keyboard to appear
        }
    }, true);
}

// Call on modal open
document.getElementById('jobModal').addEventListener('shown.bs.modal', function() {
    setupMobileKeyboardFix();
});
```

**Step 4: Improve form UX on mobile**

```html
<!-- src/static/admin/index.html -->

<!-- Before: Small select dropdown -->
<select class="form-select" id="job-type">
    <option value="full_refresh">Full Refresh</option>
    <option value="last_30_days">Last 30 Days</option>
</select>

<!-- After: Larger, more touch-friendly -->
<select class="form-select form-select-lg" id="job-type" aria-label="Job type">
    <option value="" disabled selected>Select job type...</option>
    <option value="full_refresh">Full Refresh</option>
    <option value="last_30_days">Last 30 Days</option>
    <option value="custom">Custom</option>
</select>

<!-- Add input hints for mobile -->
<label for="job-name" class="form-label">
    Job Name
    <span class="text-muted" style="font-weight: 400;">(e.g., "Weekly Sync")</span>
</label>
<input
    type="text"
    class="form-control"
    id="job-name"
    placeholder="Enter job name"
    autocomplete="off"
    autocapitalize="words"
    required
>
```

**Step 5: Testing checklist**

```javascript
// Manual testing checklist
const mobileTestChecklist = [
    '✓ All form inputs are at least 44×44px',
    '✓ Text inputs are 16px font (no iOS zoom)',
    '✓ Buttons are full-width on mobile',
    '✓ Modal doesn\'t exceed viewport height',
    '✓ Keyboard doesn\'t cover active input',
    '✓ Scrolling is smooth (-webkit-overflow-scrolling)',
    '✓ Safe area insets respected (iPhone notch)',
    '✓ All interactive elements have visual hover/active states'
];

// Test on these devices:
const testDevices = [
    'iPhone SE (375×667)',
    'iPhone 12 Pro (390×844)',
    'iPhone 14 Pro Max (430×932)',
    'Samsung Galaxy S21 (360×800)',
    'iPad (768×1024)',
    'iPad Pro 12.9" (1024×1366)'
];
```

### Expected Outcome

**Result**: Mobile-optimized job creation modal with:
- ✅ All tap targets ≥44×44px (iOS Human Interface Guidelines)
- ✅ Font size 16px+ (prevents iOS auto-zoom)
- ✅ Full-width buttons on mobile
- ✅ Modal fits within viewport (no vertical overflow)
- ✅ Keyboard doesn't cover active input fields
- ✅ Smooth scrolling on iOS
- ✅ Proper safe area handling (notch, home indicator)

**Before/After Comparison**:
| Issue | Before | After |
|-------|--------|-------|
| Button width | Fixed 120px (overflow) | 100% width (fits perfectly) |
| Input height | 38px (hard to tap) | 44px (easy to tap) |
| Font size | 14px (iOS zooms) | 16px (no zoom) |
| Keyboard overlap | Covers inputs | Auto-scrolls into view |
| Modal height | Fixed (overflow) | max-height: calc(100vh - 200px) |

---

## Example 4: Add New Docusaurus Page with Interactive Code Examples

### User Request
> "Can you add a new documentation page explaining how to use the spatial layers API with interactive code examples?"

### Agent Workflow

**Step 1: Create markdown file**

```markdown
<!-- docs/user-guides/spatial-layers-api.md -->

---
sidebar_position: 5
---

# Spatial Layers API Guide

Upload and query administrative boundaries for spatial analysis.

## Overview

The Spatial Layers API allows you to:
- Upload GeoJSON or Shapefiles (zipped)
- Store features in PostGIS database
- Query layers for spatial joins with crash data
- Manage layer metadata and lifecycle

## Quick Start

### 1. Upload a GeoJSON Layer

\`\`\`bash
curl -X POST http://localhost:8000/spatial/layers \\
  -F "name=Senate Districts" \\
  -F "description=Illinois Senate District Boundaries" \\
  -F "file=@districts.geojson"
\`\`\`

**Response:**
\`\`\`json
{
  "id": 1,
  "name": "Senate Districts",
  "description": "Illinois Senate District Boundaries",
  "feature_count": 59,
  "created_at": "2024-12-13T10:30:00Z",
  "is_active": true
}
\`\`\`

### 2. Upload a Shapefile

Shapefiles must be zipped with `.shp`, `.shx`, `.dbf`, and `.prj` files.

\`\`\`bash
# Create zip with required files
zip chicago-wards.zip wards.shp wards.shx wards.dbf wards.prj

# Upload
curl -X POST http://localhost:8000/spatial/layers \\
  -F "name=Chicago Wards" \\
  -F "file=@chicago-wards.zip"
\`\`\`

:::tip
Download official Chicago boundaries from [Chicago Open Data Portal](https://data.cityofchicago.org/Facilities-Geographic-Boundaries/Boundaries-Wards-2023-/cpy5-gf85)
:::

### 3. List All Layers

\`\`\`bash
curl http://localhost:8000/spatial/layers
\`\`\`

**Response:**
\`\`\`json
[
  {
    "id": 1,
    "name": "Senate Districts",
    "feature_count": 59,
    "is_active": true
  },
  {
    "id": 2,
    "name": "Chicago Wards",
    "feature_count": 50,
    "is_active": true
  }
]
\`\`\`

### 4. Get Layer Details

\`\`\`bash
curl http://localhost:8000/spatial/layers/1
\`\`\`

**Response includes sample features:**
\`\`\`json
{
  "id": 1,
  "name": "Senate Districts",
  "feature_count": 59,
  "sample_features": [
    {
      "properties": {
        "district": "01",
        "name": "First District"
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[-87.6298, 41.8781], ...]]
      }
    }
  ]
}
\`\`\`

## Advanced Usage

### Spatial Queries (Coming Soon)

Once layers are uploaded, you can query crashes within boundaries:

\`\`\`python
# Python example using requests
import requests

# Get crashes in Senate District 01
response = requests.get(
    "http://localhost:8000/spatial/query",
    params={
        "layer_id": 1,
        "feature_property": "district",
        "feature_value": "01",
        "entity": "crashes"
    }
)

crashes = response.json()
print(f"Found {len(crashes)} crashes in Senate District 01")
\`\`\`

### Replace Layer Data

Update layer without changing metadata:

\`\`\`bash
curl -X POST http://localhost:8000/spatial/layers/1/replace \\
  -F "file=@updated-districts.geojson"
\`\`\`

### Delete a Layer

\`\`\`bash
curl -X DELETE http://localhost:8000/spatial/layers/1
\`\`\`

:::caution
Deleting a layer removes all associated features. This action cannot be undone.
:::

## API Reference

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/spatial/layers` | List all layers |
| `POST` | `/spatial/layers` | Upload new layer |
| `GET` | `/spatial/layers/{id}` | Get layer details |
| `PATCH` | `/spatial/layers/{id}` | Update layer metadata |
| `POST` | `/spatial/layers/{id}/replace` | Replace layer features |
| `DELETE` | `/spatial/layers/{id}` | Delete layer |

### Request Schemas

#### Upload Layer

**Multipart form data:**
- `name` (required): Layer name
- `description` (optional): Layer description
- `file` (required): GeoJSON or zipped Shapefile
- `is_active` (optional): Boolean, default true

#### Update Metadata

**JSON body:**
\`\`\`json
{
  "name": "Updated Layer Name",
  "description": "Updated description",
  "is_active": false
}
\`\`\`

## Common Use Cases

### 1. Crash Analysis by Ward

\`\`\`bash
# Upload Chicago Wards
curl -X POST http://localhost:8000/spatial/layers \\
  -F "name=Wards 2023" \\
  -F "file=@wards-2023.zip"

# Query crashes in Ward 42
# (Coming soon in API)
\`\`\`

### 2. Senate District Reporting

\`\`\`bash
# Upload Senate Districts
curl -X POST http://localhost:8000/spatial/layers \\
  -F "name=IL Senate Districts" \\
  -F "file=@senate-districts.geojson"

# Generate report by district
# (Use spatial_layer_features table in SQL)
\`\`\`

## Database Schema

Layers are stored in two tables:

\`\`\`sql
-- Layer metadata
CREATE TABLE spatial_layers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    feature_count INTEGER,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Layer features (PostGIS geometry)
CREATE TABLE spatial_layer_features (
    id SERIAL PRIMARY KEY,
    layer_id INTEGER REFERENCES spatial_layers(id) ON DELETE CASCADE,
    properties JSONB,
    geometry GEOMETRY(Geometry, 4326),  -- WGS84
    created_at TIMESTAMP DEFAULT NOW()
);

-- Spatial index for fast queries
CREATE INDEX idx_spatial_features_geom
    ON spatial_layer_features USING GIST(geometry);
\`\`\`

## Troubleshooting

### Error: "Invalid GeoJSON payload"

**Cause**: File is not valid GeoJSON.

**Solution**: Validate your GeoJSON at [geojson.io](https://geojson.io) before uploading.

### Error: "Missing required shapefile components"

**Cause**: Zipped Shapefile missing `.shp`, `.shx`, `.dbf`, or `.prj` files.

**Solution**: Ensure all four files are in the zip:
\`\`\`bash
unzip -l your-shapefile.zip
# Should show: file.shp, file.shx, file.dbf, file.prj
\`\`\`

### Error: "Feature count is 0"

**Cause**: GeoJSON has no features or invalid geometry.

**Solution**: Check your GeoJSON structure:
\`\`\`json
{
  "type": "FeatureCollection",
  "features": [  // ← Must have at least one feature
    {
      "type": "Feature",
      "properties": {...},
      "geometry": {...}
    }
  ]
}
\`\`\`

## Next Steps

- [Admin Portal Guide](/user-guides/admin-portal) - Upload layers via web UI
- [API Reference](/api-reference) - Full API documentation
- [Spatial Queries Tutorial](/tutorials/spatial-queries) - Advanced spatial analysis

---

*Last updated: December 13, 2024*
```

**Step 2: Add to sidebar**

```typescript
// sidebars.ts

const sidebars: SidebarsConfig = {
  tutorialSidebar: [
    'intro',
    {
      type: 'category',
      label: 'User Guides',
      items: [
        'user-guides/admin-portal',
        'user-guides/api-reference',
        'user-guides/sync-operations',
        'user-guides/spatial-layers-api',  // NEW PAGE
      ],
    },
    // ... other categories
  ],
};
```

**Step 3: Add custom styling for code blocks**

```css
/* src/css/custom.css */

/* Custom code block styling */
.theme-code-block {
    margin-bottom: 1.5rem;
    border-radius: 8px;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

/* Language badge */
.theme-code-block-title {
    background: linear-gradient(135deg, #4f46e5 0%, #0ea5e9 100%);
    color: white;
    padding: 0.5rem 1rem;
    border-radius: 8px 8px 0 0;
    font-weight: 600;
    font-size: 0.875rem;
}

/* Copy button styling */
.theme-code-block .buttonGroup__atx {
    opacity: 0;
    transition: opacity 0.2s;
}

.theme-code-block:hover .buttonGroup__atx {
    opacity: 1;
}

/* API method badges in tables */
table code {
    background: linear-gradient(135deg, rgba(79, 70, 229, 0.1) 0%, rgba(14, 165, 233, 0.1) 100%);
    padding: 0.25rem 0.5rem;
    border-radius: 4px;
    font-weight: 600;
}

/* Admonitions (tips, cautions, etc.) */
.admonition {
    border-left: 4px solid;
    border-radius: 0 8px 8px 0;
}

.admonition-tip {
    border-color: #10b981;
    background: rgba(16, 185, 129, 0.1);
}

.admonition-caution {
    border-color: #f59e0b;
    background: rgba(245, 158, 11, 0.1);
}
```

**Step 4: Build and test**

```bash
# Run from project root directory

# Start dev server
npm run start

# Open browser to http://localhost:3000/user-guides/spatial-layers-api

# Test links work
# Test code blocks render correctly
# Test responsive layout
# Test dark mode

# Build for production
npm run build

# Verify output
ls -lh src/static/documentation/
```

### Expected Outcome

**Result**: New Docusaurus documentation page with:
- ✅ Clear API examples with curl commands
- ✅ Interactive code blocks with syntax highlighting
- ✅ Copy-to-clipboard functionality
- ✅ Proper sidebar navigation
- ✅ Responsive layout (mobile/tablet/desktop)
- ✅ Light/dark mode support
- ✅ Admonitions (tips, cautions) for user guidance
- ✅ Internal links to related pages
- ✅ Database schema documentation

**SEO Benefits**:
- Searchable content (Docusaurus generates static HTML)
- Proper heading hierarchy (H1 → H2 → H3)
- Meta descriptions from front matter

---

## Example 5: Optimize Admin Portal Loading Performance

### User Request
> "The admin portal takes 8 seconds to load on first visit. Can you optimize the initial load time?"

### Agent Workflow

**Step 1: Measure current performance**

```javascript
// Add performance tracking to app.js

performance.mark('app-init-start');

async function initializeApp() {
    try {
        // Track each phase
        performance.mark('data-load-start');

        // Sequential loading (SLOW)
        await loadDashboardData();
        await loadJobs();
        await loadExecutions();
        await loadDataStatistics();
        await loadSpatialLayers();

        performance.mark('data-load-end');
        performance.measure('data-load', 'data-load-start', 'data-load-end');

        performance.mark('app-init-end');
        performance.measure('app-init', 'app-init-start', 'app-init-end');

        // Log metrics
        const initMeasure = performance.getEntriesByName('app-init')[0];
        const dataLoadMeasure = performance.getEntriesByName('data-load')[0];

        console.log(`[Performance] App initialized in ${initMeasure.duration.toFixed(0)}ms`);
        console.log(`[Performance] Data loading took ${dataLoadMeasure.duration.toFixed(0)}ms`);

        // Send to analytics (optional)
        if (window.gtag) {
            window.gtag('event', 'timing_complete', {
                name: 'app_init',
                value: Math.round(initMeasure.duration)
            });
        }
    } catch (error) {
        console.error('Failed to initialize app:', error);
    }
}

// Chrome DevTools Performance tab shows:
// - Total: 8200ms
// - Data loading: 7800ms (5 sequential API calls)
// - Rendering: 400ms
```

**Findings**:
- 5 API calls executed sequentially (5 × ~1500ms = ~7500ms)
- No caching (re-fetches on every page load)
- Loading all tabs upfront (even if user never opens them)

**Step 2: Optimize with parallel loading**

```javascript
// src/static/admin/app.js

async function initializeApp() {
    try {
        performance.mark('app-init-start');

        // Parallel loading (FAST)
        const [dashboardData, jobs, recentExecutions] = await Promise.all([
            loadDashboardData(),   // Critical for default tab
            loadJobs(),            // Critical for default tab
            loadExecutions()       // Critical for default tab
        ]);

        // DON'T load these until tabs are activated
        // await loadDataStatistics();  // Only load when "Data Management" tab clicked
        // await loadSpatialLayers();   // Only load when "Spatial Layers" tab clicked

        setupEventListeners();
        startAutoRefresh();

        performance.mark('app-init-end');
        performance.measure('app-init', 'app-init-start', 'app-init-end');

        const measure = performance.getEntriesByName('app-init')[0];
        console.log(`[Performance] App initialized in ${measure.duration.toFixed(0)}ms`);

        showToast('Connected', 'Admin portal loaded successfully', 'success');
    } catch (error) {
        console.error('Failed to initialize app:', error);
        showToast('Error', 'Failed to connect to API', 'danger');
    }
}

// Result: 3 parallel calls = ~1500ms (down from 7500ms)
```

**Step 3: Implement lazy loading for tabs**

```javascript
// Track what's been loaded
let dataStatsLoaded = false;
let spatialLayersLoaded = false;

// Setup tab event listeners
function setupEventListeners() {
    // ... existing listeners ...

    // Lazy load data statistics
    document.querySelector('[data-bs-target="#data-management"]').addEventListener('shown.bs.tab', function() {
        if (!dataStatsLoaded) {
            loadDataStatistics();
            dataStatsLoaded = true;
        }
    });

    // Lazy load spatial layers
    document.querySelector('[data-bs-target="#spatial-layers"]').addEventListener('shown.bs.tab', function() {
        if (!spatialLayersLoaded) {
            loadSpatialLayers();
            spatialLayersLoaded = true;
        }
    });
}

// Result: Only load data when user actually needs it
```

**Step 4: Add caching layer**

```javascript
// Simple in-memory cache with TTL
class Cache {
    constructor(ttl = 60000) {  // 60 seconds default
        this.cache = new Map();
        this.ttl = ttl;
    }

    get(key) {
        const item = this.cache.get(key);
        if (!item) return null;

        const now = Date.now();
        if (now - item.timestamp > this.ttl) {
            this.cache.delete(key);  // Expired
            return null;
        }

        return item.value;
    }

    set(key, value) {
        this.cache.set(key, {
            value,
            timestamp: Date.now()
        });
    }

    clear() {
        this.cache.clear();
    }
}

// Create cache instances
const apiCache = new Cache(30000);  // 30 seconds

// Wrap apiRequest with caching
const originalApiRequest = apiRequest;
async function apiRequest(endpoint, options = {}) {
    // Only cache GET requests
    const method = options.method || 'GET';
    if (method !== 'GET') {
        return originalApiRequest(endpoint, options);
    }

    // Check cache
    const cacheKey = endpoint;
    const cached = apiCache.get(cacheKey);
    if (cached) {
        console.log(`[Cache HIT] ${endpoint}`);
        return cached;
    }

    console.log(`[Cache MISS] ${endpoint}`);

    // Fetch and cache
    const data = await originalApiRequest(endpoint, options);
    apiCache.set(cacheKey, data);
    return data;
}

// Clear cache on mutations
async function saveJob() {
    // ... save logic ...
    apiCache.clear();  // Invalidate cache
    await loadJobs();
}

// Result: Subsequent loads use cache (0ms instead of 1500ms)
```

**Step 5: Add loading skeleton screens**

```html
<!-- src/static/admin/index.html -->

<!-- Replace loading spinner with skeleton -->
<div id="jobs-loading" class="skeleton-container">
    <div class="skeleton-item">
        <div class="skeleton-line skeleton-line-title"></div>
        <div class="skeleton-line skeleton-line-subtitle"></div>
    </div>
    <div class="skeleton-item">
        <div class="skeleton-line skeleton-line-title"></div>
        <div class="skeleton-line skeleton-line-subtitle"></div>
    </div>
    <div class="skeleton-item">
        <div class="skeleton-line skeleton-line-title"></div>
        <div class="skeleton-line skeleton-line-subtitle"></div>
    </div>
</div>
```

```css
/* src/static/admin/styles.css */

.skeleton-container {
    display: flex;
    flex-direction: column;
    gap: 1rem;
}

.skeleton-item {
    padding: 1rem;
    background: var(--surface-bg);
    border-radius: 12px;
}

.skeleton-line {
    height: 16px;
    background: linear-gradient(
        90deg,
        rgba(0, 0, 0, 0.06) 25%,
        rgba(0, 0, 0, 0.15) 50%,
        rgba(0, 0, 0, 0.06) 75%
    );
    background-size: 200% 100%;
    animation: skeleton-loading 1.5s infinite;
    border-radius: 4px;
}

.skeleton-line-title {
    width: 60%;
    height: 20px;
    margin-bottom: 0.5rem;
}

.skeleton-line-subtitle {
    width: 40%;
}

@keyframes skeleton-loading {
    0% {
        background-position: 200% 0;
    }
    100% {
        background-position: -200% 0;
    }
}

/* Result: Perceived performance improvement (users see content placeholder) */
```

**Step 6: Optimize asset loading**

```html
<!-- src/static/admin/index.html -->

<!-- Preload critical resources -->
<head>
    <link rel="preconnect" href="https://cdn.jsdelivr.net">
    <link rel="preload" href="styles.css" as="style">
    <link rel="preload" href="app.js" as="script">

    <!-- Async load non-critical resources -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css" media="print" onload="this.media='all'">

    <!-- Critical CSS inline (first paint) -->
    <style>
        /* Critical above-the-fold styles */
        body { margin: 0; font-family: Inter, sans-serif; }
        .app-header { background: linear-gradient(135deg, #4f46e5 0%, #0ea5e9 100%); }
    </style>

    <!-- Defer non-critical JavaScript -->
    <script src="app.js" defer></script>
</head>

<!-- Result: Faster first paint, deferred non-critical resources -->
```

**Step 7: Performance metrics summary**

```javascript
// Before optimization:
const before = {
    timeToFirstByte: 120,      // ms
    timeToFirstPaint: 850,     // ms
    timeToInteractive: 8200,   // ms  ← SLOW
    totalAPITime: 7500,        // ms (5 sequential calls)
    cacheHits: 0
};

// After optimization:
const after = {
    timeToFirstByte: 120,      // ms (same)
    timeToFirstPaint: 450,     // ms  ↓ 47% (inline CSS, preload)
    timeToInteractive: 2100,   // ms  ↓ 74% (parallel loading, lazy tabs)
    totalAPITime: 1500,        // ms  ↓ 80% (3 parallel calls)
    cacheHits: 60              // %  (subsequent visits)
};

// Improvements:
// - First paint: 850ms → 450ms (47% faster)
// - Time to interactive: 8200ms → 2100ms (74% faster)
// - Subsequent loads: 8200ms → 500ms (94% faster with cache)
```

### Expected Outcome

**Result**: Optimized admin portal with:
- ✅ 74% faster initial load (8200ms → 2100ms)
- ✅ 94% faster subsequent loads (caching)
- ✅ Parallel API requests (3 instead of 5 sequential)
- ✅ Lazy loading for non-critical tabs
- ✅ Skeleton screens for perceived performance
- ✅ Optimized asset loading (preload, defer, async)
- ✅ Performance tracking and metrics

**User Experience**:
- Before: 8-second wait on blank screen
- After: Content visible in 2 seconds, full interactivity in 2.1 seconds

---

## Summary

These examples demonstrate the **Frontend Developer Agent's** capabilities:

1. **Admin portal features** - New analytics tab with charts, insights, responsive design
2. **Real-time updates** - WebSocket integration with reconnection logic and fallback
3. **Responsive design** - Mobile-first fixes for modals, forms, touch-friendly UI
4. **Documentation** - New Docusaurus page with interactive code examples
5. **Performance optimization** - Parallel loading, caching, lazy loading, skeleton screens

The agent provides:
- ✅ **Complete implementations** with HTML, CSS, and JavaScript
- ✅ **Responsive design** that works on mobile, tablet, desktop
- ✅ **Security best practices** (XSS prevention with escapeHtml)
- ✅ **Performance optimization** (parallel loading, caching, lazy loading)
- ✅ **User experience focus** (loading states, error handling, accessibility)
- ✅ **Cross-browser compatibility** (iOS-specific fixes, vendor prefixes)

Invoke the Frontend Developer Agent whenever you need beautiful, performant, user-friendly interfaces.
