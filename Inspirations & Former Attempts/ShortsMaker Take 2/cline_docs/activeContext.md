# Active Context: Launching New Development Roadmap

## What you're working on now
Having successfully implemented a robust "Enhanced MVP" for ShortsMakerAI (including stable GPU-accelerated transcription with `faster-whisper`, advanced AI clip suggestion using Groq LLMs, and core UI functionalities) and completed an extensive analysis of related projects (`Whisper-WebUI-master`, `Clipify-main` concepts, `SubtitleEdit` concepts), we are now transitioning to a new comprehensive development roadmap.

This new roadmap is detailed in **`cline_docs/next_steps_and_improvements.md`**.

Our immediate focus is **Phase 0: Current System Tuning & Stabilization** from this new roadmap. This involves:
1.  Thoroughly testing all recently implemented features to ensure they are working as expected.
2.  Fine-tuning the `suggest_clips` AI logic for optimal performance, particularly with general user prompts and varied video content.
3.  Addressing any remaining bugs or stability issues identified during this initial testing and tuning phase.

## Recent changes
*   **Project Initiated & Initial MVP Development:** (Details of initial setup, Opus.pro analysis, original MVP planning, and early backend/frontend implementation are preserved from previous versions of this document but summarized here for brevity as "Core MVP Built").
    *   Core MVP Built: Video upload, audio extraction (FFmpeg), transcription (`faster-whisper`), initial AI clip suggestion (keywords, sentiment), video clipping, ASS subtitle generation (karaoke-style), subtitle burning, download functionality, basic UI for interaction.
*   **Major Refactor for Stability & Real-time Communication (Early May 2025):**
    *   Transitioned from SSE to WebSockets (`Flask-SocketIO` with `python-eventlet`).
    *   Modularized backend and frontend code.
    *   Implemented robust, stage-based progress updates.
    *   Significantly improved server stability and error handling.
*   **Key Milestones Achieved (Leading to New Roadmap - Mid-May 2025):**
    *   **Groq LLM Integration:** Implemented advanced AI clip suggestion using Groq API for LLMs (Llama 3, Gemma, Mixtral). This includes prioritized model rotation (`GROQ_MODELS_CONFIG`), exhaustive API key cycling, input token pre-checks (`tiktoken`), and transcript chunking for context-aware Llama analysis.
    *   **`faster-whisper` Optimization:** Refined compute type selection, ensuring optimal GPU utilization (e.g., `int8_float16`, `float16` via "Auto" mode). Resolved CUDA environment and PyTorch installation issues.
    *   **Enhanced Clip Suggestion Fallback:** Implemented a more robust fallback in `suggest_clips` (using wider internal duration filters if primary suggestions fail).
    *   **UI Controls:** Added UI options for Whisper Beam Size and Min/Max Short Duration.
    *   **Cancel Processing:** Implemented a fully functional "Cancel Processing" button with backend task termination.
    *   **External Project Analysis:** Completed detailed analysis of `Whisper-WebUI-master`, conceptual analysis of `Clipify-main` (from its README & diagram), and conceptual analysis of `subtitleedit-main` (from its structure & core classes).
    *   **New Comprehensive Roadmap Created:** Developed a new detailed, phased roadmap for ShortsMakerAI, documented in `cline_docs/next_steps_and_improvements.md`.
    *   **`cline_docs` Overhaul:** All `cline_docs` files (`productContext.md`, `techContext.md`, `systemPatterns.md`, `progress.md`, and `next_steps_and_improvements.md`) have been updated to align with this new roadmap and the current project state.

## Next steps (Immediate - Phase 0 of New Roadmap)

Our immediate next steps are focused on **Phase 0: Current System Tuning & Stabilization** as detailed in `cline_docs/next_steps_and_improvements.md`. This involves:

1.  **Thorough Testing of All Recent Features:**
    *   Systematically test the Groq LLM integration (model rotation, key cycling, token checks, chunking) with diverse inputs.
    *   Verify `faster-whisper` compute type selection ("Auto" mode and explicit choices) on GPU.
    *   Confirm the enhanced fallback logic for clip suggestions behaves as expected.
    *   Test all UI controls (Beam Size, Min/Max Duration, Cancel button).
2.  **Fine-Tuning the `suggest_clips` AI Logic (`ai_processing.py`):**
    *   **Crucial Diagnostic Test:** Conduct systematic tests using various videos with a general AI prompt (e.g., "Find interesting segments") and **very wide duration filters** (e.g., Min: 5s, Max: 300s). Analyze server logs to understand the scores and durations of all "potential clips" found before any duration filtering. This data is essential for tuning.
    *   **Iteratively Adjust `SUGGESTION_WEIGHTS`:** Based on test results, fine-tune the weights for keywords, sentiment, Llama relevance, ideal length bonus, and short/long penalties to improve the primary scoring logic.
    *   **Refine Llama System Prompt:** Experiment with the system prompt provided to Groq LLMs to enhance their ability to identify "generally interesting" content or to provide more structured, useful output for clip selection.
    *   **Experiment with `LLAMA_CHUNK_SIZE_SEGMENTS`:** Evaluate if adjusting the number of transcript segments per chunk (e.g., 1, 3, or 5) improves the quality of Llama's analysis and relevance scores.
3.  **Bug Fixing & Stability:**
    *   Identify and resolve any bugs, errors, or performance issues discovered during the Phase 0 testing and tuning process.
    *   Ensure error handling is robust and logging is clear and comprehensive.

Upon completion of Phase 0, the project will be well-positioned to begin implementing the new features outlined in Phase 1 of the roadmap (e.g., Speaker Diarization, BGM Removal).
