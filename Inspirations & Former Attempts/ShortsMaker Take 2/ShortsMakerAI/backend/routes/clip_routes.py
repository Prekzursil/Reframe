import os
import logging
import re
from pathlib import Path
import ffmpeg 
from flask import Blueprint, request, jsonify, current_app

try:
    from backend.video_processing import cut_video_segment, burn_ass_subtitles
    from backend.subtitle_utils import generate_ass_subtitles
except ImportError as e:
    logging.error(f"clip_routes.py: Failed to import dependencies: {e}", exc_info=True)
    cut_video_segment = None
    burn_ass_subtitles = None
    generate_ass_subtitles = None

logger = logging.getLogger(__name__)
clip_bp = Blueprint('clip_routes', __name__)

@clip_bp.route('/create_clip', methods=['POST'])
def create_clip_route_handler():
    if not all([cut_video_segment, burn_ass_subtitles, generate_ass_subtitles]):
        logger.error("/create_clip: Critical components not loaded.")
        return jsonify({"error": "Server configuration error, please try again later."}), 500

    logger.info(f"Received /create_clip request from {request.remote_addr}")
    data = request.json
    original_video_filepath_from_client = data.get('original_video_filepath')
    clip_name = data.get('clip_name', 'final_clip.mp4') 
    start_time_str = data.get('start_time')
    end_time_str = data.get('end_time')
    segments_for_subs = data.get('segments_for_subs') 

    if not all([original_video_filepath_from_client, clip_name, segments_for_subs is not None, start_time_str is not None, end_time_str is not None]):
        logger.warning(f"/create_clip missing required parameters. Data: {data}")
        return jsonify({"error": "Missing required parameters"}), 400
    
    try:
        start_time = float(start_time_str)
        end_time = float(end_time_str)
        if start_time < 0 or end_time <= start_time:
             logger.warning(f"/create_clip invalid time range: start={start_time}, end={end_time}")
             return jsonify({"error": "Invalid time range provided."}), 400
    except ValueError:
         logger.warning(f"/create_clip invalid time format: start={start_time_str}, end={end_time_str}")
         return jsonify({"error": "Invalid time format. Must be numbers."}), 400

    original_video_basename = os.path.basename(original_video_filepath_from_client)
    abs_original_video_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], original_video_basename)
    
    if not os.path.exists(abs_original_video_filepath):
        logger.error(f"Original video not found at expected path: {abs_original_video_filepath}")
        return jsonify({"error": f"Original video '{original_video_basename}' not found on server."}), 404

    base_original_filename = os.path.splitext(original_video_basename)[0]
    sanitized_project_name = re.sub(r'[^\w\-]+', '_', base_original_filename)
    sanitized_project_name = re.sub(r'_+', '_', sanitized_project_name).strip('_')
    if not sanitized_project_name:
        sanitized_project_name = "video_project_clips" 

    project_output_dir = Path(current_app.config['OUTPUT_FOLDER']) / sanitized_project_name
    shorts_output_dir = project_output_dir / "shorts"
    os.makedirs(shorts_output_dir, exist_ok=True)
    
    logger.info(f"Target output directory for clips: {shorts_output_dir}")

    base_clip_name_part, clip_ext_part = os.path.splitext(os.path.basename(clip_name))
    file_ext = clip_ext_part if clip_ext_part else '.mp4' 

    raw_clip_name_only = f"{base_clip_name_part}_raw{file_ext}"
    final_clip_name_only = f"{base_clip_name_part}_subtitled{file_ext}"
    subtitle_name_only = f"{base_clip_name_part}.ass"

    # These are Path objects now
    raw_clip_filepath = shorts_output_dir / raw_clip_name_only
    final_clip_filepath = shorts_output_dir / final_clip_name_only
    subtitle_filepath = shorts_output_dir / subtitle_name_only
    
    try:
        logger.info(f"Cutting segment for '{clip_name}' ({start_time}-{end_time}s) -> {str(raw_clip_filepath)}")
        cut_video_segment(str(abs_original_video_filepath), start_time, end_time, str(raw_clip_filepath))
        
        logger.info(f"Generating subtitles for '{clip_name}' -> {str(subtitle_filepath)}")
        ass_content = generate_ass_subtitles(segments_for_subs if segments_for_subs else [])
        
        with open(subtitle_filepath, "w", encoding="utf-8") as f_ass:
            f_ass.write(ass_content)
        
        # Pass string paths to burn_ass_subtitles
        logger.info(f"Burning subtitles onto '{raw_clip_name_only}' -> {str(final_clip_filepath)}")
        burn_ass_subtitles(str(raw_clip_filepath), str(subtitle_filepath), str(final_clip_filepath))
        
        logger.info(f"Clip '{clip_name}' created successfully.")
        return jsonify({
            "message": "Clip created successfully.",
            "subtitled_clip_filename": str(Path(sanitized_project_name) / "shorts" / final_clip_name_only),
            "raw_clip_filename": str(Path(sanitized_project_name) / "shorts" / raw_clip_name_only),
            "subtitle_filename": str(Path(sanitized_project_name) / "shorts" / subtitle_name_only)
        }), 200

    except ffmpeg.Error as fe:
        # Ensure stderr is bytes before decoding
        stderr_msg = fe.stderr.decode('utf8', errors='ignore') if fe.stderr else str(fe)
        logger.error(f"FFmpeg error during clip creation for '{clip_name}': {stderr_msg}", exc_info=True)
        error_message = f"Video processing error (FFmpeg): {stderr_msg}"
        return jsonify({"error": error_message}), 500
    except Exception as e:
        logger.error(f"Unexpected error during clip creation for '{clip_name}': {e}", exc_info=True)
        return jsonify({"error": f"An unexpected server error occurred: {str(e)}"}), 500
