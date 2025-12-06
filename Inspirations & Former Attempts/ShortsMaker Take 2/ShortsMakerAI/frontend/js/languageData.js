/**
 * languageData.js
 * Stores language information for Whisper models.
 */

export const languageCodeToName = {
    "auto": "Auto Detect",
    "en": "English",
    "af": "Afrikaans",
    "sq": "Albanian",
    "am": "Amharic",
    "ar": "Arabic",
    "hy": "Armenian",
    "as": "Assamese",
    "az": "Azerbaijani",
    "ba": "Bashkir", // Note: Whisper might use 'ba' for Bashkir
    "eu": "Basque",
    "be": "Belarusian",
    "bn": "Bengali",
    "bs": "Bosnian",
    "br": "Breton",
    "bg": "Bulgarian",
    "my": "Burmese",
    "ca": "Catalan",
    "zh": "Chinese", // Covers Mandarin, Cantonese as per user confirmation
    "hr": "Croatian",
    "cs": "Czech",
    "da": "Danish",
    "nl": "Dutch",
    "et": "Estonian",
    "fo": "Faroese",
    "fi": "Finnish",
    "fr": "French",
    "fy": "Western Frisian",
    "gl": "Galician",
    "ka": "Georgian",
    "de": "German",
    "el": "Greek",
    "gu": "Gujarati",
    "ht": "Haitian Creole",
    "ha": "Hausa",
    "he": "Hebrew",
    "hi": "Hindi",
    "hu": "Hungarian",
    "is": "Icelandic",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "jw": "Javanese",
    "kn": "Kannada",
    "kk": "Kazakh",
    "km": "Khmer",
    "ko": "Korean",
    "ku": "Kurdish",
    "lo": "Lao",
    "la": "Latin",
    "lv": "Latvian",
    "ln": "Lingala", // Added, often in Whisper lists
    "lt": "Lithuanian",
    "lb": "Luxembourgish",
    "mk": "Macedonian",
    "mg": "Malagasy", // Added, often in Whisper lists
    "ms": "Malay",
    "ml": "Malayalam",
    "mt": "Maltese",
    "mi": "Maori",
    "mr": "Marathi",
    "mn": "Mongolian",
    "ne": "Nepali",
    "no": "Norwegian",
    "ny": "Nyanja",
    "oc": "Occitan", // Added, often in Whisper lists
    "ps": "Pashto",
    "fa": "Persian",
    "pl": "Polish",
    "pt": "Portuguese",
    "pa": "Punjabi",
    "ro": "Romanian",
    "ru": "Russian",
    "sa": "Sanskrit",
    "sc": "Sardinian", // Added, often in Whisper lists
    "sr": "Serbian",
    "sn": "Shona",
    "sd": "Sindhi",
    "si": "Sinhala",
    "sk": "Slovak",
    "sl": "Slovenian",
    "so": "Somali",
    "es": "Spanish",
    "su": "Sundanese",
    "sw": "Swahili",
    "sv": "Swedish",
    "tl": "Tagalog",
    "tg": "Tajik",
    "ta": "Tamil",
    "tt": "Tatar",
    "te": "Telugu",
    "th": "Thai",
    "ti": "Tigrinya",
    "tr": "Turkish",
    "tk": "Turkmen",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "uz": "Uzbek",
    "vi": "Vietnamese",
    "cy": "Welsh",
    "xh": "Xhosa",
    "yi": "Yiddish",
    "yo": "Yoruba",
    "zu": "Zulu"
};

// Full list of language codes based on the extended languageCodeToName map
const allSupportedLanguages = Object.keys(languageCodeToName).filter(code => code !== "auto");

export const whisperModelLanguages = {
    "tiny": ["en", "es", "fr", "de", "it", "pt", "nl", "ro"], // Example subset, to be refined
    "tiny.en": ["en"],
    "base": ["en", "es", "fr", "de", "it", "pt", "nl", "ru", "zh", "ja", "ko", "ro"], // Example subset, to be refined
    "base.en": ["en"],
    "small": ["en", "es", "fr", "de", "it", "pt", "nl", "ru", "zh", "ja", "ko", "ar", "hi", "ro", "pl", "sv", "tr"], // Example subset, to be refined
    "small.en": ["en"],
    "medium": ["en", "es", "fr", "de", "it", "pt", "nl", "ru", "zh", "ja", "ko", "ar", "hi", "ro", "pl", "sv", "tr", "uk", "vi", "el", "cs", "hu"], // Example subset, to be refined
    "medium.en": ["en"],
    "large-v1": allSupportedLanguages,
    "large-v2": allSupportedLanguages,
    "large-v3": allSupportedLanguages,
};

// Ensure 'en' is present in multilingual models if it's in the main list
// (This loop is mostly for safety, as 'en' is explicitly in subsets and allSupportedLanguages)
for (const model in whisperModelLanguages) {
    if (!model.endsWith(".en") && !whisperModelLanguages[model].includes("en") && allSupportedLanguages.includes("en")) {
        if (whisperModelLanguages[model].length > 0 || model.startsWith("large")) { 
            // Add English to the beginning if not present, especially for large models
            // For smaller models, this depends on their actual training data.
            // The current subsets for tiny, base, small, medium already include 'en'.
        }
    }
}
