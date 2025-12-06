import {
    updateUploadStatus,
    setUploadProgress, // For XHR upload progress
    toggleUploadButton,
    displayProcessingOutput,
    showFinalOutput,
    updateClipCreationStatus,
    toggleCreateClipButton,
    populateAdjustmentControls,
    showBackendProgress,      // New UI function for backend progress bar
    updateBackendProgress     // New UI function for backend progress bar
} from './ui.js';

import { uploadVideoToServer, createClipOnServer } from './api.js';

import {
    // Individual handlers are no longer imported directly by main.js
    // handleConnect,
    // handleDisconnect,
    // handleProgressUpdate,
    // handleFinalResult,
    // handleTaskError,
    // handleTaskEnded,
    // handleTaskCancelled 
    initializeSocketConnection // New main function from socketHandlers
} from './socketHandlers.js';

import {
    setupTranscriptTimeAdjustControls,
    highlightTranscriptForTimes, // Imported for direct use in clip selection
    clearTranscriptHighlights,   // Imported for direct use
    enableTranscriptWordSelection, // Import the new function
    // unhighlightAiSuggestions is not directly exported/used here, ui.js handles it via displayProcessingOutput's callback logic
} from './transcript.js';
import { domElements } from './domElements.js'; // Import the new domElements module
import { initPresetManager, getCurrentAdvancedSettings } from './presetManager.js'; // Import from presetManager
import { initTooltipManager } from './tooltipManager.js'; // Import from tooltipManager
import { initHelpModalManager } from './helpModalManager.js'; // Import from helpModalManager
import { initSliderEventListeners } from './sliderEventListeners.js'; // Import from sliderEventListeners
import { initUploadHandler } from './uploadHandler.js'; // Import from uploadHandler
import { initCancelHandler } from './cancelHandler.js'; // Import from cancelHandler
import { initClipCreator } from './clipCreator.js'; // Import from clipCreator
import * as appState from './appState.js'; // Import appState module
import { initClipInterface, handleClipSelection, unhighlightSelectedAiClip } from './clipInterfaceManager.js'; // Import from clipInterfaceManager
import { whisperModelLanguages, languageCodeToName } from './languageData.js'; // Import language data

document.addEventListener('DOMContentLoaded', () => {
    // Application State is now managed by appState.js
    // Application State is now managed by appState.js
    // const STALL_TIMEOUT = 30000; // This constant can move to socketHandlers.js if ellipsis logic moves there fully or stay if main needs it.
                                 // For now, socketHandlers.js has it hardcoded.

    // UI Updater functions to pass to handlers
    const uiUpdateFns = {
        updateUploadStatus,
        toggleUploadButton,
        showBackendProgress,
        updateBackendProgress
    };
    // Diagnostic log for uiUpdateFns content
    console.log("MAIN.JS: uiUpdateFns created. updateBackendProgress type:", typeof uiUpdateFns.updateBackendProgress, "Is it same as imported updateBackendProgress from ui.js?", uiUpdateFns.updateBackendProgress === updateBackendProgress);


    // Callbacks for socketManager, specifically for handleFinalResult
    // These functions (handleClipSelection, unhighlightSelectedAiClip) are still local to main.js
    // and use appState and domElements.
    function handleClipSelection(clip, clipDivElement, clipsContainer, populateAdjustmentControlsFn, highlightTranscriptFn, createClipBtn) { 
        const currentlySelected = clipsContainer.querySelector('.clip-item.selected');
        if (currentlySelected) {
            currentlySelected.classList.remove('selected');
        }
        clipDivElement.classList.add('selected');
        appState.setSelectedClipData(clip); 
        populateAdjustmentControlsFn(clip.start_time, clip.end_time); 
        highlightTranscriptForTimes(clip.start_time, clip.end_time); // Direct call, ensure it's imported or passed
        if (createClipBtn) {
            createClipBtn.style.display = 'inline-block';
            toggleCreateClipButton(false); // from ui.js
        }
    }
    
    function unhighlightSelectedAiClip() {
        if (domElements.suggestedClipsContainer) {
            const currentlySelected = domElements.suggestedClipsContainer.querySelector('.clip-item.selected');
            if (currentlySelected) {
                currentlySelected.classList.remove('selected');
            }
        }
    }

    const displayFnForSocketHandler = (eventData) => displayProcessingOutput(
        eventData,
        domElements.fullTranscriptDisplay, domElements.suggestedClipsContainer, domElements.clipAdjustmentControls, domElements.createSelectedClipButton,
        domElements.uploadSection, domElements.processingOutputSection, domElements.outputSection,
        populateAdjustmentControls, // from ui.js
        highlightTranscriptForTimes, // from transcript.js
        unhighlightSelectedAiClip, 
        handleClipSelection 
    );

    // Initialize Socket Connection and Handlers
    // window.socketInstance is now set inside initializeSocketConnection
    const socket = initializeSocketConnection(uiUpdateFns, { displayFn: displayFnForSocketHandler });
    // Note: If other parts of main.js need `socket` directly, they can use `window.socketInstance`.
    // The STALL_TIMEOUT and ellipsis logic is now inside socketHandlers.js's progress handler.
    
    // Initialize Slider Event Listeners
    initSliderEventListeners();
    // --- End Slider Event Listener Logic (now handled in sliderEventListeners.js) ---

    // Initialize Preset Manager (which handles its own map and dropdown)
    initPresetManager(); 
    // --- End Parameter Preset Logic (now handled in presetManager.js) ---

    // Initialize Tooltip Manager
    initTooltipManager();
    // --- End Dynamic Contextual Tooltip Logic (now handled in tooltipManager.js) ---

    // Initialize Help Modal Manager
    initHelpModalManager();
    // --- End Help Modal Logic (now handled in helpModalManager.js) ---

    // Initialize Upload Handler - will need to be updated to use appState
    initUploadHandler(socket, appState); // Pass appState module directly
    // --- End Upload Handler Logic (now in uploadHandler.js) ---

    // Initialize Cancel Handler - will need to be updated
    initCancelHandler(socket, appState); // Pass appState module directly
    // --- End Cancel Handler Logic (now in cancelHandler.js) ---

    // Initialize Clip Creator Handler - will need to be updated
    initClipCreator(appState); // Pass appState module directly
    // --- End Clip Creator Logic (now in clipCreator.js) ---

    // Initialize Clip Interface Manager (handles transcript interactions and related helpers)
    initClipInterface();
    // --- End Clip Interface Logic (now in clipInterfaceManager.js) ---

    // --- Dynamic Language Dropdown Logic ---
    function updateLanguageDropdown() {
        const selectedModel = domElements.whisperModelSelect.value;
        const supportedCodes = whisperModelLanguages[selectedModel] || [];
        const currentLanguageValue = domElements.whisperLanguageSelect.value;
        
        domElements.whisperLanguageSelect.innerHTML = ''; // Clear existing options

        // Add "Auto Detect" first
        const autoOption = document.createElement('option');
        autoOption.value = "auto";
        autoOption.textContent = languageCodeToName["auto"] || "Auto Detect";
        domElements.whisperLanguageSelect.appendChild(autoOption);

        // Add "English" second if supported (and not the only option for .en models)
        if (selectedModel.endsWith('.en')) {
            if (languageCodeToName["en"]) {
                 const enOptionForEnModel = document.createElement('option');
                 enOptionForEnModel.value = "en";
                 enOptionForEnModel.textContent = languageCodeToName["en"];
                 domElements.whisperLanguageSelect.appendChild(enOptionForEnModel);
            }
        } else if (supportedCodes.includes("en") && languageCodeToName["en"]) {
            const enOption = document.createElement('option');
            enOption.value = "en";
            enOption.textContent = languageCodeToName["en"];
            domElements.whisperLanguageSelect.appendChild(enOption);
        }
        
        // Add other supported languages, sorted alphabetically
        const otherSupportedLanguages = supportedCodes
            .filter(code => code !== "en") // Filter out English as it's already added
            .map(code => ({ code, name: languageCodeToName[code] || code }))
            .sort((a, b) => a.name.localeCompare(b.name));

        otherSupportedLanguages.forEach(lang => {
            const option = document.createElement('option');
            option.value = lang.code;
            option.textContent = lang.name;
            domElements.whisperLanguageSelect.appendChild(option);
        });

        // Try to reselect previous language if still available, else default
        if (supportedCodes.includes(currentLanguageValue) || (currentLanguageValue === "auto") || (currentLanguageValue === "en" && selectedModel.endsWith(".en"))) {
            domElements.whisperLanguageSelect.value = currentLanguageValue;
        } else if (supportedCodes.includes("en") && !selectedModel.endsWith(".en")) {
            domElements.whisperLanguageSelect.value = "en";
        } else {
            domElements.whisperLanguageSelect.value = "auto";
        }
    }

    if (domElements.whisperModelSelect && domElements.whisperLanguageSelect) {
        domElements.whisperModelSelect.addEventListener('change', updateLanguageDropdown);
        // Initial population
        updateLanguageDropdown();
    }
    // --- End Dynamic Language Dropdown Logic ---

    // Event Listeners and other direct DOMContentLoaded logic are now minimal in main.js
    // The main role of main.js is to initialize all the imported modules.
});
