import os
import nltk
import time
import queue
import threading
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO
import logging
import eventlet

# Import configurations from config.py
try:
    from backend.config import UPLOAD_FOLDER, OUTPUT_FOLDER, MODEL_DOWNLOAD_ROOT, VALID_WHISPER_MODELS
    logging.info("app_init.py: Successfully imported configurations from backend.config")
except ImportError as e:
    logging.error("app_init.py: Could not import configurations from backend.config.", exc_info=True)
    # Define fallbacks or re-raise, as these are critical
    UPLOAD_FOLDER, OUTPUT_FOLDER, MODEL_DOWNLOAD_ROOT, VALID_WHISPER_MODELS = None, None, None, []


# Initialize Flask app and extensions
# Path to the frontend directory, assuming 'backend' and 'frontend' are siblings
FRONTEND_FOLDER_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))

app = Flask(__name__, static_folder=FRONTEND_FOLDER_PATH, static_url_path='')
CORS(app)
# Ensure async_mode is compatible with your deployment server (eventlet is good for development)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Apply configurations to the Flask app
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MODEL_DOWNLOAD_ROOT'] = MODEL_DOWNLOAD_ROOT
app.config['VALID_WHISPER_MODELS'] = VALID_WHISPER_MODELS # Store this in app.config too if needed by routes/tasks

# Ensure essential directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(MODEL_DOWNLOAD_ROOT, exist_ok=True)

# Setup basic logging (if not already configured globally elsewhere, e.g. in run.py)
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# This was in app.py, let's keep it here for now, or move to run.py if preferred.
# For modularity, it's often better to configure logging once at the application entry point (run.py).
# However, if modules need to log before run.py configures it, having a basicConfig here is a fallback.
# Let's assume run.py will handle comprehensive logging setup.
# For now, individual modules can use logging.getLogger(__name__)

def download_nltk_data():
    """Downloads NLTK data if not already present."""
    try:
        nltk.data.find('tokenizers/punkt')
    except LookupError:
        logging.info("NLTK 'punkt' tokenizer not found. Downloading...")
        nltk.download('punkt', quiet=True)
        logging.info("'punkt' tokenizer downloaded.")
    try:
        nltk.data.find('sentiment/vader_lexicon.zip/vader_lexicon/vader_lexicon.txt')
    except LookupError:
        logging.info("NLTK 'vader_lexicon' not found. Downloading...")
        nltk.download('vader_lexicon', quiet=True)
        logging.info("'vader_lexicon' downloaded.")

download_nltk_data()

analyzer = None
try:
    analyzer = SentimentIntensityAnalyzer()
    logging.info("SentimentIntensityAnalyzer initialized successfully.")
except Exception as e:
    logging.error(f"Error initializing SentimentIntensityAnalyzer: {e}", exc_info=True)

# This module provides `app` and `socketio` for other modules to import.

# Global dictionary to store task statuses (for the /status endpoint)
# This is a simple in-memory store. For production, a more robust solution (e.g., Redis, DB) would be better.
TASK_STATUSES = {}

# Thread-safe queue for progress updates from worker threads
# This allows worker threads to safely queue up progress updates without causing the greenlet error
progress_update_queue = queue.Queue()

# Queue processing flag
_queue_processor_running = False
_last_heartbeat_time = time.time()

def enqueue_progress_update(task_id, sid, pct, msg, step_name=""):
    """
    Thread-safe function to queue a progress update that will be emitted 
    from the main thread via the background task.
    """
    try:
        progress_update_queue.put({
            "task_id": task_id,
            "sid": sid,
            "pct": pct,
            "msg": msg,
            "step_name": step_name,
            "timestamp": time.time()
        })
        logging.debug(f"Queued progress update for task {task_id}, step '{step_name}'")
    except Exception as e:
        logging.error(f"Error enqueueing progress update: {e}")

def process_progress_queue():
    """
    Process queued progress updates in the main eventlet thread.
    This avoids the "Cannot switch to a different thread" error.
    """
    global _last_heartbeat_time
    
    # Process all currently queued updates
    processed = 0
    try:
        current_time = time.time()
        
        # Process all updates currently in the queue
        while not progress_update_queue.empty() and processed < 50:  # Process up to 50 items per cycle to avoid blocking
            try:
                update = progress_update_queue.get_nowait()
                task_id = update.get("task_id")
                sid = update.get("sid")
                pct = update.get("pct")
                msg = update.get("msg")
                step_name = update.get("step_name", "")
                
                # Update the task status first (always reliable)
                current = TASK_STATUSES.get(task_id, {})
                if current.get("status") not in {"error", "cancelled", "completed"}:
                    current["status"] = "processing"
                
                TASK_STATUSES[task_id] = {
                    **current,
                    "progress_percent": pct,
                    "message": msg,
                    "step": step_name or current.get("step", ""),
                    "last_update": time.time(),
                }
                
                # Now emit via socketio (this is in the main thread, so it's safe)
                socket_payload = {
                    "task_id": task_id,
                    "progress_percent": pct,
                    "message": msg
                }
                if step_name:
                    socket_payload["step"] = step_name
                    
                logging.debug(f"Emitting queued progress update: task={task_id}, step='{step_name}', pct={pct}")
                socketio.emit("progress_update", socket_payload, room=sid)
                
                # Mark task as processed
                progress_update_queue.task_done()
                processed += 1
                
            except queue.Empty:
                break  # Queue is empty now
            except Exception as e:
                logging.error(f"Error processing progress update: {e}")
                try:
                    progress_update_queue.task_done()  # Still mark as done even if error
                except:
                    pass
        
        # Emit heartbeat updates for tasks with active transcription
        if current_time - _last_heartbeat_time >= 2.0:  # Every 2 seconds
            for task_id, status in TASK_STATUSES.items():
                if status.get("status") == "processing" and status.get("step") in ["transcribing_progress_fw", "vad_lang_detect_fw"]:
                    # Resend the last known state as a heartbeat
                    socket_payload = {
                        "task_id": task_id,
                        "progress_percent": status.get("progress_percent", 0),
                        "message": status.get("message", "Processing..."),
                        "step": status.get("step", ""),
                        "is_heartbeat": True  # Flag to indicate this is a heartbeat (frontend can use this)
                    }
                    sid = status.get("sid")
                    if sid:
                        try:
                            socketio.emit("progress_update", socket_payload, room=sid)
                            logging.debug(f"Emitted heartbeat for task {task_id}, step '{status.get('step', '')}'")
                        except Exception as e:
                            logging.error(f"Error emitting heartbeat: {e}")
            
            _last_heartbeat_time = current_time
    
    except Exception as e:
        logging.error(f"Error in process_progress_queue: {e}")
    
    # Schedule the next execution
    if _queue_processor_running:
        socketio.sleep(0.1)  # Small delay to avoid CPU spinning
        eventlet.spawn_after(0.1, process_progress_queue)

def start_queue_processor():
    """Start the background task to process progress updates"""
    global _queue_processor_running
    if not _queue_processor_running:
        _queue_processor_running = True
        eventlet.spawn(process_progress_queue)
        logging.info("Progress update queue processor started")

# Start the queue processor when the module is imported
start_queue_processor()

# Import and register blueprints
try:
    from .routes.main_routes import main_bp
    from .routes.upload_routes import upload_bp
    from .routes.clip_routes import clip_bp
    from .routes.status_routes import status_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(upload_bp) # Mounted at /upload
    app.register_blueprint(clip_bp)   # Mounted at /create_clip
    app.register_blueprint(status_bp, url_prefix='/api') # Mounted at /api/status
    logging.info("app_init.py: Blueprints registered successfully.")
except ImportError as e:
    logging.error(f"app_init.py: Failed to import or register blueprints: {e}", exc_info=True)


# Socket.IO event handlers
@socketio.on('connect')
def handle_connect():
    # request.sid is available here if needed, ensure 'request' is imported from flask
    from flask import request as flask_request # Import locally to ensure it's available
    logging.info(f"Client connected: {flask_request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    from flask import request as flask_request
    logging.info(f"Client disconnected: {flask_request.sid}")

@socketio.on('cancel_task_request')
def handle_cancel_task_request(data):
    from flask import request as flask_request
    task_id = data.get('task_id')
    client_sid = flask_request.sid 
    if task_id and task_id in TASK_STATUSES:
        logging.info(f"Received cancel_task_request for task_id: {task_id} from client {client_sid}")
        current_task_status = TASK_STATUSES[task_id].get("status")
        if current_task_status == "processing" or current_task_status == "queued":
            TASK_STATUSES[task_id]['cancel_requested'] = True
            # Update status message to reflect cancellation attempt
            if 'message' in TASK_STATUSES[task_id]:
                 TASK_STATUSES[task_id]['message'] = f"Cancellation requested for: {TASK_STATUSES[task_id]['message']}"
            else:
                 TASK_STATUSES[task_id]['message'] = "Cancellation requested by user."
            
            logging.info(f"Task {task_id} marked for cancellation. Current status was: {current_task_status}")
            socketio.emit('task_cancel_ack', {'task_id': task_id, 'message': 'Cancellation request received and being processed.'}, room=client_sid)
        else:
            logging.warning(f"Task {task_id} is not in a cancellable state (e.g. 'processing' or 'queued'). Current state: {current_task_status}")
            socketio.emit('task_cancel_ack', {'task_id': task_id, 'error': f'Task not cancellable. Current state: {current_task_status}.'}, room=client_sid)
    else:
        logging.warning(f"Received cancel_task_request for unknown or invalid task_id: {task_id} from client {client_sid}")
        socketio.emit('task_cancel_ack', {'task_id': task_id, 'error': 'Invalid or unknown task ID for cancellation.'}, room=client_sid)
