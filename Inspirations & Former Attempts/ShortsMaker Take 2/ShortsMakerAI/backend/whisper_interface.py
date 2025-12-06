import logging
import time
import json
import os
from pathlib import Path
import threading # Added for the new transcribe_audio

from faster_whisper import WhisperModel
import torch
import ffmpeg
import eventlet
from eventlet.queue import Queue as EventletQueue, Empty as EventletQueueEmpty
import eventlet.tpool

# Assuming MODEL_DOWNLOAD_ROOT is correctly configured and accessible
from backend.config import MODEL_DOWNLOAD_ROOT 
# For progress emitting and cancellation check
# These might cause circular dependencies if app_init imports this module.
# Consider passing socketio and TASK_STATUSES as arguments if that happens.
try:
    from backend.app_init import socketio, TASK_STATUSES, enqueue_progress_update
except ImportError:
    logging.warning("whisper_interface.py: Could not import socketio, TASK_STATUSES, or enqueue_progress_update. Progress/cancellation might not work.")
    socketio = None
    TASK_STATUSES = {}
    
    # Define a fallback enqueue function if the import fails
    def enqueue_progress_update(task_id, sid, pct, msg, step_name=""):
        logging.warning(f"Fallback enqueue_progress_update called for task {task_id}: {msg}")
        if TASK_STATUSES and task_id in TASK_STATUSES:
            TASK_STATUSES[task_id].update({
                "progress_percent": pct,
                "message": msg,
                "step": step_name or TASK_STATUSES[task_id].get("step", ""),
                "last_update": time.time(),
                "sid": sid  # Store the sid in status for potential heartbeat reuse
            })


logger = logging.getLogger(__name__)

# -------------------------------------------------------------------- #
# public error types (already used by tests in tasks & whisper_interface)
# -------------------------------------------------------------------- #


class UserCancelledError(RuntimeError):
    """Raised when a client explicitly aborts a running transcription."""


class UnsupportedComputeTypeError(RuntimeError):
    """Raised when *compute_type* is not supported on the current hardware."""


# -------------------------------------------------------------------- #
# constants / helpers
# -------------------------------------------------------------------- #

SUPPORTED_COMPUTE_TYPES = {
    "auto",
    "float16",
    "float32",
    "int8",
    "int8_float16",
    "int16",
}


def _validate_compute_type(compute_type: str) -> None:
    if compute_type not in SUPPORTED_COMPUTE_TYPES:
        raise UnsupportedComputeTypeError(
            f"Unsupported compute type '{compute_type}' for this hardware."
        )

# Global model instance variables
_faster_whisper_model_instance = None
_loaded_model_size = None
_loaded_compute_type = None

def _emit_progress(task_id, sid, pct, msg, step_name=""): 
    """
    Emit a progress update via socketio in a thread-safe manner.
    
    This function is designed to work safely when called from different thread contexts,
    including from the _perform_transcription_in_thread function running in eventlet.tpool.
    Using enqueue_progress_update ensures the actual socket emission happens in the main thread.
    """
    try:
        # First, always update the task status directly for reference
        if TASK_STATUSES and task_id in TASK_STATUSES:
            TASK_STATUSES[task_id].update({
                "progress_percent": pct,
                "message": msg,
                "step": step_name or TASK_STATUSES[task_id].get("step", ""),
                "last_update": time.time(),
                "sid": sid  # Store the sid in status
            })
        
        # Then use the thread-safe queue mechanism
        try:
            # Use the imported enqueue_progress_update function
            enqueue_progress_update(task_id, sid, pct, msg, step_name)
            logger.debug(f"WHISPER_INTERFACE: Queued progress update for task {task_id}, step '{step_name}', {pct}%")
        except Exception as e:
            logger.error(f"WHISPER_INTERFACE: Error queuing progress update: {e}")
            
            # If direct emit still fails (perhaps app_init isn't fully set up yet)
            if socketio:
                try:
                    # As a last resort, try direct emission (only works if in main thread)
                    payload = {"task_id": task_id, "progress_percent": pct, "message": msg}
                    if step_name:
                        payload["step"] = step_name
                    socketio.emit("progress_update", payload, room=sid)
                    logger.info(f"WHISPER_INTERFACE: Direct emit fallback for task {task_id} as backup")
                except Exception as e_direct:
                    logger.error(f"WHISPER_INTERFACE: Direct emit fallback also failed: {e_direct}")
            else:
                logger.warning(f"WHISPER_INTERFACE: SocketIO not available for task {task_id}. Message: {msg}")
                
    except Exception as e_outer:
        logger.error(f"WHISPER_INTERFACE: Critical error in _emit_progress: {e_outer}")

def get_audio_duration_ffmpeg(filepath):
    try:
        probe = ffmpeg.probe(filepath)
        return float(probe['format']['duration'])
    except Exception as e:
        logger.error(f"Error getting duration for {filepath} using ffmpeg: {e}", exc_info=True)
        return None

def format_eta(seconds):
    if not isinstance(seconds, (int, float)) or seconds < 0 or seconds > (3600*24*7): # Added type check
        return "??:??" 
    return time.strftime('%M:%S', time.gmtime(seconds))

def _perform_transcription_in_thread( 
    audio_path_thread, model_instance_thread, whisper_params_thread, 
    audio_len_seconds_thread, 
    transcription_phase_actual_start_time_thread,
    task_id, sid, # Changed: task_id_log_thread -> task_id, sid_log_thread -> sid
    transcribe_phase_start_pct_thread, transcribe_phase_end_pct_thread
    ):
    # This function now runs in a tpool thread and will emit SocketIO messages directly.
    # It will return the final result or raise an exception.
    try:
        logger.info(f"WHISPER_THREAD (Task {task_id}): Starting transcription for {audio_path_thread}")
        segments_iterable, info = model_instance_thread.transcribe(audio_path_thread, **whisper_params_thread)
        logger.info(f"WHISPER_THREAD (Task {task_id}): model.transcribe() call finished. Lang: {info.language}, Duration: {info.duration_after_vad:.2f}s")
        
        final_segments_thread = []
        full_text_list_thread = []

        for segment_idx, segment_obj in enumerate(segments_iterable):
            if TASK_STATUSES and TASK_STATUSES.get(task_id, {}).get('cancel_requested', False):
                logger.info(f"WHISPER_THREAD (Task {task_id}): Cancellation requested. Stopping transcription.")
                # No queue to put "cancelled" on; raise an exception to be caught by transcribe_audio
                raise UserCancelledError("Transcription cancelled by user during segment processing.")

            full_text_list_thread.append(segment_obj.text)
            words_list_thread = []
            if segment_obj.words:
                for w in segment_obj.words:
                    words_list_thread.append({
                        "word": w.word, 
                        "start": round(w.start,3), 
                        "end": round(w.end,3), 
                        "probability": round(w.probability,3)
                    })
            
            current_segment_data_thread = {
                "id": f"segment_{len(final_segments_thread)}", 
                "seek": round(segment_obj.seek,3) if hasattr(segment_obj,'seek') else 0, 
                "start": round(segment_obj.start,3), 
                "end": round(segment_obj.end,3), 
                "text": segment_obj.text.strip(), 
                "tokens": segment_obj.tokens, 
                "temperature": round(segment_obj.temperature,3), 
                "avg_logprob": round(segment_obj.avg_logprob,3), 
                "compression_ratio": round(segment_obj.compression_ratio,3), 
                "no_speech_prob": round(segment_obj.no_speech_prob,3), 
                "words": words_list_thread
            }
            final_segments_thread.append(current_segment_data_thread)

            if audio_len_seconds_thread and audio_len_seconds_thread > 0:
                current_progress_seconds = segment_obj.end
                ratio = min(current_progress_seconds / audio_len_seconds_thread, 1.0)
                span = transcribe_phase_end_pct_thread - transcribe_phase_start_pct_thread
                span = span if span > 0 else 1 
                pct = transcribe_phase_start_pct_thread + int(ratio * span)
                pct = min(pct, transcribe_phase_end_pct_thread)
                
                eta_s, eta_str = 0, "unknown"
                elapsed = time.time() - transcription_phase_actual_start_time_thread
                if current_progress_seconds > 0.1 and elapsed > 0.1: 
                    rate = current_progress_seconds / elapsed
                    if rate > 1e-6: 
                        eta_s = (audio_len_seconds_thread - current_progress_seconds) / rate
                
                eta_str = format_eta(eta_s)
                msg = f"Step 3/4 – Transcribing: {int(ratio*100)}% (ETA: {eta_str})"
                
                # Enhanced logging and progress emission
                logger.info(f"WHISPER_THREAD (Task {task_id}): Transcription progress: RawRatio={ratio:.2f}, Pct={pct}%, Msg='{msg}'")
                
                # Force step name to ensure consistency
                const_step_name = "transcribing_progress_fw"
                
                try:
                    # Emit progress with consistent step name
                    _emit_progress(task_id, sid, pct, msg, const_step_name)
                    logger.info(f"WHISPER_THREAD (Task {task_id}): Successfully emitted progress with step='{const_step_name}'")
                except Exception as emit_err:
                    logger.error(f"WHISPER_THREAD (Task {task_id}): Error emitting progress: {emit_err}")
                
                # Every 5th segment, try to emit a special heartbeat progress to ensure frontend stays synchronized
                if segment_idx % 5 == 0:
                    try:
                        # Add small delay to avoid collision with previous emit
                        time.sleep(0.05)
                        _emit_progress(task_id, sid, pct, f"{msg} (sync: {segment_idx})", const_step_name)
                        logger.info(f"WHISPER_THREAD (Task {task_id}): Extra sync emission at segment {segment_idx}")
                    except Exception as sync_err:
                        logger.error(f"WHISPER_THREAD (Task {task_id}): Error in sync emission: {sync_err}")

        result = {
            "text": " ".join(full_text_list_thread).strip(), 
            "segments": final_segments_thread, 
            "language": info.language if 'info' in locals() and hasattr(info,'language') else "unknown"
        }
        logger.info(f"WHISPER_THREAD (Task {task_id}): Transcription successful. Returning result.")
        return result # Return the result

    except UserCancelledError: # Re-raise to be caught by transcribe_audio
        logger.info(f"WHISPER_THREAD (Task {task_id}): UserCancelledError caught and re-raised.")
        raise
    except Exception as e:
        logger.error(f"WHISPER_THREAD (Task {task_id}): Error: {e}", exc_info=True)
        # Raise a runtime error to be caught by transcribe_audio
        raise RuntimeError(f"Error in transcription thread: {str(e)}") from e
    # No finally block needed to put "done" on queue


def transcribe_audio(audio_path, task_id, sid, model_size="large-v3", beam_size=5, user_compute_type="auto", 
                       temperature=0.0, no_speech_threshold=0.6, min_silence_duration_ms=1000, 
                       best_of=5, patience=1.0, length_penalty=1.0, repetition_penalty=1.0, no_repeat_ngram_size=0,
                       log_prob_threshold=-1.0, compression_ratio_threshold=2.4, vad_threshold=0.382, 
                       prompt_reset_on_temperature=0.5, max_initial_timestamp=1.0,
                       min_speech_duration_ms_vad=250, max_speech_duration_s_vad=float('inf'), speech_pad_ms_vad=200, 
                       initial_prompt=None, prefix=None, suppress_tokens=[-1],
                       prepend_punctuations="\"'\“¿([{-", append_punctuations="\"'.。,，!！?？:：”)]}、",
                       condition_on_previous_text=True, suppress_blank=True,
                       language=None, task="transcribe",
                       model_init_start_pct=25, model_init_done_pct=35, 
                       transcribe_phase_start_pct=35, transcribe_phase_end_pct=74):
    global _faster_whisper_model_instance, _loaded_model_size, _loaded_compute_type
    
    log_params = {k: v for k, v in locals().items() if k not in ['audio_path', 'sid', 'whisper_params_thread', 'progress_queue_thread']}
    logger.info(f"WHISPER_INTERFACE: Transcribe called with params: {json.dumps(log_params, default=lambda o: '<not serializable>')}")
    
    _emit_progress(task_id, sid, model_init_start_pct, f"Step 2/4 – Initializing transcription model ({model_size})...", "model_init_fw_start")
    if socketio: socketio.sleep(0.1) # Allow emit to process
    else: time.sleep(0.1) # Fallback if socketio is None, though not ideal
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type_to_pass_to_model = "auto" 

    if user_compute_type.lower() not in ["auto", "default"]:
        compute_type_to_pass_to_model = user_compute_type.lower() 
    
    requested_or_auto_compute_type = compute_type_to_pass_to_model

    if (_faster_whisper_model_instance is None or 
        _loaded_model_size != model_size or
        (_loaded_compute_type != requested_or_auto_compute_type and requested_or_auto_compute_type != "auto") ):
        
        logger.info(f"WHISPER_INTERFACE: Reloading model. Current: {_loaded_model_size} ({_loaded_compute_type}), Requested: {model_size} (Compute: {requested_or_auto_compute_type})")
        try: 
            _faster_whisper_model_instance = WhisperModel(
                model_size, 
                device=device, 
                compute_type=compute_type_to_pass_to_model, 
                download_root=str(Path(MODEL_DOWNLOAD_ROOT).resolve())
            )
            _loaded_model_size = model_size
            _loaded_compute_type = _faster_whisper_model_instance.model.compute_type 
            logger.info(f"Model '{model_size}' loaded successfully. Effective compute type: '{_loaded_compute_type}'")
        except ValueError as e_val:
            if "Requested float16 compute type" in str(e_val) or "support efficient" in str(e_val) or "incompatible constructor arguments" in str(e_val):
                 logger.error(f"Failed to load model '{model_size}' with compute type '{user_compute_type}': {e_val}", exc_info=True)
                 raise UnsupportedComputeTypeError(f"Compute type '{user_compute_type}' is not efficiently supported on this hardware for model '{model_size}'. Please try 'auto' or other options like 'int8'.") from e_val
            else: 
                 logger.error(f"ValueError loading model '{model_size}' (Compute: {user_compute_type}): {e_val}", exc_info=True)
                 raise RuntimeError(f"Failed to initialize model due to ValueError: {e_val}") from e_val
        except Exception as e_load: 
            logger.error(f"Failed to load model '{model_size}' (Compute: {user_compute_type}): {e_load}", exc_info=True)
            raise RuntimeError(f"Failed to initialize model: {e_load}") from e_load
    else: 
        logger.info(f"WHISPER_INTERFACE: Using pre-loaded model: {_loaded_model_size} ({_loaded_compute_type})")

    _emit_progress(task_id, sid, model_init_done_pct -1, f"Model '{_loaded_model_size}' (Compute: '{_loaded_compute_type}') initialized.", "model_init_fw_done")
    if socketio: socketio.sleep(0.1)
    else: time.sleep(0.1)
    
    audio_len_seconds = get_audio_duration_ffmpeg(audio_path)
    _emit_progress(task_id, sid, transcribe_phase_start_pct, "Step 3/4 - Analyzing audio structure (VAD, Lang Detect)...", "vad_lang_detect_fw")
    if socketio: socketio.sleep(0.1)
    else: time.sleep(0.1)
    transcription_phase_actual_start_time = time.time()

    whisper_params = {
        "beam_size": beam_size, "best_of": best_of, "patience": patience,
        "length_penalty": length_penalty, "repetition_penalty": repetition_penalty,
        "no_repeat_ngram_size": no_repeat_ngram_size,
        "temperature": temperature if isinstance(temperature, (list, tuple)) else [temperature],
        "compression_ratio_threshold": compression_ratio_threshold,
        "log_prob_threshold": log_prob_threshold,
        "no_speech_threshold": no_speech_threshold,
        "condition_on_previous_text": condition_on_previous_text,
        "prompt_reset_on_temperature": prompt_reset_on_temperature,
        "initial_prompt": initial_prompt, "prefix": prefix,
        "suppress_blank": suppress_blank, "suppress_tokens": suppress_tokens,
        "without_timestamps": False, "max_initial_timestamp": max_initial_timestamp,
        "word_timestamps": True, "prepend_punctuations": prepend_punctuations,
        "append_punctuations": append_punctuations, "vad_filter": True,
        "vad_parameters": {
            "threshold": vad_threshold,
            "min_speech_duration_ms": min_speech_duration_ms_vad,
            "max_speech_duration_s": max_speech_duration_s_vad,
            "min_silence_duration_ms": min_silence_duration_ms,
            "speech_pad_ms": speech_pad_ms_vad
        },
        "language": language if language and language.lower() != "auto" else None,
        "task": task
    }
    
    if whisper_params.get("initial_prompt") is None: del whisper_params["initial_prompt"]
    if whisper_params.get("prefix") is None: del whisper_params["prefix"]
    if whisper_params.get("language") is None: del whisper_params["language"]
        
    logger.info(f"WHISPER_INTERFACE (Task {task_id}): Whisper params for transcribe(): {json.dumps(whisper_params, indent=2, default=lambda o: '<not serializable>')}")
    
    # No longer uses progress_q. Worker thread emits directly and returns result/raises error.
    
    logger.info(f"WHISPER_INTERFACE (Task {task_id}): PREPARING to launch worker thread via tpool.execute.")

    try:
        # eventlet.tpool.execute will block this greenlet until the worker thread is done,
        # and will return the worker's result or propagate its exceptions.
        transcription_result = eventlet.tpool.execute(
            _perform_transcription_in_thread, 
            audio_path, _faster_whisper_model_instance, whisper_params, 
            audio_len_seconds, transcription_phase_actual_start_time, 
            task_id, sid, 
            transcribe_phase_start_pct, transcribe_phase_end_pct
        )
        # If we reach here, the worker thread completed successfully and returned its result.
        logger.info(f"WHISPER_INTERFACE (Task {task_id}): Worker thread finished. Result received directly from tpool.execute.")

    except UserCancelledError: 
        logger.info(f"WHISPER_INTERFACE (Task {task_id}): Transcription cancelled by user (propagated from worker).")
        raise 
    except RuntimeError as e_worker: 
        # This will catch RuntimeErrors raised by _perform_transcription_in_thread
        # or errors from proxy.wait() if it were still used and failed.
        logger.error(f"WHISPER_INTERFACE (Task {task_id}): Error from worker thread execution: {e_worker}", exc_info=True)
        raise RuntimeError(f"Transcription failed in worker thread: {str(e_worker)}") from e_worker
    except Exception as e_tpool_related: 
        logger.error(f"WHISPER_INTERFACE (Task {task_id}): CRITICAL ERROR during tpool.execute: {e_tpool_related}", exc_info=True)
        raise RuntimeError(f"Failed during transcription thread execution via tpool: {str(e_tpool_related)}") from e_tpool_related
    
    # Check if transcription_result is valid (should be a dict with 'text' and 'segments')
    if not transcription_result or not isinstance(transcription_result, dict) or "text" not in transcription_result or "segments" not in transcription_result:
        logger.error(f"WHISPER_INTERFACE (Task {task_id}): Worker finished but returned an invalid/empty result: {transcription_result}")
        raise RuntimeError("Transcription worker finished but provided an invalid or empty result.")
        
    logger.info(f"WHISPER_INTERFACE (Task {task_id}): Transcription process completed successfully. Returning result.")
    return transcription_result
