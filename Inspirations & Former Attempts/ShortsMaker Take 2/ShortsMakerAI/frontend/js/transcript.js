// Transcript interaction functions

// This module will need access to DOM elements like fullTranscriptDisplay,
// clipStartTimeInput, clipEndTimeInput, and potentially functions from ui.js
// or main.js to manage state like selectedClipData or toggle buttons.

// For now, functions will query DOM elements directly.
// Callbacks or direct imports from ui.js might be used for more complex UI updates.

// Let's assume main.js will handle selectedClipData state and createSelectedClipButton state.
// This module will focus on highlighting and calling back to main.js if needed.

function getTranscriptWordElements() {
    const fullTranscriptDisplay = document.getElementById('fullTranscriptDisplay');
    return fullTranscriptDisplay ? fullTranscriptDisplay.querySelectorAll('.transcript-word') : [];
}

export function clearTranscriptHighlights() {
    getTranscriptWordElements().forEach(el => {
        el.classList.remove('highlighted-range');
    });
}

export function highlightTranscriptForTimes(startTime, endTime) {
    clearTranscriptHighlights();
    const words = getTranscriptWordElements();
    let firstHighlightedWord = null;

    words.forEach(wordSpan => {
        const wordStart = parseFloat(wordSpan.dataset.start);
        const wordEnd = parseFloat(wordSpan.dataset.end);
        
        if (!isNaN(wordStart) && !isNaN(wordEnd) && wordStart < endTime && wordEnd > startTime) {
             wordSpan.classList.add('highlighted-range');
             if (!firstHighlightedWord) {
                 firstHighlightedWord = wordSpan;
             }
        }
    });

    if (firstHighlightedWord) {
        firstHighlightedWord.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

// This function might be better placed in ui.js or main.js if it affects more global state
// For now, keeping it here as it's related to transcript interaction.
// It will need a callback to update selectedClipData and button states in main.js
export function setupTranscriptTimeAdjustControls(callbacks) {
    const clipStartTimeInput = document.getElementById('clipStartTime');
    const clipEndTimeInput = document.getElementById('clipEndTime');

    // Ensure elements exist before adding listeners
    if (!clipStartTimeInput || !clipEndTimeInput) {
        console.warn("Time input fields not found for transcript adjustment controls.");
        return;
    }

    function handleTimeInputChange() {
        const start = parseFloat(clipStartTimeInput.value);
        const end = parseFloat(clipEndTimeInput.value);

        if (!isNaN(start) && !isNaN(end) && end > start && start >= 0) {
            if (callbacks.onValidTimeRange) {
                callbacks.onValidTimeRange(start, end); // Notifies main.js to update state
            }
            highlightTranscriptForTimes(start, end);
        } else {
            clearTranscriptHighlights();
            if (callbacks.onInvalidTimeRange) {
                callbacks.onInvalidTimeRange(); // Notifies main.js
            }
        }
    }

    // This part remains the same
    if (clipStartTimeInput && clipEndTimeInput) {
        clipStartTimeInput.addEventListener('input', handleTimeInputChange);
        clipEndTimeInput.addEventListener('input', handleTimeInputChange);
    }
}

// --- New Click-and-Drag Selection Logic ---
let isDragging = false;
let selectionStartWordElement = null;

// Helper to highlight a single word (can be part of a range)
function styleWordHighlight(wordElement, shouldHighlight) {
    if (shouldHighlight) {
        wordElement.classList.add('highlighted-range');
    } else {
        wordElement.classList.remove('highlighted-range');
    }
}

// Highlights words between startElement and endElement (inclusive) in DOM order
function highlightWordRange(startElement, endElement) {
    clearTranscriptHighlights(); // Clear previous highlights first
    const words = getTranscriptWordElements();
    let inSelectionRange = false;
    
    const startIndex = Array.prototype.indexOf.call(words, startElement);
    const endIndex = Array.prototype.indexOf.call(words, endElement);

    if (startIndex === -1 || endIndex === -1) return; // Should not happen

    const trueStartNode = words[Math.min(startIndex, endIndex)];
    const trueEndNode = words[Math.max(startIndex, endIndex)];

    for (const word of words) {
        if (word === trueStartNode) {
            inSelectionRange = true;
        }
        if (inSelectionRange) {
            styleWordHighlight(word, true);
        }
        if (word === trueEndNode) {
            inSelectionRange = false; // Stop highlighting after the end element
        }
    }
}

export function enableTranscriptWordSelection(updateTimeInputsCallback) {
    const fullTranscriptDisplay = document.getElementById('fullTranscriptDisplay');
    if (!fullTranscriptDisplay) {
        console.warn("fullTranscriptDisplay element not found for word selection.");
        return;
    }

    fullTranscriptDisplay.addEventListener('mousedown', (e) => {
        if (e.target.classList.contains('transcript-word')) {
            isDragging = true;
            selectionStartWordElement = e.target;
            
            clearTranscriptHighlights();
            styleWordHighlight(selectionStartWordElement, true); // Highlight just the start word

            fullTranscriptDisplay.style.userSelect = 'none'; // Prevent browser text selection
            e.preventDefault(); // Prevent default drag behaviors
        }
    });

    fullTranscriptDisplay.addEventListener('mousemove', (e) => {
        if (!isDragging || !selectionStartWordElement) return;

        if (e.target.classList.contains('transcript-word')) {
            const currentHoverWordElement = e.target;
            // Highlight the range from the initial mousedown word to the current hover word
            highlightWordRange(selectionStartWordElement, currentHoverWordElement);
        }
    });

    // Mouseup should be on document to catch mouse release outside the transcript box
    document.addEventListener('mouseup', (e) => {
        if (!isDragging) return; // Only act if dragging was in progress

        isDragging = false;
        if (fullTranscriptDisplay) { // Check again in case it was removed
            fullTranscriptDisplay.style.userSelect = ''; // Re-enable text selection
        }

        const selectedWords = Array.from(fullTranscriptDisplay.querySelectorAll('.transcript-word.highlighted-range'));
        
        if (selectedWords.length > 0) {
            // Sort selectedWords by their actual DOM order / time, just in case mousemove was erratic
            // Though highlightWordRange should ensure they are contiguous.
            // For simplicity, assume highlightWordRange correctly highlights a contiguous block.
            const firstWord = selectedWords[0];
            const lastWord = selectedWords[selectedWords.length - 1];
            
            const startTime = parseFloat(firstWord.dataset.start);
            const endTime = parseFloat(lastWord.dataset.end);

            if (!isNaN(startTime) && !isNaN(endTime) && updateTimeInputsCallback) {
                // Ensure start is less than end, can happen if dragged backwards quickly
                updateTimeInputsCallback(Math.min(startTime, endTime), Math.max(startTime, endTime));
            }
        }
        selectionStartWordElement = null; // Reset for the next drag operation
    });

    // Optional: Handle mouse leaving the transcript display area while dragging
    if (fullTranscriptDisplay) {
        fullTranscriptDisplay.addEventListener('mouseleave', (e) => {
            // If isDragging is true when mouse leaves, you might want to finalize selection
            // or just let mouseup on document handle it. For now, let mouseup handle it.
        });
    }
}

export function clearAllAiSuggestionMarks() {
    getTranscriptWordElements().forEach(el => {
        el.classList.remove('ai-suggested-segment');
        el.removeAttribute('data-ai-clip-id');
    });
}

// Marks words in transcript that fall within an AI suggested clip time range
export function markAiSuggestedSegment(startTime, endTime, clipId, onAiSegmentClickCallback) {
    const words = getTranscriptWordElements();
    words.forEach(wordSpan => {
        const wordStart = parseFloat(wordSpan.dataset.start);
        const wordEnd = parseFloat(wordSpan.dataset.end);
        
        // Check if the word is within the AI suggested segment time range
        if (!isNaN(wordStart) && !isNaN(wordEnd) && wordStart < endTime && wordEnd > startTime) {
             wordSpan.classList.add('ai-suggested-segment');
             wordSpan.dataset.aiClipId = clipId; // Store clipId for potential click interaction

             // Add click listener to these words to select the AI clip
             // Ensure listener is not added multiple times if function is called repeatedly
             // A simple way is to check if it already has one, or manage listeners more carefully.
             // For now, let's assume this is called once per transcript render.
             if (onAiSegmentClickCallback) {
                wordSpan.addEventListener('click', (e) => {
                    // Prevent interference with drag selection if a click happens during a drag
                    if (isDragging) return; 
                    onAiSegmentClickCallback(clipId);
                });
             }
        }
    });
}
