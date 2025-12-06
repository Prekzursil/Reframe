import ffmpeg
import logging
import os # For os.path.exists if needed, though not directly in these functions
import subprocess # For TimeoutExpired in extract_audio

# Configure a logger for this module (or rely on global config if set up in run.py)
logger = logging.getLogger(__name__)

# Attempt to import emit_progress from tasks. If it causes circular dependency,
# tasks.py might need to pass socketio, client_sid, task_id to this function.
# For now, let's assume tasks.py will pass these if emit_progress is not moved.
# Update: User's example implies socketio, sid, tid are passed.
# We will need emit_progress or replicate its logic.
# To avoid circular import, we'll expect socketio, client_sid, task_id to be passed
# and call socketio.emit directly.

def _emit_progress_video_processing(socketio_instance, sid, task_id, pct, msg, step_name=""):
    if not socketio_instance:
        # logger.warning(f"_emit_progress_video_processing: SocketIO not available for task {task_id}. Message: {msg}")
        return
    payload = {
        "task_id": task_id,
        "progress_percent": pct,
        "message": msg
    }
    if step_name:
        payload["step"] = step_name
        
    socketio_instance.emit("progress_update", payload, room=sid)
    socketio_instance.sleep(0)


def extract_audio(video_filepath, initial_output_audio_filepath, 
                  socketio=None, client_sid=None, task_id=None,
                  start_overall_pct=5, end_overall_pct=25):
    logger.info(f"extract_audio: Starting extraction for {video_filepath} to {initial_output_audio_filepath}")
    
    final_output_audio_filepath = initial_output_audio_filepath
    duration = None
    
    try:
        logger.debug(f"Probing video file: {video_filepath}")
        probe = ffmpeg.probe(video_filepath)
        audio_streams = [s for s in probe.get('streams', []) if s.get('codec_type') == 'audio']
        
        try:
            duration = float(probe["format"]["duration"])
        except Exception:
            logger.warning(f"Could not read duration from video probe for {video_filepath}")
            duration = None # Progress reporting will be less accurate or disabled

        can_copy_codec = False
        codec_name = None
        if audio_streams:
            codec_name = audio_streams[0].get('codec_name')
            logger.info(f"Detected audio codec: {codec_name}")
            if codec_name in ('aac', 'mp3'):
                can_copy_codec = True
        else:
            logger.warning(f"No audio streams found in {video_filepath}")

        ffmpeg_global_opts = ['-hide_banner', '-nostats']
        if socketio and client_sid and task_id and duration:
            ffmpeg_global_opts.append('-progress')
            ffmpeg_global_opts.append('pipe:1')
            run_async = True
            process_kwargs = {
                'pipe_stdout': True, 
                'pipe_stderr': True
            }
        else:
            run_async = False
            process_kwargs = {
                'capture_stdout': True,
                'capture_stderr': True
            }

        if can_copy_codec:
            base, ext = os.path.splitext(initial_output_audio_filepath)
            if codec_name == 'aac':
                final_output_audio_filepath = base + '.aac'
                logger.info(f"extract_audio: Audio codec 'aac' can be copied. Outputting to .aac: {final_output_audio_filepath}")
            elif codec_name == 'mp3':
                logger.info(f"extract_audio: Audio codec 'mp3' can be copied. Outputting to .mp3: {final_output_audio_filepath}")
            
            stream = ffmpeg.input(video_filepath).output(final_output_audio_filepath, acodec='copy', vn=None).overwrite_output()
            
        else:
            base, ext = os.path.splitext(initial_output_audio_filepath)
            if ext.lower() != '.mp3': # Ensure MP3 output if re-encoding
                final_output_audio_filepath = base + '.mp3'
            logger.info(f"extract_audio: Re-encoding to MP3: {final_output_audio_filepath}")
            stream = ffmpeg.input(video_filepath).output(final_output_audio_filepath, acodec='mp3', audio_bitrate='192k').overwrite_output()

        if run_async:
            logger.info(f"Running FFmpeg asynchronously for {final_output_audio_filepath} with progress.")
            process = stream.global_args(*ffmpeg_global_opts).run_async(**process_kwargs)
            
            progress_span = end_overall_pct - start_overall_pct
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                line_str = line.decode('utf-8', errors='ignore').strip()
                if "out_time_ms=" in line_str:
                    try:
                        ms_str = line_str.split("out_time_ms=")[1].strip()
                        us = int(ms_str) # FFmpeg's out_time_ms is in microseconds
                        ffmpeg_pct = (us / 1000000) / duration * 100 # Calculate percentage of FFmpeg task
                        ffmpeg_pct = max(0, min(ffmpeg_pct, 100)) # Clamp to 0-100%

                        current_overall_pct = start_overall_pct + int(ffmpeg_pct / 100 * progress_span)
                        current_overall_pct = min(current_overall_pct, end_overall_pct -1) # Cap just below end for final emit
                        _emit_progress_video_processing(socketio, client_sid, task_id, current_overall_pct, "Step 1/4 – extracting audio…", "audio_extract_progress")
                    except ValueError:
                        logger.debug(f"Could not parse progress line: {line_str}")
                    except Exception as e_prog:
                        logger.error(f"Error processing progress line: {line_str}, {e_prog}")
                elif line_str : # Log other stdout lines if any
                    logger.debug(f"FFMPEG STDOUT: {line_str}")

            process.wait()
            if process.returncode != 0:
                stderr_data = process.stderr.read().decode('utf8', errors='ignore')
                logger.error(f"FFmpeg async error for {final_output_audio_filepath}. Return code: {process.returncode}\nStderr: {stderr_data}")
                raise ffmpeg.Error('ffmpeg', process.stdout.read(), process.stderr.read()) # Reconstruct ffmpeg.Error
        else: # Synchronous path
            logger.info(f"Running FFmpeg synchronously for {final_output_audio_filepath}.")
            # process_kwargs is {'capture_stdout': True, 'capture_stderr': True}
            if can_copy_codec:
                logger.info("Using quiet=True for synchronous fast copy.")
                stream.run(quiet=True, **process_kwargs)
            else: # re-encoding
                logger.info("Using quiet=False for synchronous re-encode to capture output.")
                stream.run(quiet=False, **process_kwargs) # This maintains current behavior for re-encoding

        logger.info(f"extract_audio: Successfully processed audio to {final_output_audio_filepath}")
        return final_output_audio_filepath

    except ffmpeg.Error as e:
        stderr_output = e.stderr.decode('utf8', errors='ignore') if e.stderr else "No stderr"
        stdout_output = e.stdout.decode('utf8', errors='ignore') if e.stdout else "No stdout"
        # Set exc_info=False if stderr contains the full error, to avoid redundant traceback in logs.
        # However, keeping exc_info=True can be useful to see where in our Python code it was raised.
        stdout_output = e.stdout.decode('utf8', errors='ignore') if e.stdout else "No stdout" # Added for completeness
        logger.error(
            f"extract_audio: FFmpeg error.\n"
            f"Stdout: {stdout_output}\n" # Added stdout_output here
            f"Stderr: {stderr_output}", 
            exc_info=True 
        )
        raise 
    except Exception as e_gen:
        logger.error(f"extract_audio: Unexpected generic error during extraction for {video_filepath}.", exc_info=True)
        raise RuntimeError(f"Unexpected error in audio extraction: {str(e_gen)}") from e_gen
    # This return might be hit if an exception occurs after final_output_audio_filepath is set but before the try block completes.
    # The one inside the try block is the primary success path.
    return final_output_audio_filepath 

def cut_video_segment(video_filepath, start_time, end_time, output_clip_filepath):
    """
    Cuts a segment from the video using FFmpeg.
    start_time and end_time are in seconds.
    """
    logger.info(f"cut_video_segment: Cutting {video_filepath} from {start_time}s to {end_time}s -> {output_clip_filepath}")
    try:
        input_stream = ffmpeg.input(video_filepath, ss=start_time, to=end_time)
        (
            ffmpeg
            .output(input_stream, output_clip_filepath, vcodec='copy', acodec='copy', format='mp4')
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        logger.info(f"Successfully cut segment to {output_clip_filepath}")
    except ffmpeg.Error as e:
        logger.error(f"cut_video_segment: Codec copy failed for {output_clip_filepath}. Stdout: {e.stdout.decode('utf8', errors='ignore')}, Stderr: {e.stderr.decode('utf8', errors='ignore')}")
        logger.info("cut_video_segment: Attempting re-encode...")
        try:
            input_stream = ffmpeg.input(video_filepath, ss=start_time, to=end_time)
            (
                ffmpeg
                .output(input_stream, output_clip_filepath, format='mp4') # Default codecs for re-encoding
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            logger.info(f"Successfully cut segment (re-encoded) to {output_clip_filepath}")
        except ffmpeg.Error as e2:
            logger.error(f"cut_video_segment: Re-encode failed for {output_clip_filepath}. Stdout: {e2.stdout.decode('utf8', errors='ignore')}, Stderr: {e2.stderr.decode('utf8', errors='ignore')}")
            raise e2 # Raise the error from the re-encode attempt
        # If the first attempt (codec copy) raised an error, we should probably raise that original error
        # or a more generic one if re-encode also fails. Here, we raise e2 from re-encode.
        # Consider how to best report this chain of failures. For now, raising the last one.

def burn_ass_subtitles(video_input_path, ass_filepath, video_output_path):
    """
    Burns ASS subtitles from a file onto a video using FFmpeg.
    This will re-encode the video.
    ass_filepath is the path to the .ass subtitle file.
    """
    logger.info(f"burn_ass_subtitles: Burning subtitles from {ass_filepath} onto {video_input_path} -> {video_output_path}")
    try:
        # Ensure the ass_filepath is correctly escaped for ffmpeg command line filters
        # On Windows, paths with colons (C:\...) need special handling in FFmpeg filters.
        # A common method is to escape backslashes and colons.
        # Python's os.path.normpath and then manual escaping might be needed.
        # For now, using a simplified escaping that often works.
        # For robust cross-platform, consider using pathlib and then specific escaping.
        escaped_ass_filepath = ass_filepath.replace('\\', '\\\\').replace(':', '\\:')
        
        (
            ffmpeg
            .input(video_input_path)
            .output(video_output_path, vf=f"ass='{escaped_ass_filepath}'", acodec='copy', format='mp4')
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        logger.info(f"Successfully burned subtitles to {video_output_path}")

    except ffmpeg.Error as e:
        logger.error(f"burn_ass_subtitles: FFmpeg error. Stdout: {e.stdout.decode('utf8', errors='ignore')}, Stderr: {e.stderr.decode('utf8', errors='ignore')}")
        raise e
