import { domElements } from './domElements.js';

function addSliderListener(slider, valueDisplay, toFixed = 0) {
    if (slider && valueDisplay) {
        // Set initial value on load
        valueDisplay.textContent = parseFloat(slider.value).toFixed(toFixed);
        // Add event listener for changes
        slider.addEventListener('input', () => {
            valueDisplay.textContent = parseFloat(slider.value).toFixed(toFixed);
        });
    }
}

export function initSliderEventListeners() {
    addSliderListener(domElements.beamSizeSlider, domElements.beamSizeValue);
    addSliderListener(domElements.temperatureSlider, domElements.temperatureValue, 2);
    addSliderListener(domElements.noSpeechThresholdSlider, domElements.noSpeechThresholdValue, 2);
    addSliderListener(domElements.minSilenceDurationMsSlider, domElements.minSilenceDurationMsValue);
    addSliderListener(domElements.bestOfSlider, domElements.bestOfValue);
    addSliderListener(domElements.patienceSlider, domElements.patienceValue, 1);
    addSliderListener(domElements.lengthPenaltySlider, domElements.lengthPenaltyValue, 1);
    addSliderListener(domElements.repetitionPenaltySlider, domElements.repetitionPenaltyValue, 2);
    addSliderListener(domElements.noRepeatNgramSizeSlider, domElements.noRepeatNgramSizeValue);
    addSliderListener(domElements.logProbThresholdSlider, domElements.logProbThresholdValue, 2);
    addSliderListener(domElements.compressionRatioThresholdSlider, domElements.compressionRatioThresholdValue, 1);
    addSliderListener(domElements.vadThresholdSlider, domElements.vadThresholdValue, 2);
    addSliderListener(domElements.promptResetOnTemperatureSlider, domElements.promptResetOnTemperatureValue, 2);
    addSliderListener(domElements.maxInitialTimestampSlider, domElements.maxInitialTimestampValue, 1);
}
