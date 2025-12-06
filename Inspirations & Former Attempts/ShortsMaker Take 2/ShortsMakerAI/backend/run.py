import eventlet
eventlet.monkey_patch() # Must be called before other imports

import logging

# Import app and socketio from app_init - this also runs all initializations in app_init
# When run with `python -m backend.run` from project root, or via start_app.py,
# 'backend' should be a known package.
try:
    from backend.app_init import app, socketio
    logging.info("run.py: Successfully imported app and socketio from backend.app_init")
except ImportError as e:
    logging.basicConfig(level=logging.ERROR) 
    logging.error(f"run.py: Failed to import app and socketio from backend.app_init: {e}", exc_info=True)
    logging.error("Ensure the script is run in a context where 'backend' is a discoverable package (e.g., `python -m backend.run` from project root, or ensure project root is in PYTHONPATH).")
    app = None
    socketio = None

# Import routes to ensure they are registered with the app instance from app_init
if app:
    try:
        from backend import routes # This will execute routes.py, registering the routes
        logging.info("run.py: Successfully imported routes from backend.")
    except ImportError as e:
        logging.error(f"run.py: Failed to import routes from backend: {e}", exc_info=True)
    except Exception as e: # Catch other potential errors during routes import
        logging.error(f"run.py: An unexpected error occurred while importing routes: {e}", exc_info=True)


# Configure global logging here (this will apply to all modules if they use logging.getLogger)
# This basicConfig in run.py will be effective if run.py is the entry point.
# If start_app.py is the entry point, its basicConfig will take precedence.
# This provides a central place for logging setup.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


if __name__ == '__main__':
    if app and socketio:
        logger = logging.getLogger(__name__) # Get logger for this module
        logger.info("Starting ShortsMakerAI backend server with SocketIO...")
        # Use host='0.0.0.0' to make it accessible externally if needed, otherwise '127.0.0.1'
        socketio.run(app, host='127.0.0.1', port=5001, debug=True, use_reloader=True)
        # use_reloader=True is good for development.
        # For production, a proper WSGI server like Gunicorn with eventlet/gevent workers is recommended.
    else:
        logging.critical("Application or SocketIO not initialized. Cannot start server.")
