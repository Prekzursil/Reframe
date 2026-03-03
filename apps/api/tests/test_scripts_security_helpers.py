from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def _load_security_helpers_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "scripts" / "security_helpers.py"
    spec = spec_from_file_location("security_helpers", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load module spec from {module_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalize_https_url_rejects_private_and_non_https():
    module = _load_security_helpers_module()

    with pytest.raises(ValueError):
        module.normalize_https_url("http://example.com")

    with pytest.raises(ValueError):
        module.normalize_https_url("https://localhost/resource")


def test_normalize_https_url_accepts_allowed_host_and_keeps_query():
    module = _load_security_helpers_module()

    normalized = module.normalize_https_url(
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main?x=1#frag",
        allowed_hosts={"huggingface.co"},
    )
    if normalized != "https://huggingface.co/ggerganov/whisper.cpp/resolve/main?x=1":
        raise AssertionError(f"Unexpected normalized URL: {normalized}")


def test_normalize_https_url_supports_host_suffix_allowlist_and_optional_query_strip():
    module = _load_security_helpers_module()

    normalized = module.normalize_https_url(
        "https://api.sentry.io/api/0/projects?x=1#frag",
        allowed_host_suffixes={"sentry.io"},
        strip_query=True,
    )
    if normalized != "https://api.sentry.io/api/0/projects":
        raise AssertionError(f"Unexpected normalized URL: {normalized}")
