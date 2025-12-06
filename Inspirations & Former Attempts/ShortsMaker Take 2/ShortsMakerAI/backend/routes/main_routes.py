import os
import logging
from flask import Blueprint, send_from_directory, jsonify, current_app

logger = logging.getLogger(__name__)
main_bp = Blueprint('main_routes', __name__)

@main_bp.route('/')
def serve_index():
    # current_app is the instance of the Flask application for the current request context
    # Flask will look for 'index.html' in the 'static_folder' 
    # defined in app_init.py (which points to the frontend directory)
    logger.info(f"Serving index.html from static folder: {current_app.static_folder}")
    return current_app.send_static_file('index.html')

@main_bp.route('/download/<path:filename>', methods=['GET'])
def download_file_route(filename):
    logger.info(f"Received /download request for '{filename}'")
    if '..' in filename or filename.startswith('/'):
         logger.warning(f"Attempt to access potentially unsafe path: {filename}")
         return jsonify({"error": "Invalid filename"}), 400
         
    try:
        # Use current_app.config for folder paths
        directory = os.path.abspath(current_app.config['OUTPUT_FOLDER'])
        file_path = os.path.join(directory, filename)
        
        # Security check: Ensure the requested file is within the designated OUTPUT_FOLDER
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            logger.error(f"File not found for download: {filename} in {directory}")
            return jsonify({"error": "File not found"}), 404

        if not os.path.commonpath([directory]) == os.path.commonpath([directory, file_path]):
             logger.warning(f"Attempt to access file outside designated directory: {filename}")
             return jsonify({"error": "Invalid file path"}), 400
             
        logger.info(f"Sending file: {file_path} from directory {directory}")
        return send_from_directory(directory, filename, as_attachment=True)
    except Exception as e:
        logger.error(f"Error during download of {filename}: {e}", exc_info=True)
        return jsonify({"error": "An unexpected server error occurred during download."}), 500
