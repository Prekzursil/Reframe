# System Patterns: ShortsMakerAI

## Key Technical Decisions

*This section documents key architectural and technical decisions for the ShortsMakerAI project, reflecting current implementation and future plans based on the comprehensive roadmap.*

*   **Core Video Processing:**
    *   **Current:** `ffmpeg-python` (wrapper for FFmpeg) for audio extraction, video clipping, subtitle burning.
    *   **Planned (Phase 1):** Extend `ffmpeg-python` usage for dynamic video resizing and aspect ratio conversion (e.g., for 9:16 vertical shorts).
*   **AI/ML for Content Analysis:**
    *   **Transcription (ASR):**
        *   **Current:** `faster-whisper` (local execution of optimized Whisper models like `large-v3`) with robust compute type selection (GPU: `int8_float16`, `float16`; CPU: `int8`, `float32`).
    *   **Text-based Clip Suggestion NLP:**
        *   **Current:** `nltk` (VADER for sentiment), basic keyword spotting. Groq API for LLMs (Llama 3, Gemma, Mixtral) for advanced relevance scoring of transcript chunks, with token pre-checks (`tiktoken`) and API key/model rotation.
        *   **Planned (Phase 2):** `spaCy` for more advanced NLP (NER, topic analysis, summarization hints) to augment or replace some NLTK usage.
    *   **Audio Pre-processing for ASR:**
        *   **Planned (Phase 1):** Background Music (BGM) / Noise Removal using `demucs` or similar source separation models.
    *   **Audio Post-processing for ASR Context:**
        *   **Planned (Phase 1):** Speaker Diarization using `pyannote.audio` to identify speakers and attribute transcript segments.
    *   **Visual Analysis for Clip Suggestion:**
        *   **Planned (Phase 2):** Scene Detection using `PySceneDetect` or OpenCV.
        *   **Planned (Phase 3):** Facial Recognition/Tracking using OpenCV, `dlib`, or `mediapipe` for smart reframing and content analysis.
    *   **Custom AI Model for Clip Selection (Long-Term R&D):**
        *   **Planned (Phase 3):** Fine-tuning a custom LLM (e.g., Llama 3, Gemma) using Hugging Face `transformers`, `PEFT` for specialized "interesting clip" identification.
*   **Subtitle Generation & Styling:**
    *   **Current:** Generation of SRT (full transcript) and ASS (styled, burned-in for clips) using custom Python logic (`subtitle_utils.py`). Basic karaoke-style highlighting in ASS.
    *   **Planned (Phase 1):** Expanded download formats (WebVTT, TXT).
    *   **Planned (Phase 2):** Full subtitle customization UI and backend logic for advanced ASS styling (fonts, colors, position, effects), potentially storing style presets.
    *   **Planned (Phase 2):** Subtitle Translation using local NLLB models (via Hugging Face `transformers`).
*   **Frontend Framework:**
    *   **Current:** HTML5, CSS3, plain JavaScript (ES6 Modules).
*   **Backend Framework & Language:**
    *   **Current:** Python with Flask.
*   **Real-time Client Communication:**
    *   **Current:** WebSockets via `Flask-SocketIO` (using `python-eventlet`).
*   **Database:**
    *   **Current:** None (in-memory task tracking).
    *   **Planned (Phase 3):** Integration of a database (e.g., SQLite via `SQLAlchemy`/`sqlmodel` initially, possibly PostgreSQL later) for persistent task management, project/media library, and user style presets.
*   **Deployment Strategy:**
    *   **Current:** Flask development server.
    *   **Future (Production):** Gunicorn with `eventlet` or `gevent` workers for WebSocket compatibility. Containerization with Docker is a strong consideration.

## Architecture Patterns

*This section describes the overall system architecture and significant design patterns, reflecting current state and planned evolution.*

*   **Current Architecture (Enhanced MVP):**
    *   **Monolithic Application:** Frontend (HTML/CSS/JS) and Backend (Flask/Python) are part of the same project structure.
    *   **Client-Server Model:** Standard web application interaction.
    *   **Asynchronous Task Processing:** Python's `threading` and `eventlet.queue.Queue` (managed by `socketio.start_background_task`) handle long-running video processing tasks initiated by user uploads.
    *   **Real-time Progress Updates:** WebSockets (Flask-SocketIO) stream progress updates and results from backend to frontend.
    *   **Modular Backend Code:** Python modules for `video_processing`, `ai_processing` (including Whisper and Groq LLM calls), `subtitle_utils`, `tasks`, `routes`, `config`.
    *   **Configuration-Driven LLM Selection:** `GROQ_MODELS_CONFIG` in `config.py` allows prioritized model rotation and token limit awareness for LLM calls.

*   **Planned Architectural Enhancements & Patterns (Derived from New Roadmap):**
    *   **Formalized Multi-Stage Processing Pipeline:**
        *   The backend task execution (currently in `tasks.py`) will evolve into a more explicit pipeline where video/audio data flows through sequential, configurable stages:
            1.  Audio Extraction (`ffmpeg-python`).
            2.  (Optional) BGM/Noise Removal (e.g., `demucs`).
            3.  Transcription (`faster-whisper`).
            4.  (Optional) Speaker Diarization (`pyannote.audio` + alignment logic).
            5.  (Optional) Visual Analysis - Scene Detection (`PySceneDetect`/OpenCV).
            6.  (Optional) Advanced NLP (`spaCy`) on transcript.
            7.  Clip Suggestion (`suggest_clips` using multimodal inputs if available).
            8.  (User Interaction) Clip selection/adjustment.
            9.  Video Clipping & Resizing (`ffmpeg-python`).
            10. Subtitle Generation & Styling (for selected clip).
            11. (Optional) Subtitle Translation (NLLB).
            12. (Future) Visual Analysis - Face Tracking for smart reframing.
    *   **Modular AI Services/Components:** Each major AI capability (BGM removal, diarization, scene detection, spaCy NLP, NLLB translation, facial recognition) will be encapsulated in its own Python module/class with clear interfaces, promoting reusability and testability.
    *   **Persistent Data Store (Database Integration - Phase 3):**
        *   A database (e.g., SQLite initially, then potentially PostgreSQL) will be integrated to manage:
            *   Task queue, status, history, and results (replacing in-memory `TASK_STATUSES`).
            *   User projects and uploaded media library.
            *   User-defined subtitle style presets.
            *   (Future) User accounts and preferences.
        *   This will involve using an ORM like `SQLAlchemy` or `sqlmodel`.
    *   **Multimodal Data Fusion for Clip Suggestion:**
        *   The `suggest_clips` logic will be enhanced to accept and fuse inputs from various modalities:
            *   Textual: Transcript, keywords, sentiment, spaCy NLP features, Llama relevance scores.
            *   Audio: Speaker diarization info.
            *   Visual: Scene change data, facial presence/tracking data.
        *   The scoring algorithm will need to intelligently weigh these diverse features.
    *   **Local Model Management System:**
        *   As more local ML models are added (Demucs, NLLB, spaCy language models, `pyannote` models, OpenCV-based models), a system for managing their:
            *   Downloading from sources (Hugging Face Hub, PyTorch Hub, etc.).
            *   Local caching (in `ShortsMakerAI/models/` subdirectories).
            *   Efficient loading into memory/VRAM.
            *   Optional offloading from VRAM to conserve resources (inspired by Whisper-WebUI).
    *   **Configuration-Driven Feature Toggles:** UI options and backend logic to enable/disable computationally intensive or optional features (BGM removal, diarization, translation, visual analysis) will be crucial for user experience and resource management. These will be managed via `config.py` and passed through the pipeline.
    *   **Advanced Subtitle Engine (Conceptual):**
        *   If full subtitle customization is implemented, the system will require a more sophisticated internal representation of styled text (inspired by `SubtitleEdit.Core.Common.Paragraph`) and an enhanced ASS/WebVTT generation engine in `subtitle_utils.py`.

*   **Longer-Term Scalability Considerations (Post Core Features):**
    *   **Dedicated Task Queue:** If user load increases significantly, migrating from `eventlet` background tasks to a dedicated message broker/task queue (e.g., Celery with Redis or RabbitMQ) would provide better scalability, resilience, and task distribution capabilities.
    *   **Microservices Architecture:** For very large scale or independent team development, some components (e.g., a dedicated "AI Analysis Service" or "Video Processing Service") could be broken out into microservices. This is a major architectural shift and would only be considered much later.

## Analysis of Opus.pro (Preliminary - Based on Public Information)
*This section contains existing analysis of Opus.pro, which serves as a valuable source of inspiration for advanced features and user experience. It will be reviewed and updated periodically as ShortsMakerAI evolves.*

*   **Web-Based Service:** Opus.pro is a SaaS application.
*   **AI-Powered:** Heavily markets its AI capabilities for identifying key moments and generating clips.
*   **Focus on Virality:** Aims to create clips that are likely to perform well on social media.
*   **Key Features (from Help Docs Analysis):**
    *   **Input:** Accepts various video sources (YouTube links, local files implied).
    *   **AI Clipping:**
        *   "ClipAnything" feature: Multimodal AI using visual, audio, sentiment cues. Works even with little dialogue.
        *   Auto-clipping based on AI analysis.
        *   Virality scoring.
        *   Active Speaker Detection / Auto-reframing.
    *   **Customization Options (Pre-Clipping):**
        *   Brand Templates (logo, fonts, styles).
        *   Custom Fonts & Logo upload.
        *   Selectable Aspect Ratio (9:16 implied for shorts).
        *   Selectable Clip Length ranges.
        *   Specific Timeframe selection for clipping.
        *   Keyword/Prompt-based clipping.
        *   Subtitle Language Translation.
        *   Brand Vocabulary (for transcription accuracy).
    *   **Editing (Post-Clipping):**
        *   In-app editor (Text-based and Timeline-based).
        *   Layout adjustments (e.g., split screen).
        *   Manual Reframe.
        *   Subject Tracking (likely related to reframing).
        *   Caption/Subtitle editing.
        *   AI Emojis/Keywords insertion into captions.
        *   Trim/Extend clips.
        *   Text Overlays.
        *   Transition Effects.
        *   Filler Word & Pause Removal ("AI Silence Remover").
        *   AI B-Roll insertion.
        *   AI Voiceover generation.
        *   Intro/Outro Cards.
        *   Upload Custom Media Assets (for B-roll, overlays?).
        *   Add Music.
        *   Keyboard Shortcuts for editing.
        *   Rearrange Scenes/Sections in timeline.
        *   Curse Word Censoring.
    *   **Management & Publishing:**
        *   Project Saving.
        *   Project Sharing/Collaboration.
        *   Bulk Download.
        *   Direct Publishing/Scheduling to Social Accounts (YouTube, Instagram mentioned).
        *   Post Customization (captions, descriptions for social media).
    *   **Export:**
        *   Standard video file download.
        *   XML Export for Adobe Premiere Pro.
        *   XML Export for DaVinci Resolve.
    *   **Account/Team:**
        *   Team Workspace features.
        *   Billing based on credits (consumed per video minute processed).

*(This file will be updated significantly as the project progresses and decisions are made, or existing systems are analyzed.)*
