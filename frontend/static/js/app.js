/**
 * Biodata Management System - AngularJS Application
 * Wedding Theme Edition
 */

// Create the AngularJS module
var app = angular.module('biodataApp', []);

// API Base URL
var API_BASE = '/api';

// ==============================================
// MAIN CONTROLLER
// ==============================================
app.controller('MainController', ['$scope', '$http', '$timeout', function ($scope, $http, $timeout) {

    // ==================== STATE ====================
    $scope.currentPage = 'upload';
    $scope.isLoading = false;
    $scope.isDragOver = false;

    // Models
    $scope.availableModels = [];
    $scope.selectedModel = null;
    $scope.defaultModel = null;

    // Upload
    $scope.uploadQueue = [];
    $scope.uploadType = 'files';  // 'files' or 'folder'
    $scope.batchJob = null;
    $scope.batchPollInterval = null;

    // Biodatas
    $scope.biodatas = [];
    $scope.totalBiodatas = 0;

    // Validation
    $scope.pendingValidation = [];
    $scope.autoApproveConfidence = 0.35;

    // Search
    $scope.searchTab = 'preferences';
    $scope.searchPrefs = {};
    $scope.searchResults = [];
    $scope.searchStats = null;
    $scope.isSearching = false;
    $scope.hasSearched = false;

    // Graph
    $scope.graphData = null;
    $scope.graphStats = null;
    $scope.network = null;

    // Modals
    $scope.showBiodataModal = false;
    $scope.showEditModal = false;
    $scope.selectedBiodata = null;
    $scope.editingBiodata = null;

    // Toasts
    $scope.toasts = [];

    // Field definitions
    $scope.validationFields = [
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

    $scope.editFields = [
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

    $scope.allFields = [
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

    // ==================== INITIALIZATION ====================
    $scope.init = function () {
        $scope.loadAvailableModels();
    };

    // ==================== NAVIGATION ====================
    $scope.navigateTo = function (page) {
        $scope.currentPage = page;

        switch (page) {
            case 'validation':
                $scope.loadPendingValidation();
                break;
            case 'biodatas':
                $scope.loadBiodatas();
                break;
            case 'search':
                $scope.loadSearchStats();
                break;
            case 'graph':
                $scope.loadGraphData();
                break;
        }
    };

    // ==================== TOAST ====================
    $scope.showToast = function (message, type) {
        type = type || 'success';
        var toast = { message: message, type: type };
        $scope.toasts.push(toast);

        $timeout(function () {
            var index = $scope.toasts.indexOf(toast);
            if (index > -1) {
                $scope.toasts.splice(index, 1);
            }
        }, 3000);
    };

    // ==================== MODELS ====================
    $scope.loadAvailableModels = function () {
        $http.get(API_BASE + '/upload/models')
            .then(function (response) {
                $scope.availableModels = response.data.models;
                $scope.defaultModel = response.data.default;
                $scope.selectedModel = response.data.default;
            })
            .catch(function (error) {
                console.error('Failed to load models:', error);
                $scope.availableModels = [
                    'gemini-2.0-flash-001',
                    'gemini-2.0-flash-lite-001',
                    'gemini-2.5-pro-preview-06-05',
                    'gemini-2.5-flash-preview-05-20'
                ];
                $scope.selectedModel = 'gemini-2.0-flash-001';
                $scope.defaultModel = 'gemini-2.0-flash-001';
            });
    };

    // ==================== UPLOAD ====================
    $scope.triggerFileInput = function () {
        document.getElementById('fileInput').click();
    };

    $scope.handleDragOver = function (event) {
        event.preventDefault();
        $scope.isDragOver = true;
    };

    $scope.handleDrop = function (event) {
        event.preventDefault();
        $scope.isDragOver = false;
        var files = event.dataTransfer ? event.dataTransfer.files : [];
        $scope.processFiles(files);
    };

    $scope.handleFileSelect = function (files) {
        $scope.$apply(function () {
            $scope.processFiles(files);
        });
    };

    $scope.processFiles = function (files) {
        var validFiles = [];
        for (var i = 0; i < files.length; i++) {
            var file = files[i];
            var ext = file.name.split('.').pop().toLowerCase();
            if (['pdf', 'png', 'jpg', 'jpeg'].indexOf(ext) !== -1) {
                validFiles.push(file);
            }
        }

        if (validFiles.length === 0) {
            $scope.showToast('No valid files selected. Allowed: PDF, PNG, JPG', 'error');
            return;
        }

        // Add to queue
        validFiles.forEach(function (file) {
            $scope.uploadQueue.push({
                id: Date.now() + Math.random().toString(36).substr(2, 9),
                file: file,
                name: file.name,
                status: 'pending',
                message: ''
            });
        });

        // Process uploads
        if (validFiles.length === 1) {
            $scope.uploadSingleFile($scope.uploadQueue[$scope.uploadQueue.length - 1]);
        } else {
            $scope.uploadBulkFiles(validFiles);
        }
    };

    $scope.uploadSingleFile = function (queueItem) {
        queueItem.status = 'uploading';

        var formData = new FormData();
        formData.append('file', queueItem.file);

        var modelParam = $scope.selectedModel ? '?model=' + encodeURIComponent($scope.selectedModel) : '';

        $http.post(API_BASE + '/upload/single' + modelParam, formData, {
            transformRequest: angular.identity,
            headers: { 'Content-Type': undefined }
        }).then(function (response) {
            queueItem.status = 'completed';
            queueItem.message = response.data.message;
            $scope.showToast(queueItem.name + ' uploaded successfully!', 'success');
        }).catch(function (error) {
            queueItem.status = 'failed';
            queueItem.error = error.data ? error.data.detail : 'Upload failed';
            $scope.showToast('Failed to upload ' + queueItem.name, 'error');
        });
    };

    $scope.uploadBulkFiles = function (files) {
        var formData = new FormData();
        files.forEach(function (file) {
            formData.append('files', file);
        });

        $scope.uploadQueue.forEach(function (item) {
            if (item.status === 'pending') {
                item.status = 'uploading';
            }
        });

        // Use async bulk endpoint for large batches (> 20 files)
        var endpoint = files.length > 20 ? '/upload/async/bulk' : '/upload/bulk';
        var modelParam = $scope.selectedModel ? '?model=' + encodeURIComponent($scope.selectedModel) : '';

        $http.post(API_BASE + endpoint + modelParam, formData, {
            transformRequest: angular.identity,
            headers: { 'Content-Type': undefined }
        }).then(function (response) {
            var result = response.data;

            // Check if async response (has job_id)
            if (result.job_id) {
                $scope.showToast('Batch upload started: ' + result.queued + ' files queued', 'success');
                $scope.startBatchPolling(result.job_id);
                return;
            }

            // Sync response
            result.uploads.forEach(function (upload) {
                var queueItem = $scope.uploadQueue.find(function (q) {
                    return q.name === upload.filename;
                });
                if (queueItem) {
                    queueItem.status = upload.status === 'failed' ? 'failed' : 'completed';
                    queueItem.message = upload.message;
                }
            });
            $scope.showToast('Uploaded ' + result.successful + '/' + result.total + ' files',
                result.failed > 0 ? 'error' : 'success');
        }).catch(function (error) {
            $scope.uploadQueue.forEach(function (item) {
                if (item.status === 'uploading') {
                    item.status = 'failed';
                    item.error = 'Upload failed';
                }
            });
            $scope.showToast('Bulk upload failed: ' + (error.data ? error.data.detail : 'Unknown error'), 'error');
        });
    };

    // ==================== FOLDER UPLOAD ====================
    $scope.triggerFolderInput = function () {
        document.getElementById('folderInput').click();
    };

    $scope.handleFolderSelect = function (files) {
        $scope.$apply(function () {
            $scope.processFolderFiles(files);
        });
    };

    $scope.processFolderFiles = function (files) {
        var validFiles = [];
        var skippedCount = 0;

        for (var i = 0; i < files.length; i++) {
            var file = files[i];
            var ext = file.name.split('.').pop().toLowerCase();

            // Skip hidden files and non-supported formats
            if (file.name.startsWith('.')) {
                skippedCount++;
                continue;
            }

            if (['pdf', 'png', 'jpg', 'jpeg'].indexOf(ext) !== -1) {
                validFiles.push(file);
            } else {
                skippedCount++;
            }
        }

        if (validFiles.length === 0) {
            $scope.showToast('No valid files found in folder. Supported: PDF, PNG, JPG', 'error');
            return;
        }

        if (validFiles.length > 200) {
            $scope.showToast('Too many files (' + validFiles.length + '). Maximum 200 files allowed.', 'error');
            return;
        }

        $scope.showToast('Found ' + validFiles.length + ' valid files' + (skippedCount > 0 ? ' (' + skippedCount + ' skipped)' : ''), 'success');

        // Clear old queue
        $scope.uploadQueue = [];

        // Add to queue
        validFiles.forEach(function (file) {
            $scope.uploadQueue.push({
                id: Date.now() + Math.random().toString(36).substr(2, 9),
                file: file,
                name: file.webkitRelativePath || file.name,
                status: 'pending',
                message: ''
            });
        });

        // Upload using async bulk endpoint
        $scope.uploadFolderAsync(validFiles);
    };

    $scope.uploadFolderAsync = function (files) {
        var formData = new FormData();
        files.forEach(function (file) {
            formData.append('files', file);
        });

        $scope.uploadQueue.forEach(function (item) {
            item.status = 'uploading';
        });

        var modelParam = $scope.selectedModel ? '?model=' + encodeURIComponent($scope.selectedModel) : '';

        $http.post(API_BASE + '/upload/async/bulk' + modelParam, formData, {
            transformRequest: angular.identity,
            headers: { 'Content-Type': undefined }
        }).then(function (response) {
            var result = response.data;
            $scope.showToast('Folder upload started: ' + result.queued + ' files queued for processing', 'success');

            // Show validation errors immediately
            if (result.validation_errors > 0) {
                $scope.showToast(result.validation_errors + ' files failed validation', 'error');
            }

            // Start polling for progress
            $scope.startBatchPolling(result.job_id);
        }).catch(function (error) {
            $scope.uploadQueue.forEach(function (item) {
                item.status = 'failed';
                item.error = 'Upload failed';
            });
            $scope.showToast('Folder upload failed: ' + (error.data ? error.data.detail : 'Unknown error'), 'error');
        });
    };

    // ==================== BATCH PROGRESS POLLING ====================
    $scope.startBatchPolling = function (jobId) {
        // Clear any existing poll
        if ($scope.batchPollInterval) {
            clearInterval($scope.batchPollInterval);
        }

        $scope.batchJob = {
            id: jobId,
            status: 'processing',
            total: $scope.uploadQueue.length,
            processed: 0,
            successful: 0,
            failed: 0,
            progress_percent: 0,
            errors: []
        };

        // Poll every 2 seconds
        $scope.batchPollInterval = setInterval(function () {
            $scope.pollBatchStatus(jobId);
        }, 2000);

        // Initial poll
        $scope.pollBatchStatus(jobId);
    };

    $scope.pollBatchStatus = function (jobId) {
        $http.get(API_BASE + '/upload/batch/' + jobId + '/status')
            .then(function (response) {
                $scope.batchJob = response.data;

                // Update upload queue items based on progress
                var processedCount = response.data.processed;
                $scope.uploadQueue.forEach(function (item, index) {
                    if (index < processedCount) {
                        item.status = 'completed';
                    }
                });

                // Check if complete
                if (response.data.status !== 'processing') {
                    $scope.stopBatchPolling();

                    if (response.data.status === 'completed') {
                        $scope.showToast('All ' + response.data.successful + ' files processed successfully!', 'success');
                    } else if (response.data.status === 'partial') {
                        $scope.showToast('Batch completed: ' + response.data.successful + ' success, ' + response.data.failed + ' failed', 'error');
                    } else if (response.data.status === 'failed') {
                        $scope.showToast('Batch failed: ' + response.data.failed + ' files failed', 'error');
                    }

                    // Mark failed items in queue
                    if (response.data.errors && response.data.errors.length > 0) {
                        response.data.errors.forEach(function (err) {
                            var queueItem = $scope.uploadQueue.find(function (q) {
                                return q.name.endsWith(err.filename) || q.name === err.filename;
                            });
                            if (queueItem) {
                                queueItem.status = 'failed';
                                queueItem.error = err.error;
                            }
                        });
                    }
                }
            })
            .catch(function (error) {
                console.error('Failed to poll batch status:', error);
                // Don't stop polling on transient errors
            });
    };

    $scope.stopBatchPolling = function () {
        if ($scope.batchPollInterval) {
            clearInterval($scope.batchPollInterval);
            $scope.batchPollInterval = null;
        }
    };

    // ==================== BIODATAS ====================
    $scope.loadBiodatas = function () {
        $scope.isLoading = true;

        $http.get(API_BASE + '/biodata?page=1&page_size=20')
            .then(function (response) {
                $scope.biodatas = response.data.items;
                $scope.totalBiodatas = response.data.total;
                $scope.isLoading = false;
            })
            .catch(function (error) {
                $scope.isLoading = false;
                $scope.showToast('Failed to load biodatas', 'error');
            });
    };

    $scope.viewBiodata = function (id) {
        $http.get(API_BASE + '/biodata/' + id)
            .then(function (response) {
                $scope.selectedBiodata = response.data;
                $scope.showBiodataModal = true;
            })
            .catch(function (error) {
                $scope.showToast('Failed to load biodata details', 'error');
            });
    };

    $scope.deleteBiodata = function (id) {
        if (!confirm('Are you sure you want to delete this biodata?')) return;

        $http.delete(API_BASE + '/biodata/' + id)
            .then(function (response) {
                $scope.showToast('Biodata deleted successfully', 'success');
                $scope.loadBiodatas();
            })
            .catch(function (error) {
                $scope.showToast('Failed to delete biodata', 'error');
            });
    };

    $scope.closeBiodataModal = function (event) {
        if (event.target === event.currentTarget) {
            $scope.showBiodataModal = false;
        }
    };

    // ==================== VALIDATION ====================
    $scope.loadPendingValidation = function () {
        $scope.isLoading = true;

        $http.get(API_BASE + '/biodata/pending')
            .then(function (response) {
                $scope.pendingValidation = response.data.items;
                $scope.isLoading = false;
            })
            .catch(function (error) {
                $scope.isLoading = false;
                $scope.showToast('Failed to load pending validations', 'error');
            });
    };

    $scope.approveValidation = function (id) {
        $http.post(API_BASE + '/validation/approve/' + id)
            .then(function (response) {
                $scope.showToast('Biodata approved successfully', 'success');
                $scope.loadPendingValidation();
            })
            .catch(function (error) {
                $scope.showToast('Failed to approve biodata', 'error');
            });
    };

    $scope.rejectValidation = function (id) {
        if (!confirm('Are you sure you want to reject this biodata?')) return;

        $http.post(API_BASE + '/validation/reject/' + id)
            .then(function (response) {
                $scope.showToast('Biodata rejected', 'success');
                $scope.loadPendingValidation();
            })
            .catch(function (error) {
                $scope.showToast('Failed to reject biodata', 'error');
            });
    };

    $scope.rerunOCR = function (id) {
        $scope.showToast('Re-running OCR...', 'success');

        $http.post(API_BASE + '/validation/re-ocr/' + id)
            .then(function (response) {
                $scope.showToast('OCR re-processed successfully', 'success');
                $scope.loadPendingValidation();
            })
            .catch(function (error) {
                $scope.showToast('Failed to re-run OCR', 'error');
            });
    };

    $scope.editValidation = function (biodata) {
        $scope.editingBiodata = angular.copy(biodata);
        $scope.showEditModal = true;
    };

    $scope.closeEditModal = function (event) {
        if (event.target === event.currentTarget) {
            $scope.showEditModal = false;
        }
    };

    $scope.saveEditAndApprove = function () {
        if (!$scope.editingBiodata) return;

        $http.put(API_BASE + '/biodata/' + $scope.editingBiodata.id, $scope.editingBiodata)
            .then(function (response) {
                return $http.post(API_BASE + '/validation/approve/' + $scope.editingBiodata.id);
            })
            .then(function (response) {
                $scope.showToast('Biodata saved and approved', 'success');
                $scope.showEditModal = false;
                $scope.loadPendingValidation();
            })
            .catch(function (error) {
                $scope.showToast('Failed to save biodata', 'error');
            });
    };

    $scope.autoApproveAll = function () {
        var confidence = $scope.autoApproveConfidence || 0.35;

        $http.post(API_BASE + '/validation/auto-approve-all?min_confidence=' + confidence)
            .then(function (response) {
                $scope.showToast('Auto-approved ' + response.data.approved_count + ' biodatas', 'success');
                $scope.loadPendingValidation();
            })
            .catch(function (error) {
                $scope.showToast('Error during auto-approve', 'error');
            });
    };

    // ==================== SEARCH ====================
    $scope.loadSearchStats = function () {
        $http.get(API_BASE + '/search/stats')
            .then(function (response) {
                $scope.searchStats = response.data;
            })
            .catch(function (error) {
                console.error('Failed to load search stats', error);
            });
    };

    $scope.performSearch = function () {
        $scope.isSearching = true;
        $scope.hasSearched = true;

        var preferences = {};
        if ($scope.searchPrefs.gender) preferences.gender = $scope.searchPrefs.gender;
        if ($scope.searchPrefs.min_age) preferences.min_age = parseInt($scope.searchPrefs.min_age);
        if ($scope.searchPrefs.max_age) preferences.max_age = parseInt($scope.searchPrefs.max_age);
        if ($scope.searchPrefs.religion) preferences.religion = $scope.searchPrefs.religion;
        if ($scope.searchPrefs.caste) preferences.caste = $scope.searchPrefs.caste;
        if ($scope.searchPrefs.education) preferences.education = $scope.searchPrefs.education;
        if ($scope.searchPrefs.location) preferences.location = $scope.searchPrefs.location;

        $http.post(API_BASE + '/search/preferences?limit=20', preferences)
            .then(function (response) {
                $scope.searchResults = response.data;
                $scope.isSearching = false;
            })
            .catch(function (error) {
                $scope.isSearching = false;
                $scope.showToast('Search failed', 'error');
            });
    };

    $scope.searchByUpload = function () {
        var fileInput = document.getElementById('searchFileInput');
        if (!fileInput || !fileInput.files.length) {
            $scope.showToast('Please select a file first', 'error');
            return;
        }

        $scope.isSearching = true;
        $scope.hasSearched = true;

        var formData = new FormData();
        formData.append('file', fileInput.files[0]);

        $http.post(API_BASE + '/search/by-upload?limit=20', formData, {
            transformRequest: angular.identity,
            headers: { 'Content-Type': undefined }
        }).then(function (response) {
            $scope.searchResults = response.data;
            $scope.isSearching = false;
        }).catch(function (error) {
            $scope.isSearching = false;
            $scope.showToast('Search failed', 'error');
        });
    };

    $scope.loadGraphData = function () {
        $http.get(API_BASE + '/search/graph?limit=100')
            .then(function (response) {
                $scope.graphData = response.data;
                $scope.renderGraph();
                $scope.showToast('Graph loaded successfully', 'success');
            })
            .catch(function (error) {
                $scope.showToast('Failed to load graph data', 'error');
            });
    };

    $scope.loadGraphStats = function () {
        // Note: This would need a separate endpoint for stats, but for now we'll use graph data
        $scope.showToast('Stats feature coming soon', 'info');
    };

    $scope.renderGraph = function () {
        if (!$scope.graphData || !$scope.graphData.nodes || $scope.graphData.nodes.length === 0) {
            return;
        }

        var container = document.getElementById('graphContainer');

        // Prepare nodes for Vis.js
        var nodes = $scope.graphData.nodes.map(function (node) {
            var color = '#97c2fc'; // default blue
            if (node.type === 'Person') {
                color = node.group === 'male' ? '#7be141' : '#e7717d'; // green for male, pink for female
            } else if (node.type === 'Religion') {
                color = '#ffa500'; // orange
            } else if (node.type === 'Caste') {
                color = '#ff6b6b'; // red
            } else if (node.type === 'Location') {
                color = '#4ecdc4'; // teal
            } else if (node.type === 'Education') {
                color = '#45b7d1'; // blue
            } else if (node.type === 'Occupation') {
                color = '#96ceb4'; // green
            }

            return {
                id: node.id,
                label: node.label || node.id,
                color: color,
                title: node.title || node.label,
                group: node.type
            };
        });

        // Prepare edges
        var edges = ($scope.graphData.edges || []).map(function (edge) {
            return {
                from: edge.source,
                to: edge.target,
                label: edge.type,
                arrows: 'to'
            };
        });

        var data = {
            nodes: new vis.DataSet(nodes),
            edges: new vis.DataSet(edges)
        };

        var options = {
            nodes: {
                shape: 'dot',
                size: 16,
                font: {
                    size: 12,
                    color: '#333'
                },
                borderWidth: 2
            },
            edges: {
                width: 2,
                font: {
                    size: 10,
                    align: 'middle'
                }
            },
            physics: {
                stabilization: false,
                barnesHut: {
                    gravitationalConstant: -80000,
                    springConstant: 0.001,
                    springLength: 200
                }
            },
            interaction: {
                hover: true,
                tooltipDelay: 200
            }
        };

        if ($scope.network) {
            $scope.network.destroy();
        }

        $scope.network = new vis.Network(container, data, options);
    };

    // ==================== GRAPH ====================
    $scope.loadGraphData = function () {
        $scope.isLoading = true;
        $http.get(API_BASE + '/search/graph')
            .then(function (response) {
                $scope.isLoading = false;
                $scope.renderGraph(response.data);
            })
            .catch(function (error) {
                $scope.isLoading = false;
                $scope.showToast('Failed to load graph data', 'error');
                console.error(error);
            });
    };

    $scope.renderGraph = function (data) {
        var container = document.getElementById('network-container');

        var nodes = new vis.DataSet(data.nodes.map(function (node) {
            var color = '#e3f2fd'; // Default Person
            var shape = 'dot';
            var icon = null;

            if (node.group === 'city') { color = '#e8f5e9'; shape = 'hexagon'; }
            else if (node.group === 'education') { color = '#fff3e0'; shape = 'box'; }
            else if (node.group === 'occupation') { color = '#f3e5f5'; shape = 'ellipse'; }
            else if (node.group === 'religion') { color = '#fce4ec'; shape = 'diamond'; }
            else if (node.group === 'caste') { color = '#e0f7fa'; shape = 'triangle'; }

            return {
                id: node.id,
                label: node.label,
                title: node.title,
                group: node.group,
                color: { background: color, border: color },
                font: { size: 14 }
            };
        }));

        var edges = new vis.DataSet(data.edges);

        var options = {
            nodes: {
                borderWidth: 1,
                shadow: true
            },
            edges: {
                width: 1,
                color: { inherit: 'from' },
                smooth: { type: 'continuous' }
            },
            physics: {
                stabilization: false,
                barnesHut: {
                    gravitationalConstant: -2000,
                    springConstant: 0.04,
                    springLength: 95
                }
            },
            groups: {
                person: { shape: 'dot', color: '#e3f2fd' }
            },
            interaction: {
                hover: true,
                tooltipDelay: 200
            }
        };

        var network = new vis.Network(container, { nodes: nodes, edges: edges }, options);

        network.on("click", function (params) {
            if (params.nodes.length > 0) {
                var nodeId = params.nodes[0];
                var node = nodes.get(nodeId);
                if (node.group === 'person') {
                    $scope.$apply(function () {
                        $scope.viewBiodata(node.id); // Open modal on click
                    });
                }
            }
        });
    };

    // ==================== HELPERS ====================
    $scope.getConfidenceClass = function (confidence) {
        if (!confidence) return 'low';
        if (confidence >= 0.7) return 'high';
        if (confidence >= 0.4) return 'medium';
        return 'low';
    };

    $scope.getFileUrl = function (filePath) {
        if (!filePath) return '#';
        // Handle Windows and Unix separators
        var filename = filePath.split(/[/\\]/).pop();
        return '/files/' + filename;
    };

    // Initialize
    $scope.init();
}]);

// ==============================================
// DIRECTIVES
// ==============================================

// Drag and Drop Directive
app.directive('ngDragover', function () {
    return function (scope, element, attrs) {
        element.bind('dragover', function (event) {
            event.preventDefault();
            scope.$apply(function () {
                scope.$eval(attrs.ngDragover, { $event: event });
            });
        });
    };
});

app.directive('ngDragleave', function () {
    return function (scope, element, attrs) {
        element.bind('dragleave', function (event) {
            scope.$apply(function () {
                scope.$eval(attrs.ngDragleave, { $event: event });
            });
        });
    };
});

app.directive('ngDrop', function () {
    return function (scope, element, attrs) {
        element.bind('drop', function (event) {
            event.preventDefault();
            scope.$apply(function () {
                scope.$eval(attrs.ngDrop, { $event: event });
            });
        });
    };
});

// Array find polyfill for older browsers
if (!Array.prototype.find) {
    Array.prototype.find = function (predicate) {
        for (var i = 0; i < this.length; i++) {
            if (predicate(this[i], i, this)) {
                return this[i];
            }
        }
        return undefined;
    };
}
