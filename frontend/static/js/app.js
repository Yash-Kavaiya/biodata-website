/**
 * Biodata Management System - Frontend Application
 */

const API_BASE = '/api';

// State management
const state = {
    currentPage: 'upload',
    biodatas: [],
    pendingValidation: [],
    searchResults: [],
    uploadQueue: []
};

// DOM Elements
const elements = {
    navLinks: document.querySelectorAll('.nav-links a'),
    pageSections: document.querySelectorAll('.page-section'),
    uploadArea: document.getElementById('uploadArea'),
    fileInput: document.getElementById('fileInput'),
    uploadQueue: document.getElementById('uploadQueue'),
    biodataTable: document.getElementById('biodataTable'),
    validationList: document.getElementById('validationList'),
    searchResults: document.getElementById('searchResults'),
    toastContainer: document.getElementById('toastContainer')
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initUpload();
    initSearch();
    loadInitialData();
});

// Navigation
function initNavigation() {
    document.querySelectorAll('.nav-links a').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const page = link.dataset.page;
            navigateTo(page);
        });
    });
}

function navigateTo(page) {
    state.currentPage = page;

    // Update nav links
    document.querySelectorAll('.nav-links a').forEach(link => {
        link.classList.toggle('active', link.dataset.page === page);
    });

    // Update page sections
    document.querySelectorAll('.page-section').forEach(section => {
        section.classList.toggle('active', section.id === `${page}Page`);
    });

    // Load data for page
    switch(page) {
        case 'upload':
            break;
        case 'validation':
            loadPendingValidation();
            break;
        case 'biodatas':
            loadBiodatas();
            break;
        case 'search':
            loadSearchStats();
            break;
    }
}

// Upload functionality
function initUpload() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');

    if (!uploadArea || !fileInput) return;

    // Click to upload
    uploadArea.addEventListener('click', () => fileInput.click());

    // Drag and drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('drag-over');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('drag-over');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('drag-over');
        const files = Array.from(e.dataTransfer.files);
        handleFiles(files);
    });

    // File input change
    fileInput.addEventListener('change', (e) => {
        const files = Array.from(e.target.files);
        handleFiles(files);
        fileInput.value = '';
    });
}

async function handleFiles(files) {
    const validFiles = files.filter(f => {
        const ext = f.name.split('.').pop().toLowerCase();
        return ['pdf', 'png', 'jpg', 'jpeg'].includes(ext);
    });

    if (validFiles.length === 0) {
        showToast('No valid files selected. Allowed: PDF, PNG, JPG', 'error');
        return;
    }

    // Add to queue
    validFiles.forEach(file => {
        const id = Date.now() + Math.random().toString(36).substr(2, 9);
        state.uploadQueue.push({
            id,
            file,
            name: file.name,
            status: 'pending',
            progress: 0
        });
    });

    renderUploadQueue();

    // Process uploads
    if (validFiles.length === 1) {
        await uploadSingleFile(state.uploadQueue[state.uploadQueue.length - 1]);
    } else {
        await uploadBulkFiles(validFiles);
    }
}

async function uploadSingleFile(queueItem) {
    queueItem.status = 'uploading';
    renderUploadQueue();

    const formData = new FormData();
    formData.append('file', queueItem.file);

    try {
        const response = await fetch(`${API_BASE}/upload/single`, {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (response.ok) {
            queueItem.status = 'completed';
            queueItem.result = result;
            showToast(`${queueItem.name} uploaded successfully!`, 'success');
        } else {
            queueItem.status = 'failed';
            queueItem.error = result.detail || 'Upload failed';
            showToast(`Failed to upload ${queueItem.name}`, 'error');
        }
    } catch (error) {
        queueItem.status = 'failed';
        queueItem.error = error.message;
        showToast(`Error uploading ${queueItem.name}`, 'error');
    }

    renderUploadQueue();
}

async function uploadBulkFiles(files) {
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));

    // Update all queue items to uploading
    state.uploadQueue.forEach(item => {
        if (item.status === 'pending') {
            item.status = 'uploading';
        }
    });
    renderUploadQueue();

    try {
        const response = await fetch(`${API_BASE}/upload/bulk`, {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (response.ok) {
            // Update queue items with results
            result.uploads.forEach((upload, i) => {
                const queueItem = state.uploadQueue.find(q => q.name === upload.filename);
                if (queueItem) {
                    queueItem.status = upload.status === 'failed' ? 'failed' : 'completed';
                    queueItem.result = upload;
                }
            });

            showToast(`Uploaded ${result.successful}/${result.total} files`,
                result.failed > 0 ? 'error' : 'success');
        } else {
            state.uploadQueue.forEach(item => {
                if (item.status === 'uploading') {
                    item.status = 'failed';
                }
            });
            showToast('Bulk upload failed', 'error');
        }
    } catch (error) {
        state.uploadQueue.forEach(item => {
            if (item.status === 'uploading') {
                item.status = 'failed';
                item.error = error.message;
            }
        });
        showToast('Error during bulk upload', 'error');
    }

    renderUploadQueue();
}

function renderUploadQueue() {
    const container = document.getElementById('uploadQueue');
    if (!container) return;

    if (state.uploadQueue.length === 0) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = state.uploadQueue.map(item => `
        <div class="upload-item">
            <div class="upload-item-info">
                <div class="upload-item-name">${item.name}</div>
                <div class="upload-item-status">
                    ${item.status === 'pending' ? 'Waiting...' : ''}
                    ${item.status === 'uploading' ? 'Uploading...' : ''}
                    ${item.status === 'completed' ? `Completed - ${item.result?.message || 'Success'}` : ''}
                    ${item.status === 'failed' ? `Failed - ${item.error || 'Error'}` : ''}
                </div>
            </div>
            <span class="badge badge-${item.status}">${item.status}</span>
        </div>
    `).join('');
}

// Biodata Table
async function loadBiodatas(page = 1) {
    const container = document.getElementById('biodataTable');
    if (!container) return;

    container.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

    try {
        const response = await fetch(`${API_BASE}/biodata?page=${page}&page_size=20`);
        const data = await response.json();

        state.biodatas = data.items;
        renderBiodataTable(data);
    } catch (error) {
        container.innerHTML = `<div class="empty-state">
            <div class="empty-state-text">Failed to load biodatas</div>
        </div>`;
    }
}

function renderBiodataTable(data) {
    const container = document.getElementById('biodataTable');
    if (!container) return;

    if (data.items.length === 0) {
        container.innerHTML = `<div class="empty-state">
            <div class="empty-state-icon">📋</div>
            <div class="empty-state-text">No biodatas found</div>
            <p>Upload some biodata files to get started</p>
        </div>`;
        return;
    }

    container.innerHTML = `
        <div class="table-container">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Age</th>
                        <th>Gender</th>
                        <th>Education</th>
                        <th>Location</th>
                        <th>Status</th>
                        <th>Confidence</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.items.map(biodata => `
                        <tr>
                            <td>${biodata.name || '-'}</td>
                            <td>${biodata.age || '-'}</td>
                            <td>${biodata.gender || '-'}</td>
                            <td>${biodata.education || '-'}</td>
                            <td>${biodata.current_city || biodata.state || '-'}</td>
                            <td><span class="badge badge-${biodata.ocr_status}">${biodata.ocr_status}</span></td>
                            <td>
                                <div class="confidence-indicator">
                                    <div class="confidence-bar">
                                        <div class="confidence-fill ${getConfidenceClass(biodata.ocr_confidence)}"
                                             style="width: ${(biodata.ocr_confidence || 0) * 100}%"></div>
                                    </div>
                                    <span>${Math.round((biodata.ocr_confidence || 0) * 100)}%</span>
                                </div>
                            </td>
                            <td>
                                <div class="btn-group">
                                    <button class="btn btn-sm btn-secondary" onclick="viewBiodata('${biodata.id}')">View</button>
                                    <button class="btn btn-sm btn-danger" onclick="deleteBiodata('${biodata.id}')">Delete</button>
                                </div>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
        <div style="margin-top: 1rem; text-align: center; color: var(--text-secondary);">
            Showing ${data.items.length} of ${data.total} biodatas
        </div>
    `;
}

function getConfidenceClass(confidence) {
    if (!confidence) return 'low';
    if (confidence >= 0.7) return 'high';
    if (confidence >= 0.4) return 'medium';
    return 'low';
}

async function viewBiodata(id) {
    try {
        const response = await fetch(`${API_BASE}/biodata/${id}`);
        const biodata = await response.json();
        showBiodataModal(biodata);
    } catch (error) {
        showToast('Failed to load biodata details', 'error');
    }
}

async function deleteBiodata(id) {
    if (!confirm('Are you sure you want to delete this biodata?')) return;

    try {
        const response = await fetch(`${API_BASE}/biodata/${id}`, { method: 'DELETE' });
        if (response.ok) {
            showToast('Biodata deleted successfully', 'success');
            loadBiodatas();
        } else {
            showToast('Failed to delete biodata', 'error');
        }
    } catch (error) {
        showToast('Error deleting biodata', 'error');
    }
}

// Validation
async function loadPendingValidation() {
    const container = document.getElementById('validationList');
    if (!container) return;

    container.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

    try {
        const response = await fetch(`${API_BASE}/biodata/pending`);
        const data = await response.json();

        state.pendingValidation = data.items;
        renderValidationList(data.items);
    } catch (error) {
        container.innerHTML = `<div class="empty-state">
            <div class="empty-state-text">Failed to load pending validations</div>
        </div>`;
    }
}

function renderValidationList(items) {
    const container = document.getElementById('validationList');
    if (!container) return;

    if (items.length === 0) {
        container.innerHTML = `<div class="empty-state">
            <div class="empty-state-icon">✅</div>
            <div class="empty-state-text">No pending validations</div>
            <p>All OCR results have been validated</p>
        </div>`;
        return;
    }

    container.innerHTML = items.map(biodata => `
        <div class="validation-card">
            <div class="validation-header">
                <div>
                    <strong>${biodata.name || 'Unknown'}</strong>
                    <span class="badge badge-${biodata.ocr_status}" style="margin-left: 0.5rem;">${biodata.ocr_status}</span>
                </div>
                <div class="confidence-indicator">
                    <span>Confidence:</span>
                    <div class="confidence-bar">
                        <div class="confidence-fill ${getConfidenceClass(biodata.ocr_confidence)}"
                             style="width: ${(biodata.ocr_confidence || 0) * 100}%"></div>
                    </div>
                    <span>${Math.round((biodata.ocr_confidence || 0) * 100)}%</span>
                </div>
            </div>
            <div class="validation-body">
                <div class="form-row">
                    ${renderValidationFields(biodata)}
                </div>
            </div>
            <div class="validation-actions">
                <button class="btn btn-success" onclick="approveValidation('${biodata.id}')">
                    ✓ Approve
                </button>
                <button class="btn btn-warning" onclick="editValidation('${biodata.id}')">
                    ✎ Edit & Approve
                </button>
                <button class="btn btn-secondary" onclick="rerunOCR('${biodata.id}')">
                    ↻ Re-OCR
                </button>
                <button class="btn btn-danger" onclick="rejectValidation('${biodata.id}')">
                    ✕ Reject
                </button>
            </div>
        </div>
    `).join('');
}

function renderValidationFields(biodata) {
    const fields = [
        { key: 'name', label: 'Name' },
        { key: 'age', label: 'Age' },
        { key: 'gender', label: 'Gender' },
        { key: 'education', label: 'Education' },
        { key: 'occupation', label: 'Occupation' },
        { key: 'religion', label: 'Religion' },
        { key: 'caste', label: 'Caste' },
        { key: 'current_city', label: 'City' },
        { key: 'state', label: 'State' },
        { key: 'contact_number', label: 'Contact' }
    ];

    return fields.map(f => `
        <div class="form-group">
            <label class="form-label">${f.label}</label>
            <input type="text" class="form-input" value="${biodata[f.key] || ''}"
                   data-biodata-id="${biodata.id}" data-field="${f.key}" readonly>
        </div>
    `).join('');
}

async function approveValidation(id) {
    try {
        const response = await fetch(`${API_BASE}/validation/approve/${id}`, { method: 'POST' });
        if (response.ok) {
            showToast('Biodata approved successfully', 'success');
            loadPendingValidation();
        } else {
            showToast('Failed to approve biodata', 'error');
        }
    } catch (error) {
        showToast('Error approving biodata', 'error');
    }
}

async function rejectValidation(id) {
    if (!confirm('Are you sure you want to reject this biodata?')) return;

    try {
        const response = await fetch(`${API_BASE}/validation/reject/${id}`, { method: 'POST' });
        if (response.ok) {
            showToast('Biodata rejected', 'success');
            loadPendingValidation();
        } else {
            showToast('Failed to reject biodata', 'error');
        }
    } catch (error) {
        showToast('Error rejecting biodata', 'error');
    }
}

async function rerunOCR(id) {
    showToast('Re-running OCR...', 'success');

    try {
        const response = await fetch(`${API_BASE}/validation/re-ocr/${id}`, { method: 'POST' });
        if (response.ok) {
            showToast('OCR re-processed successfully', 'success');
            loadPendingValidation();
        } else {
            showToast('Failed to re-run OCR', 'error');
        }
    } catch (error) {
        showToast('Error re-running OCR', 'error');
    }
}

async function editValidation(id) {
    const biodata = state.pendingValidation.find(b => b.id === id);
    if (!biodata) return;

    showEditModal(biodata);
}

async function autoApproveAll() {
    const confidence = document.getElementById('autoApproveConfidence')?.value || 0.7;

    try {
        const response = await fetch(`${API_BASE}/validation/auto-approve-all?min_confidence=${confidence}`, {
            method: 'POST'
        });
        const result = await response.json();

        showToast(`Auto-approved ${result.approved_count} biodatas`, 'success');
        loadPendingValidation();
    } catch (error) {
        showToast('Error during auto-approve', 'error');
    }
}

// Search
function initSearch() {
    const form = document.getElementById('searchForm');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await performSearch();
    });
}

async function performSearch() {
    const container = document.getElementById('searchResults');
    if (!container) return;

    container.innerHTML = '<div class="empty-state"><div class="spinner"></div></div>';

    const formData = new FormData(document.getElementById('searchForm'));
    const preferences = {
        gender: formData.get('gender') || null,
        min_age: formData.get('min_age') ? parseInt(formData.get('min_age')) : null,
        max_age: formData.get('max_age') ? parseInt(formData.get('max_age')) : null,
        religion: formData.get('religion') || null,
        caste: formData.get('caste') || null,
        education: formData.get('education') || null,
        location: formData.get('location') || null
    };

    // Remove null values
    Object.keys(preferences).forEach(key => {
        if (preferences[key] === null) delete preferences[key];
    });

    try {
        const response = await fetch(`${API_BASE}/search/preferences?limit=20`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(preferences)
        });

        const results = await response.json();
        state.searchResults = results;
        renderSearchResults(results);
    } catch (error) {
        container.innerHTML = `<div class="empty-state">
            <div class="empty-state-text">Search failed</div>
        </div>`;
    }
}

function renderSearchResults(results) {
    const container = document.getElementById('searchResults');
    if (!container) return;

    if (results.length === 0) {
        container.innerHTML = `<div class="empty-state">
            <div class="empty-state-icon">🔍</div>
            <div class="empty-state-text">No matches found</div>
            <p>Try adjusting your search criteria</p>
        </div>`;
        return;
    }

    container.innerHTML = `
        <div class="match-grid">
            ${results.map(match => `
                <div class="match-card">
                    <div class="match-card-header">
                        <div class="match-score">${Math.round(match.similarity_score * 100)}%</div>
                        <div class="match-score-label">Match Score</div>
                    </div>
                    <div class="match-card-body">
                        <div class="match-detail">
                            <span class="match-detail-label">Name</span>
                            <span class="match-detail-value">${match.biodata.name || '-'}</span>
                        </div>
                        <div class="match-detail">
                            <span class="match-detail-label">Age</span>
                            <span class="match-detail-value">${match.biodata.age || '-'}</span>
                        </div>
                        <div class="match-detail">
                            <span class="match-detail-label">Education</span>
                            <span class="match-detail-value">${match.biodata.education || '-'}</span>
                        </div>
                        <div class="match-detail">
                            <span class="match-detail-label">Occupation</span>
                            <span class="match-detail-value">${match.biodata.occupation || '-'}</span>
                        </div>
                        <div class="match-detail">
                            <span class="match-detail-label">Location</span>
                            <span class="match-detail-value">${match.biodata.current_city || match.biodata.state || '-'}</span>
                        </div>
                        ${match.match_reasons.length > 0 ? `
                            <div class="match-reasons">
                                <div class="match-reasons-title">Match Reasons:</div>
                                ${match.match_reasons.map(r => `
                                    <div class="match-reason-item">✓ ${r}</div>
                                `).join('')}
                            </div>
                        ` : ''}
                        <button class="btn btn-primary btn-sm" style="margin-top: 1rem; width: 100%;"
                                onclick="viewBiodata('${match.biodata.id}')">
                            View Full Profile
                        </button>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

async function loadSearchStats() {
    try {
        const response = await fetch(`${API_BASE}/search/stats`);
        const stats = await response.json();

        const container = document.getElementById('searchStats');
        if (container) {
            container.innerHTML = `
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-value">${stats.total_approved}</div>
                        <div class="stat-label">Total Profiles</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${stats.by_gender.male || 0}</div>
                        <div class="stat-label">Male Profiles</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${stats.by_gender.female || 0}</div>
                        <div class="stat-label">Female Profiles</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${stats.age_range.min || '-'} - ${stats.age_range.max || '-'}</div>
                        <div class="stat-label">Age Range</div>
                    </div>
                </div>
            `;
        }
    } catch (error) {
        console.error('Failed to load search stats', error);
    }
}

async function searchByUpload() {
    const fileInput = document.getElementById('searchFileInput');
    if (!fileInput || !fileInput.files.length) {
        showToast('Please select a file first', 'error');
        return;
    }

    const container = document.getElementById('searchResults');
    container.innerHTML = '<div class="empty-state"><div class="spinner"></div><p>Processing file and finding matches...</p></div>';

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    try {
        const response = await fetch(`${API_BASE}/search/by-upload?limit=20`, {
            method: 'POST',
            body: formData
        });

        const results = await response.json();
        renderSearchResults(results);
    } catch (error) {
        container.innerHTML = `<div class="empty-state">
            <div class="empty-state-text">Search failed</div>
        </div>`;
    }
}

// Modal
function showBiodataModal(biodata) {
    const modal = document.getElementById('biodataModal');
    const content = document.getElementById('modalContent');

    const fields = [
        { key: 'name', label: 'Name' },
        { key: 'age', label: 'Age' },
        { key: 'gender', label: 'Gender' },
        { key: 'date_of_birth', label: 'Date of Birth' },
        { key: 'height', label: 'Height' },
        { key: 'weight', label: 'Weight' },
        { key: 'complexion', label: 'Complexion' },
        { key: 'blood_group', label: 'Blood Group' },
        { key: 'education', label: 'Education' },
        { key: 'occupation', label: 'Occupation' },
        { key: 'income', label: 'Income' },
        { key: 'company', label: 'Company' },
        { key: 'father_name', label: 'Father Name' },
        { key: 'father_occupation', label: 'Father Occupation' },
        { key: 'mother_name', label: 'Mother Name' },
        { key: 'mother_occupation', label: 'Mother Occupation' },
        { key: 'siblings', label: 'Siblings' },
        { key: 'native_place', label: 'Native Place' },
        { key: 'current_city', label: 'Current City' },
        { key: 'state', label: 'State' },
        { key: 'country', label: 'Country' },
        { key: 'religion', label: 'Religion' },
        { key: 'caste', label: 'Caste' },
        { key: 'subcaste', label: 'Subcaste' },
        { key: 'gotra', label: 'Gotra' },
        { key: 'rashi', label: 'Rashi' },
        { key: 'nakshatra', label: 'Nakshatra' },
        { key: 'manglik', label: 'Manglik' },
        { key: 'contact_number', label: 'Contact Number' },
        { key: 'email', label: 'Email' },
        { key: 'marital_status', label: 'Marital Status' },
        { key: 'hobbies', label: 'Hobbies' },
        { key: 'about', label: 'About' },
        { key: 'partner_preferences', label: 'Partner Preferences' }
    ];

    content.innerHTML = `
        <div style="margin-bottom: 1rem;">
            <span class="badge badge-${biodata.ocr_status}">${biodata.ocr_status}</span>
            <span style="margin-left: 1rem;">Confidence: ${Math.round((biodata.ocr_confidence || 0) * 100)}%</span>
        </div>
        <div class="form-row">
            ${fields.map(f => `
                <div class="validation-field" style="display: ${biodata[f.key] ? 'grid' : 'none'};">
                    <span class="validation-field-label">${f.label}</span>
                    <span class="validation-field-value">${biodata[f.key] || '-'}</span>
                </div>
            `).join('')}
        </div>
    `;

    modal.classList.add('active');
}

function showEditModal(biodata) {
    const modal = document.getElementById('editModal');
    const content = document.getElementById('editModalContent');

    const fields = [
        { key: 'name', label: 'Name' },
        { key: 'age', label: 'Age', type: 'number' },
        { key: 'gender', label: 'Gender', type: 'select', options: ['male', 'female', 'other'] },
        { key: 'education', label: 'Education' },
        { key: 'occupation', label: 'Occupation' },
        { key: 'religion', label: 'Religion' },
        { key: 'caste', label: 'Caste' },
        { key: 'current_city', label: 'Current City' },
        { key: 'state', label: 'State' },
        { key: 'contact_number', label: 'Contact' },
        { key: 'email', label: 'Email', type: 'email' }
    ];

    content.innerHTML = `
        <form id="editForm" data-biodata-id="${biodata.id}">
            <div class="form-row">
                ${fields.map(f => `
                    <div class="form-group">
                        <label class="form-label">${f.label}</label>
                        ${f.type === 'select' ? `
                            <select class="form-select" name="${f.key}">
                                <option value="">Select...</option>
                                ${f.options.map(o => `
                                    <option value="${o}" ${biodata[f.key] === o ? 'selected' : ''}>${o}</option>
                                `).join('')}
                            </select>
                        ` : `
                            <input type="${f.type || 'text'}" class="form-input" name="${f.key}"
                                   value="${biodata[f.key] || ''}">
                        `}
                    </div>
                `).join('')}
            </div>
        </form>
    `;

    modal.classList.add('active');
}

async function saveEditAndApprove() {
    const form = document.getElementById('editForm');
    const id = form.dataset.biodataId;
    const formData = new FormData(form);

    const updateData = {};
    formData.forEach((value, key) => {
        if (value) {
            updateData[key] = key === 'age' ? parseInt(value) : value;
        }
    });

    try {
        const response = await fetch(`${API_BASE}/validation/edit/${id}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updateData)
        });

        if (response.ok) {
            closeModal('editModal');
            showToast('Biodata updated and approved', 'success');
            loadPendingValidation();
        } else {
            showToast('Failed to update biodata', 'error');
        }
    } catch (error) {
        showToast('Error updating biodata', 'error');
    }
}

function closeModal(modalId) {
    document.getElementById(modalId).classList.remove('active');
}

// Toast notifications
function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    container.appendChild(toast);

    setTimeout(() => {
        toast.remove();
    }, 3000);
}

// Initial data load
async function loadInitialData() {
    // Nothing to load initially, data loads when navigating
}

// Expose functions to global scope for onclick handlers
window.viewBiodata = viewBiodata;
window.deleteBiodata = deleteBiodata;
window.approveValidation = approveValidation;
window.rejectValidation = rejectValidation;
window.rerunOCR = rerunOCR;
window.editValidation = editValidation;
window.autoApproveAll = autoApproveAll;
window.searchByUpload = searchByUpload;
window.closeModal = closeModal;
window.saveEditAndApprove = saveEditAndApprove;
window.performSearch = performSearch;
