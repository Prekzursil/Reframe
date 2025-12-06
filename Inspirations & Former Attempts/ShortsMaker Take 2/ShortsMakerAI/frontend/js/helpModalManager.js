import { domElements } from './domElements.js';

export function initHelpModalManager() {
    // Diagnostic: Try to fetch elements directly inside this function
    const localHelpBtn = document.getElementById('whisper-params-help-btn');
    const localHelpModal = document.getElementById('whisper-params-help-modal');
    const localCloseBtn = document.getElementById('whisper-params-help-modal-close-btn');

    console.log("Diagnostic fetch in initHelpModalManager:", { 
        localBtn: localHelpBtn, 
        localModal: localHelpModal, 
        localCloseBtn: localCloseBtn 
    });
    console.log("Values from imported domElements:", {
        importedBtn: domElements.whisperParamsHelpBtn,
        importedModal: domElements.whisperParamsHelpModal,
        importedCloseBtn: domElements.whisperParamsHelpModalCloseBtn
    });

    if (localHelpBtn && localHelpModal && localCloseBtn) {
        // Event listener to open the modal
        localHelpBtn.addEventListener('click', () => {
            console.log("Help button clicked (using local fetch), attempting to show modal.");
            localHelpModal.style.display = 'block';
            // Future: Initialize search/TOC for the modal if they are dynamic
        });

        // Event listener for the close button on the modal
        localCloseBtn.addEventListener('click', () => {
            console.log("Modal close button clicked (using local fetch), attempting to hide modal.");
            localHelpModal.style.display = 'none';
        });

        // Event listener to close the modal if the user clicks outside of it
        window.addEventListener('click', (event) => {
            // Check if the modal exists and is currently displayed
            if (localHelpModal && localHelpModal.style.display === 'block') {
                if (event.target === localHelpModal) {
                    console.log("Clicked outside modal content (using local fetch), attempting to hide modal.");
                    localHelpModal.style.display = 'none';
                }
            }
        });
        console.log("Help modal (using local fetch) initialized successfully.");
    } else {
        console.error('Help modal elements (using local fetch) not found, initialization failed. This means elements are not in DOM when initHelpModalManager runs, or IDs are still incorrect in index.html.', {
            btn: localHelpBtn, 
            modal: localHelpModal, 
            closeBtn: localCloseBtn
        });
        // Log the state of domElements from import as well for comparison
        console.error('State of imported domElements for help modal:', {
            importedBtn: domElements.whisperParamsHelpBtn,
            importedModal: domElements.whisperParamsHelpModal,
            importedCloseBtn: domElements.whisperParamsHelpModalCloseBtn
        });
    }

    // Future: Add logic for help modal search input and TOC navigation here
    // e.g., if (domElements.helpModalSearchInput) { ... }
    // e.g., if (domElements.helpModalToc) { ... generate and attach listeners ... }
}
