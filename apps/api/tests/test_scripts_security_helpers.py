from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def _load_security_helpers_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "scripts" / "security_helpers.py"
    spec = spec_from_file_location("security_helpers", module_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalize_https_url_rejects_private_and_non_https():
    module = _load_security_helpers_module()

    with pytest.raises(ValueError):
        module.normalize_https_url("http://example.com")

    with pytest.raises(ValueError):
        module.normalize_https_url("https://localhost/resource")



def test_normalize_https_url_accepts_allowed_host_and_strips_query_fragment():
    module = _load_security_helpers_module()

    normalized = module.normalize_https_url(
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main?x=1#frag",
        allowed_hosts={"huggingface.co"},
    )
    assert normalized == "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
