# conftest.py for tests in the 'backend' directory (pytest rootdir).
# Ensures that the project root (ShortsMakerAI/) is in sys.path,
# so that imports like 'from backend.config import ...' work correctly.

import sys
import os
import pytest # Added for @pytest.fixture
import types  # Added for types.ModuleType and types.SimpleNamespace

# Calculate the project root directory (ShortsMakerAI/)
# __file__ in this conftest.py is ShortsMakerAI/backend/conftest.py
# os.path.dirname(__file__) is ShortsMakerAI/backend/
# os.path.join(..., '..') is ShortsMakerAI/
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
    # Adding a print statement to confirm execution during pytest discovery
    print(f"INFO: backend/conftest.py: Added {PROJECT_ROOT} to sys.path")

# --- Session-scoped monkeypatch fixture ---
@pytest.fixture(scope="session")
def monkeypatch_session():
    """Session-scoped monkeypatch to allow patching for the whole test session."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()

# --- Autouse fixture to mock problematic imports globally for the test session ---
@pytest.fixture(scope="session", autouse=True)
def mock_global_problematic_imports(monkeypatch_session):
    """
    Mocks 'tiktoken' globally for the test session to prevent collection errors
    related to 'tiktoken.__spec__ is None' when transformers library probes for it.
    This fixture runs automatically for the entire test session.
    """
    # Mock tiktoken
    # Check if it's already genuinely imported or mocked by another higher-level conftest
    if "tiktoken" not in sys.modules:
        mock_tt_module = types.ModuleType("tiktoken")
        # The __spec__ attribute is crucial for importlib.util.find_spec
        mock_tt_module.__spec__ = types.SimpleNamespace(name="tiktoken_conftest_mock_spec", origin="conftest.py")
        
        # Add a dummy get_encoding to satisfy transformers' checks if it tries to use it
        # This mock should be sufficient for transformers' _is_package_available check.
        dummy_encoding = types.SimpleNamespace(encode=lambda text: [0] * (len(text) // 4))
        mock_tt_module.get_encoding = lambda encoding_name: dummy_encoding
        
        monkeypatch_session.setitem(sys.modules, "tiktoken", mock_tt_module)
        print("INFO: backend/conftest.py: Globally mocked 'tiktoken' in sys.modules for test session.")
    
    elif hasattr(sys.modules.get("tiktoken"), "__spec__") and getattr(sys.modules["tiktoken"], "__spec__", "not_present") is None:
        # If tiktoken is in sys.modules but __spec__ is None (problematic state)
        current_tt_module = sys.modules["tiktoken"]
        current_tt_module.__spec__ = types.SimpleNamespace(name="tiktoken_conftest_fixed_spec", origin="conftest.py")
        if not hasattr(current_tt_module, "get_encoding"):
            dummy_encoding = types.SimpleNamespace(encode=lambda text: [0] * (len(text) // 4))
            current_tt_module.get_encoding = lambda encoding_name: dummy_encoding
        print("INFO: backend/conftest.py: Fixed existing 'tiktoken' in sys.modules to have a __spec__.")

    # Note: If other libraries cause similar collection issues (e.g., 'transformers' itself),
    # they could be mocked here in a similar fashion. For now, only 'tiktoken' is addressed.
