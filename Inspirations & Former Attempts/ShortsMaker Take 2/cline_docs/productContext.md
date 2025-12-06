# Product Context: ShortsMakerAI

## Why this project exists
The user wants to build a powerful, locally-runnable alternative to cloud-based services like [opus.pro](https://www.opus.pro/). The goal is to create a sophisticated system that can take long videos and automatically generate multiple high-quality, engaging short clips with customizable subtitles, suitable for various social media platforms (YouTube Shorts, TikTok, Instagram Reels, etc.). The emphasis is on leveraging advanced AI techniques for intelligent content analysis and providing users with significant control over the output.

## What problems it solves
-   **Efficient Content Repurposing:** Enables creators to easily transform long-form video content (podcasts, interviews, lectures, gameplay, etc.) into numerous short-form pieces, maximizing content value.
-   **Significant Time Savings:** Automates the traditionally labor-intensive processes of identifying interesting segments, transcribing, clipping, resizing, and generating subtitles.
-   **Enhanced Engagement & Virality:** Aims to produce short-form video with compelling content and accurate, styled subtitles, which are key drivers for engagement on social media.
-   **Improved Accessibility:** Automatically generated and customizable subtitles make content accessible to a broader audience, including those with hearing impairments or who watch videos with sound off.
-   **Higher Content Quality & Wider Reach (Planned):**
    *   **Quality:** Features like BGM/noise removal, speaker diarization for clear attribution, and visual analysis for better shot composition will lead to more professional and polished short clips.
    *   **Reach:** Subtitle translation will allow content to connect with international audiences. Dynamic resizing ensures optimal presentation on different platforms.

## How it should work (High-Level Vision based on Roadmap)

1.  **Input:**
    *   User uploads a long video file.
    *   (Planned) User provides a YouTube URL for direct processing.

2.  **AI-Powered Multimodal Analysis Pipeline:**
    *   The system processes the video through a configurable pipeline of AI modules:
        *   **Audio Extraction:** Isolates the audio track from the video.
        *   **(Optional) BGM/Noise Removal (Phase 1 Plan):** Separates vocals from background music/noise using models like Demucs for cleaner audio input to ASR.
        *   **Transcription (ASR):** Generates a highly accurate transcript with word-level timestamps using `faster-whisper` (leveraging GPU acceleration like `int8_float16` or `float16`).
        *   **(Optional) Speaker Diarization (Phase 1 Plan):** Identifies different speakers and attributes transcript segments to them using `pyannote.audio` or similar, aligning speaker turns with word timestamps.
        *   **Textual NLP Analysis:**
            *   **Current:** NLTK for sentiment (VADER) and basic keyword spotting.
            *   **Current:** Groq API for LLMs (Llama 3, Gemma, Mixtral) to analyze transcript chunks for relevance to user prompts, providing scores and justifications. Includes token pre-checks and model/key rotation.
            *   **(Planned - Phase 2):** `spaCy` for deeper NLP (Named Entity Recognition, topic analysis, summarization cues, advanced question/imperative detection) to enrich content understanding.
        *   **(Optional) Visual Analysis:**
            *   **(Planned - Phase 2):** Scene Detection (using `PySceneDetect` or OpenCV) to identify scene changes, which can guide clip boundaries or scoring.
            *   **(Planned - Phase 3):** Facial Recognition/Tracking (using OpenCV, `dlib`, or `mediapipe`) to identify segments with human presence, track speakers for smart reframing, and potentially assess visual engagement.
    *   **Clip Scoring & Suggestion:**
        *   A sophisticated scoring algorithm fuses data from textual, audio (speaker info), and visual analyses to identify the most promising segments for short clips.
        *   User-provided AI prompts and keywords heavily influence this scoring.
        *   (Long-term Aspiration) Potential for a "virality score" or custom-trained ML model for clip selection.

3.  **Clip Generation & Customization:**
    *   **Automated Suggestions:** The system proposes multiple short clip candidates based on the AI analysis, respecting user-defined duration ranges (with an enhanced fallback for broader suggestions if needed).
    *   **Dynamic Resizing & Reframing (Phase 1 & 3 Plan):**
        *   Clips can be automatically reformatted to various social media aspect ratios (e.g., 9:16 vertical, 1:1 square).
        *   (Future) Smart reframing using facial tracking data to keep the main subject optimally in view for vertical formats.
    *   **Subtitle Generation & Advanced Customization (Phase 2 Plan):**
        *   Accurate subtitles are generated for each clip.
        *   Users will have extensive UI controls to customize subtitle appearance: font, size, color, position, outline, shadow, background, karaoke-style highlighting, and potentially save/load style presets (inspired by Subtitle Edit). Output primarily in ASS format for rich styling.
    *   **(Optional) Subtitle Translation (Phase 2 Plan):**
        *   Generated subtitles can be translated into multiple languages using locally run NLLB models.

4.  **User Interface & Workflow:**
    *   **Review & Editing:** Users can review the full transcript (with speaker labels - planned), see suggested clips, adjust clip start/end times, and edit subtitle text.
    *   **Preview:** Preview generated clips with subtitles.
    *   **Download Options:**
        *   Download final video clips (with or without burned-in subtitles).
        *   Download subtitle files in various formats (SRT, WebVTT, TXT - planned).
    *   **(Planned - Phase 3) Project Library & Task Management:** A database backend will support persistent storage of tasks, projects, uploaded media, and generated assets, with a UI for managing them.

5.  **Output:**
    *   High-quality, engaging short video clips, optimized for social media platforms, with accurate and customizable subtitles.

This vision aims for a powerful, locally-runnable tool that rivals commercial offerings in intelligence and feature set, while giving users full control over their data and processing.
