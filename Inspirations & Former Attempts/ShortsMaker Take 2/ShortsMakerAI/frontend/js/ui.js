// UI related functions

// DOM Element references (can be initialized here or passed from main.js)
// For now, assume they will be accessed via document.getElementById in each function
// or passed as arguments if a more decoupled approach is taken later.

export function updateUploadStatus(message, color = 'black') {
    const uploadStatus = document.getElementById('uploadStatus');
    if (uploadStatus) {
        uploadStatus.textContent = message;
        uploadStatus.style.color = color;
    }
}

export function setUploadProgress(value) {
    const uploadProgressBar = document.getElementById('uploadProgressBar');
    if (uploadProgressBar) {
        uploadProgressBar.value = value;
        uploadProgressBar.style.display = value > 0 && value < 100 ? 'block' : 'none';
    }
}

export function toggleUploadButton(disabled) {
    const uploadButton = document.getElementById('uploadButton');
    if (uploadButton) {
        uploadButton.disabled = disabled;
    }
}

// Import new functions from transcript.js
// Note: Standard JS modules don't allow imports inside functions.
// They must be at the top level of the module.
// Assuming this file is a module and transcript.js exports these:
import { markAiSuggestedSegment, clearAllAiSuggestionMarks } from './transcript.js';


export function displayProcessingOutput(data, fullTranscriptDisplay, suggestedClipsContainer, clipAdjustmentControls, createSelectedClipButton, uploadSection, processingOutputSection, outputSection, populateAdjustmentControlsFn, highlightTranscriptForTimesFn, unhighlightAiSuggestionsFn, handleClipSelectionFn) {
    if (uploadSection) uploadSection.style.display = 'none';
    if (processingOutputSection) processingOutputSection.style.display = 'block';
    if (outputSection) outputSection.style.display = 'none';

    // Clear any previous AI suggestion markings on the transcript
    clearAllAiSuggestionMarks();

    // Render interactive transcript
    if (fullTranscriptDisplay) {
        fullTranscriptDisplay.innerHTML = ''; // Clear previous content
        if (data.all_segments && data.all_segments.length > 0) {
            data.all_segments.forEach(segment => {
                if (segment.words && segment.words.length > 0) {
                    segment.words.forEach(wordInfo => {
                        const wordSpan = document.createElement('span');
                        wordSpan.className = 'transcript-word';
                        wordSpan.textContent = wordInfo.word + ' ';
                        wordSpan.dataset.start = wordInfo.start;
                        wordSpan.dataset.end = wordInfo.end;
                        fullTranscriptDisplay.appendChild(wordSpan);
                    });
                } else {
                    const segmentSpan = document.createElement('span');
                    segmentSpan.textContent = (segment.text || '') + ' ';
                    fullTranscriptDisplay.appendChild(segmentSpan);
                }
            });
        } else {
            fullTranscriptDisplay.textContent = data.transcription_text || 'No transcript available.';
        }
    }

    // Display suggested clips
    if (suggestedClipsContainer) {
        suggestedClipsContainer.innerHTML = ''; // Clear previous suggestions
        if (data.suggested_clips && data.suggested_clips.length > 0) {
            data.suggested_clips.forEach(clip => {
                const clipDiv = document.createElement('div');
                clipDiv.className = 'clip-item';
                // Add score to the display if available
                const scoreDisplay = clip.score !== undefined ? ` | <strong>Score:</strong> ${clip.score.toFixed(2)}` : '';
                clipDiv.innerHTML = `
                    <h4>Suggested Clip (${clip.id}${scoreDisplay})</h4>
                    <p><strong>Reason:</strong> ${clip.reason}</p>
                    <p><strong>Text:</strong> ${clip.text}</p>
                    <p><em>Time: ${clip.start_time.toFixed(2)}s - ${clip.end_time.toFixed(2)}s</em></p>
                `;
                clipDiv.dataset.clipId = clip.id; // Used to find this div if transcript segment is clicked

                // Mark this AI suggestion on the transcript
                markAiSuggestedSegment(clip.start_time, clip.end_time, clip.id, (clickedClipId) => {
                    // This callback is invoked when a marked segment on the transcript is clicked
                    // Find the corresponding clipDiv in the list and simulate a click on it
                    // to reuse the existing selection logic.
                    const correspondingClipDiv = suggestedClipsContainer.querySelector(`.clip-item[data-clip-id="${clickedClipId}"]`);
                    if (correspondingClipDiv) {
                        correspondingClipDiv.click(); // Simulate click on the clip item in the list
                    }
                });

                clipDiv.addEventListener('click', () => handleClipSelectionFn(clip, clipDiv, suggestedClipsContainer, populateAdjustmentControlsFn, highlightTranscriptForTimesFn, createSelectedClipButton));
                suggestedClipsContainer.appendChild(clipDiv);
            });
            if (clipAdjustmentControls) clipAdjustmentControls.style.display = 'none'; // Hide time inputs until a clip is selected
            if (createSelectedClipButton) {
                createSelectedClipButton.style.display = 'inline-block';
                createSelectedClipButton.disabled = true;
            }
        } else {
            suggestedClipsContainer.textContent = 'No specific clips suggested.';
            if (clipAdjustmentControls) clipAdjustmentControls.style.display = 'none';
            if (createSelectedClipButton) createSelectedClipButton.style.display = 'none';
        }
    }
}


export function showFinalOutput(subtitledClipFilename, rawClipFilename, subtitleFilename, processingOutputSection, outputSection, playerContainer, downloadWithSubsButton, downloadWithoutSubsButton, downloadSrtButton) {
    if (processingOutputSection) processingOutputSection.style.display = 'none';
    if (outputSection) outputSection.style.display = 'block';
    
    const subtitledDownloadUrl = `http://localhost:5001/download/${subtitledClipFilename}`;
    const rawDownloadUrl = `http://localhost:5001/download/${rawClipFilename}`;
    const subtitleDownloadUrl = `http://localhost:5001/download/${subtitleFilename}`;

    if (playerContainer) {
        playerContainer.innerHTML = `
            <video controls width="100%">
                <source src="${subtitledDownloadUrl}" type="video/mp4">
                Your browser does not support the video tag.
            </video>
            <p>Generated subtitled clip: ${subtitledClipFilename}</p>
        `;
    }
    
    if(downloadWithSubsButton) {
        downloadWithSubsButton.onclick = () => { window.open(subtitledDownloadUrl, '_blank'); };
        downloadWithSubsButton.disabled = false;
    }
    if(downloadWithoutSubsButton) {
        downloadWithoutSubsButton.onclick = () => { window.open(rawDownloadUrl, '_blank'); };
        downloadWithoutSubsButton.disabled = false;
    }
    if(downloadSrtButton) {
        downloadSrtButton.textContent = 'Download Subtitles (.ass)';
        downloadSrtButton.onclick = () => { window.open(subtitleDownloadUrl, '_blank'); };
        downloadSrtButton.disabled = false;
    }
}

export function updateClipCreationStatus(message, color = 'black') {
    const clipCreationStatusEl = document.getElementById('clipCreationStatus');
    if (clipCreationStatusEl) {
        clipCreationStatusEl.textContent = message;
        clipCreationStatusEl.style.color = color;
    }
}

export function toggleCreateClipButton(disabled) {
    const createSelectedClipButton = document.getElementById('createSelectedClipButton');
    if (createSelectedClipButton) {
        createSelectedClipButton.disabled = disabled;
    }
}

// Transcript UI functions will be in transcript.js, but ui.js might have helpers they call.
// For now, keeping populateAdjustmentControls here as it's a direct UI update.
export function populateAdjustmentControls(start, end) {
    const clipAdjustmentControls = document.getElementById('clipAdjustmentControls');
    const clipStartTimeInput = document.getElementById('clipStartTime');
    const clipEndTimeInput = document.getElementById('clipEndTime');
    if (clipAdjustmentControls && clipStartTimeInput && clipEndTimeInput) {
       clipStartTimeInput.value = parseFloat(start).toFixed(1);
       clipEndTimeInput.value = parseFloat(end).toFixed(1);
       clipAdjustmentControls.style.display = 'block';
   }
}

// Function to specifically update Whisper progress display
export function displayWhisperProgress(transcriptionPercent, etaString) {
    const whisperProgressTextEl = document.getElementById('whisperProgressText');
    const whisperEtaTextEl = document.getElementById('whisperEtaText');
    const whisperContainerEl = document.getElementById('whisperProgressContainer');

    if (whisperContainerEl) {
        whisperContainerEl.style.display = 'block';
        // Remove debug background color
    } else {
        console.warn("UI.JS: whisperProgressContainer not found");
    }
    if (whisperProgressTextEl) {
        whisperProgressTextEl.textContent = transcriptionPercent ? `Transcription: ${transcriptionPercent}%` : '';
    } else {
        console.warn("UI.JS: whisperProgressTextEl not found");
    }
    if (whisperEtaTextEl) {
        whisperEtaTextEl.textContent = etaString ? `ETA: ${etaString}` : '';
    } else {
        console.warn("UI.JS: whisperEtaTextEl not found");
    }
}

// New functions for backend processing progress bar
export function showBackendProgress(show = true) {
    const progressBar = document.getElementById('backendProcessingProgressBar');
    const statusEl = document.getElementById('backendProcessStatus');
    const whisperContainerEl = document.getElementById('whisperProgressContainer');
    const whisperProgressTextEl = document.getElementById('whisperProgressText');
    const whisperEtaTextEl = document.getElementById('whisperEtaText');

    if (progressBar) {
        progressBar.style.display = show ? 'block' : 'none';
        if (!show) progressBar.value = 0; // Reset progress when hiding
    }
    if (statusEl) {
        statusEl.style.display = show ? 'block' : 'none';
        if (!show) statusEl.textContent = ''; // Clear status when hiding
    }
    if (whisperContainerEl) {
        whisperContainerEl.style.display = show ? 'block' : 'none'; // Show/hide with main progress
        if (!show) { // Clear content when hiding
            if (whisperProgressTextEl) whisperProgressTextEl.textContent = '';
            if (whisperEtaTextEl) whisperEtaTextEl.textContent = '';
        }
    }
}

export function updateBackendProgress(percent, message, stepName = '') {
    console.log(`UI.JS: updateBackendProgress received: percent=${percent}, message="${message}", stepName="${stepName}"`); // Enhanced logging

    // DOM updates are now direct, no more nested requestAnimationFrame calls here.
    // Throttling is handled by socketHandlers.js before this function is called.

    const progressBar = document.getElementById('backendProcessingProgressBar');
    const statusEl = document.getElementById('backendProcessStatus');
    const whisperContainerEl = document.getElementById('whisperProgressContainer');
    const whisperProgressTextEl = document.getElementById('whisperProgressText');
    const whisperEtaTextEl = document.getElementById('whisperEtaText');

    if (progressBar) progressBar.value = percent;

    // General status message update
    if (stepName === "transcribing_progress_fw") {
        if (statusEl) statusEl.textContent = `Step 3/4 - Transcribing Audio... ${percent}%`;
    } else {
        if (statusEl) statusEl.textContent = message;
    }

    // Handle Whisper-specific UI elements for both VAD and Transcription steps
    if (stepName === "transcribing_progress_fw" || stepName === "vad_lang_detect_fw") {
        console.log(`UI.JS: Processing step "${stepName}". Message: "${message}"`); // DIAGNOSTIC
        
        if (stepName === "transcribing_progress_fw") {
            // For actual transcription progress
            if (statusEl) statusEl.textContent = `Step 3/4 - Transcribing Audio... ${percent}%`; 
            
            // Extract ETA information
            const simplePercent = String(percent);
            const etaMatch = message.match(/\(ETA:\s*([^)]+)\)/);
            const simpleEta = etaMatch && etaMatch[1] ? etaMatch[1].trim() : "N/A";

            console.log(`UI.JS: Displaying transcription progress. Percent='${simplePercent}', ETA='${simpleEta}'`);
            
            // Show the whisper progress container and update its contents
            if (whisperContainerEl) whisperContainerEl.style.display = 'block';
            if (whisperProgressTextEl) whisperProgressTextEl.textContent = `Transcription: ${simplePercent}%`;
            if (whisperEtaTextEl) whisperEtaTextEl.textContent = `ETA: ${simpleEta}`;
        } 
        else if (stepName === "vad_lang_detect_fw") {
            // For VAD/Language detection
            if (whisperContainerEl) whisperContainerEl.style.display = 'block';
            if (whisperProgressTextEl) whisperProgressTextEl.textContent = 'Analyzing audio...';
            if (whisperEtaTextEl) whisperEtaTextEl.textContent = '';
        }
    } else {
        // For any step that is NOT transcription or VAD, ensure Whisper specific section is hidden.
        console.log(`UI.JS: HIDING whisper UI because stepName is '${stepName}'`);
        if (whisperContainerEl) whisperContainerEl.style.display = 'none';
        if (whisperProgressTextEl) whisperProgressTextEl.textContent = '';
        if (whisperEtaTextEl) whisperEtaTextEl.textContent = '';
    }
}
