"""Cross-edit tests for runtime_setup.bootstrap.extract_tool_archives (WU reconcile).

Covers the RELEASE_TAG-bump clear-once + marker-write branches added to pair with
tools_resolver's version-aware detect gate:
  * a stale build (old exe + old marker) is WIPED before a new nested layout is
    extracted, and the fresh build is hoisted with a marker == LLAMA_RELEASE_TAG
    (``target not in cleared`` True + ``target.exists()`` True);
  * a SECOND archive extracting INTO the same dir (the cudart zip lands in the
    CUDA build dir) does NOT wipe what the CUDA archive just populated
    (``target not in cleared`` False).

The ``target not in cleared`` True + ``target.exists()`` False branch is already
covered by test_runtime_setup.TestExtraction.test_extract_tool_archives_uses_manifest_dest.

NO real pip / network / subprocess — zips built in tmp_path with stdlib zipfile.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from media_studio import tools_resolver as tr
from media_studio.assets import manifest
from runtime_setup import bootstrap as bs


def _make_zip(path: Path, members: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


class TestExtractToolArchivesReleaseTag:
    def test_stale_build_wiped_and_marker_rewritten(self, tmp_path):
        """An old exe + stale marker + orphan DLL are cleared; the new nested build
        is hoisted and the marker text becomes LLAMA_RELEASE_TAG."""
        root = tmp_path / "root"
        target = root / tr.TOOL_DIR_CUDA
        target.mkdir(parents=True)
        # Pre-existing STALE build from a previous LLAMA_RELEASE_TAG.
        (target / tr.LLAMA_EXE).write_bytes(b"stale-exe")
        (target / "orphan.dll").write_bytes(b"stale-dll")
        (target / tr.RELEASE_TAG_MARKER).write_text("OLD-TAG", encoding="utf-8")

        cuda_entry = manifest.get_asset(tr.LLAMA_CUDA_ASSET)
        _make_zip(
            root / cuda_entry.dest,
            {f"build/bin/{tr.LLAMA_EXE}": b"new-exe", "build/bin/new.dll": b"new-dll"},
        )

        done = bs.extract_tool_archives(root)

        assert done == [tr.LLAMA_CUDA_ASSET]
        # The stale build (orphan DLL) is gone — target was wiped before extraction.
        assert not (target / "orphan.dll").exists()
        # The fresh nested exe is hoisted to the dir root.
        assert (target / tr.LLAMA_EXE).read_bytes() == b"new-exe"
        assert (target / "new.dll").read_bytes() == b"new-dll"
        # The marker now attests the CURRENT release tag.
        assert (target / tr.RELEASE_TAG_MARKER).read_text(encoding="utf-8") == tr.LLAMA_RELEASE_TAG

    def test_cudart_archive_does_not_wipe_the_cuda_build(self, tmp_path):
        """CUDA + CUDART both extract into TOOL_DIR_CUDA; the cudart archive must NOT
        clear the exe the CUDA archive just extracted (clear-once per target)."""
        root = tmp_path / "root"
        cuda_entry = manifest.get_asset(tr.LLAMA_CUDA_ASSET)
        cudart_entry = manifest.get_asset(tr.LLAMA_CUDART_ASSET)
        _make_zip(
            root / cuda_entry.dest,
            {f"build/bin/{tr.LLAMA_EXE}": b"exe", "build/bin/ggml.dll": b"d"},
        )
        # cudart runtime ships flat DLLs that land beside the exe.
        _make_zip(root / cudart_entry.dest, {"cudart64_12.dll": b"rt"})

        done = bs.extract_tool_archives(root)

        assert done == [tr.LLAMA_CUDA_ASSET, tr.LLAMA_CUDART_ASSET]
        target = root / tr.TOOL_DIR_CUDA
        # The CUDA exe survives the cudart pass (target not re-wiped).
        assert (target / tr.LLAMA_EXE).read_bytes() == b"exe"
        # The cudart DLL landed alongside it.
        assert (target / "cudart64_12.dll").read_bytes() == b"rt"
        assert (target / tr.RELEASE_TAG_MARKER).read_text(encoding="utf-8") == tr.LLAMA_RELEASE_TAG
