"""Real-media acceptance tests for the scrollshot Markdown RPC.

These tests deliberately cross the public composition root and asynchronous job
boundary.  The input is a deterministic H.264 MP4 generated at runtime with the
repository's ffmpeg resolver; the production sampler, OCR reader, edge finder,
pose solver, composer, evidence verifier, and atomic publisher are not replaced.

Run explicitly (the repository excludes E2E tests from the default gate)::

    python -m pytest -m e2e tests/test_scrollshot_real_media_e2e.py -vv
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from media_studio import ffmpeg, handlers, protocol
from media_studio.features import scrollshot
from media_studio.handlers import Services
from media_studio.jobs import Job, JobRegistry
from media_studio.protocol import RpcContext

pytestmark = pytest.mark.e2e

_WIDTH = 480
_HEIGHT = 288
_HEADER_HEIGHT = 48
_ROW_HEIGHT = 40
_SAMPLE_EVERY = 12  # ScrollshotConfig.sample_every default: acceptance pins it.
_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
_RESULT_SCHEMA = "reframe.scrollshot-result/v1"
_CANONICAL_VERDICTS = {"FULL_DOCUMENT_COMPLETE", "RECORDED_SPAN_COMPLETE", "INCOMPLETE", "REVIEW_REQUIRED"}


@dataclass(frozen=True)
class ExportRun:
    service: Services
    job: Job
    receipt: dict[str, Any]
    events: tuple[tuple[Any, ...], ...]


def _real_cv2() -> Any:
    return pytest.importorskip("cv2", reason="OpenCV is required for the real scrollshot E2E")


def _document(cv2_mod: Any, *, rows: int = 16) -> np.ndarray:
    """Build a high-contrast document with machine- and OCR-readable row IDs."""
    image = np.full((rows * _ROW_HEIGHT, _WIDTH, 3), 255, dtype=np.uint8)
    for row in range(rows):
        top = row * _ROW_HEIGHT
        shade = 235 if row % 2 == 0 else 250
        image[top : top + _ROW_HEIGHT, :] = (shade, shade, shade)
        # A unique color slug makes accidental row duplication visible even when
        # OCR is imperfect.  Broad blocks survive yuv420p H.264 compression.
        color = ((37 * row + 31) % 190 + 30, (71 * row + 47) % 190 + 30, (97 * row + 59) % 190 + 30)
        cv2_mod.rectangle(image, (8, top + 7), (42, top + 32), color, -1)
        cv2_mod.putText(
            image,
            f"ROW{row:03d}TOKEN",
            (58, top + 29),
            cv2_mod.FONT_HERSHEY_SIMPLEX,
            0.72,
            (0, 0, 0),
            2,
            cv2_mod.LINE_AA,
        )
        cv2_mod.line(image, (0, top + _ROW_HEIGHT - 1), (_WIDTH - 1, top + _ROW_HEIGHT - 1), (80, 80, 80), 1)
    return image


def _viewport(cv2_mod: Any, document: np.ndarray, offset: int) -> np.ndarray:
    """Render one browser viewport with a sticky header and document crop."""
    body_height = _HEIGHT - _HEADER_HEIGHT
    frame = np.full((_HEIGHT, _WIDTH, 3), 255, dtype=np.uint8)
    frame[:_HEADER_HEIGHT, :] = (34, 34, 34)
    cv2_mod.putText(
        frame,
        "STICKY HEADER",
        (92, 33),
        cv2_mod.FONT_HERSHEY_SIMPLEX,
        0.82,
        (255, 255, 255),
        2,
        cv2_mod.LINE_AA,
    )
    available = max(0, min(body_height, document.shape[0] - offset))
    if available:
        frame[_HEADER_HEIGHT : _HEADER_HEIGHT + available, :] = document[offset : offset + available, :]
    return frame


def _run_checked(argv: Sequence[str], *, timeout: float = 45.0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(list(argv), capture_output=True, text=True, check=False, timeout=timeout)
    assert result.returncode == 0, f"command failed ({result.returncode}): {argv!r}\n{result.stderr}"
    return result


def _encode_h264(path: Path, offsets: Sequence[int]) -> None:
    """Encode logical viewports so default sampling selects each one exactly."""
    assert offsets, "at least one logical viewport is required"
    cv2_mod = _real_cv2()
    document = _document(cv2_mod)
    frames_dir = path.parent / f"{path.stem}-frames"
    frames_dir.mkdir()

    logical = [_viewport(cv2_mod, document, offset) for offset in offsets]
    # Frames at 0, 12, 24, ... are the logical states.  Ending exactly on a
    # sampling boundary prevents the sampler from appending an accidental tail.
    expanded: list[np.ndarray] = []
    for frame in logical[:-1]:
        expanded.extend([frame] * _SAMPLE_EVERY)
    expanded.append(logical[-1])
    for index, frame in enumerate(expanded):
        target = frames_dir / f"frame_{index:04d}.png"
        assert cv2_mod.imwrite(str(target), frame), f"OpenCV could not write {target}"

    ffmpeg_bin = ffmpeg.ffmpeg_path()
    _run_checked(
        [
            ffmpeg_bin,
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            "12",
            "-start_number",
            "0",
            "-i",
            str(frames_dir / "frame_%04d.png"),
            "-c:v",
            ffmpeg.H264_ENCODER,
            "-preset",
            "ultrafast",
            "-crf",
            "0",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(path),
        ]
    )
    probe = _run_checked(
        [
            ffmpeg.ffprobe_path(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height",
            "-of",
            "json",
            str(path),
        ]
    )
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream == {"codec_name": "h264", "width": _WIDTH, "height": _HEIGHT}


def _drive_public_rpc(tmp_path: Path, media: Path, *, assurance: str) -> ExportRun:
    """Drive the production composition registry and asynchronous job boundary."""
    events: list[tuple[Any, ...]] = []
    service = Services(data_dir=tmp_path / "app-data")
    protocol.clear_methods()
    handlers.register_all(services=service)
    handler = protocol.METHODS.get(scrollshot.KIND)
    assert handler is not None, "composition root did not register scrollshot.exportMarkdown"
    registry = JobRegistry(
        emit_progress=lambda job_id, pct, message: events.append(("progress", job_id, pct, message)),
        emit_done=lambda job_id, result: events.append(("done", job_id, result)),
    )
    context = RpcContext(emit_notification=lambda _obj: None, jobs=registry)
    receipt = handler(
        {"path": str(media), "title": "Real media acceptance", "language": "eng", "assurance": assurance},
        context,
    )
    assert receipt["kind"] == scrollshot.KIND
    assert isinstance(receipt.get("jobId"), str) and receipt["jobId"]
    job = registry.get(receipt["jobId"])
    job.wait(timeout=90)
    assert any(event[:2] == ("progress", job.id) for event in events), events
    assert any(event[:2] == ("done", job.id) for event in events), events
    return ExportRun(service=service, job=job, receipt=receipt, events=tuple(events))


def _canonical_result(run: ExportRun) -> dict[str, Any]:
    assert run.job.error is None, f"scrollshot job failed: {run.job.error}"
    assert isinstance(run.job.result, dict), run.job.result
    result = run.job.result
    assert result["schemaVersion"] == _RESULT_SCHEMA
    assert isinstance(result["runId"], str) and result["runId"]
    assert result["verdict"] in _CANONICAL_VERDICTS
    assert isinstance(result["reviewRequired"], bool)
    assert isinstance(result["warnings"], list)
    assert isinstance(result["panoramaPaths"], list) and result["panoramaPaths"]
    return result


def _manifest(run: ExportRun) -> tuple[Path, dict[str, Any]]:
    result = _canonical_result(run)
    manifest_path = Path(result["manifestPath"])
    assert manifest_path.is_file()
    return manifest_path, json.loads(manifest_path.read_text(encoding="utf-8"))


def _assert_recorded_span_complete(run: ExportRun) -> dict[str, Any]:
    result = _canonical_result(run)
    assert result["verdict"] == "RECORDED_SPAN_COMPLETE"
    assert result["verdict"] != "FULL_DOCUMENT_COMPLETE", "no independent top+bottom terminal proof exists"
    assert result["reviewRequired"] is False
    assert result["warnings"] == []
    return result


def _assert_global_positions(manifest: dict[str, Any], expected: Sequence[int]) -> None:
    positions = manifest["coverage"]["positions"]
    assert len(positions) == len(expected), (positions, expected)
    assert positions == pytest.approx(list(expected), abs=4), (
        "global frame poses must retain duplicates and signed reversals",
        positions,
        expected,
    )


def _compact_ocr(path: Path) -> str:
    assert _TESSERACT.is_file(), f"required local OCR executable is missing: {_TESSERACT}"
    result = _run_checked([str(_TESSERACT), str(path), "stdout", "-l", "eng", "--psm", "6"])
    return re.sub(r"[^A-Z0-9]", "", result.stdout.upper())


def _assert_fixed_header_once(image_path: Path, fixture_frame: Path) -> None:
    """Prove chrome retention by pixels; OCR ignores white-on-dark text here."""
    cv2_mod = _real_cv2()
    panorama = cv2_mod.imread(str(image_path))
    source = cv2_mod.imread(str(fixture_frame))
    assert panorama is not None and source is not None
    header = source[:_HEADER_HEIGHT]
    scores = cv2_mod.matchTemplate(panorama, header, cv2_mod.TM_CCOEFF_NORMED).max(axis=1)
    matches = np.flatnonzero(scores >= 0.98).tolist()
    assert matches == [0], (matches, float(scores.max()))


def test_real_h264_downscroll_recovers_skips_without_duplicate_or_sticky_ghost_rows(tmp_path: Path) -> None:
    """Down-scroll, exact duplicate, and a recoverable skipped viewport stay complete."""
    # 80 -> 240 skips one expected 80px step but still overlaps by 80px, so a
    # max-skip/global graph must recover it.  Offset 80 is an exact duplicate.
    offsets = [0, 80, 80, 240, 320, 400]
    media = tmp_path / "down-duplicate-recoverable.mp4"
    _encode_h264(media, offsets)

    run = _drive_public_rpc(tmp_path, media, assurance="strict")
    manifest_path, manifest = _manifest(run)
    result = _assert_recorded_span_complete(run)
    assert manifest["coverage"]["verdict"] == "complete"
    assert manifest["coverage"]["issues"] == []
    _assert_global_positions(manifest, offsets)
    assert scrollshot.verify_manifest(manifest_path) == []

    image_path = Path(result["panoramaPaths"][0])
    compact = _compact_ocr(image_path)
    _assert_fixed_header_once(image_path, media.parent / f"{media.stem}-frames" / "frame_0000.png")
    # The recovered span is exactly the 16-row document.  A correct seam policy
    # emits each row once; full-frame pasting or bad poses create ghosts/holes.
    for row in range(16):
        token = f"ROW{row:03d}TOKEN"
        assert compact.count(token) == 1, (token, compact)


def test_real_h264_global_pose_preserves_signed_reversal_and_oscillation(tmp_path: Path) -> None:
    """A revisit is placed at its earlier global pose, not forced forward."""
    offsets = [0, 80, 160, 80, 160, 240]
    media = tmp_path / "reverse-oscillation.mp4"
    _encode_h264(media, offsets)

    run = _drive_public_rpc(tmp_path, media, assurance="strict")
    _manifest_path, manifest = _manifest(run)
    _assert_recorded_span_complete(run)
    assert manifest["coverage"]["verdict"] == "complete"
    _assert_global_positions(manifest, offsets)
    assert manifest["coverage"]["positions"][3] < manifest["coverage"]["positions"][2]
    assert manifest["coverage"]["positions"][4] > manifest["coverage"]["positions"][3]


def test_real_h264_nonrecoverable_gap_is_explicit_and_strict_publish_is_atomic(tmp_path: Path) -> None:
    """A true uncovered span is explicit in balanced mode and atomic in strict mode."""
    media = tmp_path / "nonrecoverable-gap.mp4"
    _encode_h264(media, [0, 80, 440])

    balanced_root = tmp_path / "balanced"
    balanced_run = _drive_public_rpc(balanced_root, media, assurance="balanced")
    _balanced_manifest_path, balanced_manifest = _manifest(balanced_run)
    balanced_result = _canonical_result(balanced_run)
    assert balanced_result["verdict"] == "INCOMPLETE"
    assert balanced_result["reviewRequired"] is True
    assert any("gap" in str(item).lower() for item in balanced_result["warnings"]), balanced_result
    assert str(balanced_manifest["coverage"]["verdict"]).lower() == "incomplete"
    assert any("gap" in str(item).lower() for item in balanced_manifest["coverage"]["issues"]), balanced_manifest

    strict_root = tmp_path / "strict"
    strict_run = _drive_public_rpc(strict_root, media, assurance="strict")
    assert strict_run.job.error is not None, "strict mode silently published a document with a nonrecoverable gap"
    assert "coverage" in str(strict_run.job.error).lower() and "gap" in str(strict_run.job.error).lower(), strict_run.job.error

    output_root = strict_run.service.exports_dir / "scrollshots"
    if output_root.exists():
        assert list(output_root.glob(".*.tmp")) == [], "failed export leaked a staging directory"
        assert [item for item in output_root.iterdir() if item.is_dir() and not item.name.startswith(".")] == [], (
            "failed strict export published a partial final bundle",
            list(output_root.iterdir()),
        )


def test_real_h264_atomic_bundle_detects_source_and_artifact_hash_mutation(tmp_path: Path) -> None:
    """A real successful bundle is all-or-nothing and every byte mutation is detected."""
    media = tmp_path / "single-viewport.mp4"
    _encode_h264(media, [0])

    run = _drive_public_rpc(tmp_path, media, assurance="strict")
    manifest_path, manifest = _manifest(run)
    result = _assert_recorded_span_complete(run)
    assert manifest["coverage"] == {
        "verdict": "complete",
        "issues": [],
        "positions": [0],
        "acceptedEdges": [],
        "rejectedEdges": [],
    }
    assert scrollshot.verify_manifest(manifest_path) == []

    bundle_dir = manifest_path.parent
    assert not bundle_dir.name.startswith(".")
    assert result["runId"] in bundle_dir.name
    assert list(bundle_dir.parent.glob(".*.tmp")) == []
    for logical_name, relative_path in manifest["files"].items():
        target = bundle_dir / relative_path
        assert target.is_file(), (logical_name, target)
        assert target.stat().st_size > 0, (logical_name, target)

    markdown_path = bundle_dir / manifest["files"]["markdown"]
    image_path = bundle_dir / manifest["files"]["image"]
    media.write_bytes(media.read_bytes() + b"SOURCE-TAMPER")
    markdown_path.write_text(markdown_path.read_text(encoding="utf-8") + "\nARTIFACT-TAMPER\n", encoding="utf-8")
    image_path.write_bytes(image_path.read_bytes() + b"IMAGE-TAMPER")
    assert set(scrollshot.verify_manifest(manifest_path)) == {"source", "markdown", "image"}


# UNIT-COMPLETE: scrollshot-real-media-acceptance-20260819
