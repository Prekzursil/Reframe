    // DOM Element Selectors
// This module centralizes all DOM element selections for the application.

export const domElements = {
    // Upload Section
    videoFile: document.getElementById('videoFile'),
    userKeywordsInput: document.getElementById('userKeywords'),
    aiPromptTextarea: document.getElementById('aiPrompt'),
    whisperModelSelect: document.getElementById('whisperModel'),
    whisperLanguageSelect: document.getElementById('whisperLanguage'), // New
    whisperTaskSelect: document.getElementById('whisperTask'),       // New
    computeTypeSelect: document.getElementById('computeType'),
    minShortDurationInput: document.getElementById('minShortDuration'),
    maxShortDurationInput: document.getElementById('maxShortDuration'),
    uploadButton: document.getElementById('uploadButton'),
    cancelProcessingButton: document.getElementById('cancelProcessingButton'),
    uploadProgressBar: document.getElementById('uploadProgressBar'),
    uploadStatusEl: document.getElementById('uploadStatus'),
    backendProcessStatusEl: document.getElementById('backendProcessStatus'),
    backendProcessingProgressBarEl: document.getElementById('backendProcessingProgressBar'),

    // Advanced Whisper Parameters (Sliders & Value Displays)
    beamSizeSlider: document.getElementById('beamSizeSlider'),
    beamSizeValue: document.getElementById('beamSizeValue'),
    temperatureSlider: document.getElementById('temperatureSlider'),
    temperatureValue: document.getElementById('temperatureValue'),
    noSpeechThresholdSlider: document.getElementById('noSpeechThresholdSlider'),
    noSpeechThresholdValue: document.getElementById('noSpeechThresholdValue'),
    minSilenceDurationMsSlider: document.getElementById('minSilenceDurationMsSlider'),
    minSilenceDurationMsValue: document.getElementById('minSilenceDurationMsValue'),
    bestOfSlider: document.getElementById('bestOfSlider'),
    bestOfValue: document.getElementById('bestOfValue'),
    patienceSlider: document.getElementById('patienceSlider'),
    patienceValue: document.getElementById('patienceValue'),
    lengthPenaltySlider: document.getElementById('lengthPenaltySlider'),
    lengthPenaltyValue: document.getElementById('lengthPenaltyValue'),
    repetitionPenaltySlider: document.getElementById('repetitionPenaltySlider'),
    repetitionPenaltyValue: document.getElementById('repetitionPenaltyValue'),
    noRepeatNgramSizeSlider: document.getElementById('noRepeatNgramSizeSlider'),
    noRepeatNgramSizeValue: document.getElementById('noRepeatNgramSizeValue'),
    logProbThresholdSlider: document.getElementById('logProbThresholdSlider'),
    logProbThresholdValue: document.getElementById('logProbThresholdValue'),
    compressionRatioThresholdSlider: document.getElementById('compressionRatioThresholdSlider'),
    compressionRatioThresholdValue: document.getElementById('compressionRatioThresholdValue'),
    vadThresholdSlider: document.getElementById('vadThresholdSlider'),
    vadThresholdValue: document.getElementById('vadThresholdValue'),
    promptResetOnTemperatureSlider: document.getElementById('promptResetOnTemperatureSlider'),
    promptResetOnTemperatureValue: document.getElementById('promptResetOnTemperatureValue'),
    maxInitialTimestampSlider: document.getElementById('maxInitialTimestampSlider'),
    maxInitialTimestampValue: document.getElementById('maxInitialTimestampValue'),

    // Advanced Whisper Parameters (Inputs & Checkboxes)
    minSpeechDurationMsInput: document.getElementById('minSpeechDurationMsInput'),
    maxSpeechDurationSInput: document.getElementById('maxSpeechDurationSInput'),
    speechPadMsInput: document.getElementById('speechPadMsInput'),
    whisperInitialPromptInput: document.getElementById('whisperInitialPromptInput'),
    whisperPrefixInput: document.getElementById('whisperPrefixInput'),
    suppressTokensInput: document.getElementById('suppressTokensInput'),
    prependPunctuationsInput: document.getElementById('prependPunctuationsInput'),
    appendPunctuationsInput: document.getElementById('appendPunctuationsInput'),
    conditionOnPreviousTextCheckbox: document.getElementById('conditionOnPreviousTextCheckbox'),
    suppressBlankCheckbox: document.getElementById('suppressBlankCheckbox'),
    // wordTimestampsCheckbox and vadFilterCheckbox are disabled, not typically manipulated by JS logic directly for value.

    // Help Modal Elements
    whisperParamsHelpBtn: document.getElementById('whisper-params-help-btn'),
    whisperParamsHelpModal: document.getElementById('whisper-params-help-modal'),
    whisperParamsHelpModalCloseBtn: document.getElementById('whisper-params-help-modal-close-btn'), // Corrected property name to match expected
    whisperParamsHelpContent: document.getElementById('whisperParamsHelpContent'), // Though content is static HTML for now
    helpModalSearchInput: document.getElementById('helpModalSearchInput'), // New
    helpModalToc: document.getElementById('helpModalToc'),                 // New

    // Preset Controls
    whisperPresetSelect: document.getElementById('whisperPresetSelect'),
    loadWhisperPresetBtn: document.getElementById('loadWhisperPresetBtn'),
    savePresetNameInput: document.getElementById('savePresetNameInput'),
    saveWhisperPresetBtn: document.getElementById('saveWhisperPresetBtn'),
    resetAdvancedWhisperParamsBtn: document.getElementById('resetAdvancedWhisperParamsBtn'),

    // Contextual Tooltip Container
    paramTooltip: document.getElementById('paramTooltip'),

    // Sections
    uploadSection: document.getElementById('upload-section'),
    processingOutputSection: document.getElementById('processing-output-section'),
    outputSection: document.getElementById('output-section'),
    
    // Processing Output Elements
    fullTranscriptDisplay: document.getElementById('fullTranscriptDisplay'),
    suggestedClipsContainer: document.getElementById('suggestedClipsContainer'),
    clipAdjustmentControls: document.getElementById('clipAdjustmentControls'),
    clipStartTimeInput: document.getElementById('clipStartTime'),
    clipEndTimeInput: document.getElementById('clipEndTime'),
    createSelectedClipButton: document.getElementById('createSelectedClipButton'),
    
    // Final Output Elements
    playerContainer: document.getElementById('playerContainer'),
    downloadWithSubsButton: document.getElementById('downloadWithSubsButton'),
    downloadWithoutSubsButton: document.getElementById('downloadWithoutSubsButton'),
    downloadSrtButton: document.getElementById('downloadSrtButton')
};
