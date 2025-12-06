import { domElements } from './domElements.js';
import * as appState from './appState.js';
import { toggleCreateClipButton, populateAdjustmentControls } from './ui.js';
import { 
    setupTranscriptTimeAdjustControls, 
    enableTranscriptWordSelection,
    highlightTranscriptForTimes 
} from './transcript.js';

export function unhighlightSelectedAiClip() {
    if (domElements.suggestedClipsContainer) {
        const currentlySelected = domElements.suggestedClipsContainer.querySelector('.clip-item.selected');
        if (currentlySelected) {
            currentlySelected.classList.remove('selected');
        }
    }
}

export function handleClipSelection(clip, clipDivElement, clipsContainer, /*populateAdjustmentControlsFn, highlightTranscriptFn,*/ createClipBtn) {
    // populateAdjustmentControlsFn is populateAdjustmentControls from ui.js
    // highlightTranscriptFn is highlightTranscriptForTimes from transcript.js
    // createClipBtn is domElements.createSelectedClipButton
    
    const currentlySelected = clipsContainer.querySelector('.clip-item.selected');
    if (currentlySelected) {
        currentlySelected.classList.remove('selected');
    }
    clipDivElement.classList.add('selected');
    appState.setSelectedClipData(clip); 
    
    populateAdjustmentControls(clip.start_time, clip.end_time); 
    highlightTranscriptForTimes(clip.start_time, clip.end_time); 
    
    if (createClipBtn) { // This is domElements.createSelectedClipButton
        createClipBtn.style.display = 'inline-block';
        toggleCreateClipButton(false); // from ui.js
    }
}

export function initClipInterface() {
    setupTranscriptTimeAdjustControls({ 
        onValidTimeRange: (start, end) => {
            appState.setSelectedClipData(null); 
            unhighlightSelectedAiClip(); // Uses the local version
            if (domElements.createSelectedClipButton) toggleCreateClipButton(false); 
        },
        onInvalidTimeRange: () => {
            if (domElements.createSelectedClipButton) toggleCreateClipButton(true); 
        }
    });

    enableTranscriptWordSelection((startTime, endTime) => { 
        if (domElements.clipStartTimeInput && domElements.clipEndTimeInput) {
            domElements.clipStartTimeInput.value = startTime.toFixed(1);
            domElements.clipEndTimeInput.value = endTime.toFixed(1);
            // Manually trigger 'input' event on one of the inputs 
            // to make setupTranscriptTimeAdjustControls logic run (highlighting, onValidTimeRange callback)
            domElements.clipStartTimeInput.dispatchEvent(new Event('input', { bubbles: true }));
        }
    });
}
