# ShortsMakerAI Project File Tree

This document outlines the file structure of the ShortsMakerAI project, along with the purpose and key dependencies of each significant file.

```
ShortsMakerAI/
├── .env
│   └── Purpose: Stores environment variables (e.g., API keys). Loaded by backend/config.py.
├── README.md
│   └── Purpose: General project overview, (somewhat outdated) MVP goals, and tech stack.
├── note.py
│   └── Purpose: Standalone utility script to check PyTorch and CUDA installation details for debugging.
├── start_app.py
│   └── Purpose: Main entry point to launch the Flask-SocketIO backend server. Handles eventlet monkey-patching and sys.path setup.
│   └── Dependencies: backend.app_init (app, socketio), backend.routes.
├── backend/
│   ├── __init__.py
│   │   └── Purpose: Makes the 'backend' directory a Python package.
│   ├── app_init.py
│   │   └── Purpose: Initializes the Flask app, Flask-SocketIO, CORS, NLTK SentimentIntensityAnalyzer. Loads configurations, creates essential directories, and registers Flask blueprints.
│   │   └── Dependencies: backend.config, Flask, Flask-CORS, Flask-SocketIO, NLTK. Exports `app`, `socketio`, `analyzer`, `TASK_STATUSES`.
│   ├── clip_suggester.py
│   │   └── Purpose: Core logic for suggesting video clips. Includes scoring based on keywords, sentiment, and AI prompts (using Groq LLMs). Handles Llama API calls, token counting, and fallback logic.
│   │   └── Dependencies: backend.config (GROQ_API_KEYS, GROQ_MODELS_CONFIG), backend.app_init (analyzer), groq SDK, tiktoken.
│   ├── config.py
│   │   └── Purpose: Centralized configuration. Defines paths (UPLOAD_FOLDER, OUTPUT_FOLDER, MODEL_DOWNLOAD_ROOT), valid Whisper models, default short durations, Groq API keys (from .env), and Groq model configurations.
│   │   └── Dependencies: dotenv, os.
│   ├── requirements.txt
│   │   └── Purpose: Lists Python package dependencies for the backend.
│   ├── run.py
│   │   └── Purpose: Alternative script to run the backend server, similar to start_app.py but located within the backend package. Uses `use_reloader=True`.
│   │   └── Dependencies: backend.app_init, backend.routes.
│   ├── subtitle_utils.py
│   │   └── Purpose: Utilities for generating subtitle files. Creates ASS (with karaoke styling) and SRT format content from transcription segments.
│   │   └── Dependencies: logging.
│   ├── tasks.py
│   │   └── Purpose: Orchestrates the main video processing pipeline in a background task. Handles audio extraction, transcription, clip suggestion, and emits progress via SocketIO.
│   │   └── Dependencies: backend.app_init (socketio, app, TASK_STATUSES), backend.config (duration defaults), backend.video_processing (extract_audio), backend.whisper_interface (transcribe_audio), backend.clip_suggester (suggest_clips), backend.subtitle_utils (segments_to_srt_content).
│   ├── video_processing.py
│   │   └── Purpose: Handles video and audio manipulation using FFmpeg (via ffmpeg-python). Includes audio extraction, video segment cutting, and burning ASS subtitles into video.
│   │   └── Dependencies: ffmpeg-python, logging.
│   ├── whisper_interface.py
│   │   └── Purpose: Interface for `faster-whisper` transcription. Manages model loading (CPU/GPU, compute types), runs transcription in a separate thread, handles progress reporting, and cancellation.
│   │   └── Dependencies: faster_whisper, torch, ffmpeg, eventlet, backend.config (MODEL_DOWNLOAD_ROOT), backend.app_init (socketio, TASK_STATUSES).
│   ├── routes/
│   │   ├── __init__.py
│   │   │   └── Purpose: Makes 'routes' a Python package. May also aggregate blueprints.
│   │   ├── clip_routes.py
│   │   │   └── Purpose: Defines Flask blueprint for the `/create_clip` API endpoint. Handles final clip generation (cutting, subtitle burning).
│   │   │   └── Dependencies: Flask, backend.video_processing, backend.subtitle_utils.
│   │   ├── main_routes.py
│   │   │   └── Purpose: Defines Flask blueprint for main routes (e.g., serving `index.html`).
│   │   │   └── Dependencies: Flask.
│   │   ├── status_routes.py
│   │   │   └── Purpose: Defines Flask blueprint for `/api/status` endpoint to get task statuses.
│   │   │   └── Dependencies: Flask, backend.app_init (TASK_STATUSES).
│   │   └── upload_routes.py
│   │       └── Purpose: Defines Flask blueprint for the `/upload` API endpoint. Handles video upload, collects processing parameters, and initiates `process_video_task`.
│   │       └── Dependencies: Flask, backend.app_init (socketio, app), backend.config (VALID_WHISPER_MODELS), backend.tasks (process_video_task).
│   └── tests/
│       ├── __init__.py
│       │   └── Purpose: Makes 'tests' a Python package.
│       ├── test_clip_suggester.py
│       │   └── Purpose: Unit tests for `clip_suggester.py` with mocked dependencies.
│       ├── test_config.py
│       │   └── Purpose: Unit tests for `config.py` constants.
│       ├── test_subtitle_utils.py
│       │   └── Purpose: Unit tests for `subtitle_utils.py`.
│       ├── test_video_processing.py
│       │   └── Purpose: Unit tests for `video_processing.py` with mocked ffmpeg.
│       └── test_whisper_interface.py
│           └── Purpose: Unit tests for `whisper_interface.py` with mocked heavy dependencies.
├── frontend/
│   ├── index.html
│   │   └── Purpose: Main HTML page for the user interface. Includes forms for video upload, parameter selection, and areas for displaying transcripts, suggested clips, and final output.
│   │   └── Dependencies: style.css, Socket.IO client lib (CDN), js/main.js.
│   ├── style.css
│   │   └── Purpose: CSS styles for the frontend.
│   └── js/
│       ├── main.js
│       │   └── Purpose: Main entry point for frontend JavaScript. Initializes all other JS modules and sets up core event handling.
│       │   └── Dependencies: ui.js, api.js, socketHandlers.js, transcript.js, domElements.js, presetManager.js, tooltipManager.js, helpModalManager.js, sliderEventListeners.js, uploadHandler.js, cancelHandler.js, clipCreator.js, appState.js, clipInterfaceManager.js.
│       ├── api.js
│       │   └── Purpose: Handles direct HTTP requests to the backend API (e.g., for `/upload` using XHR, `/create_clip` using Fetch).
│       │   └── Dependencies: (none explicit, uses browser XHR/Fetch).
│       ├── appState.js
│       │   └── Purpose: Manages global frontend application state (e.g., current task ID, selected clip data, progress info).
│       ├── cancelHandler.js
│       │   └── Purpose: Manages logic for the "Cancel Processing" button, emitting 'cancel_task_request' via Socket.IO.
│       │   └── Dependencies: domElements.js, appState.js, (socket instance from main.js).
│       ├── clipCreator.js
│       │   └── Purpose: Handles logic for the "Create Selected Clip" button, calling `api.createClipOnServer`.
│       │   └── Dependencies: domElements.js, appState.js, api.js, ui.js.
│       ├── clipInterfaceManager.js
│       │   └── Purpose: Manages interactions related to selecting clips from the suggested list and adjusting their times via transcript interaction or input fields.
│       │   └── Dependencies: domElements.js, appState.js, ui.js, transcript.js.
│       ├── domElements.js
│       │   └── Purpose: Centralizes DOM element selections using `document.getElementById()`. Exports an object with references to UI elements.
│       ├── helpModalManager.js
│       │   └── Purpose: Manages the display and interaction of the help modal for advanced Whisper parameters.
│       │   └── Dependencies: domElements.js.
│       ├── presetManager.js
│       │   └── Purpose: Manages loading, saving, and applying presets for advanced Whisper parameters using localStorage.
│       │   └── Dependencies: domElements.js.
│       ├── sliderEventListeners.js
│       │   └── Purpose: Sets up event listeners for all slider input elements to update their corresponding value display spans.
│       │   └── Dependencies: domElements.js.
│       ├── socketHandlers.js
│       │   └── Purpose: Initializes and manages the Socket.IO connection and handles incoming real-time events from the server (progress, results, errors, cancellation).
│       │   └── Dependencies: appState.js, (uiUpdateFns passed from main.js).
│       ├── tooltipManager.js
│       │   └── Purpose: Manages the display of contextual tooltips for UI elements (especially advanced parameters).
│       │   └── Dependencies: domElements.js.
│       ├── transcript.js
│       │   └── Purpose: Handles rendering and interaction with the transcript display, including word highlighting, click-and-drag selection, and marking AI-suggested segments.
│       ├── ui.js
│       │   └── Purpose: Contains functions for updating various parts of the UI (status messages, progress bars, visibility of sections, rendering transcript and clips).
│       │   └── Dependencies: transcript.js (for marking AI suggestions).
│       └── uploadHandler.js
│           └── Purpose: Handles the video upload process, collecting form data, managing UI state during upload, and calling `api.uploadVideoToServer`.
│           └── Dependencies: domElements.js, ui.js, api.js, presetManager.js, appState.js.
├── models/
│   └── Purpose: Directory for storing downloaded machine learning models (e.g., `faster-whisper` models like `large-v3.pt`, NLLB models, etc.).
│   ├── large-v3.pt
│   └── models--Systran--faster-whisper-large-v3/
│       └── ... (cached model files from Hugging Face format)
├── outputs/
│   └── Purpose: Default directory for storing processed outputs (extracted audio, generated clips, subtitle files), organized into subdirectories per project.
└── uploads/
    └── Purpose: Default directory for storing uploaded video files.
