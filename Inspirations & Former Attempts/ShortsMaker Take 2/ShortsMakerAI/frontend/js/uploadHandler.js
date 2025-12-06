import { domElements } from './domElements.js';
import { 
    updateUploadStatus, 
    toggleUploadButton, 
    showBackendProgress, 
    updateBackendProgress,
    updateClipCreationStatus // For resetting
} from './ui.js';
import { uploadVideoToServer } from './api.js';
import { getCurrentAdvancedSettings } from './presetManager.js';
import * as appState from './appState.js'; // Import appState

// State is now managed by appState.js

function handleVideoUpload(socket) { // stateAccessors removed from parameters
    console.log("UPLOAD_HANDLER: Upload button clicked. Socket connected:", socket.connected, "Socket ID:", socket.id);
    
    if (!domElements.videoFile.files || domElements.videoFile.files.length === 0) {
        updateUploadStatus('Please select a video file first.', 'red');
        return;
    }
    if (!socket.connected) {
        updateUploadStatus('Not connected to server. Please wait or refresh.', 'red');
        return;
    }

    const file = domElements.videoFile.files[0];
    const userKeywords = domElements.userKeywordsInput.value.trim();
    const aiPrompt = domElements.aiPromptTextarea.value.trim();
    const selectedModel = domElements.whisperModelSelect.value;
    const selectedComputeType = domElements.computeTypeSelect.value;
    const minDuration = domElements.minShortDurationInput.value;
    const maxDuration = domElements.maxShortDurationInput.value;

    const minDurationNum = parseFloat(minDuration);
    const maxDurationNum = parseFloat(maxDuration);

    if (isNaN(minDurationNum) || minDurationNum < 0 || isNaN(maxDurationNum) || maxDurationNum < 0 || minDurationNum >= maxDurationNum) {
        updateUploadStatus('Error: Invalid min/max short duration values.', 'red');
        return;
    }

    const formData = new FormData();
    formData.append('video', file);
    formData.append('whisper_model', selectedModel);
    formData.append('compute_type', selectedComputeType);
    formData.append('min_short_duration', minDuration);
    formData.append('max_short_duration', maxDuration);

    const advancedSettings = getCurrentAdvancedSettings();
    for (const formKey in advancedSettings) {
        const value = advancedSettings[formKey];
        let isTextTypeWithPlaceholder = false;
        // Check if the formKey from advancedSettings (which should be an HTML name attribute)
        // corresponds to a known DOM element to check its type and placeholder.
        // This assumes domElements keys might match formKey or a transformation of it.
        // For now, we rely on the value's characteristics.
        // A more robust way would be if getCurrentAdvancedSettings also returned type info.
        const element = document.getElementsByName(formKey)[0] || domElements[formKey]; // Try by name first

        if (element && element.type === 'text' && element.placeholder) {
            if (value === element.placeholder) {
                isTextTypeWithPlaceholder = true;
            }
        }
        
        if (value.length > 0 || typeof advancedSettings[formKey] === 'boolean' || advancedSettings[formKey] === true || advancedSettings[formKey] === false) {
             // Booleans from checkboxes are already strings "true"/"false" from presetManager
            formData.append(formKey, value);
        } else if (isTextTypeWithPlaceholder) {
            // Don't send if value is same as placeholder
        } else if (typeof value === 'string' && value.length === 0) {
            formData.append(formKey, value); // Send empty string for text inputs
        }
    }

    formData.append('language', domElements.whisperLanguageSelect.value);
    formData.append('task', domElements.whisperTaskSelect.value);

    if (userKeywords) {
        formData.append('user_keywords', userKeywords);
    }
    if (aiPrompt) {
        formData.append('ai_prompt', aiPrompt);
    }

    if (socket && socket.id) {
        formData.append('socket_id', socket.id);
    } else {
        updateUploadStatus('Error: Socket not connected or ID unavailable. Cannot proceed.', 'red');
        toggleUploadButton(false);
        return;
    }

    // Reset UI for new upload
    if (domElements.processingOutputSection) domElements.processingOutputSection.style.display = 'none';
    if (domElements.outputSection) domElements.outputSection.style.display = 'none';
    updateClipCreationStatus('');
    if (domElements.suggestedClipsContainer) domElements.suggestedClipsContainer.innerHTML = '';
    if (domElements.fullTranscriptDisplay) domElements.fullTranscriptDisplay.innerHTML = '';
    if (domElements.clipAdjustmentControls) domElements.clipAdjustmentControls.style.display = 'none';
    if (domElements.createSelectedClipButton) domElements.createSelectedClipButton.style.display = 'none';
    showBackendProgress(false);

    // Reset state variables using appState module
    if (appState.getEllipsisIntervalId()) {
        clearInterval(appState.getEllipsisIntervalId());
        appState.setEllipsisIntervalId(null);
    }
    appState.setLastProgressTimestamp(0);
    appState.setLastKnownProgressPercent(0);
    appState.setLastKnownMessage('');
    appState.setSelectedClipData(null);
    // appState.setOriginalVideoFilepath(null); // originalVideoFilepath is set by final_result handler

    let newTaskId;
    if (self.crypto && self.crypto.randomUUID) {
        newTaskId = self.crypto.randomUUID();
    } else {
        newTaskId = Date.now().toString(36) + Math.random().toString(36).substring(2);
    }
    appState.setCurrentTaskId(newTaskId); // Update currentTaskId using appState
    console.info(`UPLOAD_HANDLER: Generated client-side task_id: ${newTaskId}`);
    formData.append('task_id', newTaskId);

    toggleUploadButton(true); // Disable upload button
    if (domElements.cancelProcessingButton) {
        domElements.cancelProcessingButton.style.display = 'inline-block';
        domElements.cancelProcessingButton.disabled = false;
        domElements.cancelProcessingButton.textContent = 'Cancel Processing';
    }

    uploadVideoToServer(formData, domElements.uploadProgressBar, updateUploadStatus,
        (serverAssignedTaskId) => { // onUploadSuccess
            console.log("UPLOAD_HANDLER: Upload success. Client-generated Task ID was:", newTaskId, "Server's actual Task ID:", serverAssignedTaskId);
            if (serverAssignedTaskId) {
                appState.setCurrentTaskId(serverAssignedTaskId); // CRITICAL: Update appState with the server's task_id
                console.log("UPLOAD_HANDLER: appState.currentTaskId updated to server's ID:", serverAssignedTaskId);
            } else {
                // This case should ideally not happen if the server always returns a task_id on success.
                // If it can, we might fall back to the client-generated one, but it would indicate a server-side issue.
                console.warn("UPLOAD_HANDLER: Server did not return a task_id. Frontend will use client-generated ID, but this might lead to issues if server uses a different one.");
                // appState.setCurrentTaskId(newTaskId); // Already set, but good to be aware
            }
            showBackendProgress(true);
            updateBackendProgress(0, 'Server processing initiated...');
        },
        (errorMsg) => { // onUploadError
            toggleUploadButton(false); // Re-enable upload button
            if (domElements.cancelProcessingButton) domElements.cancelProcessingButton.style.display = 'none';
            showBackendProgress(false);
        }
    );
}


export function initUploadHandler(socket) { // stateAccessors removed
    if (domElements.uploadButton) {
        domElements.uploadButton.addEventListener('click', () => handleVideoUpload(socket));
    }
}
