import { domElements } from './domElements.js';
// No direct ui.js functions needed here if main.js passes updateBackendProgress via uiUpdateFns in stateAccessors or similar.
// For now, let's assume main.js will provide necessary update functions if needed by the handler logic.
// Actually, updateBackendProgress is used. Let's import it.
import { updateBackendProgress } from './ui.js';
import * as appState from './appState.js'; // Import appState


export function initCancelHandler(socket) { // stateAccessors removed
    if (domElements.cancelProcessingButton) { 
        domElements.cancelProcessingButton.addEventListener('click', () => {
            const currentTaskId = appState.getCurrentTaskId(); // Use appState
            const lastKnownProgressPercent = appState.getLastKnownProgressPercent(); // Use appState

            if (currentTaskId && socket.connected) {
                console.log(`CANCEL_HANDLER: Cancel button clicked for task_id: ${currentTaskId}`);
                socket.emit('cancel_task_request', { task_id: currentTaskId });
                
                if (domElements.cancelProcessingButton) { // Check again in case it was removed from DOM
                    domElements.cancelProcessingButton.disabled = true;
                    domElements.cancelProcessingButton.textContent = 'Cancelling...';
                }
                // Update UI immediately to reflect cancellation request
                updateBackendProgress(lastKnownProgressPercent, 'Cancellation requested...'); 
            } else {
                console.warn("CANCEL_HANDLER: Cancel button clicked but no active task or socket not connected.");
            }
        });
    }
}
