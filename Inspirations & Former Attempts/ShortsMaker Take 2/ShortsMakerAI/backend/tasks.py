import os
import tempfile
import logging
import ffmpeg
import uuid 
import time 
import re # For sanitizing filename
from pathlib import Path # For path manipulation
from threading import Thread 

# Imports from our new modules
try:
    from backend.app_init import socketio, app, TASK_STATUSES
    logging.info("tasks.py: Successfully imported socketio, app, and TASK_STATUSES from backend.app_init")
    from backend.config import DEFAULT_MIN_SHORT_DURATION_S, DEFAULT_MAX_SHORT_DURATION_S # Import new duration defaults
except ImportError as e: 
    logging.error("tasks.py: Could not import app_init elements or config. SocketIO emits and app.config will fail.", exc_info=True)
    socketio = None 
    app = None 
    TASK_STATUSES = {} # Define TASK_STATUSES in case of import error
    DEFAULT_MIN_SHORT_DURATION_S = 30 # Fallback defaults
    DEFAULT_MAX_SHORT_DURATION_S = 90 # Fallback defaults

try:
    from backend.video_processing import extract_audio
    # Updated imports for modularized AI processing:
    from backend.whisper_interface import transcribe_audio, UserCancelledError, UnsupportedComputeTypeError
    from backend.clip_suggester import suggest_clips
    from backend.subtitle_utils import segments_to_srt_content # Import SRT utility
    logging.info("tasks.py: Successfully imported video_processing, whisper_interface, clip_suggester, custom errors, and subtitle_utils functions.")
except ImportError as e:
    logging.error("tasks.py: Could not import video_processing, whisper_interface, or clip_suggester functions.", exc_info=True)
    # Define dummy functions or re-raise
    def extract_audio(*args, **kwargs): logging.error("extract_audio is not available"); raise NotImplementedError
    def transcribe_audio(*args, **kwargs): logging.error("transcribe_audio is not available"); raise NotImplementedError
    def suggest_clips(*args, **kwargs): logging.error("suggest_clips is not available"); raise NotImplementedError

# subtitle_utils might be needed if subtitle generation happens in task, but it's in create_clip route for now
# import whisper # No longer needed here, ai_processing handles model loading with faster-whisper

logger = logging.getLogger(__name__)

# Helper function to emit progress updates
def emit_progress(socketio_instance, sid, task_id, pct, msg, step_name=""):
    """
    • Always updates ``TASK_STATUSES`` – even in an offline/unit-test
      environment where we don’t have a live ``socketio`` instance.
    • **Never** downgrades a terminal state (``error``, ``cancelled``,
      ``completed``) back to *processing*.  Everything else
      (including the initial ``queued``) is advanced to *processing*.
    """

    current = TASK_STATUSES.get(task_id, {})
    status_now = current.get("status", "processing")

    if status_now not in {"error", "cancelled", "completed"}:
        status_now = "processing"

    new_message = msg
    if status_now in {"error", "cancelled", "completed"} and "message" in current:
        new_message = current["message"] # Preserve existing terminal message

    TASK_STATUSES[task_id] = {
        **current, # Preserve existing fields not explicitly updated
        "status": status_now,
        "progress_percent": pct,
        "message": new_message, # Use potentially preserved message
        # Preserve step if status is terminal and the new step_name is a generic final signal,
        # otherwise update step if step_name is provided, or keep current if step_name is empty.
        "step": (current.get("step", "") 
                 if status_now in {"error", "cancelled", "completed"} and step_name == "task_ended_signal" 
                 else step_name or current.get("step", "")),
        "last_update": time.time(),
    }

    # Nothing more to do if we’re running without Socket.IO
    if not socketio_instance:
        logger.warning(
            "emit_progress: SocketIO not available for task %s. Message: %s",
            task_id,
            msg,
        )
        return

    # Payload for socketio event - use the new_message for consistency
    socket_payload = {
        "task_id": task_id,
        "progress_percent": pct,
        "message": new_message
    }
    if step_name: # Only include step in socket payload if it's explicitly provided for this update
        socket_payload["step"] = step_name
        
    socketio_instance.emit("progress_update", socket_payload, room=sid)
    socketio_instance.sleep(0) 


def process_video_task(app_context, client_sid, task_id, video_filepath, filename,
                       selected_model_name, beam_size, compute_type, 
                       user_keywords_str, ai_prompt, 
                       min_short_duration, max_short_duration,
                       # All Whisper parameters from routes.py
                       temperature, no_speech_threshold, min_silence_duration_ms, 
                       best_of, patience, length_penalty, repetition_penalty, no_repeat_ngram_size,
                       log_prob_threshold, compression_ratio_threshold, vad_threshold,
                       prompt_reset_on_temperature, max_initial_timestamp,
                       min_speech_duration_ms_vad, max_speech_duration_s_vad, speech_pad_ms_vad, 
                       whisper_initial_prompt, whisper_prefix, suppress_tokens,
                       prepend_punctuations, append_punctuations,
                       condition_on_previous_text, suppress_blank,
                       # New Language and Task parameters
                       language, task,
                       model_download_root):
    TASK_STATUSES[task_id] = {
        "status": "queued", 
        "progress_percent": 0, 
        "message": "Task queued for processing...", 
        "step": "queued",
        "filename": filename,
        "start_time": time.time()
    }
    logger.info(f"Task {task_id} initialized in TASK_STATUSES.")

    # Parameters from existing code:
    # app_context, client_sid, task_id, video_filepath, filename, selected_model_name, user_keywords_str, model_download_root
    # User's example signature:
    # process_video_task(task_id, client_sid, video_filepath, whisper_model)
    # We will use the more complete signature from existing code and adapt.
    # 'selected_model_name' corresponds to 'whisper_model'.

    actual_audio_filepath = None 
    project_output_dir_str = "" # For cleanup in finally block

    with app_context:
        if not socketio or not app:
            logger.error(f"Task {task_id}: SocketIO or Flask app not initialized. Aborting.")
            TASK_STATUSES[task_id].update({"status": "error", "message": "Server components not ready.", "last_update": time.time()})
            return
        
        # Sanitize filename to create a project-specific directory name
        base_filename = os.path.splitext(filename)[0]
        sanitized_project_name = re.sub(r'[^\w\-]+', '_', base_filename)
        sanitized_project_name = re.sub(r'_+', '_', sanitized_project_name).strip('_')
        if not sanitized_project_name:
            sanitized_project_name = f"video_project_{task_id[:8]}" # Fallback name

        project_output_dir = Path(app.config['OUTPUT_FOLDER']) / sanitized_project_name
        project_output_dir_str = str(project_output_dir) # Store as string for potential use in finally
        os.makedirs(project_output_dir, exist_ok=True)
        logger.info(f"Task {task_id}: Project output directory created/ensured: {project_output_dir}")
        
        # Update TASK_STATUSES with project folder info
        if task_id in TASK_STATUSES:
            TASK_STATUSES[task_id].update({"project_folder": sanitized_project_name})
        else: # Should have been initialized already
            TASK_STATUSES[task_id] = {"project_folder": sanitized_project_name, "status": "processing"}


        try:
            logger.info(f"Task {task_id} for client {client_sid}: Processing '{filename}' started. Output to: {project_output_dir}")
            emit_progress(socketio, client_sid, task_id, 0, "Processing started...", "start") 
            
            # Step 1: Extract Audio
            emit_progress(socketio, client_sid, task_id, 5, "Step 1/4 – extracting audio…", "audio_extract_start")
            
            # Define path for extracted audio within the project folder
            # extract_audio will determine the final extension (.aac or .mp3)
            audio_output_base_name = "extracted_audio" # Base name for the audio file
            initial_audio_output_path = project_output_dir / f"{audio_output_base_name}.mp3"

            actual_audio_filepath = extract_audio(
                video_filepath, 
                str(initial_audio_output_path), # Pass the full desired output path
                socketio=socketio,
                client_sid=client_sid,
                task_id=task_id
                # start_overall_pct and end_overall_pct will use defaults (5 and 25)
            )
            # If extract_audio emitted its own progress, the final emit for this stage (25%)
            # should ideally be done by extract_audio itself upon completion.
            # If extract_audio does NOT emit its own final "25% done" message, we might need one here.
            # For now, assuming extract_audio will handle emits from 5% up to just before 25%.
            # This next emit marks the end of audio extraction and the beginning of the transcription phase,
            # which now includes model initialization by faster-whisper.
            emit_progress(socketio, client_sid, task_id, 25, "Step 2/4 – Initializing transcription model...", "model_init_start")

            # Step 2 & 3: Initialize Model and Transcribe Audio (handled by ai_processing.transcribe_audio)
            # ai_processing.transcribe_audio will emit:
            # - "Initializing transcription model (Faster Whisper)..." (around 25%)
            # - Progress for model download/conversion by faster-whisper (if applicable, though not explicitly implemented yet for this part)
            # - "Model initialized. Starting transcription..." (around 35%)
            # - Granular "Transcribing: X% (ETA: MM:SS)" (from ~35% to ~74%)
            # Note: ai_processing.transcribe_audio now imports socketio itself.
            # Its signature is: transcribe_audio(audio_path, task_id, sid, model_size, ...)
            transcription_result = transcribe_audio(
                audio_path=actual_audio_filepath,
                task_id=task_id,
                sid=client_sid,
                model_size=selected_model_name,
                beam_size=beam_size, 
                user_compute_type=compute_type,
                temperature=temperature,
                no_speech_threshold=no_speech_threshold,
                min_silence_duration_ms=min_silence_duration_ms, # This is one of the VAD params
                # Pass all other new Whisper parameters
                best_of=best_of,
                patience=patience,
                length_penalty=length_penalty,
                repetition_penalty=repetition_penalty,
                no_repeat_ngram_size=no_repeat_ngram_size,
                log_prob_threshold=log_prob_threshold,
                compression_ratio_threshold=compression_ratio_threshold,
                vad_threshold=vad_threshold, # VAD specific
                prompt_reset_on_temperature=prompt_reset_on_temperature,
                max_initial_timestamp=max_initial_timestamp,
                min_speech_duration_ms_vad=min_speech_duration_ms_vad, # VAD specific
                max_speech_duration_s_vad=max_speech_duration_s_vad, # VAD specific
                speech_pad_ms_vad=speech_pad_ms_vad, # VAD specific
                initial_prompt=whisper_initial_prompt, 
                prefix=whisper_prefix, 
                suppress_tokens=suppress_tokens,
                prepend_punctuations=prepend_punctuations,
                append_punctuations=append_punctuations,
                condition_on_previous_text=condition_on_previous_text,
                suppress_blank=suppress_blank,
                # Pass Language and Task
                language=language,
                task=task
                # model_download_root is handled by ai_processing.py internally now
            )
            # After transcribe_audio returns, the transcription part is complete.
            
            # Save full transcription as SRT file
            if transcription_result and 'segments' in transcription_result:
                srt_filename = "full_transcription.srt"
                srt_filepath = project_output_dir / srt_filename
                try:
                    srt_content = segments_to_srt_content(transcription_result['segments'])
                    with open(srt_filepath, "w", encoding="utf-8") as f_srt:
                        f_srt.write(srt_content)
                    logger.info(f"Task {task_id}: Full transcription saved to {srt_filepath}")
                except Exception as e_srt:
                    logger.error(f"Task {task_id}: Failed to save full SRT transcription: {e_srt}", exc_info=True)
            
            # Extracted audio (actual_audio_filepath) is now saved in project_output_dir and should NOT be deleted here.
            logger.info(f"Task {task_id}: Extracted audio kept at {actual_audio_filepath}")
            # actual_audio_filepath = None # No longer nullifying as it's a permanent file

            emit_progress(socketio, client_sid, task_id, 75, "Step 4/4 – mining best clips…", "suggestion_start") 
            
            # Call suggest_clips with debug_return_all_potential=True for diagnostics
            suggested_clips_data = suggest_clips(
                segments=transcription_result['segments'], 
                user_keywords=user_keywords_str,
                ai_prompt=ai_prompt,
                min_duration_seconds=min_short_duration, # Use passed param
                max_duration_seconds=max_short_duration,  # Use passed param
                debug_return_all_potential=True # TEMPORARY FOR DIAGNOSTICS
            )

            final_suggestions, all_potential_clips_for_debug = [], []
            if isinstance(suggested_clips_data, tuple) and len(suggested_clips_data) == 2:
                final_suggestions, all_potential_clips_for_debug = suggested_clips_data
                # Log the detailed all_potential_clips data
                try:
                    # Using a simple logger for info level, consider a dedicated debug log file for large outputs
                    logger.info(f"TASK {task_id} DEBUG: All potential clips (before duration/overlap filter):")
                    for pot_clip_idx, pot_clip in enumerate(all_potential_clips_for_debug):
                        logger.info(f"  Potential Clip #{pot_clip_idx + 1}: Score={pot_clip.get('score',0):.2f}, Dur={pot_clip.get('duration',0):.1f}s, Reason='{pot_clip.get('reason','')}', Text='{pot_clip.get('text','')[:100]}...'")
                except Exception as log_e:
                    logger.error(f"TASK {task_id} DEBUG: Error logging all_potential_clips_for_debug: {log_e}")

            else: # Fallback if suggest_clips didn't return a tuple (e.g., if debug flag was missed)
                final_suggestions = suggested_clips_data if isinstance(suggested_clips_data, list) else []
                logger.warning(f"TASK {task_id}: suggest_clips did not return tuple in debug mode. Received: {type(suggested_clips_data)}")


            emit_progress(socketio, client_sid, task_id, 100, "✅ done", "suggestion_end") 
            
            final_payload = {
                "task_id": task_id,
                "message": f"Video '{filename}' processed successfully.",
                "video_filepath": video_filepath, # This is path to original uploaded video
                "project_folder": sanitized_project_name, # Pass project folder name to frontend
                "full_transcription_srt_path": str(project_output_dir / srt_filename) if 'srt_filename' in locals() else None,
                "extracted_audio_path": actual_audio_filepath, # Path to the saved audio
                "transcription_text": transcription_result['text'],
                "all_segments": transcription_result['segments'],
                "suggested_clips": final_suggestions # Use the filtered suggestions for the frontend
            }
            
            task_status_update = TASK_STATUSES.get(task_id, {})
            task_status_update.update({
                "status": "completed",
                "progress_percent": 100,
                "message": "Processing complete.",
                "step": "done",
                "result": { # Storing a summary, not the full potentially large transcription result
                    "video_filepath": video_filepath,
                    "project_folder": sanitized_project_name,
                    "num_suggested_clips": len(final_suggestions)
                },
                "last_update": time.time()
            })
            TASK_STATUSES[task_id] = task_status_update
            socketio.emit("final_result", final_payload, room=client_sid)
            logger.info(f"Task {task_id}: Successfully processed video '{filename}'. Status updated to completed.")

        except UserCancelledError as e_cancel:
            logger.info(f"Task {task_id} was cancelled by user: {e_cancel}")
            cancel_message = str(e_cancel)
            TASK_STATUSES[task_id].update({
                "status": "cancelled",
                "message": cancel_message,
                "step": "cancelled",
                "last_update": time.time()
            })
            socketio.emit("task_cancelled", {"task_id": task_id, "message": cancel_message}, room=client_sid)
        except UnsupportedComputeTypeError as e_uct:
            logger.error(f"Task {task_id} failed due to unsupported compute type: {e_uct}")
            error_message = str(e_uct) # This should be the user-friendly message from ai_processing.py
            TASK_STATUSES[task_id].update({
                "status": "error",
                "message": error_message,
                "step": "model_init_error", # Specific step for this error
                "error_detail": error_message, # More detailed if needed, but str(e_uct) is good
                "last_update": time.time()
            })
            socketio.emit("task_error", {"task_id": task_id, "error": error_message}, room=client_sid)
        except BaseException as err: # Changed from Exception to BaseException
            logger.exception(f"Task {task_id} crashed") 
            error_message = f"Server error: {str(err)}"
            # Update TASK_STATUSES for error
            TASK_STATUSES[task_id].update({ # Use update to preserve existing fields like filename, start_time
                "status": "error",
                "progress_percent": TASK_STATUSES.get(task_id, {}).get("progress_percent", 0), 
                "message": error_message,
                "step": TASK_STATUSES.get(task_id, {}).get("step", "error"), 
                "error_detail": error_message,
                "last_update": time.time()
            })
            socketio.emit("task_error",
                          {"task_id": task_id, "error": error_message},
                          room=client_sid)
        finally:
            logger.info(f"Task {task_id}: Entering finally block of process_video_task.")
            # Ensure task_ended_signal still updates status if not already error/completed
            current_status_entry = TASK_STATUSES.get(task_id, {})
            if current_status_entry.get("status") == "processing": # Check if it's still processing
                 current_status_entry.update({
                     "message": "Processing thread finished (outcome captured in error/complete status).", 
                     "last_update": time.time()
                 })
                 TASK_STATUSES[task_id] = current_status_entry # Ensure update is saved

            # Do NOT remove actual_audio_filepath as it's now a permanent saved asset
            # if actual_audio_filepath and os.path.exists(actual_audio_filepath):
            #     try:
            #         os.remove(actual_audio_filepath)
            #         logger.info(f"Task {task_id}: Cleaned up temp audio file {actual_audio_filepath} in finally block (if not already cleaned).")
            #     except OSError as ose:
            #         logger.error(f"Task {task_id}: Error removing temp audio file {actual_audio_filepath} in finally block: {ose}")
            
            # The initial_temp_audio_path_for_extract was a full path to the desired final audio file,
            # so no separate placeholder to clean.

            # Emit task_ended to signal frontend that this specific task's lifecycle is over
            # This is different from task_error or final_result which carry specific outcomes.
            emit_progress(socketio, client_sid, task_id, 100, "Processing thread finished.", "task_ended_signal") # Re-using emit_progress for consistency
            # Or use a dedicated event if frontend handles 'task_ended' differently:
            # socketio.emit('task_ended', {'task_id': task_id, 'message': 'Processing thread finished.'}, room=client_sid)
            # socketio.sleep(0)

            logger.info(f"Task {task_id} for client {client_sid}: Processing thread finished.")
