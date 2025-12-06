import os
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env file

# Define root directory for the application if needed for path constructions
# For example, if backend is a subdirectory of the project root:
# PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Or, if these paths are relative to where the backend is run from (e.g., from within backend/):
# For simplicity, let's assume these paths are relative to the project root (ShortsMakerAI/)
# and the backend script (e.g., run.py) will be in backend/.

# If UPLOAD_FOLDER, OUTPUT_FOLDER, MODEL_DOWNLOAD_ROOT are intended to be outside the `backend` dir,
# at the same level as `frontend` and `backend` (i.e., in `ShortsMakerAI/uploads`, etc.)
# then the os.path.join(os.getcwd(), '..', 'uploads') logic from app.py was assuming app.py
# is run from within backend/. We should make these paths more robust.

# Let's define them relative to this config.py file, assuming config.py is in backend/
# and the folders (uploads, outputs, models) are one level up, in the project root.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # This should be ShortsMakerAI project root

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'outputs')
MODEL_DOWNLOAD_ROOT = os.path.join(BASE_DIR, 'models')

VALID_WHISPER_MODELS = [
    "tiny", "tiny.en",
    "base", "base.en",
    "small", "small.en",
    "medium", "medium.en",
    "large-v1", "large-v2", "large-v3"
]

# Default durations for suggested shorts (in seconds)
DEFAULT_MIN_SHORT_DURATION_S = 30
DEFAULT_MAX_SHORT_DURATION_S = 90

# Groq API Keys for Llama integration
# Expects a comma-separated string of API keys in the environment variable GROQ_API_KEYS
GROQ_API_KEYS_STR = os.environ.get('GROQ_API_KEYS', '')
GROQ_API_KEYS = [key.strip() for key in GROQ_API_KEYS_STR.split(',') if key.strip()]

if not GROQ_API_KEYS:
    # This import is fine here as it's for a startup warning, not core functionality.
    import logging 
    logging.getLogger(__name__).warning(
        "GROQ_API_KEYS environment variable not set or empty. "
        "Llama-based AI Prompt feature will be disabled."
    )

# Configuration for Groq LLM models to be used by the application
# Priority: Lower number means higher priority.
# Context window sizes should be verified from Groq documentation.
GROQ_MODELS_CONFIG = [
    {
        "model_id": "gemma2-9b-it", 
        "context_window": 8192, # Verify from Groq docs, assuming 8k for Gemma 2
        "priority": 1,
        "description": "Gemma 2 9B (High TPM, Good Quality)"
    },
    {
        "model_id": "llama3-70b-8192", 
        "context_window": 8192, 
        "priority": 2,
        "description": "Llama3 70B (Highest Quality, Moderate TPM)"
    },
    {
        "model_id": "llama3-8b-8192", 
        "context_window": 8192, 
        "priority": 3,
        "description": "Llama3 8B (Good Quality, Moderate TPM)"
    },
    {
        "model_id": "mixtral-8x7b-32768", 
        "context_window": 32768, 
        "priority": 4,
        "description": "Mixtral 8x7B (Large Context Window, Moderate TPM)"
    },
    # Add other models from the Groq list if desired, with their properties
]

# Ensure directories exist (optional here, could be done in app_init.py)
# os.makedirs(UPLOAD_FOLDER, exist_ok=True)
# os.makedirs(OUTPUT_FOLDER, exist_ok=True)
# os.makedirs(MODEL_DOWNLOAD_ROOT, exist_ok=True)
