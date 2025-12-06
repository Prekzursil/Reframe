# Technical Context: ShortsMakerAI

This document outlines the technologies currently used in ShortsMakerAI and those planned or considered for future development, aligned with the project's roadmap.

## Current Core Stack (As of May 2025)

*   **Backend Framework:** Python with Flask.
    *   **Real-time Communication:** `Flask-SocketIO` (using `python-eventlet` for asynchronous operations) for progress updates and communication with the frontend.
    *   **Environment Management:** `python-dotenv` for loading configurations.
*   **Video Processing:**
    *   `ffmpeg-python`: Python wrapper for FFmpeg, used for audio extraction, video clipping, and burning subtitles. (FFmpeg itself is a system dependency).
*   **Audio Transcription (Speech-to-Text):**
    *   `faster-whisper`: Local execution of optimized Whisper models (e.g., `large-v3`) for high-quality transcription with word-level timestamps. Runs on CPU or GPU (CUDA).
    *   `torch`, `torchaudio`, `ctranslate2`: Core dependencies for `faster-whisper` and GPU support.
*   **Natural Language Processing (NLP) & AI for Clip Suggestion:**
    *   **Basic NLP:** `nltk` (Natural Language Toolkit), primarily using VADER for sentiment analysis and basic keyword spotting.
    *   **Advanced Relevance Scoring:** Groq API, providing access to LLMs like Llama 3, Gemma, and Mixtral for analyzing transcript chunks and scoring relevance to user prompts.
    *   **Token Counting:** `tiktoken` for pre-checking input token counts against LLM context windows.
*   **Subtitle Generation:**
    *   **Output Formats:** SRT (for full transcript), ASS (Advanced SubStation Alpha for styled, burned-in subtitles on clips).
    *   Custom Python logic in `subtitle_utils.py` for generating these formats.
*   **Frontend:**
    *   HTML5, CSS3, plain JavaScript (ES6 Modules).
    *   Socket.IO client library for real-time communication.
*   **Task Management:**
    *   Python's built-in `threading` and `eventlet.queue.Queue` for managing asynchronous processing tasks in-memory.
*   **Development Environment:**
    *   Python (typically 3.10+).
    *   Virtual environments (`venv`).
    *   `pip` with `requirements.txt` for package management.

## Technologies for Future Enhancements (Based on Roadmap)

This section lists technologies identified for implementing features in the project roadmap (see `next_steps_and_improvements.md`).

*   **Speaker Diarization (Phase 1):**
    *   `pyannote.audio`: Core library.
    *   `speechbrain`: Often a core dependency for `pyannote.audio`.
    *   `torch`, `torchaudio`: Required by `pyannote.audio`.
    *   *Consideration:* Requires Hugging Face Hub token and user agreement to `pyannote` model terms. Models are downloaded and cached locally.
    *   `whisperx` (Alternative): Library that bundles Whisper with `pyannote` alignment.
*   **BGM Removal / Source Separation (Phase 1):**
    *   `demucs`: (PyTorch Hub or pip package).
    *   *Consideration:* Demucs models are large and computationally intensive; requires local model downloads.
*   **Dynamic Video Resizing (Phase 1):**
    *   `ffmpeg-python` (already in use): Its filter system (`scale`, `crop`, `pad`) can handle resizing and aspect ratio conversion.
    *   `MoviePy` (Alternative): Higher-level library, wraps FFmpeg.
*   **Expanded Subtitle Formats (Phase 1):**
    *   (No major new external libraries, primarily new parsing/formatting logic in `subtitle_utils.py` for WebVTT, TXT).
*   **Visual Analysis - Scene Detection (Phase 2):**
    *   `PySceneDetect`: Dedicated library for scene change detection in videos.
    *   `OpenCV-Python` (`cv2`): General computer vision library, can also be used for scene detection or other frame analysis.
*   **Advanced NLP (Phase 2):**
    *   `spaCy`: Comprehensive NLP library for tasks like named entity recognition (NER), part-of-speech tagging, dependency parsing, text categorization, more advanced sentence segmentation.
    *   *Consideration:* Requires downloading spaCy language models (e.g., for English).
*   **Subtitle Translation - Local NLLB (Phase 2):**
    *   Hugging Face `transformers`: To load and run NLLB (No Language Left Behind) models.
    *   `sentencepiece`: Tokenizer often required for NLLB models.
    *   `torch`: As a backend for `transformers`.
    *   *Consideration:* NLLB models are very large (e.g., `nllb-200-distilled-600M` is manageable, but larger ones like 1.3B or 3.3B are multi-GB) and require significant resources for local inference.
*   **Full Subtitle Customization (Phase 2):**
    *   (Primarily frontend UI development and significant expansion of backend ASS generation logic in `subtitle_utils.py`. May involve JSON for style preset storage/exchange).
*   **Database for Task Management & Project Library (Phase 3):**
    *   `SQLAlchemy`: Python SQL toolkit and ORM.
    *   `sqlmodel`: Modern Python library built on Pydantic and SQLAlchemy, good for data validation and ORM (especially if considering FastAPI in future).
    *   Database engine: `sqlite3` (Python built-in, for simplicity) or a more robust server like `PostgreSQL` (requires `psycopg2-binary`) or `MySQL` (requires `mysql-connector-python`).
*   **Visual Analysis - Facial Recognition/Tracking (Phase 3):**
    *   `OpenCV-Python` (`cv2`).
    *   `dlib`: Library for face detection, landmark detection.
    *   `face_recognition`: Simpler library built on `dlib`.
    *   `mediapipe` (Google): For face detection, mesh, tracking, and other perception tasks.
    *   *Consideration:* These often require pre-trained model files and can be computationally intensive.
*   **Fine-tuning Custom LLM for Clip Selection (Phase 3 - R&D):**
    *   Hugging Face `transformers`, `datasets`, `evaluate`.
    *   `PEFT` (Parameter-Efficient Fine-Tuning) library from Hugging Face for LoRA/QLoRA.
    *   `bitsandbytes`: For 8-bit/4-bit quantization during training (QLoRA).
    *   `accelerate`: For distributed training and large model handling.
    *   PyTorch (already used).
*   **Direct Social Media Publishing (Phase 3):**
    *   Official Python SDKs or direct API interaction (`requests`) for YouTube Data API, TikTok API, Instagram Graph API, etc. (Requires research into each platform's capabilities and terms).

## Development Setup

*   **Version Control:** Git, GitHub.
*   **Python Version:** 3.10 or newer recommended.
*   **Package Management:** `pip` with `requirements.txt` within a Python virtual environment (`venv`).
*   **System Dependencies:**
    *   FFmpeg: Must be installed and accessible in the system PATH.
    *   CUDA Toolkit & NVIDIA Drivers: Required for GPU acceleration with PyTorch and `faster-whisper`. Version compatibility is crucial (e.g., CUDA 11.8 or 12.x for recent PyTorch/`faster-whisper` builds).
*   **IDE:** Visual Studio Code with Python extension recommended.
*   **Configuration:** `.env` file for API keys and sensitive configurations.

## Technical Constraints & Considerations

*   **Resource Requirements:** Many planned features (BGM removal, NLLB translation, advanced visual analysis, custom LLM fine-tuning/hosting) involve large AI models that demand significant CPU, GPU (VRAM), RAM, and disk space. This will impact usability for users with less powerful hardware. Model offloading strategies might be needed.
*   **Processing Time:** Each additional AI processing step (UVR, diarization, visual analysis, advanced NLP, translation) will add to the total time taken to generate clips. Balancing feature richness with acceptable processing speed is key.
*   **Complexity of Integration:** Managing a pipeline with multiple, potentially resource-intensive AI models requires careful design for efficiency, error handling, and resource sharing/conflict avoidance.
*   **External Dependencies & Setup:** Some features (diarization via `pyannote`, NLLB models, spaCy models, Demucs models) require users to download large model files or obtain API keys/tokens (e.g., Hugging Face token for `pyannote`). Clear instructions and robust error handling for missing dependencies are essential.
*   **Licensing:**
    *   Core ShortsMakerAI aims for a permissive license (e.g., MIT).
    *   Care must be taken when drawing inspiration or integrating libraries. For example, `pyannote.audio` models have specific terms of use (requiring HF login and agreement). GPL-licensed code (like from Subtitle Edit) cannot be directly incorporated if we wish to maintain a non-GPL license for ShortsMakerAI.
*   **API Costs & Rate Limits:** While we currently use Groq's free tier (generous but subject to change), any future use of commercial APIs (e.g., DeepL, other LLM providers if Groq limits become an issue) would introduce cost considerations and require robust rate limit handling.
