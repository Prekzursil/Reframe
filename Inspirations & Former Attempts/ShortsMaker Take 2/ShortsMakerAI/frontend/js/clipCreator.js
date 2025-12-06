import { domElements } from './domElements.js';
import { 
    updateClipCreationStatus, 
    toggleCreateClipButton,
    showFinalOutput 
} from './ui.js';
import { createClipOnServer } from './api.js';
import * as appState from './appState.js'; // Import appState

function handleCreateClip() { // stateAccessors removed
    if (domElements.clipAdjustmentControls.style.display !== 'block' || !domElements.clipStartTimeInput.value || !domElements.clipEndTimeInput.value) {
        updateClipCreationStatus('Please select a clip or transcript range first.', 'red');
        return;
    }

    const startTime = parseFloat(domElements.clipStartTimeInput.value);
    const endTime = parseFloat(domElements.clipEndTimeInput.value);

    if (isNaN(startTime) || isNaN(endTime) || startTime < 0 || endTime <= startTime) {
        updateClipCreationStatus('Error: Invalid time range.', 'red');
        return;
    }

    const selectedClipData = appState.getSelectedClipData(); // Use appState
    const originalVideoFilepath = appState.getOriginalVideoFilepath(); // Use appState

    if (!originalVideoFilepath) {
        updateClipCreationStatus('Error: Original video path not found. Please re-upload.', 'red');
        return;
    }

    let clipIdBase = "custom_clip";
    let segmentsForSubs = [];
    let clipText = `Selection ${startTime.toFixed(1)}s-${endTime.toFixed(1)}s`;

    if (selectedClipData && Math.abs(startTime - selectedClipData.start_time) < 0.01 && Math.abs(endTime - selectedClipData.end_time) < 0.01) {
        clipIdBase = selectedClipData.id;
        segmentsForSubs = [selectedClipData]; // Assumes selectedClipData has words if it's an AI suggestion
        clipText = selectedClipData.text;
    } else {
        // For custom or adjusted range, create a simple segment object.
        // Words are not available for custom ranges unless we re-process the transcript segment.
        // For now, send an empty words array. Subtitle generation will handle this.
        clipIdBase = selectedClipData ? selectedClipData.id + "_adj" : "custom_clip";
        segmentsForSubs = [{ 
            id: clipIdBase, 
            start: startTime, // Ensure keys match what generate_ass_subtitles expects
            end: endTime, 
            text: clipText, 
            words: [] 
        }];
    }

    const payload = {
        original_video_filepath: originalVideoFilepath,
        clip_name: `${clipIdBase}_output.mp4`,
        start_time: startTime,
        end_time: endTime,
        segments_for_subs: segmentsForSubs
    };
    
    toggleCreateClipButton(true); // Disable button while creating
    createClipOnServer(payload, 
        updateClipCreationStatus, // Pass the status update function
        (subtitledFile, rawFile, assFile) => { // onSuccess
            showFinalOutput(
                subtitledFile, 
                rawFile, 
                assFile, 
                domElements.processingOutputSection, 
                domElements.outputSection, 
                domElements.playerContainer, 
                domElements.downloadWithSubsButton, 
                domElements.downloadWithoutSubsButton, 
                domElements.downloadSrtButton
            );
            // Button state (enabled/disabled) is handled by showFinalOutput or should be reset if user goes back
        },
        (errorMsg) => { // onError
            toggleCreateClipButton(false); // Re-enable button on error
            // updateClipCreationStatus is already called by createClipOnServer via its callback
        }
    );
}

export function initClipCreator() { // stateAccessors removed
    if (domElements.createSelectedClipButton) {
        domElements.createSelectedClipButton.addEventListener('click', () => handleCreateClip());
    }
}
