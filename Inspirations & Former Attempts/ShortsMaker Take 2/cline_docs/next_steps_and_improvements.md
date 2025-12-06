# ShortsMakerAI: Next Steps & Improvements Roadmap

This document outlines a comprehensive plan for enhancing ShortsMakerAI, drawing inspiration and technical insights from the analysis of projects like Whisper-WebUI, Clipify, and Subtitle Edit. The goal is to significantly improve clip suggestion quality, expand features, and increase robustness.

## Phase 0: Current System Tuning & Stabilization (Immediate Next Steps)

**Objective:** Maximize the performance of the existing features and ensure stability before adding major new components.

1.  **Thorough Testing of Recent Features:**
    *   **Groq LLM Integration:** Verify model rotation (from `GROQ_MODELS_CONFIG`), API key cycling (including the new exhaustive key trial logic), input token pre-checks, and segment chunking for Llama analysis. Test with various AI prompts and video lengths.
    *   **Compute Type Selection:** Confirm `faster-whisper` uses optimal GPU compute types (e.g., `int8_float16` or `float16`) with "Auto" mode. Test explicit selections.
    *   **Enhanced Fallback for Clip Suggestions:** Verify the new fallback (using wider duration filters if primary suggestions fail) provides reasonable results.
    *   **UI Controls:** Test Beam Size, Min/Max Duration inputs, and the Cancel Processing button across various scenarios.
2.  **Fine-Tuning `suggest_clips` Logic (`ai_processing.py`):**
    *   **Crucial Test:** Conduct systematic tests with various videos using a general AI prompt (e.g., "Find interesting segments") and **very wide duration filters** (e.g., 5s to 300s or more). Analyze the logs to understand:
        *   The number of "potential clips" (score > 0) found before any duration filtering.
        *   The actual scores and durations of these potential clips.
        *   This data is VITAL for understanding if the current scoring is fundamentally working but misaligned with typical short clip durations, or if scores are too low overall.
    *   **Adjust `SUGGESTION_WEIGHTS`:** Based on the test results, iteratively tune the weights for keywords, sentiment, Llama relevance, ideal length bonus, and short/long penalties. The goal is to have the primary scoring logic (before fallback) identify good clips within typical short durations (e.g., 30-90s) more reliably.
    *   **Refine Llama System Prompt:** Experiment with the system prompt sent to Groq LLMs. For general user AI prompts (like "find interesting parts"), the system prompt could guide the LLM to look for specific characteristics of "interesting" content (e.g., emotional peaks, clear explanations, surprising statements, humor).
    *   **Experiment with `LLAMA_CHUNK_SIZE_SEGMENTS`:** Test if changing the number of transcript segments per chunk (e.g., from 3 to 1 for more granularity, or to 5 for more context) improves Llama's relevance scores or the quality of justifications.
3.  **Bug Fixing & Stability:** Address any bugs, errors, or performance bottlenecks identified during this tuning and testing phase. Ensure robust error handling and clear logging.

## Phase 1: Core Clip Intelligence & Output Enhancements

**Objective:** Significantly improve the AI's ability to identify high-quality clips and enhance the utility of the output.

1.  **Speaker Diarization:**
    *   **Goal:** Identify *who* speaks *when* in the video. Massively improves context for clip selection.
    *   **Inspiration:** `Whisper-WebUI` (uses `pyannote.audio`).
    *   **Tech:** Integrate `pyannote.audio` library. Requires Hugging Face token and user agreement to `pyannote` model terms.
    *   **Implementation Steps:**
        *   Add `pyannote.audio` and its dependencies (e.g., `speechbrain`) to `requirements.txt`.
        *   Develop a module for diarization (e.g., `diarization_processing.py`).
        *   In `tasks.py`, after transcription, pass the audio and transcript segments to the diarization module.
        *   Implement alignment of `pyannote` speaker turns with `faster-whisper` word/segment timestamps (can study `Whisper-WebUI`'s `assign_word_speakers` or libraries like `whisperx`).
        *   Update internal segment data structure to store `speaker_id`.
        *   Modify `suggest_clips` to use speaker information (e.g., prefer clips with a single dominant speaker, identify dialogues, allow AI prompt to specify speaker interest).
        *   Update UI (`index.html`, `js/ui.js`) to display speaker labels in the transcript and suggested clips.
        *   Add UI option to enable/disable diarization (as it adds processing time).
        *   Guide users on obtaining/configuring an HF token.
2.  **Background Music (BGM) / Noise Removal (Source Separation):**
    *   **Goal:** Improve transcript accuracy for noisy audio.
    *   **Inspiration:** `Whisper-WebUI` (uses UVR/Demucs).
    *   **Tech:** Integrate a source separation library like `demucs` (from PyTorch Hub or pip).
    *   **Implementation Steps:**
        *   Add `demucs` dependency. Manage Demucs model downloads/paths (e.g., in `ShortsMakerAI/models/uvr_models/`).
        *   Add as an optional pre-processing step in `tasks.py`: after `extract_audio`, pass the audio track to a new BGM removal module. The "vocals" track output becomes the input for `transcribe_audio`.
        *   Add UI option (e.g., checkbox "Remove Background Music").
        *   Handle model loading/offloading for Demucs to manage resources.
3.  **Dynamic Video Resizing & Formatting (for Social Media):**
    *   **Goal:** Allow users to output clips in common social media aspect ratios (e.g., 9:16 vertical, 1:1 square).
    *   **Inspiration:** `Clipify-main` (conceptual).
    *   **Tech:** `ffmpeg-python` (which we already use).
    *   **Implementation Steps:**
        *   Add UI options in `index.html` for target aspect ratio (e.g., Original, 9:16, 1:1, 4:5).
        *   In `video_processing.py` (`create_clip` function), add logic to apply `ffmpeg` filters for resizing, cropping, and padding (e.g., `scale`, `crop`, `pad` filters) to achieve the target aspect ratio.
        *   Consider initial strategies like center cropping, or scaling to fit and adding blurred background padding. (Advanced "smart cropping" that keeps action/speaker in frame would depend on visual analysis from later phases).
4.  **Expanded Subtitle Download Formats:**
    *   **Goal:** Offer WebVTT and plain TXT downloads for full transcripts and/or clip subtitles.
    *   **Inspiration:** `Whisper-WebUI`, `SubtitleEdit`.
    *   **Tech:** Minor additions to `subtitle_utils.py`.
    *   **Implementation Steps:**
        *   Add functions `generate_vtt_content(segments)` and `generate_txt_content(segments)`.
        *   Add corresponding download buttons/options in the UI for the full transcript and for individual generated clips.

## Phase 2: Advanced Content Understanding & User Experience

**Objective:** Incorporate deeper content analysis (visual, advanced NLP) and provide a richer user experience for subtitle customization and project management.

1.  **Visual Analysis - Scene Detection:**
    *   **Goal:** Identify scene changes in the video. This can be used to improve clip segmentation (avoiding cuts mid-scene) or as a factor in scoring "visual interest."
    *   **Inspiration:** `Clipify-main` (conceptual).
    *   **Tech:** `PySceneDetect` library or OpenCV-based custom solution.
    *   **Implementation Steps:**
        *   Add dependency.
        *   In `tasks.py`, after video upload, run scene detection.
        *   Store scene change timestamps.
        *   In `suggest_clips`, use scene change information:
            *   As potential preferred boundaries for clips.
            *   To penalize clips that span too many jarring scene changes.
            *   Potentially as a feature for Llama analysis (e.g., "this chunk spans 3 scenes").
2.  **Advanced NLP with spaCy:**
    *   **Goal:** Deeper text understanding beyond current keywords/sentiment (e.g., named entities, topics, summarization hints).
    *   **Inspiration:** `Clipify-main` (conceptual).
    *   **Tech:** `spaCy` library.
    *   **Implementation Steps:**
        *   Add `spaCy` dependency and download language models (e.g., for English).
        *   Create a new NLP processing module using `spaCy`.
        *   In `suggest_clips`, after getting the transcript, run `spaCy` analysis on segments or chunks.
        *   Incorporate new features (e.g., density of key entities, presence of questions/imperatives, topic shift indicators) into the segment scoring logic.
3.  **Subtitle Translation (Local NLLB Models):**
    *   **Goal:** Allow users to translate subtitles of generated clips into multiple languages locally.
    *   **Inspiration:** `Whisper-WebUI` (NLLB integration).
    *   **Tech:** Hugging Face `transformers` library, `sentencepiece`, NLLB models.
    *   **Implementation Steps:**
        *   Add dependencies.
        *   Implement NLLB model management (downloading selected models like `nllb-200-distilled-600M` to `ShortsMakerAI/models/nllb_models/`).
        *   Create a translation module (`translation_processing.py`?) that takes text segments and target language, loads the NLLB pipeline, and returns translated segments.
        *   Add UI elements (e.g., after a clip is generated) to select a target language and initiate translation.
        *   Generate a new SRT/ASS file with translated text, preserving timings.
        *   Inform users about NLLB model download sizes and processing requirements.
4.  **Full Subtitle Customization UI & Multiple Styles:**
    *   **Goal:** Give users extensive control over subtitle appearance (font, size, color, position, outline, shadow, background, karaoke-style highlighting options). Allow saving/loading style presets.
    *   **Inspiration:** User's original roadmap, capabilities of `SubtitleEdit`.
    *   **Tech:**
        *   Frontend: Advanced HTML/CSS/JS controls for style parameters.
        *   Backend:
            *   Extend internal segment data structure (or add a parallel style track) to store detailed styling information per segment or per defined style group.
            *   Significantly enhance `subtitle_utils.generate_ass_content` to interpret these detailed style objects and generate complex ASS tags.
            *   Potentially add a `styles.json` or similar to save/load user-defined style presets.
    *   **Implementation Steps:** This is a large UI and backend effort. Design style editor UI. Define style data structures. Implement robust ASS tag generation.

## Phase 3: Platform Robustness & Cutting-Edge AI

**Objective:** Build a highly robust, scalable platform and explore state-of-the-art AI for clip selection.

1.  **Database for Task Management & Project Library:**
    *   **Goal:** Persistent task tracking, job history, user project/media library.
    *   **Inspiration:** `Whisper-WebUI` backend architecture, user's original roadmap.
    *   **Tech:** Python DB library (e.g., `SQLAlchemy` with SQLite for initial simplicity, potentially PostgreSQL for future scale).
    *   **Implementation Steps:**
        *   Design database schema (tasks, projects, videos, clips, user accounts if added).
        *   Replace current in-memory `TASK_STATUSES` with database operations.
        *   Develop UI for a project library to view/manage past jobs and generated assets.
2.  **Visual Analysis - Facial Recognition/Tracking (Advanced):**
    *   **Goal:** Enable features like keeping the main speaker in frame for dynamically resized vertical videos ("smart reframing"), or identifying clips with high face-time.
    *   **Inspiration:** `Clipify-main` (conceptual).
    *   **Tech:** OpenCV, face detection models (e.g., from `dlib`, `mediapipe`, or OpenCV's DNN module), object tracking algorithms.
    *   **Implementation Steps:**
        *   Integrate face detection and tracking libraries.
        *   Process video to get face bounding boxes over time.
        *   Use this data in `video_processing.py` to guide cropping/panning for reframing.
        *   Use face presence/duration as a potential scoring factor in `suggest_clips`.
3.  **Fine-tuning a Custom LLM for Clip Selection (Long-Term R&D):**
    *   **Goal:** Develop an LLM highly specialized in identifying "interesting" or "viral" clips from transcripts, potentially outperforming general-purpose LLMs with prompting.
    *   **Inspiration:** Discussions about Opus Pro's AI capabilities.
    *   **Tech:** Hugging Face `transformers`, PEFT (LoRA/QLoRA), dataset creation and annotation tools/pipeline.
    *   **Implementation Steps:** This is a research-heavy effort.
        1.  Define precise criteria for "good clips."
        2.  Collect and meticulously annotate a large dataset of (video transcript segment, interestingness_score, reasons/tags).
        3.  Choose a suitable open-source base LLM (e.g., Llama 3, Gemma).
        4.  Set up a fine-tuning pipeline.
        5.  Train, evaluate, and iterate.
        6.  Deploy the fine-tuned model locally (e.g., using CTranslate2, llama.cpp, or other optimized inference engines) and integrate it into `ai_processing.py`.
4.  **Direct Social Media Publishing (Long-Term):**
    *   **Goal:** Allow users to directly publish or schedule their generated short clips to platforms like YouTube Shorts, TikTok, Instagram Reels.
    *   **Inspiration:** User's original roadmap.
    *   **Tech:** Research and integrate official APIs for each target platform (if available and suitable for this use case). Handle authentication (OAuth).
    *   **Implementation Steps:** Complex, involves per-platform API integration and UI for managing accounts/scheduling.

## Ongoing Considerations (Across All Phases)

*   **Performance Optimization:** Continuously monitor and optimize processing speed for all steps (audio extraction, transcription, AI analysis, video rendering).
*   **User Experience (UX) Refinements:** Iteratively improve the UI based on user feedback and usability testing.
*   **Error Handling & Robustness:** Enhance error handling throughout the application to make it more resilient.
*   **Configuration & Customization:** Provide users with more control over default settings and processing parameters where appropriate.
*   **Documentation:** Keep user and developer documentation up-to-date.
*   **Code Quality:** Maintain clean, modular, and well-commented code.
