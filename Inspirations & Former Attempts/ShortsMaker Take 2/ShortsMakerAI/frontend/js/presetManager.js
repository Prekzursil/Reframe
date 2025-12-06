import { domElements } from './domElements.js';

const PRESET_STORAGE_KEY = 'whisperAdvancedParamsPresets';
let allAdvancedParamElements = {}; // Module-scoped cache for param element details

// This function maps parameter names (used in storage) to their DOM elements and value spans
// It should be called once by initPresetManager.
function initializeAdvancedParamElementsMapInternal() {
    allAdvancedParamElements = {
        beamSizeSlider: {el: domElements.beamSizeSlider, valueEl: domElements.beamSizeValue, type: 'slider', default: '5'},
        temperatureSlider: {el: domElements.temperatureSlider, valueEl: domElements.temperatureValue, type: 'slider', toFixed: 2, default: '0.0'},
        bestOfSlider: {el: domElements.bestOfSlider, valueEl: domElements.bestOfValue, type: 'slider', default: '5'},
        patienceSlider: {el: domElements.patienceSlider, valueEl: domElements.patienceValue, type: 'slider', toFixed: 1, default: '1.0'},
        lengthPenaltySlider: {el: domElements.lengthPenaltySlider, valueEl: domElements.lengthPenaltyValue, type: 'slider', toFixed: 1, default: '1.0'},
        repetitionPenaltySlider: {el: domElements.repetitionPenaltySlider, valueEl: domElements.repetitionPenaltyValue, type: 'slider', toFixed: 2, default: '1.0'},
        noRepeatNgramSizeSlider: {el: domElements.noRepeatNgramSizeSlider, valueEl: domElements.noRepeatNgramSizeValue, type: 'slider', default: '0'},
        logProbThresholdSlider: {el: domElements.logProbThresholdSlider, valueEl: domElements.logProbThresholdValue, type: 'slider', toFixed: 2, default: '-1.0'},
        compressionRatioThresholdSlider: {el: domElements.compressionRatioThresholdSlider, valueEl: domElements.compressionRatioThresholdValue, type: 'slider', toFixed: 1, default: '2.4'},
        noSpeechThresholdSlider: {el: domElements.noSpeechThresholdSlider, valueEl: domElements.noSpeechThresholdValue, type: 'slider', toFixed: 2, default: '0.5'},
        vadThresholdSlider: {el: domElements.vadThresholdSlider, valueEl: domElements.vadThresholdValue, type: 'slider', toFixed: 2, default: '0.38'},
        promptResetOnTemperatureSlider: {el: domElements.promptResetOnTemperatureSlider, valueEl: domElements.promptResetOnTemperatureValue, type: 'slider', toFixed: 2, default: '0.5'},
        maxInitialTimestampSlider: {el: domElements.maxInitialTimestampSlider, valueEl: domElements.maxInitialTimestampValue, type: 'slider', toFixed: 1, default: '1.0'},
        minSilenceDurationMsSlider: {el: domElements.minSilenceDurationMsSlider, valueEl: domElements.minSilenceDurationMsValue, type: 'slider', default: '250'},
        
        minSpeechDurationMsInput: {el: domElements.minSpeechDurationMsInput, type: 'number', default: '250'},
        maxSpeechDurationSInput: {el: domElements.maxSpeechDurationSInput, type: 'number', default: '15'},
        speechPadMsInput: {el: domElements.speechPadMsInput, type: 'number', default: '200'},
        
        whisperInitialPromptInput: {el: domElements.whisperInitialPromptInput, type: 'text', default: ''},
        whisperPrefixInput: {el: domElements.whisperPrefixInput, type: 'text', default: ''},
        suppressTokensInput: {el: domElements.suppressTokensInput, type: 'text', default: '-1'},
        prependPunctuationsInput: {el: domElements.prependPunctuationsInput, type: 'text', default: "\"'\“¿([{-"},
        appendPunctuationsInput: {el: domElements.appendPunctuationsInput, type: 'text', default: "\"'.。,，!！?？:：”)]}、"},
        
        conditionOnPreviousTextCheckbox: {el: domElements.conditionOnPreviousTextCheckbox, type: 'checkbox', default: true},
        suppressBlankCheckbox: {el: domElements.suppressBlankCheckbox, type: 'checkbox', default: true},
    };
}

export function getCurrentAdvancedSettings() {
    const settings = {};
    if (Object.keys(allAdvancedParamElements).length === 0) {
        initializeAdvancedParamElementsMapInternal(); // Ensure map is populated if not already
    }
    for (const keyInMap in allAdvancedParamElements) {
        const item = allAdvancedParamElements[keyInMap];
        if (item.el) {
            const formKey = item.el.name || keyInMap; // Use HTML name attribute if present, else map key
            const value = item.type === 'checkbox' ? item.el.checked.toString() : item.el.value; // Checkboxes as strings "true"/"false"
            settings[formKey] = value;
        }
    }
    return settings;
}

function applyAdvancedSettings(settings) {
    if (Object.keys(allAdvancedParamElements).length === 0) {
        initializeAdvancedParamElementsMapInternal();
    }
    for (const key in settings) {
        const item = allAdvancedParamElements[key];
        if (item && item.el) {
            if (item.type === 'checkbox') {
                item.el.checked = settings[key] === true || settings[key] === 'true';
            } else {
                item.el.value = settings[key];
            }
            if (item.type === 'slider' && item.valueEl) {
                const toFixedVal = item.toFixed !== undefined ? item.toFixed : 0;
                item.valueEl.textContent = parseFloat(item.el.value).toFixed(toFixedVal);
            }
        }
    }
}

function loadPresetsFromStorage() {
    const presetsJson = localStorage.getItem(PRESET_STORAGE_KEY);
    return presetsJson ? JSON.parse(presetsJson) : [];
}

function savePresetsToStorage(presets) {
    localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(presets));
}

function populatePresetDropdown() {
    if (!domElements.whisperPresetSelect) return;
    const presets = loadPresetsFromStorage();
    domElements.whisperPresetSelect.innerHTML = '<option value="">-- Select a Preset --</option>'; 
    presets.forEach(preset => {
        const option = document.createElement('option');
        option.value = preset.name;
        option.textContent = preset.name;
        domElements.whisperPresetSelect.appendChild(option);
    });
}

export function initPresetManager() {
    initializeAdvancedParamElementsMapInternal(); // Populate the map
    populatePresetDropdown();

    if (domElements.saveWhisperPresetBtn) {
        domElements.saveWhisperPresetBtn.addEventListener('click', () => {
            const presetName = domElements.savePresetNameInput.value.trim();
            if (!presetName) {
                alert('Please enter a name for the preset.');
                return;
            }
            const currentSettings = getCurrentAdvancedSettings();
            let presets = loadPresetsFromStorage();
            const existingPresetIndex = presets.findIndex(p => p.name === presetName);
            if (existingPresetIndex !== -1) {
                if (!confirm(`A preset named "${presetName}" already exists. Overwrite it?`)) {
                    return;
                }
                presets[existingPresetIndex].settings = currentSettings;
            } else {
                presets.push({ name: presetName, settings: currentSettings });
            }
            savePresetsToStorage(presets);
            populatePresetDropdown();
            domElements.savePresetNameInput.value = ''; 
            alert(`Preset "${presetName}" saved!`);
        });
    }

    if (domElements.loadWhisperPresetBtn) {
        domElements.loadWhisperPresetBtn.addEventListener('click', () => {
            const selectedPresetName = domElements.whisperPresetSelect.value;
            if (!selectedPresetName) {
                alert('Please select a preset to load.');
                return;
            }
            const presets = loadPresetsFromStorage();
            const presetToLoad = presets.find(p => p.name === selectedPresetName);
            if (presetToLoad) {
                applyAdvancedSettings(presetToLoad.settings);
                alert(`Preset "${selectedPresetName}" loaded!`);
            } else {
                alert(`Error: Preset "${selectedPresetName}" not found.`);
            }
        });
    }

    if (domElements.resetAdvancedWhisperParamsBtn) {
        domElements.resetAdvancedWhisperParamsBtn.addEventListener('click', () => {
            const defaultSettings = {};
            for(const key in allAdvancedParamElements) {
                if(allAdvancedParamElements[key].default !== undefined) {
                    defaultSettings[key] = allAdvancedParamElements[key].default;
                }
            }
            applyAdvancedSettings(defaultSettings);
            alert('Advanced Whisper parameters reset to defaults.');
        });
    }
}
