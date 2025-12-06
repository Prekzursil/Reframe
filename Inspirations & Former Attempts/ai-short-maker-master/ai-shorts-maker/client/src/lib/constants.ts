export const LANGUAGES = [
  { value: "af", label: "Afrikaans" },
  { value: "ar", label: "Arabic" },
  { value: "bn", label: "Bengali" },
  { value: "bg", label: "Bulgarian" },
  { value: "zh", label: "Chinese" },
  { value: "hr", label: "Croatian" },
  { value: "cs", label: "Czech" },
  { value: "da", label: "Danish" },
  { value: "nl", label: "Dutch" },
  { value: "en", label: "English" },
  { value: "et", label: "Estonian" },
  { value: "fi", label: "Finnish" },
  { value: "fr", label: "French" },
  { value: "de", label: "German" },
  { value: "el", label: "Greek" },
  { value: "gu", label: "Gujarati" },
  { value: "he", label: "Hebrew" },
  { value: "hi", label: "Hindi" },
  { value: "hu", label: "Hungarian" },
  { value: "is", label: "Icelandic" },
  { value: "id", label: "Indonesian" },
  { value: "it", label: "Italian" },
  { value: "ja", label: "Japanese" },
  { value: "kn", label: "Kannada" },
  { value: "ko", label: "Korean" },
  { value: "lv", label: "Latvian" },
  { value: "lt", label: "Lithuanian" },
  { value: "ms", label: "Malay" },
  { value: "ml", label: "Malayalam" },
  { value: "mr", label: "Marathi" },
  { value: "no", label: "Norwegian" },
  { value: "fa", label: "Persian" },
  { value: "pl", label: "Polish" },
  { value: "pt", label: "Portuguese" },
  { value: "ro", label: "Romanian" },
  { value: "ru", label: "Russian" },
  { value: "sr", label: "Serbian" },
  { value: "sk", label: "Slovak" },
  { value: "sl", label: "Slovenian" },
  { value: "es", label: "Spanish" },
  { value: "sw", label: "Swahili" },
  { value: "sv", label: "Swedish" },
  { value: "ta", label: "Tamil" },
  { value: "te", label: "Telugu" },
  { value: "th", label: "Thai" },
  { value: "tr", label: "Turkish" },
  { value: "uk", label: "Ukrainian" },
  { value: "ur", label: "Urdu" },
  { value: "vi", label: "Vietnamese" }
];

export const WHISPER_MODELS = [
  { value: 'tiny', label: 'Tiny (Fastest)' },
  { value: 'base', label: 'Base (Fast)' },
  { value: 'small', label: 'Small (Balanced)' },
  { value: 'medium', label: 'Medium (Accurate)' },
  { value: 'large', label: 'Large (Most Accurate)' }
];

export const SUBTITLE_TEMPLATES = [
  {
    id: 'tiktok',
    name: 'TikTok Style',
    style: {
      fontSize: 24,
      fontColor: '#FFFFFF',
      highlightColor: '#FF3B30',
      backgroundColor: '#000000',
      opacity: 80
    }
  },
  {
    id: 'youtube',
    name: 'YouTube Style',
    style: {
      fontSize: 20,
      fontColor: '#FFFFFF',
      highlightColor: '#FF0000',
      backgroundColor: '#000000',
      opacity: 70
    }
  },
  {
    id: 'instagram',
    name: 'Instagram Style',
    style: {
      fontSize: 22,
      fontColor: '#FFFFFF',
      highlightColor: '#E1306C',
      backgroundColor: '#000000',
      opacity: 75
    }
  },
  {
    id: 'modern',
    name: 'Modern Clean',
    style: {
      fontSize: 26,
      fontColor: '#FFFFFF',
      highlightColor: '#3B82F6',
      backgroundColor: '#1F2937',
      opacity: 85
    }
  },
  {
    id: 'minimal',
    name: 'Minimal',
    style: {
      fontSize: 20,
      fontColor: '#FFFFFF',
      highlightColor: '#6B7280',
      backgroundColor: '#000000',
      opacity: 60
    }
  }
];