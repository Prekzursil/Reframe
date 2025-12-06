import * as appState from './appState.js'; // Import appState
import { domElements } from './domElements.js'; // Needed for registerSocketEventHandlers if it uses it directly
// ui.js functions will be passed via uiUpdateFns from main.js where needed

// Helper to update UI elements related to backend processing status
// This function is internal to this module or could be moved to ui.js if more generic
function updateProcessingStatusDisplay(isProcessing, message = '', progress = 0, uiUpdateFns) {
    if (uiUpdateFns && uiUpdateFns.updateBackendProgress) { // Ensure uiUpdateFns is checked first
        uiUpdateFns.updateBackendProgress(progress, message);
    }
    if (uiUpdateFns && uiUpdateFns.showBackendProgress) { // Ensure uiUpdateFns is checked first
        uiUpdateFns.showBackendProgress(isProcessing);
    }
}

// These handlers are now internal or called by registerSocketEventHandlers
function handleConnectInternal(uiUpdateFns, socketId) {
    console.log('SOCKET_HANDLERS.JS: ===== CONNECTED ===== SID:', socketId); 
    if (uiUpdateFns && uiUpdateFns.updateUploadStatus) {
        uiUpdateFns.updateUploadStatus('Connected to server. Ready to upload.', 'green');
    }
    if (uiUpdateFns && uiUpdateFns.toggleUploadButton) {
        uiUpdateFns.toggleUploadButton(false);
    }
}

function handleDisconnectInternal(uiUpdateFns) {
    console.log('SOCKET_HANDLERS.JS: ===== DISCONNECTED =====');
    // Direct DOM access for this specific check, consider passing domElements.uploadStatusEl if preferred
    const uploadStatusEl = document.getElementById('uploadStatus'); 
    if (uploadStatusEl && (uploadStatusEl.textContent.startsWith('Server:') || uploadStatusEl.textContent.startsWith('Processing'))) {
        if (uiUpdateFns && uiUpdateFns.updateUploadStatus) {
            uiUpdateFns.updateUploadStatus('Connection lost. Please refresh and try again.', 'red');
        }
    }
    if (uiUpdateFns && uiUpdateFns.toggleUploadButton) {
        uiUpdateFns.toggleUploadButton(true); // Disable upload on disconnect
    }
    updateProcessingStatusDisplay(false, 'Disconnected.', 0, uiUpdateFns);
}

export function handleProgressUpdate(data, uiUpdateFns) {
    // Add special flag for heartbeat messages to avoid logging spam
    if (!data.is_heartbeat) {
        console.log("[SocketHandler] handleProgressUpdate received data:", JSON.stringify(data));
    } else {
        console.log("[SocketHandler] Heartbeat update received for step:", data.step);
    }
    
    const currentTaskId = appState.getCurrentTaskId();
    
    if (!data.is_heartbeat) {
        console.log("[SocketHandler] Frontend currentTaskId from appState:", currentTaskId);
        console.log("[SocketHandler] Backend event task_id:", data.task_id);
    }

    if (data.task_id === currentTaskId) {
        if (!data.is_heartbeat) {
            console.log("[SocketHandler] Task ID MATCH! Preparing to call updateBackendProgress.");
        }
        
        if (uiUpdateFns && typeof uiUpdateFns.updateBackendProgress === 'function') {
            const stepName = data.step || '';
            
            // Reset timestamp when we get any progress message for a processing step
            appState.setLastProgressTimestamp(Date.now());
            
            // Store last known values for heartbeat reuse
            if (data.progress_percent !== undefined) {
                appState.setLastKnownProgressPercent(data.progress_percent);
            }
            if (data.message) {
                appState.setLastKnownMessage(data.message);
            }
            
            if (!data.is_heartbeat) {
                console.log(`[SocketHandler] About to call uiUpdateFns.updateBackendProgress with: percent=${data.progress_percent || 0}, message="${data.message || 'Processing...'}", stepName="${stepName}"`);
            }
            
            try {
                uiUpdateFns.updateBackendProgress(data.progress_percent || 0, data.message || 'Processing...', stepName);
            } catch (e) {
                console.error("[SocketHandler] ERROR during call to uiUpdateFns.updateBackendProgress:", e);
            }
        } else {
            console.error("[SocketHandler] ERROR: uiUpdateFns.updateBackendProgress is not defined or not a function. Type:", typeof uiUpdateFns.updateBackendProgress, "uiUpdateFns available:", !!uiUpdateFns);
        }
    } else {
        if (!data.is_heartbeat) {
            console.warn("[SocketHandler] Task ID MISMATCH - Ignoring event. Event TID:", data.task_id, "Frontend TID:", currentTaskId);
        }
    }
}

export function handleFinalResult(data, uiUpdateFns, displayProcessingOutputFn) {
    console.log("WebSocket Final Result:", data);
    const currentTaskId = appState.getCurrentTaskId();
    if (data.task_id === currentTaskId) {
        if (uiUpdateFns && uiUpdateFns.updateBackendProgress) { 
            uiUpdateFns.updateBackendProgress(100, data.message || "Processing complete!");
        }
        setTimeout(() => {
            if (uiUpdateFns && uiUpdateFns.showBackendProgress) uiUpdateFns.showBackendProgress(false);
        }, 500);

        if (uiUpdateFns && uiUpdateFns.updateUploadStatus) {
            uiUpdateFns.updateUploadStatus(`Processing complete. Select a clip below.`, 'green');
        }
        appState.setOriginalVideoFilepath(data.video_filepath);
        appState.setSelectedClipData(null);
        
        if (displayProcessingOutputFn) {
            displayProcessingOutputFn(data);
        }

        if (uiUpdateFns && uiUpdateFns.toggleUploadButton) uiUpdateFns.toggleUploadButton(false);
        appState.setCurrentTaskId(null);
    }
}

export function handleTaskError(data, uiUpdateFns) {
    console.error("WebSocket Task Error:", data);
    const currentTaskId = appState.getCurrentTaskId();
    if (data.task_id === currentTaskId) {
        if (uiUpdateFns && uiUpdateFns.updateUploadStatus) {
            uiUpdateFns.updateUploadStatus(`Server Error: ${data.error || 'Unknown processing error.'}`, 'red');
        }
        if (uiUpdateFns && uiUpdateFns.showBackendProgress) uiUpdateFns.showBackendProgress(false); 
        if (uiUpdateFns && uiUpdateFns.toggleUploadButton) uiUpdateFns.toggleUploadButton(false);
        appState.setCurrentTaskId(null);
    }
}

export function handleTaskEnded(data, uiUpdateFns) {
    console.log("WebSocket Task Ended:", data);
    const currentTaskId = appState.getCurrentTaskId();
    if (data.task_id === currentTaskId) {
        const uploadStatusEl = document.getElementById('uploadStatus'); 
        if (uploadStatusEl && !uploadStatusEl.textContent.includes('complete') && !uploadStatusEl.textContent.includes('Error')) {
            if (uiUpdateFns && uiUpdateFns.updateUploadStatus) {
                uiUpdateFns.updateUploadStatus(data.message || "Processing finished.", 'grey');
            }
        }
        if (uiUpdateFns && uiUpdateFns.showBackendProgress) uiUpdateFns.showBackendProgress(false); 
        if (uiUpdateFns && uiUpdateFns.toggleUploadButton) uiUpdateFns.toggleUploadButton(false); 
        appState.setCurrentTaskId(null);
    }
}

export function handleTaskCancelled(data, uiUpdateFns) {
    console.warn("WebSocket Task Cancelled:", data);
    const currentTaskId = appState.getCurrentTaskId();
    if (data.task_id === currentTaskId) {
        if (uiUpdateFns && uiUpdateFns.updateUploadStatus) {
            uiUpdateFns.updateUploadStatus(data.message || "Task cancelled by user.", 'orange');
        }
        if (uiUpdateFns && uiUpdateFns.showBackendProgress) uiUpdateFns.showBackendProgress(false); 
        if (uiUpdateFns && uiUpdateFns.toggleUploadButton) uiUpdateFns.toggleUploadButton(false); 
        appState.setCurrentTaskId(null);
    }
}


// Main initialization function for socket connection and handlers
export function initializeSocketConnection(uiUpdateFns, callbackFunctions) {
    console.log("SOCKET_HANDLERS: initializeSocketConnection received uiUpdateFns.updateBackendProgress type:", typeof uiUpdateFns?.updateBackendProgress); // Diagnostic
    const socket = io("http://localhost:5001", { transports: ['websocket'] });
    window.socketInstance = socket; // Make it globally accessible if needed, or pass around
    console.log("SOCKET_HANDLERS: Initializing socket connection (WebSocket only). Initial SID:", socket.id);

    // Throttling logic will now be handled by requestAnimationFrame
    // let lastUiUpdateTime = 0; 
    // const UI_UPDATE_THROTTLE_MS = 50; 
    // let lastProcessedStep = null;
    // let lastProcessedPercentForStep = {}; 

    let rAFScheduled = false;
    let latestProgressData = null;

    function registerSocketEventHandlersLocal() {
        console.log("SOCKET_HANDLERS: registerSocketEventHandlersLocal CALLED for socket.id:", socket.id);

        socket.off('progress_update');
        socket.off('final_result');
        socket.off('task_error');
        socket.off('task_ended');
        socket.off('task_cancelled');

        socket.onAny((eventName, ...args) => {
            console.log(`SOCKET_HANDLERS --- GENERIC EVENT --- Name: ${eventName}, Args:`, JSON.stringify(args));
        });

        socket.on('progress_update', (data) => {
            try {
                // Enhanced logging with more details about the payload
                console.log(`[SocketHandler on.progress_update] Received event:`, {
                    step: data?.step || '(none)',
                    percent: data?.progress_percent,
                    message: data?.message || '',
                    taskId: data?.task_id,
                    currentTaskId: appState.getCurrentTaskId()
                });

            // Ellipsis logic needs access to appState's intervalId, lastTimestamp, etc.
            // This part is complex to move entirely without passing more state or making appState more global.
            // For now, keep ellipsis logic tied to where these state vars are managed (main.js or appState.js)
            // The handleProgressUpdate function itself is now self-contained with appState.
            
            // --- Temporarily Commented Out Ellipsis Logic for Diagnosis ---
            // appState.setLastProgressTimestamp(Date.now());
            // if (data.task_id === appState.getCurrentTaskId()) {
            //     appState.setLastKnownProgressPercent(data.progress_percent !== undefined ? data.progress_percent : appState.getLastKnownProgressPercent());
            //     appState.setLastKnownMessage(data.message || appState.getLastKnownMessage());
            // }
            // if (appState.getEllipsisIntervalId()) {
            //     clearInterval(appState.getEllipsisIntervalId());
            //     appState.setEllipsisIntervalId(null);
            // }
            // --- End of Temporarily Commented Out Ellipsis Logic ---

            // Store the latest data
            latestProgressData = data;

            // If an rAF callback hasn't been scheduled yet for this animation frame, schedule one.
            if (!rAFScheduled) {
                rAFScheduled = true;
                requestAnimationFrame(() => {
                    rAFScheduled = false; // Reset flag: the rAF for this frame has run.
                    if (latestProgressData) { // Check if there's data to process
                        // console.log("[SocketHandler rAF_progress] Calling handleProgressUpdate with latest data:", JSON.stringify(latestProgressData));
                        handleProgressUpdate(latestProgressData, uiUpdateFns);
                        // latestProgressData = null; // Clearing here means if no new message comes, next rAF does nothing.
                                                  // This is fine if handleProgressUpdate is cheap.
                                                  // Or, only clear if a new message *hasn't* arrived since this rAF was scheduled.
                                                  // For simplicity, let's assume handleProgressUpdate is okay to call even if data is same.
                    }
                });
            }
            // Old time-based throttling logic is removed. rAF naturally throttles to display refresh rate.
            
            // --- Temporarily Commented Out Ellipsis Interval Setup for Diagnosis ---
            // ... (ellipsis logic remains commented out) ...
            // --- End of Temporarily Commented Out Ellipsis Interval Setup ---
            } catch (e) {
                console.error("[SocketHandler on.progress_update FATAL ERROR IN HANDLER]", e);
            }
        });
        
        socket.on('final_result', (data) => {
             if (appState.getEllipsisIntervalId()) {
                clearInterval(appState.getEllipsisIntervalId());
                appState.setEllipsisIntervalId(null);
            }
            handleFinalResult(data, uiUpdateFns, callbackFunctions.displayFn);
        });
        socket.on('task_error', (data) => {
            if (appState.getEllipsisIntervalId()) {
                clearInterval(appState.getEllipsisIntervalId());
                appState.setEllipsisIntervalId(null);
            }
            handleTaskError(data, uiUpdateFns);
        });
        socket.on('task_ended', (data) => {
            if (appState.getEllipsisIntervalId()) {
                clearInterval(appState.getEllipsisIntervalId());
                appState.setEllipsisIntervalId(null);
            }
            handleTaskEnded(data, uiUpdateFns);
            // These UI updates are specific to main.js context, might need callbacks if they vary
            if (domElements.cancelProcessingButton) domElements.cancelProcessingButton.style.display = 'none';
            if (domElements.uploadButton && uiUpdateFns.toggleUploadButton) uiUpdateFns.toggleUploadButton(false);
        });
        socket.on('task_cancelled', (data) => {
            if (appState.getEllipsisIntervalId()) {
                clearInterval(appState.getEllipsisIntervalId());
                appState.setEllipsisIntervalId(null);
            }
            handleTaskCancelled(data, uiUpdateFns);
            if (domElements.cancelProcessingButton) {
                domElements.cancelProcessingButton.style.display = 'none';
                domElements.cancelProcessingButton.disabled = false;
                domElements.cancelProcessingButton.textContent = 'Cancel Processing';
            }
            if (domElements.uploadButton && uiUpdateFns.toggleUploadButton) uiUpdateFns.toggleUploadButton(false);
        });
    }

    socket.on('connect', () => {
        handleConnectInternal(uiUpdateFns, socket.id);
        registerSocketEventHandlersLocal();
    });

    socket.on('disconnect', (reason) => {
        handleDisconnectInternal(uiUpdateFns); // reason is implicitly passed by socket.io
    });

    return socket; // Optionally return the socket instance if main.js needs it for other purposes
}
