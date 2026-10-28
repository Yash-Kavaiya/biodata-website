/**
 * Biodata Management System - AngularJS Application
 * Google Material Design 3 theme
 */

var app = angular.module('biodataApp', []);

var API_BASE = '/api';
var ALLOWED_EXTENSIONS = ['pdf', 'png', 'jpg', 'jpeg'];
var MULTIPART = { transformRequest: angular.identity, headers: { 'Content-Type': undefined } };

// Every biodata field, in display order. `type` drives the edit form control.
var BIODATA_FIELDS = [
    { key: 'name', label: 'Name', section: 'Personal' },
    { key: 'age', label: 'Age', type: 'number', section: 'Personal' },
    { key: 'gender', label: 'Gender', type: 'select', options: ['male', 'female', 'other'], section: 'Personal' },
    { key: 'date_of_birth', label: 'Date of Birth', section: 'Personal' },
    { key: 'marital_status', label: 'Marital Status', type: 'select', options: ['single', 'married', 'divorced', 'widowed'], section: 'Personal' },
    { key: 'height', label: 'Height', section: 'Personal' },
    { key: 'weight', label: 'Weight', section: 'Personal' },
    { key: 'complexion', label: 'Complexion', section: 'Personal' },
    { key: 'blood_group', label: 'Blood Group', section: 'Personal' },
    { key: 'education', label: 'Education', type: 'textarea', section: 'Career' },
    { key: 'occupation', label: 'Occupation', section: 'Career' },
    { key: 'company', label: 'Company', section: 'Career' },
    { key: 'income', label: 'Income', section: 'Career' },
    { key: 'father_name', label: 'Father Name', section: 'Family' },
    { key: 'father_occupation', label: 'Father Occupation', section: 'Family' },
    { key: 'mother_name', label: 'Mother Name', section: 'Family' },
    { key: 'mother_occupation', label: 'Mother Occupation', section: 'Family' },
    { key: 'siblings', label: 'Siblings', type: 'textarea', section: 'Family' },
    { key: 'native_place', label: 'Native Place', section: 'Location' },
    { key: 'current_city', label: 'Current City', section: 'Location' },
    { key: 'state', label: 'State', section: 'Location' },
    { key: 'country', label: 'Country', section: 'Location' },
    { key: 'religion', label: 'Religion', section: 'Community' },
    { key: 'caste', label: 'Caste', section: 'Community' },
    { key: 'subcaste', label: 'Subcaste', section: 'Community' },
    { key: 'gotra', label: 'Gotra', section: 'Community' },
    { key: 'rashi', label: 'Rashi', section: 'Horoscope' },
    { key: 'nakshatra', label: 'Nakshatra', section: 'Horoscope' },
    { key: 'manglik', label: 'Manglik', section: 'Horoscope' },
    { key: 'contact_number', label: 'Contact Number', section: 'Contact' },
    { key: 'email', label: 'Email', type: 'email', section: 'Contact' },
    { key: 'hobbies', label: 'Hobbies', type: 'textarea', section: 'About' },
    { key: 'about', label: 'About', type: 'textarea', section: 'About' },
    { key: 'partner_preferences', label: 'Partner Preferences', type: 'textarea', section: 'About' }
];

// Graph node colors come from the CSS data-viz tokens so light/dark stay in sync
var GRAPH_COLOR_TOKENS = {
    male: '--viz-1',
    female: '--viz-2',
    Religion: '--viz-3',
    Location: '--viz-4',
    Education: '--viz-5',
    Occupation: '--viz-6',
    Caste: '--md-sys-color-outline',
    Person: '--md-sys-color-outline'
};

var STATUS_LABELS = {
    completed: 'Needs review',
    pending: 'Pending',
    processing: 'Processing',
    approved: 'Approved',
    rejected: 'Rejected',
    failed: 'Failed'
};

function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function apiError(error, fallback) {
    var detail = error && error.data && error.data.detail;
    if (angular.isArray(detail)) {
        return detail.map(function (d) { return d.msg; }).join('; ');
    }
    return detail || fallback;
}

function extensionOf(name) {
    return (name.split('.').pop() || '').toLowerCase();
}

// ==============================================
// MAIN CONTROLLER
// ==============================================
app.controller('MainController', ['$scope', '$http', '$timeout', '$interval', '$q',
    function ($scope, $http, $timeout, $interval, $q) {

    // ==================== STATE ====================
    $scope.currentPage = 'upload';
    $scope.isLoading = false;
    $scope.isDragOver = false;
    $scope.appInfo = null;
    $scope.counts = {};

    $scope.availableModels = [];
    $scope.selectedModel = null;
    $scope.defaultModel = null;

    $scope.uploadType = 'files';
    $scope.uploadQueue = [];
    $scope.batchJob = null;
    var batchPoll = null;

    $scope.list = { items: [], total: 0, page: 1, pages: 1, pageSize: 20, q: '', status: '' };

    $scope.pendingValidation = [];
    $scope.reviewLimit = 20;
    $scope.autoApproveConfidence = 0.35;
    $scope.busy = {};  // biodata id -> true while an action is running

    $scope.searchTab = 'preferences';
    $scope.searchPrefs = {};
    $scope.searchResults = [];
    $scope.searchTitle = 'Search Results';
    $scope.searchStats = null;
    $scope.isSearching = false;
    $scope.hasSearched = false;
    $scope.searchFile = null;

    $scope.graphStats = null;
    $scope.graphEmpty = false;
    var network = null;

    $scope.selectedBiodata = null;
    $scope.editingBiodata = null;
    $scope.toasts = [];

    $scope.navItems = [
        { id: 'upload', label: 'Upload', icon: 'cloud_upload' },
        { id: 'validation', label: 'Review', icon: 'fact_check' },
        { id: 'biodatas', label: 'Profiles', icon: 'group' },
        { id: 'search', label: 'Match', icon: 'favorite' },
        { id: 'graph', label: 'Graph', icon: 'hub' }
    ];

    $scope.statusFilters = [
        { value: '', label: 'All' },
        { value: 'completed', label: 'Needs review' },
        { value: 'approved', label: 'Approved' },
        { value: 'rejected', label: 'Rejected' },
        { value: 'failed', label: 'Failed' }
    ];

    $scope.fields = BIODATA_FIELDS;
    $scope.summaryFields = BIODATA_FIELDS.filter(function (f) {
        return ['name', 'age', 'gender', 'education', 'occupation', 'religion', 'caste',
            'current_city', 'state', 'contact_number'].indexOf(f.key) !== -1;
    });
    $scope.fieldSections = BIODATA_FIELDS.reduce(function (sections, f) {
        if (sections.indexOf(f.section) === -1) sections.push(f.section);
        return sections;
    }, []);

    // ==================== INIT & NAVIGATION ====================
    $scope.init = function () {
        $http.get(API_BASE + '/info').then(function (r) { $scope.appInfo = r.data; });
        $scope.loadAvailableModels();
        $scope.refreshCounts();
    };

    $scope.navigateTo = function (page) {
        $scope.currentPage = page;
        window.scrollTo(0, 0);
        switch (page) {
            case 'validation': $scope.loadPendingValidation(); break;
            case 'biodatas': $scope.loadBiodatas(); break;
            case 'search': $scope.loadSearchStats(); break;
            case 'graph': $scope.loadGraph(); break;
        }
    };

    $scope.refreshCounts = function () {
        $http.get(API_BASE + '/biodata/stats').then(function (r) { $scope.counts = r.data; });
    };

    $scope.pendingCount = function () {
        return ($scope.counts.completed || 0) + ($scope.counts.pending || 0) + ($scope.counts.failed || 0);
    };

    // ==================== TOASTS ====================
    $scope.showToast = function (message, type) {
        var toast = { message: message, type: type || 'success' };
        $scope.toasts.push(toast);
        $timeout(function () {
            var i = $scope.toasts.indexOf(toast);
            if (i > -1) $scope.toasts.splice(i, 1);
        }, type === 'error' ? 6000 : 3000);
    };

    // ==================== MODELS ====================
    $scope.loadAvailableModels = function () {
        $http.get(API_BASE + '/upload/models').then(function (r) {
            $scope.availableModels = r.data.models || [];
            $scope.defaultModel = r.data.default;
            $scope.selectedModel = r.data.default;
            $scope.ocrProvider = r.data.provider;
        });
    };

    function modelQuery(prefix) {
        var usable = $scope.selectedModel && $scope.availableModels.indexOf($scope.selectedModel) !== -1;
        return usable ? prefix + 'model=' + encodeURIComponent($scope.selectedModel) : '';
    }

    // ==================== UPLOAD ====================
    $scope.triggerInput = function (id) {
        document.getElementById(id).click();
    };

    $scope.handleDragOver = function () { $scope.isDragOver = true; };
    $scope.handleDragLeave = function () { $scope.isDragOver = false; };
    $scope.handleDrop = function (event) {
        $scope.isDragOver = false;
        var dt = event.dataTransfer || (event.originalEvent && event.originalEvent.dataTransfer);
        $scope.addFiles(dt ? dt.files : []);
    };

    $scope.addFiles = function (fileList) {
        var files = [], skipped = 0;
        angular.forEach(fileList, function (file) {
            if (file.name.charAt(0) !== '.' && ALLOWED_EXTENSIONS.indexOf(extensionOf(file.name)) !== -1) {
                files.push(file);
            } else {
                skipped++;
            }
        });

        if (!files.length) {
            $scope.showToast('No supported files found. Allowed: PDF, PNG, JPG', 'error');
            return;
        }
        var maxFiles = ($scope.appInfo && $scope.appInfo.max_bulk_files) || 200;
        if (files.length > maxFiles) {
            $scope.showToast('Too many files (' + files.length + '). Maximum is ' + maxFiles + '.', 'error');
            return;
        }
        if (skipped) {
            $scope.showToast(skipped + ' unsupported file(s) skipped', 'error');
        }

        $scope.uploadQueue = files.map(function (file) {
            return { file: file, name: file.name, path: file.webkitRelativePath || file.name, status: 'uploading', message: '' };
        });

        if (files.length === 1) {
            uploadSingle($scope.uploadQueue[0]);
        } else {
            uploadBatch($scope.uploadQueue);
        }
    };

    function uploadSingle(item) {
        var form = new FormData();
        form.append('file', item.file);
        $http.post(API_BASE + '/upload/single' + modelQuery('?'), form, MULTIPART).then(function (r) {
            item.status = 'completed';
            item.message = r.data.message;
            item.id = r.data.id;
            $scope.showToast(item.name + ' processed. Review it on the Validation page.', 'success');
            $scope.refreshCounts();
        }).catch(function (error) {
            item.status = 'failed';
            item.message = apiError(error, 'Upload failed');
            $scope.showToast('Failed: ' + item.name, 'error');
        });
    }

    function uploadBatch(items) {
        var form = new FormData();
        items.forEach(function (item) { form.append('files', item.file); });

        $http.post(API_BASE + '/upload/async/bulk' + modelQuery('?'), form, MULTIPART).then(function (r) {
            items.forEach(function (item) { item.status = 'processing'; });
            $scope.showToast(r.data.queued + ' file(s) queued for OCR', 'success');
            startBatchPolling(r.data.job_id, items.length);
        }).catch(function (error) {
            items.forEach(function (item) {
                item.status = 'failed';
                item.message = apiError(error, 'Upload failed');
            });
            $scope.showToast('Upload failed: ' + apiError(error, 'unknown error'), 'error');
        });
    }

    function startBatchPolling(jobId, total) {
        stopBatchPolling();
        $scope.batchJob = { id: jobId, status: 'processing', total: total, processed: 0, successful: 0, failed: 0, progress_percent: 0 };
        pollBatch(jobId);
        batchPoll = $interval(function () { pollBatch(jobId); }, 2000);
    }

    function stopBatchPolling() {
        if (batchPoll) {
            $interval.cancel(batchPoll);
            batchPoll = null;
        }
    }

    function pollBatch(jobId) {
        $http.get(API_BASE + '/upload/batch/' + jobId + '/status').then(function (r) {
            $scope.batchJob = r.data;
            if (r.data.status === 'processing') return;
            stopBatchPolling();
            $http.get(API_BASE + '/upload/batch/' + jobId + '/results').then(function (res) {
                applyBatchResults(res.data);
            });
        });
    }

    function applyBatchResults(job) {
        var byName = {};
        (job.results || []).forEach(function (r) { byName[r.filename] = { status: 'completed', message: r.message }; });
        (job.errors || []).forEach(function (e) { byName[e.filename] = { status: 'failed', message: e.error }; });
        $scope.uploadQueue.forEach(function (item) {
            var outcome = byName[item.name];
            if (outcome) {
                item.status = outcome.status;
                item.message = outcome.message;
            } else if (item.status === 'processing') {
                item.status = job.status === 'cancelled' ? 'cancelled' : 'failed';
            }
        });
        var type = job.failed ? 'error' : 'success';
        $scope.showToast('Batch ' + job.status + ': ' + job.successful + ' succeeded, ' + job.failed + ' failed', type);
        $scope.refreshCounts();
    }

    $scope.cancelBatch = function () {
        if (!$scope.batchJob) return;
        $http.delete(API_BASE + '/upload/batch/' + $scope.batchJob.id).then(function () {
            $scope.showToast('Batch cancelled. Files already sent to OCR will still finish.', 'success');
        });
    };

    $scope.hasActiveUploads = function () {
        return $scope.uploadQueue.some(function (item) {
            return item.status === 'uploading' || item.status === 'processing';
        });
    };

    $scope.clearQueue = function () {
        stopBatchPolling();
        $scope.uploadQueue = [];
        $scope.batchJob = null;
    };

    $scope.$on('$destroy', stopBatchPolling);

    // ==================== ALL BIODATAS ====================
    $scope.loadBiodatas = function (page) {
        var list = $scope.list;
        if (page) list.page = page;
        $scope.isLoading = true;
        var params = { page: list.page, page_size: list.pageSize };
        if (list.q) params.q = list.q;
        if (list.status) params.status = list.status;

        $http.get(API_BASE + '/biodata', { params: params }).then(function (r) {
            list.items = r.data.items;
            list.total = r.data.total;
            list.pages = r.data.pages;
            if (list.page > list.pages) $scope.loadBiodatas(list.pages);
        }).catch(function (error) {
            $scope.showToast(apiError(error, 'Failed to load biodatas'), 'error');
        }).finally(function () {
            $scope.isLoading = false;
        });
    };

    $scope.setStatusFilter = function (status) {
        $scope.list.status = status;
        $scope.loadBiodatas(1);
    };

    $scope.globalSearch = function () {
        $scope.list.status = '';
        $scope.list.page = 1;
        $scope.navigateTo('biodatas');
    };

    $scope.clearGlobalSearch = function () {
        $scope.list.q = '';
        if ($scope.currentPage === 'biodatas') $scope.loadBiodatas(1);
    };

    $scope.viewBiodata = function (id) {
        $http.get(API_BASE + '/biodata/' + id).then(function (r) {
            $scope.selectedBiodata = r.data;
        }).catch(function (error) {
            $scope.showToast(apiError(error, 'Failed to load biodata'), 'error');
        });
    };

    $scope.closeModals = function () {
        $scope.selectedBiodata = null;
        $scope.editingBiodata = null;
    };

    $scope.deleteBiodata = function (biodata) {
        if (!confirm('Permanently delete the biodata for ' + (biodata.name || 'this person') + '?')) return;
        $http.delete(API_BASE + '/biodata/' + biodata.id).then(function () {
            $scope.showToast('Biodata deleted', 'success');
            $scope.closeModals();
            $scope.refreshCounts();
            if ($scope.currentPage === 'biodatas') $scope.loadBiodatas();
            if ($scope.currentPage === 'validation') $scope.loadPendingValidation();
        }).catch(function (error) {
            $scope.showToast(apiError(error, 'Failed to delete biodata'), 'error');
        });
    };

    // ==================== VALIDATION ====================
    $scope.showMoreReviews = function () {
        $scope.reviewLimit += 20;
    };

    $scope.loadPendingValidation = function () {
        $scope.isLoading = true;
        $http.get(API_BASE + '/biodata/pending').then(function (r) {
            $scope.pendingValidation = r.data.items;
        }).catch(function (error) {
            $scope.showToast(apiError(error, 'Failed to load pending validations'), 'error');
        }).finally(function () {
            $scope.isLoading = false;
        });
    };

    function runAction(biodata, request, successMessage) {
        $scope.busy[biodata.id] = true;
        return request.then(function (r) {
            $scope.showToast(successMessage, 'success');
            $scope.refreshCounts();
            if ($scope.currentPage === 'validation') $scope.loadPendingValidation();
            if ($scope.currentPage === 'biodatas') $scope.loadBiodatas();
            return r;
        }).catch(function (error) {
            $scope.showToast(apiError(error, 'Action failed'), 'error');
            if ($scope.currentPage === 'validation') $scope.loadPendingValidation();
            return $q.reject(error);
        }).finally(function () {
            delete $scope.busy[biodata.id];
        });
    }

    $scope.approve = function (biodata) {
        runAction(biodata, $http.post(API_BASE + '/validation/approve/' + biodata.id), 'Approved ' + (biodata.name || 'biodata'));
    };

    $scope.reject = function (biodata) {
        if (!confirm('Reject this biodata? It will be excluded from matching.')) return;
        runAction(biodata, $http.post(API_BASE + '/validation/reject/' + biodata.id), 'Biodata rejected');
    };

    $scope.rerunOCR = function (biodata) {
        runAction(biodata, $http.post(API_BASE + '/validation/re-ocr/' + biodata.id + modelQuery('?')), 'OCR re-processed');
    };

    $scope.editBiodata = function (biodata) {
        $scope.selectedBiodata = null;
        $scope.editingBiodata = angular.copy(biodata);
    };

    $scope.saveEditAndApprove = function () {
        var biodata = $scope.editingBiodata;
        var payload = {};
        BIODATA_FIELDS.forEach(function (f) {
            var value = biodata[f.key];
            if (typeof value === 'string') value = value.trim();
            payload[f.key] = (value === '' || value === undefined) ? null : value;
        });
        runAction(biodata, $http.post(API_BASE + '/validation/edit/' + biodata.id, payload), 'Saved and approved')
            .then(function () { $scope.editingBiodata = null; });
    };

    $scope.autoApproveAll = function () {
        var threshold = parseFloat($scope.autoApproveConfidence);
        if (isNaN(threshold) || threshold < 0 || threshold > 1) {
            $scope.showToast('Confidence threshold must be between 0 and 1', 'error');
            return;
        }
        if (!confirm('Approve every pending biodata with at least ' + Math.round(threshold * 100) + '% confidence?')) return;
        $http.post(API_BASE + '/validation/auto-approve-all', null, { params: { min_confidence: threshold } }).then(function (r) {
            $scope.showToast('Auto-approved ' + r.data.approved_count + ' biodata(s)', 'success');
            $scope.refreshCounts();
            $scope.loadPendingValidation();
        }).catch(function (error) {
            $scope.showToast(apiError(error, 'Auto-approve failed'), 'error');
        });
    };

    // ==================== SEARCH ====================
    $scope.loadSearchStats = function () {
        $http.get(API_BASE + '/search/stats').then(function (r) { $scope.searchStats = r.data; });
    };

    function runSearch(request, title) {
        $scope.isSearching = true;
        $scope.hasSearched = true;
        $scope.searchTitle = title;
        $scope.searchResults = [];
        request.then(function (r) {
            $scope.searchResults = r.data;
        }).catch(function (error) {
            $scope.showToast(apiError(error, 'Search failed'), 'error');
        }).finally(function () {
            $scope.isSearching = false;
        });
    }

    $scope.performSearch = function () {
        var prefs = {};
        angular.forEach($scope.searchPrefs, function (value, key) {
            if (value !== null && value !== undefined && value !== '') prefs[key] = value;
        });
        if (!Object.keys(prefs).length) {
            $scope.showToast('Enter at least one search criterion', 'error');
            return;
        }
        runSearch($http.post(API_BASE + '/search/preferences', prefs, { params: { limit: 20 } }), 'Search Results');
    };

    $scope.resetSearch = function () {
        $scope.searchPrefs = {};
        $scope.searchResults = [];
        $scope.hasSearched = false;
    };

    $scope.setSearchFile = function (files) {
        $scope.searchFile = files && files.length ? files[0] : null;
    };

    $scope.searchByUpload = function () {
        if (!$scope.searchFile) {
            $scope.showToast('Please select a file first', 'error');
            return;
        }
        var form = new FormData();
        form.append('file', $scope.searchFile);
        runSearch($http.post(API_BASE + '/search/by-upload?limit=20', form, MULTIPART),
            'Matches for ' + $scope.searchFile.name);
    };

    $scope.findMatchesFor = function (biodata) {
        $scope.closeModals();
        $scope.navigateTo('search');
        runSearch($http.post(API_BASE + '/search/by-biodata/' + biodata.id, null, { params: { limit: 20 } }),
            'Matches for ' + (biodata.name || 'selected profile'));
    };

    // ==================== GRAPH ====================
    $scope.loadGraph = function () {
        $scope.isLoading = true;
        $http.get(API_BASE + '/graph/stats').then(function (r) { $scope.graphStats = r.data; });
        $http.get(API_BASE + '/graph/data', { params: { limit: 100 } }).then(function (r) {
            $scope.graphEmpty = !r.data.nodes.length;
            // Render after Angular has shown the container
            $timeout(function () { renderGraph(r.data); });
        }).catch(function (error) {
            $scope.showToast(apiError(error, 'Failed to load graph'), 'error');
        }).finally(function () {
            $scope.isLoading = false;
        });
    };

    function renderGraph(data) {
        if (network) {
            network.destroy();
            network = null;
        }
        if (!data.nodes.length || typeof vis === 'undefined') return;

        var colorFor = function (key) { return cssVar(GRAPH_COLOR_TOKENS[key] || GRAPH_COLOR_TOKENS.Person); };
        var textColor = cssVar('--md-sys-color-on-surface');
        var lineColor = cssVar('--md-sys-color-outline-variant');
        var primary = cssVar('--md-sys-color-primary');

        var nodes = new vis.DataSet(data.nodes.map(function (node) {
            var isPerson = node.type === 'Person';
            var color = colorFor(isPerson ? (node.gender || 'Person') : node.type);
            var tooltip = isPerson
                ? [node.label, node.age ? node.age + ' yrs' : null, node.gender].filter(Boolean).join(' · ')
                : node.type + ': ' + node.label;
            return {
                id: node.id,
                label: node.label,
                title: tooltip,
                shape: isPerson ? 'dot' : 'box',
                size: isPerson ? 14 : undefined,
                shapeProperties: { borderRadius: 8 },
                color: { background: color, border: color, highlight: { background: color, border: primary } },
                font: isPerson
                    ? { size: 13, color: textColor, face: 'Roboto' }
                    : { size: 11, color: '#fff', face: 'Roboto' },
                isPerson: isPerson
            };
        }));

        var edges = new vis.DataSet(data.edges.map(function (edge, i) {
            var similar = edge.type === 'SIMILAR_TO';
            return {
                id: i,
                from: edge.source,
                to: edge.target,
                dashes: similar,
                width: similar ? 2 : 1,
                color: { color: similar ? primary : lineColor },
                title: similar ? 'Shares ' + edge.shared + ' attributes' : edge.type
            };
        }));

        var container = document.getElementById('network-container');
        network = new vis.Network(container, { nodes: nodes, edges: edges }, {
            physics: { stabilization: { iterations: 150 }, barnesHut: { gravitationalConstant: -3000, springLength: 120 } },
            interaction: { hover: true, tooltipDelay: 150 }
        });
        network.on('click', function (params) {
            if (!params.nodes.length) return;
            var node = nodes.get(params.nodes[0]);
            if (node.isPerson) {
                $scope.$apply(function () { $scope.viewBiodata(node.id); });
            }
        });
    }

    // ==================== HELPERS ====================
    $scope.getConfidenceClass = function (confidence) {
        if (!confidence) return 'low';
        if (confidence >= 0.7) return 'high';
        if (confidence >= 0.4) return 'medium';
        return 'low';
    };

    $scope.fileUrl = function (biodata) {
        return API_BASE + '/biodata/' + encodeURIComponent(biodata.id) + '/file';
    };

    $scope.hasValue = function (value) {
        return value !== null && value !== undefined && value !== '';
    };

    $scope.providerLabel = function () {
        return { nvidia: 'Nemotron', vertexai: 'Gemini', anthropic: 'Claude' }[$scope.ocrProvider] || 'No OCR';
    };

    $scope.truthy = function (value) { return !!value; };
    $scope.min = Math.min;

    $scope.statusLabel = function (status) {
        return STATUS_LABELS[status] || status;
    };

    $scope.initials = function (name) {
        if (!name) return '?';
        var parts = String(name).trim().split(/\s+/);
        var letters = parts[0].charAt(0) + (parts.length > 1 ? parts[parts.length - 1].charAt(0) : '');
        return letters.toUpperCase();
    };

    // ==================== THEME ====================
    function effectiveDark() {
        var forced = document.documentElement.getAttribute('data-theme');
        if (forced) return forced === 'dark';
        return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    }

    $scope.isDark = effectiveDark();

    $scope.toggleTheme = function () {
        var next = effectiveDark() ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        try { localStorage.setItem('biodata-theme', next); } catch (e) { }
        $scope.isDark = next === 'dark';
        if ($scope.currentPage === 'graph') $scope.loadGraph();
    };

    $scope.init();
}]);

// ==============================================
// DIRECTIVES
// ==============================================

// <input type="file" file-change="handler(files)">
app.directive('fileChange', function () {
    return {
        restrict: 'A',
        link: function (scope, element, attrs) {
            element.on('change', function (event) {
                var files = event.target.files;
                scope.$apply(function () {
                    scope.$eval(attrs.fileChange, { files: files });
                });
                if (attrs.fileReset !== undefined) event.target.value = '';  // allow re-selecting the same file
            });
        }
    };
});

// Drag-and-drop events: drop-over="fn($event)", drop-leave="fn($event)", drop-files="fn($event)"
['dropOver:dragover', 'dropLeave:dragleave', 'dropFiles:drop'].forEach(function (pair) {
    var parts = pair.split(':');
    app.directive(parts[0], function () {
        return function (scope, element, attrs) {
            element.on(parts[1], function (event) {
                event.preventDefault();
                scope.$apply(function () {
                    scope.$eval(attrs[parts[0]], { $event: event });
                });
            });
        };
    });
});

// Elevate the top app bar once the page scrolls (M3 "on scroll" app bar)
app.directive('scrollElevate', ['$window', function ($window) {
    return function (scope, element) {
        function update() {
            element.toggleClass('scrolled', $window.pageYOffset > 4);
        }
        angular.element($window).on('scroll', update);
        update();
    };
}]);

// Material ripple from the pointer position on every state-layer element
document.addEventListener('pointerdown', function (event) {
    var target = event.target.closest && event.target.closest('.state-layer');
    if (!target || target.disabled) return;
    var rect = target.getBoundingClientRect();
    var size = Math.max(rect.width, rect.height);
    var ripple = document.createElement('span');
    ripple.className = 'ripple';
    ripple.style.width = ripple.style.height = size + 'px';
    ripple.style.left = (event.clientX - rect.left - size / 2) + 'px';
    ripple.style.top = (event.clientY - rect.top - size / 2) + 'px';
    target.appendChild(ripple);
    setTimeout(function () { ripple.remove(); }, 600);
});

// Close modals with Escape
app.run(['$rootScope', '$document', function ($rootScope, $document) {
    $document.on('keydown', function (event) {
        if (event.key === 'Escape') {
            $rootScope.$broadcast('escape');
        }
    });
}]);

app.directive('closeOnEscape', function () {
    return function (scope, element, attrs) {
        scope.$on('escape', function () {
            scope.$apply(attrs.closeOnEscape);
        });
    };
});
