# ShortsMakerAI

A tool to create short, engaging video clips with animated subtitles from longer videos, inspired by services like Opus.pro.

## Project Phases

### Phase 1: MVP (Current Focus)
-   Video file upload.
-   Audio extraction.
-   Transcription with word-level timestamps (OpenAI Whisper).
-   AI-based clip segment suggestion (NLP on transcript: sentiment, questions, keywords).
-   User interface for reviewing and selecting/adjusting suggested clips.
-   Video cutting for selected segments (FFmpeg).
-   Animated subtitle rendering (one fixed style, e.g., word highlight) burned onto the video.
-   Export options:
    -   Video with animated subtitles.
    -   Video without subtitles.
    -   Separate timed text file (e.g., enhanced SRT or JSON with word timings).

### Future Phases
-   Full subtitle customization UI.
-   Multiple subtitle styles/templates.
-   Database-backed library for project management.
-   Subtitle translation.
-   Advanced AI clip selection (multimodal analysis, virality scoring).
-   Direct social media publishing.

## Technology Stack (MVP)
-   **Backend:** Python (Flask or FastAPI)
-   **Video Processing:** FFmpeg
-   **Transcription:** OpenAI Whisper
-   **AI Clip Suggestion:** Python NLP libraries (NLTK, spaCy)
-   **Animated Subtitle Rendering:** MoviePy or similar
-   **Frontend:** HTML, CSS, JavaScript

## Setup
(To be added)

## Usage
(To be added)
