import { domElements } from './domElements.js';

const paramTooltipTexts = {
    beamSize: "How many 'best guesses' for words Whisper tries at once. More can be better but slower.",
    bestOf: "How many initial guesses Whisper makes before picking the 'beam size' number of best ones.",
    patience: "How long Whisper keeps trying if it's not finding better word guesses. More patience can help with tricky audio.",
    temperature: "Makes Whisper's word choices more or less 'surprising'. 0.0 is safest for accuracy.",
    promptResetOnTemperature: "If temperature isn't 0, this tells Whisper when to 'start fresh' with its hints.",
    lengthPenalty: "Tells Whisper if it should prefer shorter or longer sentences. 1.0 is neutral.",
    repetitionPenalty: "Helps stop Whisper from repeating the same words or phrases too much.",
    noRepeatNgramSize: "Stops Whisper from repeating exact short phrases (e.g., 3 words in a row). 0 is off.",
    conditionOnPreviousText: "Lets Whisper use words it just wrote to help guess the next words better.",
    suppressBlank: "Stops Whisper from outputting empty lines if it hears silence.",
    suppressTokens: "Tells Whisper to ignore certain sounds or symbols (like music notes).",
    logProbThreshold: "How 'sure' Whisper needs to be about words. Higher means more sure, might miss quiet words.",
    compressionRatioThreshold: "Another way Whisper guesses if a sound is real words or just noise.",
    noSpeechThreshold: "How sure Whisper is that there's NO talking in a sound bit.",
    vadFilter: "Uses a helper to find talking parts first. We always keep this on!",
    vadThreshold: "How sure the VAD helper is that it found talking, not just noise.",
    minSilenceDurationMs: "Shortest quiet pause VAD looks for to split sentences (in tiny seconds).",
    minSpeechDurationMs: "Shortest sound VAD will call 'speech'. Ignores tiny blips.",
    maxSpeechDurationS: "Longest a single 'speech bubble' can be before VAD cuts it (in seconds).",
    speechPadMs: "Adds a tiny bit of 'empty sound' at start/end of speech so words aren't cut off.",
    whisperInitialPrompt: "Give Whisper a hint about the video's topic or special words.",
    whisperPrefix: "Text to add at the start of EVERY sentence Whisper writes.",
    prependPunctuations: "Punctuation Whisper expects at the START of sentences.",
    appendPunctuations: "Punctuation Whisper expects at the END of sentences.",
    maxInitialTimestamp: "Tells Whisper not to look for the first words too far into the audio.",
    wordTimestamps: "Makes Whisper note exactly when each word is said. Super useful for subtitles!"
};

export function initTooltipManager() {
    const paramTooltip = domElements.paramTooltip; 
    const tooltipTriggers = document.querySelectorAll('.tooltip-trigger');

    if (paramTooltip && tooltipTriggers.length > 0) {
        tooltipTriggers.forEach(trigger => {
            trigger.addEventListener('mouseenter', (event) => {
                const key = event.target.dataset.tooltipKey;
                const text = paramTooltipTexts[key];
                if (text) {
                    paramTooltip.innerHTML = text;
                    const rect = event.target.getBoundingClientRect();
                    // Position tooltip slightly below and centered to the trigger
                    paramTooltip.style.left = `${rect.left + window.scrollX + (rect.width / 2) - (paramTooltip.offsetWidth / 2)}px`; 
                    paramTooltip.style.top = `${rect.bottom + window.scrollY + 8}px`; // 8px below trigger
                    // paramTooltip.style.transform = 'translateX(-50%)'; // Already centered by left calc
                    paramTooltip.style.display = 'block';
                }
            });
            trigger.addEventListener('mouseleave', () => {
                paramTooltip.style.display = 'none';
            });
            trigger.addEventListener('focus', (event) => { 
                const key = event.target.dataset.tooltipKey;
                const text = paramTooltipTexts[key];
                if (text) {
                    paramTooltip.innerHTML = text;
                    const rect = event.target.getBoundingClientRect();
                    paramTooltip.style.left = `${rect.left + window.scrollX + (rect.width / 2) - (paramTooltip.offsetWidth / 2)}px`;
                    paramTooltip.style.top = `${rect.bottom + window.scrollY + 8}px`;
                    // paramTooltip.style.transform = 'translateX(-50%)';
                    paramTooltip.style.display = 'block';
                }
            });
            trigger.addEventListener('blur', () => {
                paramTooltip.style.display = 'none';
            });
        });
    }
}
