// Chicago Crashes Pipeline Admin Portal
// JavaScript for managing jobs, executions, and data

// Configuration
const API_BASE = '';  // No prefix for our API
const REFRESH_INTERVAL = 30000; // 30 seconds
const EXECUTION_POLL_INTERVAL = 5000; // 5 seconds for live execution updates
const API_KEY_HEADER = 'X-API-Key';
const API_KEY_STORAGE_KEY = 'chicago_crashes_api_key';

// Global variables
let jobs = [];
let executions = [];
let spatialLayers = [];
let currentJobId = null;
let currentSpatialLayerId = null;
let refreshTimer = null;
let executionDetailTimer = null;
let activeExecutionId = null;

// API Key Management
function getStoredApiKey() {
    return sessionStorage.getItem(API_KEY_STORAGE_KEY);
}

function setStoredApiKey(key) {
    if (key) {
        sessionStorage.setItem(API_KEY_STORAGE_KEY, key);
    } else {
        sessionStorage.removeItem(API_KEY_STORAGE_KEY);
    }
}

function clearStoredApiKey() {
    sessionStorage.removeItem(API_KEY_STORAGE_KEY);
}

function showApiKeyModal() {
    const existingModal = document.getElementById('apiKeyModal');
    if (existingModal) {
        const modal = new bootstrap.Modal(existingModal);
        modal.show();
        return;
    }

    // Create modal dynamically
    const modalHtml = `
        <div class="modal fade" id="apiKeyModal" tabindex="-1" data-bs-backdrop="static" data-bs-keyboard="false">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content glass-card">
                    <div class="modal-header border-0">
                        <h5 class="modal-title">
                            <i class="bi bi-shield-lock me-2"></i>Admin Authentication
                        </h5>
                    </div>
                    <div class="modal-body">
                        <p class="text-muted mb-3">
                            This admin portal requires an API key for access. Enter the key configured in your deployment.
                        </p>
                        <div class="mb-3">
                            <label for="api-key-input" class="form-label">API Key</label>
                            <input type="password" class="form-control" id="api-key-input"
                                   placeholder="Enter your API key" autocomplete="off">
                            <div class="form-text">
                                The key is stored in your browser session and cleared when you close the tab.
                            </div>
                        </div>
                        <div id="api-key-error" class="alert alert-danger d-none" role="alert">
                            Invalid API key. Please check and try again.
                        </div>
                    </div>
                    <div class="modal-footer border-0">
                        <button type="button" class="btn btn-primary" id="api-key-submit-btn" onclick="submitApiKey()">
                            <i class="bi bi-unlock me-1"></i>Authenticate
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);

    // Add enter key handler
    document.getElementById('api-key-input').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            submitApiKey();
        }
    });

    const modal = new bootstrap.Modal(document.getElementById('apiKeyModal'));
    modal.show();

    // Focus the input after modal is shown
    document.getElementById('apiKeyModal').addEventListener('shown.bs.modal', function() {
        document.getElementById('api-key-input').focus();
    });
}

async function submitApiKey() {
    const input = document.getElementById('api-key-input');
    const errorDiv = document.getElementById('api-key-error');
    const submitBtn = document.getElementById('api-key-submit-btn');
    const key = input.value.trim();

    if (!key) {
        errorDiv.textContent = 'Please enter an API key.';
        errorDiv.classList.remove('d-none');
        return;
    }

    // Disable button and show loading
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Verifying...';
    errorDiv.classList.add('d-none');

    try {
        // Test the API key with a protected endpoint
        const response = await fetch(`${API_BASE}/jobs/summary`, {
            headers: {
                [API_KEY_HEADER]: key
            }
        });

        if (response.ok) {
            // Key is valid, store it and reload the app
            setStoredApiKey(key);
            const modal = bootstrap.Modal.getInstance(document.getElementById('apiKeyModal'));
            modal.hide();

            // Reinitialize the app
            await initializeApp();
        } else if (response.status === 401) {
            errorDiv.textContent = 'Invalid API key. Please check and try again.';
            errorDiv.classList.remove('d-none');
            input.select();
        } else {
            errorDiv.textContent = `Server error: ${response.status}. Please try again.`;
            errorDiv.classList.remove('d-none');
        }
    } catch (error) {
        console.error('API key verification failed:', error);
        errorDiv.textContent = 'Connection error. Please check your network and try again.';
        errorDiv.classList.remove('d-none');
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="bi bi-unlock me-1"></i>Authenticate';
    }
}

function showLogoutButton() {
    // Add logout button to navbar if not already present
    if (document.getElementById('logout-btn')) {
        return;
    }

    const navStatus = document.querySelector('.navbar .d-flex');
    if (navStatus) {
        const logoutBtn = document.createElement('button');
        logoutBtn.id = 'logout-btn';
        logoutBtn.className = 'btn btn-outline-secondary btn-sm ms-2';
        logoutBtn.innerHTML = '<i class="bi bi-box-arrow-right"></i>';
        logoutBtn.title = 'Logout (clear API key)';
        logoutBtn.onclick = function() {
            if (confirm('Clear stored API key and logout?')) {
                clearStoredApiKey();
                window.location.reload();
            }
        };
        navStatus.appendChild(logoutBtn);
    }
}

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

async function initializeApp() {
    try {
        // Set active navigation link based on current page
        setActiveNavLink();

        // Check if authentication is required by testing a protected endpoint
        const apiKey = getStoredApiKey();
        const testResponse = await fetch(`${API_BASE}/jobs/summary`, {
            headers: apiKey ? { [API_KEY_HEADER]: apiKey } : {}
        });

        if (testResponse.status === 401) {
            // Authentication required, show login modal
            showApiKeyModal();
            return;
        }

        // If we have a valid key, show logout button
        if (apiKey) {
            showLogoutButton();
        }

        await loadDashboardData();
        await loadJobs();
        await loadExecutions();
        await loadDataStatistics();
        await loadSpatialLayers();

        // Set up event listeners
        setupEventListeners();

        // Start periodic refresh
        startAutoRefresh();

        showToast('Connected', 'Admin portal loaded successfully', 'success');
    } catch (error) {
        console.error('Failed to initialize app:', error);
        // Check if it's an auth error
        if (error.message === 'Authentication required') {
            return; // Modal already shown
        }
        document.getElementById('api-status').textContent = 'API Error';
        document.getElementById('api-status').className = 'badge bg-danger me-2';
        showToast('Error', 'Failed to connect to API', 'danger');
    }
}

// Set active navigation link based on current page
function setActiveNavLink() {
    const path = window.location.pathname;
    document.querySelectorAll('.app-nav-link').forEach(link => {
        const href = link.getAttribute('href');

        // Check if current path starts with the link href (and handle root specially)
        if (path.startsWith(href) && href !== '/') {
            link.classList.add('active');
        } else if (path === '/' && href === '/') {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });
}

function setupEventListeners() {
    // Delete confirmation checkbox
    document.getElementById('confirm-deletion').addEventListener('change', function() {
        const deleteBtn = document.getElementById('delete-data-btn');
        deleteBtn.disabled = !this.checked;
    });
    
    // Job type change handler
    document.getElementById('job-type').addEventListener('change', function() {
        updateJobFormForType(this.value);
    });

    // Spatial layer upload form
    const spatialForm = document.getElementById('spatial-layer-upload-form');
    if (spatialForm) {
        spatialForm.addEventListener('submit', function(event) {
            event.preventDefault();
            uploadSpatialLayer();
        });
    }

    const spatialUploadBtn = document.getElementById('spatial-layer-upload-btn');
    if (spatialUploadBtn) {
        spatialUploadBtn.addEventListener('click', function(event) {
            event.preventDefault();
            uploadSpatialLayer();
        });
    }

    // Spatial layer file selection - preview available fields
    const spatialFileInput = document.getElementById('spatial-layer-file');
    if (spatialFileInput) {
        spatialFileInput.addEventListener('change', async function() {
            await previewSpatialLayerFields(this);
        });
    }
    
    // Tab change handlers
    document.querySelectorAll('[data-bs-toggle="tab"]').forEach(tab => {
        tab.addEventListener('shown.bs.tab', function(event) {
            const target = event.target.getAttribute('data-bs-target');
            if (target === '#executions') {
                loadExecutions();
            } else if (target === '#data-management') {
                loadDataStatistics();
            } else if (target === '#spatial-layers') {
                loadSpatialLayers();
            }
        });
    });
}

// API Helper Functions
async function apiRequest(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const isFormData = options.body instanceof FormData;
    const defaultHeaders = isFormData ? {} : { 'Content-Type': 'application/json' };

    // Include API key if available
    const apiKey = getStoredApiKey();
    const authHeaders = apiKey ? { [API_KEY_HEADER]: apiKey } : {};

    const headers = { ...defaultHeaders, ...authHeaders, ...(options.headers || {}) };
    const fetchOptions = { ...options, headers };

    const response = await fetch(url, fetchOptions);

    // Handle authentication errors
    if (response.status === 401) {
        // Clear invalid key and show login modal
        clearStoredApiKey();
        showApiKeyModal();
        throw new Error('Authentication required');
    }

    if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
            const error = await response.json();
            detail = error.detail || detail;
        } catch (parseError) {
            // Ignore parsing failure and fall back to default detail
        }
        throw new Error(detail);
    }

    if (response.status === 204) {
        return null;
    }

    const text = await response.text();
    if (!text) {
        return {};
    }

    try {
        return JSON.parse(text);
    } catch (error) {
        throw new Error('Failed to parse response JSON');
    }
}

// Dashboard Functions
async function loadDashboardData() {
    try {
        const summary = await apiRequest('/jobs/summary');
        
        document.getElementById('total-jobs').textContent = summary.total_jobs || 0;
        document.getElementById('active-jobs').textContent = summary.active_jobs || 0;
        document.getElementById('running-jobs').textContent = summary.running_jobs || 0;
        document.getElementById('failed-jobs').textContent = summary.failed_jobs_24h || 0;
        
        // Load recent executions for dashboard
        const recentExecutions = await apiRequest('/jobs/executions/recent?limit=10');
        displayRecentActivity(recentExecutions);
        
    } catch (error) {
        console.error('Failed to load dashboard data:', error);
        showToast('Error', 'Failed to load dashboard data', 'danger');
    }
}

function displayRecentActivity(executions) {
    const container = document.getElementById('recent-executions');
    
    if (!executions || executions.length === 0) {
        container.innerHTML = '<div class="text-muted text-center">No recent activity</div>';
        return;
    }
    
    const html = executions.slice(0, 5).map(execution => {
        const statusClass = `execution-${execution.status}`;
        const statusIcon = getStatusIcon(execution.status);
        const timeAgo = getTimeAgo(execution.started_at);
        
        return `
            <div class="list-group-item ${statusClass}">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <span class="status-icon ${execution.status}"></span>
                        <strong>Job ${execution.job_id}</strong>
                        <small class="text-muted ms-2">${execution.execution_id.substring(0, 8)}...</small>
                    </div>
                    <small class="text-muted">${timeAgo}</small>
                </div>
                <div class="small text-muted mt-1">
                    ${execution.records_processed || 0} records processed
                </div>
            </div>
        `;
    }).join('');
    
    container.innerHTML = html;
}

// Job Management Functions
async function loadJobs() {
    try {
        jobs = await apiRequest('/jobs/');
        displayJobs(jobs);
        updateExecutionFilter(jobs);
    } catch (error) {
        console.error('Failed to load jobs:', error);
        showToast('Error', 'Failed to load jobs', 'danger');
    }
}

function displayJobs(jobsList) {
    const tbody = document.getElementById('jobs-table-body');
    
    if (!jobsList || jobsList.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No jobs found</td></tr>';
        return;
    }
    
    const html = jobsList.map(job => {
        const statusBadge = job.enabled ? 
            '<span class="badge bg-success">Enabled</span>' : 
            '<span class="badge bg-secondary">Disabled</span>';
        
        const nextRun = job.next_run ? 
            new Date(job.next_run).toLocaleString() : 
            '<span class="text-muted">Never</span>';
        
        const lastRun = job.last_run ? 
            new Date(job.last_run).toLocaleString() : 
            '<span class="text-muted">Never</span>';
        
        return `
            <tr>
                <td>
                    <strong>${job.name}</strong>
                    ${job.description ? `<br><small class="text-muted">${job.description}</small>` : ''}
                </td>
                <td><span class="job-type-badge job-type-${job.job_type.replace('_', '-')}">${formatJobType(job.job_type)}</span></td>
                <td>${statusBadge}</td>
                <td>${formatRecurrenceType(job.recurrence_type)}</td>
                <td>${nextRun}</td>
                <td>${lastRun}</td>
                <td class="action-buttons">
                    <button class="btn btn-sm btn-outline-primary" onclick="executeJobManual(${job.id})" title="Execute Now">
                        <i class="bi bi-play-circle"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-secondary" onclick="editJob(${job.id})" title="Edit">
                        <i class="bi bi-pencil"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-info" onclick="viewJobExecutions(${job.id})" title="View Executions">
                        <i class="bi bi-clock-history"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="deleteJob(${job.id})" title="Delete">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
    
    tbody.innerHTML = html;
}

// Execution Management Functions
async function loadExecutions(jobId = null) {
    try {
        const endpoint = jobId ? 
            `/jobs/${jobId}/executions?limit=100` : 
            '/jobs/executions/recent?limit=100';
        
        executions = await apiRequest(endpoint);
        displayExecutions(executions);
    } catch (error) {
        console.error('Failed to load executions:', error);
        showToast('Error', 'Failed to load executions', 'danger');
    }
}

function displayExecutions(executionsList) {
    const tbody = document.getElementById('executions-table-body');
    
    if (!executionsList || executionsList.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No executions found</td></tr>';
        return;
    }
    
    const html = executionsList.map(execution => {
        const statusBadge = `<span class="badge status-${execution.status}">${execution.status.toUpperCase()}</span>`;
        const started = execution.started_at ? new Date(execution.started_at).toLocaleString() : 'Not started';
        const duration = execution.duration_seconds ? `${execution.duration_seconds}s` : 'N/A';
        const jobName = resolveJobName(execution);
        const hasJobId = execution.job_id !== undefined && execution.job_id !== null;
        const jobIdLabel = hasJobId ? `ID: ${escapeHtml(String(execution.job_id))}` : '';
        const processed = Number(execution.records_processed || 0).toLocaleString();
        const inserted = Number(execution.records_inserted || 0).toLocaleString();
        const hasUpdated = execution.records_updated !== undefined && execution.records_updated !== null;
        const updated = hasUpdated ? Number(execution.records_updated || 0).toLocaleString() : null;
        const executionIdText = escapeHtml(execution.execution_id);
        const executionIdAttr = String(execution.execution_id)
            .replace(/\\/g, '\\\\')
            .replace(/'/g, "\\'");

        return `
            <tr>
                <td>
                    <button type="button" class="execution-id-link" onclick="viewExecutionDetails('${executionIdAttr}')">
                        ${executionIdText}
                    </button>
                </td>
                <td>
                    <div class="execution-job">
                        <div class="execution-job-name">${escapeHtml(jobName)}</div>
                        ${jobIdLabel ? `<div class="execution-job-meta">${jobIdLabel}</div>` : ''}
                    </div>
                </td>
                <td>${statusBadge}</td>
                <td>${started}</td>
                <td>${duration}</td>
                <td>
                    <div class="execution-records">
                        <div>Processed: ${processed}</div>
                        <div>Inserted: ${inserted}</div>
                        ${hasUpdated ? `<div>Updated: ${updated}</div>` : ''}
                    </div>
                </td>
                <td>
                    <button class="btn btn-sm btn-outline-info" onclick="viewExecutionDetails('${executionIdAttr}')" title="View Details">
                        <i class="bi bi-eye"></i>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
    
    tbody.innerHTML = html;
}

// Job CRUD Operations
function showCreateJobModal() {
    currentJobId = null;
    document.getElementById('jobModalLabel').textContent = 'Create New Job';
    document.getElementById('jobForm').reset();
    document.getElementById('job-enabled').checked = true;
    
    // Show all form sections for custom jobs
    updateJobFormForType('custom');
    
    const modal = new bootstrap.Modal(document.getElementById('jobModal'));
    modal.show();
}

function editJob(jobId) {
    const job = jobs.find(j => j.id === jobId);
    if (!job) return;
    
    currentJobId = jobId;
    document.getElementById('jobModalLabel').textContent = 'Edit Job';
    
    // Populate form
    document.getElementById('job-name').value = job.name || '';
    document.getElementById('job-description').value = job.description || '';
    document.getElementById('job-type').value = job.job_type || '';
    document.getElementById('job-recurrence').value = job.recurrence_type || '';
    document.getElementById('job-enabled').checked = job.enabled;
    document.getElementById('job-timeout').value = job.timeout_minutes || 60;
    document.getElementById('job-retries').value = job.max_retries || 3;
    
    // Populate endpoints
    if (job.config && job.config.endpoints) {
        document.querySelectorAll('.job-endpoint').forEach(checkbox => {
            checkbox.checked = job.config.endpoints.includes(checkbox.value);
        });
    }
    
    // Populate dates
    if (job.config) {
        document.getElementById('job-start-date').value = job.config.start_date || '';
        document.getElementById('job-end-date').value = job.config.end_date || '';
    }
    
    updateJobFormForType(job.job_type);
    
    const modal = new bootstrap.Modal(document.getElementById('jobModal'));
    modal.show();
}

async function saveJob() {
    const form = document.getElementById('jobForm');
    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }
    
    const formData = new FormData(form);
    const endpoints = Array.from(document.querySelectorAll('.job-endpoint:checked')).map(cb => cb.value);
    
    const jobData = {
        name: document.getElementById('job-name').value,
        description: document.getElementById('job-description').value,
        job_type: document.getElementById('job-type').value,
        recurrence_type: document.getElementById('job-recurrence').value,
        enabled: document.getElementById('job-enabled').checked,
        timeout_minutes: parseInt(document.getElementById('job-timeout').value),
        max_retries: parseInt(document.getElementById('job-retries').value),
        config: {
            endpoints: endpoints,
            start_date: document.getElementById('job-start-date').value || null,
            end_date: document.getElementById('job-end-date').value || null,
            force: true
        }
    };
    
    try {
        if (currentJobId) {
            await apiRequest(`/jobs/${currentJobId}`, {
                method: 'PUT',
                body: JSON.stringify(jobData)
            });
            showToast('Success', 'Job updated successfully', 'success');
        } else {
            await apiRequest('/jobs/', {
                method: 'POST',
                body: JSON.stringify(jobData)
            });
            showToast('Success', 'Job created successfully', 'success');
        }
        
        bootstrap.Modal.getInstance(document.getElementById('jobModal')).hide();
        await loadJobs();
        await loadDashboardData();
        
    } catch (error) {
        console.error('Failed to save job:', error);
        showToast('Error', `Failed to save job: ${error.message}`, 'danger');
    }
}

async function deleteJob(jobId) {
    const job = jobs.find(j => j.id === jobId);
    if (!job) return;
    
    if (!confirm(`Are you sure you want to delete "${job.name}"? This will also delete all execution history.`)) {
        return;
    }
    
    try {
        await apiRequest(`/jobs/${jobId}`, { method: 'DELETE' });
        showToast('Success', 'Job deleted successfully', 'success');
        await loadJobs();
        await loadDashboardData();
    } catch (error) {
        console.error('Failed to delete job:', error);
        showToast('Error', `Failed to delete job: ${error.message}`, 'danger');
    }
}

// Job Execution Functions
async function executeJobManual(jobId) {
    const job = jobs.find(j => j.id === jobId);
    if (!job) return;
    
    if (!confirm(`Execute "${job.name}" now?`)) return;
    
    try {
        const result = await apiRequest(`/jobs/${jobId}/execute`, {
            method: 'POST',
            body: JSON.stringify({ force: true })
        });
        
        showToast('Success', `Job execution started: ${result.execution_id}`, 'success');
        await loadDashboardData();
        await loadExecutions();
        
    } catch (error) {
        console.error('Failed to execute job:', error);
        showToast('Error', `Failed to execute job: ${error.message}`, 'danger');
    }
}

async function executeJob(jobType) {
    // Find job by type
    const job = jobs.find(j => j.job_type === jobType);
    if (!job) {
        showToast('Error', `Job type "${jobType}" not found`, 'danger');
        return;
    }
    
    await executeJobManual(job.id);
}

function viewJobExecutions(jobId) {
    const job = jobs.find(j => j.id === jobId);
    if (!job) return;
    
    // Switch to executions tab and filter by job
    document.getElementById('executions-tab').click();
    const filterSelect = document.getElementById('execution-filter');
    if (filterSelect) {
        filterSelect.value = jobId.toString();
    }
    loadExecutions(jobId);
}

async function viewExecutionDetails(executionId) {
    stopExecutionPolling();
    activeExecutionId = executionId;

    const modalElement = document.getElementById('executionModal');
    const modalBody = document.getElementById('execution-details');
    if (modalBody) {
        modalBody.innerHTML = '<div class="text-center py-5"><span class="spinner-border spinner-border-sm me-2"></span>Loading execution...</div>';
    }

    const modal = bootstrap.Modal.getOrCreateInstance(modalElement);
    modal.show();

    await loadExecutionDetail(executionId, true);
}

async function loadExecutionDetail(executionId, allowRestart = false) {
    try {
        const detail = await apiRequest(`/jobs/executions/${executionId}`);
        if (!detail) {
            throw new Error('Execution not found');
        }

        const enrichedDetail = {
            ...detail,
            job_name: detail.job_name || resolveJobName(detail)
        };

        executions = executions.map(exec =>
            exec.execution_id === enrichedDetail.execution_id ? { ...exec, ...enrichedDetail } : exec
        );

        renderExecutionDetail(enrichedDetail);

        const isActive = ['RUNNING', 'PENDING'].includes(enrichedDetail.status);
        if (isActive) {
            if (!executionDetailTimer || allowRestart) {
                startExecutionPolling(enrichedDetail.execution_id);
            }
        } else {
            stopExecutionPolling();
            await loadExecutions();
        }
    } catch (error) {
        console.error('Failed to load execution detail:', error);
        showToast('Error', 'Failed to load execution details', 'danger');
        stopExecutionPolling();
    }
}

function renderExecutionDetail(detail) {
    const modalTitle = document.getElementById('executionModalLabel');
    if (modalTitle) {
        modalTitle.textContent = detail.job_name ? `${detail.job_name}` : 'Execution Details';
    }

    const modalBody = document.getElementById('execution-details');
    if (!modalBody) {
        return;
    }

    const jobName = detail.job_name || resolveJobName(detail);
    const statusBadge = `<span class="badge status-${detail.status}">${detail.status.toUpperCase()}</span>`;
    const startedAt = detail.started_at ? new Date(detail.started_at).toLocaleString() : 'Not started';
    const completedAt = detail.completed_at ? new Date(detail.completed_at).toLocaleString() : 'In progress';
    const computedDuration = detail.started_at && !detail.completed_at ?
        Math.max(0, Math.floor((Date.now() - new Date(detail.started_at)) / 1000)) : null;
    const durationLabel = detail.duration_seconds ? `${detail.duration_seconds}s` :
        (computedDuration ? `${computedDuration}s` : '—');

    const recordsProcessed = Number(detail.records_processed || 0).toLocaleString();
    const recordsInserted = Number(detail.records_inserted || 0).toLocaleString();
    const recordsUpdated = Number(detail.records_updated || 0).toLocaleString();

    const triggerMeta = detail.execution_context?.trigger;
    const triggerType = triggerMeta?.type || (detail.execution_context?.manual ? 'manual' : null);
    const forceRun = triggerMeta?.force ?? detail.execution_context?.force;
    const endpoints = Array.isArray(detail.execution_context?.config?.endpoints)
        ? detail.execution_context.config.endpoints.join(', ')
        : '—';
    const jobId = detail.job_id ?? '—';

    const contextChips = [];
    if (triggerType) {
        contextChips.push(`<span class="execution-chip">${escapeHtml(capitalize(triggerType))} run</span>`);
    }
    if (forceRun) {
        contextChips.push('<span class="execution-chip danger">Forced execution</span>');
    }

    const logMarkup = renderExecutionLogs(detail.logs);
    const activeLabel = ['RUNNING', 'PENDING'].includes(detail.status) ? 'Live (5s refresh)' : 'Final output';

    modalBody.innerHTML = `
        <div class="execution-overview">
            <div>
                <span class="eyebrow text-muted text-uppercase">Execution</span>
                <h3 class="execution-title">${escapeHtml(jobName)}</h3>
                ${detail.execution_id ? `<div class="execution-subtitle">Execution ${escapeHtml(detail.execution_id)}</div>` : ''}
                ${contextChips.length ? `<div class="execution-chip-group">${contextChips.join('')}</div>` : ''}
            </div>
            <div class="execution-status text-md-end text-center">
                ${statusBadge}
                <span class="timestamp">Started ${startedAt}</span>
                ${detail.completed_at ? `<span class="timestamp">Completed ${completedAt}</span>` : ''}
            </div>
        </div>

        <div class="execution-metrics">
            <div class="execution-metric-card processed">
                <span class="label">Processed</span>
                <span class="value">${recordsProcessed}</span>
            </div>
            <div class="execution-metric-card inserted">
                <span class="label">Inserted</span>
                <span class="value">${recordsInserted}</span>
            </div>
            <div class="execution-metric-card updated">
                <span class="label">Updated</span>
                <span class="value">${recordsUpdated}</span>
            </div>
            <div class="execution-metric-card duration">
                <span class="label">Duration</span>
                <span class="value">${durationLabel}</span>
            </div>
        </div>

        <div class="execution-detail-sections">
            <div class="execution-detail-card">
                <div class="title">Timing</div>
                <div class="execution-detail-item"><span class="detail-label">Started</span><span>${startedAt}</span></div>
                <div class="execution-detail-item"><span class="detail-label">Completed</span><span>${completedAt}</span></div>
            </div>
            <div class="execution-detail-card">
                <div class="title">Execution Context</div>
                <div class="execution-detail-item"><span class="detail-label">Job ID</span><span>${escapeHtml(String(jobId))}</span></div>
                <div class="execution-detail-item"><span class="detail-label">Endpoints</span><span>${escapeHtml(endpoints)}</span></div>
            </div>
        </div>

        ${detail.error_message ? `
            <div class="alert alert-danger soft-alert mt-3">
                <h6 class="mb-1">Error Message</h6>
                <pre class="mb-0 execution-error">${escapeHtml(detail.error_message)}</pre>
            </div>
        ` : ''}

        <div class="execution-log-surface mt-4">
            <div class="d-flex justify-content-between align-items-center mb-2">
                <h6 class="mb-0">Live Logs</h6>
                <span class="badge bg-light text-muted">${activeLabel}</span>
            </div>
            <div class="execution-log-stream" id="execution-log-stream">
                ${logMarkup}
            </div>
        </div>
    `;

    const logContainer = document.getElementById('execution-log-stream');
    if (logContainer) {
        logContainer.scrollTop = logContainer.scrollHeight;
    }
}

function renderExecutionLogs(logs = []) {
    if (!logs || logs.length === 0) {
        return '<div class="text-muted text-center py-3">No log entries yet</div>';
    }

    return logs.map(entry => {
        const timestampValue = entry?.timestamp ? new Date(entry.timestamp) : null;
        const timestamp = timestampValue && !Number.isNaN(timestampValue.valueOf())
            ? timestampValue.toLocaleTimeString()
            : '';
        const level = (entry?.level || 'info').toLowerCase();
        const levelLabel = level.toUpperCase();
        const message = escapeHtml(entry?.message || '');
        return `
            <div class="execution-log-entry">
                <span class="log-timestamp">${timestamp}</span>
                <span class="log-level log-${level}">${levelLabel}</span>
                <span class="log-message">${message}</span>
            </div>
        `;
    }).join('');
}

function startExecutionPolling(executionId) {
    stopExecutionPolling();
    executionDetailTimer = setInterval(() => {
        loadExecutionDetail(executionId, false);
    }, EXECUTION_POLL_INTERVAL);
}

function stopExecutionPolling() {
    if (executionDetailTimer) {
        clearInterval(executionDetailTimer);
        executionDetailTimer = null;
    }
}

// Data Management Functions
async function loadDataStatistics() {
    try {
        const counts = await apiRequest('/sync/counts');
        displayDataStatistics(counts.counts);
    } catch (error) {
        console.error('Failed to load data statistics:', error);
        showToast('Error', 'Failed to load data statistics', 'danger');
    }
}

function displayDataStatistics(counts) {
    const container = document.getElementById('data-stats');
    
    if (!counts) {
        container.innerHTML = '<div class="col-12"><p class="text-muted text-center">No data available</p></div>';
        return;
    }
    
    const stats = [
        { name: 'Crashes', count: counts.crashes || 0, icon: 'car-front', color: 'primary' },
        { name: 'People', count: counts.crash_people || 0, icon: 'people', color: 'success' },
        { name: 'Vehicles', count: counts.crash_vehicles || 0, icon: 'truck', color: 'warning' },
        { name: 'Fatalities', count: counts.vision_zero_fatalities || 0, icon: 'exclamation-diamond', color: 'danger' }
    ];
    
    const html = stats.map(stat => `
        <div class="col-md-6 mb-3">
            <div class="d-flex align-items-center">
                <div class="me-3">
                    <i class="bi bi-${stat.icon} text-${stat.color} fs-4"></i>
                </div>
                <div>
                    <div class="fw-bold">${stat.name}</div>
                    <div class="text-muted">${stat.count.toLocaleString()} records</div>
                </div>
            </div>
        </div>
    `).join('');
    
    container.innerHTML = html;
}

async function deleteTableData() {
    const tableName = document.getElementById('delete-table-select').value;
    const startDate = document.getElementById('delete-start-date').value;
    const endDate = document.getElementById('delete-end-date').value;
    const confirmed = document.getElementById('confirm-deletion').checked;
    
    if (!tableName) {
        showToast('Error', 'Please select a table', 'warning');
        return;
    }
    
    if (!confirmed) {
        showToast('Error', 'Please confirm the deletion', 'warning');
        return;
    }
    
    const dateRange = (startDate || endDate) ? { start: startDate, end: endDate } : null;
    const deleteData = {
        table_name: tableName,
        confirm: true,
        backup: true,
        date_range: dateRange
    };
    
    if (!confirm(`This will PERMANENTLY DELETE data from ${tableName}. Are you absolutely sure?`)) {
        return;
    }
    
    try {
        const result = await apiRequest('/jobs/data/delete', {
            method: 'POST',
            body: JSON.stringify(deleteData)
        });
        
        showToast('Success', `Deleted ${result.records_deleted} records from ${tableName}`, 'success');
        
        // Reset form
        document.getElementById('delete-table-select').value = '';
        document.getElementById('delete-start-date').value = '';
        document.getElementById('delete-end-date').value = '';
        document.getElementById('confirm-deletion').checked = false;
        document.getElementById('delete-data-btn').disabled = true;
        
        // Reload data statistics
        await loadDataStatistics();
        
    } catch (error) {
        console.error('Failed to delete data:', error);
        showToast('Error', `Failed to delete data: ${error.message}`, 'danger');
    }
}

// Spatial Layer Management Functions
async function loadSpatialLayers() {
    try {
        const layers = await apiRequest('/spatial/layers');
        spatialLayers = layers || [];
        displaySpatialLayers(spatialLayers);
    } catch (error) {
        console.error('Failed to load spatial layers:', error);
        showToast('Error', error.message || 'Failed to load spatial layers', 'danger');
        const tbody = document.getElementById('spatial-layer-table-body');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-danger">Unable to load spatial layers</td></tr>';
        }
    }
}

function displaySpatialLayers(layers) {
    const tbody = document.getElementById('spatial-layer-table-body');
    if (!tbody) {
        return;
    }

    if (!layers || layers.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">No spatial layers uploaded yet</td></tr>';
        return;
    }

    const rows = layers.map(layer => {
        const statusBadge = layer.is_active ?
            '<span class="badge bg-success">Active</span>' :
            '<span class="badge bg-secondary">Inactive</span>';
        const updated = layer.updated_at ? new Date(layer.updated_at).toLocaleString() : '—';
        const featureCount = layer.feature_count?.toLocaleString() || '0';
        const source = layer.original_filename ? layer.original_filename : '<span class="text-muted">Uploaded</span>';

        return `
            <tr>
                <td>
                    <strong>${layer.name}</strong><br>
                    <small class="text-muted">${layer.geometry_type} • SRID ${layer.srid}</small>
                </td>
                <td>${featureCount}</td>
                <td>${statusBadge}</td>
                <td>${source}</td>
                <td>${updated}</td>
                <td class="action-buttons">
                    <button class="btn btn-sm btn-outline-primary" onclick="openSpatialLayerModal(${layer.id})" title="View & Edit">
                        <i class="bi bi-eye"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-secondary" onclick="promptSpatialLayerReplace(${layer.id})" title="Replace data">
                        <i class="bi bi-arrow-repeat"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="deleteSpatialLayer(${layer.id})" title="Delete layer">
                        <i class="bi bi-trash"></i>
                    </button>
                </td>
            </tr>
        `;
    }).join('');

    tbody.innerHTML = rows;
}

async function previewSpatialLayerFields(fileInput) {
    const labelFieldGroup = document.getElementById('spatial-layer-label-field-group');
    const labelFieldSelect = document.getElementById('spatial-layer-label-field');
    const sortTypeGroup = document.getElementById('spatial-layer-sort-type-group');

    if (!fileInput.files || fileInput.files.length === 0) {
        labelFieldGroup.style.display = 'none';
        if (sortTypeGroup) sortTypeGroup.style.display = 'none';
        return;
    }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('srid', document.getElementById('spatial-layer-srid').value || '4326');

    try {
        labelFieldSelect.innerHTML = '<option value="">Analyzing fields...</option>';
        labelFieldGroup.style.display = 'block';
        if (sortTypeGroup) sortTypeGroup.style.display = 'block';

        const result = await apiRequest('/spatial/layers/preview-fields', {
            method: 'POST',
            body: formData
        });

        // Populate field selector
        labelFieldSelect.innerHTML = '<option value="">Auto-detect (default)</option>';
        if (result.fields && result.fields.length > 0) {
            result.fields.forEach(field => {
                const option = document.createElement('option');
                option.value = field.name;
                let label = field.name;
                if (field.suggested) {
                    label += ' (recommended)';
                }
                if (field.sample_values && field.sample_values.length > 0) {
                    const sample = String(field.sample_values[0]).substring(0, 30);
                    label += ` - e.g. "${sample}"`;
                }
                option.textContent = label;
                labelFieldSelect.appendChild(option);
            });

            // Auto-select recommended field
            if (result.recommended_field) {
                labelFieldSelect.value = result.recommended_field;
            }
        }
    } catch (error) {
        console.error('Failed to preview fields:', error);
        labelFieldSelect.innerHTML = '<option value="">Auto-detect (default)</option>';
    }
}

async function uploadSpatialLayer() {
    const form = document.getElementById('spatial-layer-upload-form');
    const fileInput = document.getElementById('spatial-layer-file');
    const uploadBtn = document.getElementById('spatial-layer-upload-btn');
    const labelFieldGroup = document.getElementById('spatial-layer-label-field-group');

    if (!fileInput.files || fileInput.files.length === 0) {
        showToast('Error', 'Please select a GeoJSON file or zipped shapefile to upload', 'warning');
        return;
    }

    const formData = new FormData(form);

    const originalButtonText = uploadBtn.innerHTML;
    uploadBtn.disabled = true;
    uploadBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Uploading';

    try {
        await apiRequest('/spatial/layers', {
            method: 'POST',
            body: formData
        });

        showToast('Success', 'Spatial layer uploaded successfully', 'success');
        form.reset();
        document.getElementById('spatial-layer-srid').value = '4326';
        labelFieldGroup.style.display = 'none';
        const sortTypeGroup = document.getElementById('spatial-layer-sort-type-group');
        if (sortTypeGroup) sortTypeGroup.style.display = 'none';
        await loadSpatialLayers();
    } catch (error) {
        console.error('Failed to upload spatial layer:', error);
        showToast('Error', error.message || 'Unable to upload layer', 'danger');
    } finally {
        uploadBtn.disabled = false;
        uploadBtn.innerHTML = originalButtonText;
    }
}

async function openSpatialLayerModal(layerId) {
    try {
        const layer = await apiRequest(`/spatial/layers/${layerId}`);
        if (!layer) {
            showToast('Error', 'Spatial layer not found', 'warning');
            return;
        }

        currentSpatialLayerId = layerId;
        populateSpatialLayerModal(layer);

        const modalElement = document.getElementById('spatialLayerModal');
        const modal = new bootstrap.Modal(modalElement);
        modal.show();
    } catch (error) {
        console.error('Failed to load spatial layer:', error);
        showToast('Error', 'Failed to load spatial layer details', 'danger');
    }
}

function populateSpatialLayerModal(layer) {
    const modalTitle = document.getElementById('spatialLayerModalLabel');
    if (modalTitle) {
        modalTitle.textContent = layer.name;
    }
    document.getElementById('spatial-layer-edit-name').value = layer.name;
    document.getElementById('spatial-layer-edit-description').value = layer.description || '';
    document.getElementById('spatial-layer-edit-active').checked = !!layer.is_active;

    // Populate label field selector
    const labelFieldSelect = document.getElementById('spatial-layer-edit-label-field');
    labelFieldSelect.innerHTML = '<option value="">Auto-detect</option>';
    if (layer.available_fields && layer.available_fields.length > 0) {
        layer.available_fields.forEach(field => {
            const option = document.createElement('option');
            option.value = field;
            option.textContent = field;
            labelFieldSelect.appendChild(option);
        });
    }
    if (layer.label_field) {
        labelFieldSelect.value = layer.label_field;
    }

    // Populate sort type selector
    const sortTypeSelect = document.getElementById('spatial-layer-edit-sort-type');
    if (sortTypeSelect && layer.sort_type) {
        sortTypeSelect.value = layer.sort_type;
    }

    const meta = document.getElementById('spatial-layer-meta');
    meta.innerHTML = `
        <div class="row g-3">
            <div class="col-md-6">
                <div class="text-muted small">Geometry Type</div>
                <div class="fw-bold">${layer.geometry_type}</div>
            </div>
            <div class="col-md-6">
                <div class="text-muted small">Features</div>
                <div class="fw-bold">${layer.feature_count?.toLocaleString() || 0}</div>
            </div>
            <div class="col-md-6">
                <div class="text-muted small">SRID</div>
                <div class="fw-bold">${layer.srid}</div>
            </div>
            <div class="col-md-6">
                <div class="text-muted small">Original File</div>
                <div class="fw-bold">${layer.original_filename || '—'}</div>
            </div>
            <div class="col-md-6">
                <div class="text-muted small">Label Field</div>
                <div class="fw-bold">${layer.label_field || 'Auto-detect'}</div>
            </div>
            <div class="col-md-6">
                <div class="text-muted small">Sort Order</div>
                <div class="fw-bold">${formatSortType(layer.sort_type)}</div>
            </div>
        </div>
    `;

    const samplesContainer = document.getElementById('spatial-layer-samples');
    if (!layer.feature_samples || layer.feature_samples.length === 0) {
        samplesContainer.innerHTML = '<p class="text-muted">No sample features available.</p>';
    } else {
        samplesContainer.innerHTML = layer.feature_samples.map(sample => `
            <div class="sample-feature mb-3">
                <div class="small text-muted">Feature ID ${sample.id}</div>
                <pre class="bg-light p-2 rounded">${JSON.stringify(sample.properties, null, 2)}</pre>
            </div>
        `).join('');
    }
}

async function saveSpatialLayerChanges() {
    if (!currentSpatialLayerId) {
        return;
    }

    const nameInput = document.getElementById('spatial-layer-edit-name');
    const descriptionInput = document.getElementById('spatial-layer-edit-description');
    const activeInput = document.getElementById('spatial-layer-edit-active');
    const labelFieldInput = document.getElementById('spatial-layer-edit-label-field');
    const sortTypeInput = document.getElementById('spatial-layer-edit-sort-type');
    const saveBtn = document.getElementById('spatial-layer-save-btn');

    const name = nameInput.value.trim();
    if (!name) {
        showToast('Error', 'Layer name is required', 'warning');
        return;
    }

    const payload = {
        name,
        description: descriptionInput.value,
        is_active: activeInput.checked,
        label_field: labelFieldInput.value || null,
        sort_type: sortTypeInput ? sortTypeInput.value : null
    };

    saveBtn.disabled = true;

    try {
        await apiRequest(`/spatial/layers/${currentSpatialLayerId}`, {
            method: 'PATCH',
            body: JSON.stringify(payload)
        });

        showToast('Success', 'Spatial layer updated', 'success');
        await loadSpatialLayers();

        const refreshed = await apiRequest(`/spatial/layers/${currentSpatialLayerId}`);
        if (refreshed) {
            populateSpatialLayerModal(refreshed);
        }
    } catch (error) {
        console.error('Failed to update spatial layer:', error);
        showToast('Error', error.message || 'Unable to update layer', 'danger');
    } finally {
        saveBtn.disabled = false;
    }
}

function promptSpatialLayerReplace(layerId) {
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = '.geojson,.json,.zip,application/geo+json,application/json,application/zip';
    fileInput.style.display = 'none';

    fileInput.addEventListener('change', async () => {
        if (fileInput.files && fileInput.files[0]) {
            await replaceSpatialLayer(layerId, fileInput.files[0]);
        }
        fileInput.remove();
    });

    document.body.appendChild(fileInput);
    fileInput.click();
}

async function replaceSpatialLayer(layerId, file) {
    const formData = new FormData();
    formData.append('file', file);

    try {
        await apiRequest(`/spatial/layers/${layerId}/replace`, {
            method: 'POST',
            body: formData
        });

        showToast('Success', 'Spatial layer replaced successfully', 'success');
        await loadSpatialLayers();

        if (currentSpatialLayerId === layerId) {
            const refreshed = await apiRequest(`/spatial/layers/${layerId}`);
            if (refreshed) {
                populateSpatialLayerModal(refreshed);
            }
        }
    } catch (error) {
        console.error('Failed to replace spatial layer:', error);
        showToast('Error', error.message || 'Unable to replace layer', 'danger');
    }
}

async function deleteSpatialLayer(layerId) {
    if (!confirm('This will delete the spatial layer and all of its features. Continue?')) {
        return;
    }

    try {
        await apiRequest(`/spatial/layers/${layerId}`, {
            method: 'DELETE'
        });
        showToast('Deleted', 'Spatial layer removed', 'success');
        await loadSpatialLayers();

        if (currentSpatialLayerId === layerId) {
            const modalElement = document.getElementById('spatialLayerModal');
            const modal = bootstrap.Modal.getInstance(modalElement);
            if (modal) {
                modal.hide();
            }
            currentSpatialLayerId = null;
        }
    } catch (error) {
        console.error('Failed to delete spatial layer:', error);
        showToast('Error', error.message || 'Unable to delete layer', 'danger');
    }
}

// Helper Functions
function updateJobFormForType(jobType) {
    const endpointsGroup = document.getElementById('job-endpoints-group');
    
    // Show/hide endpoint selection based on job type
    if (jobType === 'custom') {
        endpointsGroup.style.display = 'block';
    } else {
        endpointsGroup.style.display = 'none';
        
        // Auto-select endpoints based on job type
        document.querySelectorAll('.job-endpoint').forEach(cb => cb.checked = false);
        
        if (jobType === 'full_refresh') {
            document.querySelectorAll('.job-endpoint').forEach(cb => cb.checked = true);
        } else if (jobType === 'last_30_days_crashes') {
            document.getElementById('endpoint-crashes').checked = true;
        } else if (jobType === 'last_30_days_people') {
            document.getElementById('endpoint-people').checked = true;
        } else if (jobType === 'last_6_months_fatalities') {
            document.getElementById('endpoint-fatalities').checked = true;
        }
    }
}

function updateExecutionFilter(jobsList) {
    const select = document.getElementById('execution-filter');
    const currentValue = select.value;
    
    select.innerHTML = '<option value="">All Jobs</option>';
    
    jobsList.forEach(job => {
        const option = document.createElement('option');
        option.value = job.id;
        option.textContent = `${job.name} (ID: ${job.id})`;
        select.appendChild(option);
    });
    
    select.value = currentValue;
    
    select.addEventListener('change', function() {
        const jobId = this.value ? parseInt(this.value) : null;
        loadExecutions(jobId);
    });
}

function formatJobType(jobType) {
    return jobType.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function formatRecurrenceType(recurrenceType) {
    return recurrenceType.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function formatSortType(sortType) {
    const labels = {
        'alphabetic': 'Alphabetic',
        'numeric': 'Numeric',
        'natural': 'Natural'
    };
    return labels[sortType] || 'Alphabetic';
}

function getStatusIcon(status) {
    const icons = {
        running: 'arrow-repeat',
        completed: 'check-circle',
        failed: 'x-circle',
        pending: 'clock',
        cancelled: 'dash-circle'
    };
    return icons[status] || 'question-circle';
}

function getTimeAgo(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 30) return `${diffDays}d ago`;
    return date.toLocaleDateString();
}

function showToast(title, message, type = 'info') {
    const toast = document.getElementById('toast');
    const toastTitle = document.getElementById('toast-title');
    const toastBody = document.getElementById('toast-body');
    
    // Set content
    toastTitle.textContent = title;
    toastBody.textContent = message;
    
    // Set color based on type
    toast.className = `toast border-${type}`;
    toastTitle.className = `me-auto text-${type}`;
    
    // Show toast
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
}

function startAutoRefresh() {
    refreshTimer = setInterval(async () => {
        try {
            await loadDashboardData();
            
            // Only refresh active tab
            const activeTab = document.querySelector('.tab-pane.active');
            if (activeTab.id === 'jobs') {
                await loadJobs();
            } else if (activeTab.id === 'executions') {
                await loadExecutions();
            } else if (activeTab.id === 'spatial-layers') {
                await loadSpatialLayers();
            }
        } catch (error) {
            console.error('Auto-refresh failed:', error);
        }
    }, REFRESH_INTERVAL);
}

function refreshData() {
    loadDashboardData();
    loadJobs();
    loadExecutions();
    loadDataStatistics();
    loadSpatialLayers();
    showToast('Refreshed', 'Data refreshed successfully', 'success');
}

function resolveJobName(source) {
    if (!source) {
        return 'Unknown Job';
    }

    if (source.job_name) {
        return source.job_name;
    }

    const jobRecord = jobs.find(job => job.id === source.job_id);
    if (jobRecord?.name) {
        return jobRecord.name;
    }

    if (source.execution_context?.job?.name) {
        return source.execution_context.job.name;
    }

    return `Job ${source.job_id}`;
}

function capitalize(value) {
    if (!value || typeof value !== 'string') {
        return '';
    }
    return value.charAt(0).toUpperCase() + value.slice(1);
}

function escapeHtml(value) {
    if (value === null || value === undefined) {
        return '';
    }

    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
