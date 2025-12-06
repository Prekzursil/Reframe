import eventlet
eventlet.monkey_patch() # Must be called before other imports like socket, and ideally before Flask/SocketIO

import sys
import os
import webbrowser
import logging
import threading # For opening browser in a separate thread/timer

# --- Path Setup ---
# Add the project root directory (ShortsMakerAI) to sys.path
# This script (start_app.py) is in the project root.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# --- Logging Setup ---
# Configure logging early so imports from backend can use it if they log at module level.
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("start_app")

# --- Import Backend Components ---
# These imports should now work because PROJECT_ROOT (which contains 'backend' package) is in sys.path
try:
    from backend.app_init import app, socketio
    from backend import routes  # This import executes routes.py, registering the routes
    logger.info("Successfully imported backend application components (app, socketio, routes).")
except ImportError as e:
    logger.error(f"CRITICAL: Error importing backend components: {e}", exc_info=True)
    logger.error("Please ensure all dependencies in backend/requirements.txt are installed,")
    logger.error("and the backend package structure and __init__.py are correct.")
    app = None
    socketio = None
except Exception as e:
    logger.error(f"CRITICAL: An unexpected error occurred during backend component import: {e}", exc_info=True)
    app = None
    socketio = None

# --- Frontend Opener Function ---
def open_frontend():
    """Opens the frontend index.html in a new browser tab."""
    try:
        frontend_path = os.path.join(PROJECT_ROOT, 'frontend', 'index.html')
        # Convert to a file URI, ensuring correct path separators for file URIs
        frontend_url = f"file:///{os.path.abspath(frontend_path).replace(os.sep, '/')}"
        logger.info(f"Attempting to open frontend at: {frontend_url}")
        webbrowser.open_new_tab(frontend_url)
    except Exception as e:
        logger.error(f"Could not open frontend in browser: {e}", exc_info=True)

# --- Main Execution ---
if __name__ == '__main__':
    if app and socketio:
        logger.info("Starting ShortsMakerAI backend server with SocketIO...")
        
        # Optionally open the frontend.
        # Running in a timer to give the server a moment to start,
        # and to prevent webbrowser.open blocking if it ever did.
        # threading.Timer(1.5, open_frontend).start() # Uncomment to auto-open frontend

        try:
            # For production, use a proper WSGI server like Gunicorn with eventlet or gevent workers.
            # Example: gunicorn --worker-class eventlet -w 1 module:app
            # The host '0.0.0.0' makes the server accessible on your local network.
            # For development, '127.0.0.1' is fine.
            socketio.run(app, host='127.0.0.1', port=5001, debug=True, use_reloader=False) # Changed use_reloader to False
        except Exception as e:
            logger.critical(f"Failed to start the SocketIO server: {e}", exc_info=True)
    else:
        logger.critical("Application or SocketIO not initialized correctly. Cannot start server.")
        logger.info("Please check for import errors above.")
