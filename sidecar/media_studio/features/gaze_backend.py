"""Real heavy backend for the C15 gaze-correction engine (LAZY only).

Imported ONLY inside ``gaze._default_backend_factory`` at run-time — never at
package import, never by the unit tests (which inject a fake ``GazeBackend``). It
is therefore the one place allowed to import cv2 and to instantiate the YuNet
model, and those imports live INSIDE the method bodies so even importing THIS
module stays light (mirrors ``reframe_multispeaker_backend`` /
``scene_transnet_backend``).

Coverage of the class is excluded (it needs the native stack + the real ONNX);
the PURE half it delegates every decision to is covered exhaustively in
``test_gaze_geometry.py`` / ``test_gaze_service.py``, and this module's import
surface is covered by ``test_phase8_backend_surfaces.py``.

THIS BACKEND DECIDES NOTHING. It detects faces, hands each one to the injected
pure ``plan`` callable along with a reader for that eye's pixels, and applies
exactly what comes back. Every threshold, cap, skip rule and warp map is computed
in :mod:`media_studio.features.gaze`. Keeping it that way is what makes the
feature's behaviour testable at all, so resist adding a decision here.

MODEL PROVENANCE: the only model is **YuNet** (``opencv/face_detection_yunet``,
MIT), resolved from the ALREADY-vendored sha256-pinned asset via
``reframe_claudeshorts.resolve_yunet_model_path``. NOTHING is downloaded at run
time and there is no second face detector — the ASD path uses the same asset.

AUDIO: cv2's ``VideoWriter`` cannot carry an audio track, so the warped frames go
to a silent intermediate and a final ffmpeg pass re-attaches the SOURCE audio
stream unmodified (``-c:a copy``). A gaze correction must never re-encode or
drop the speaker's audio.
"""

from __future__ import annotations

import contextlib
import os
import subprocess  # noqa: S404 - argv lists only, no shell=True
import tempfile
from collections.abc import Callable
from typing import Any

from .. import ffmpeg
from ..util import get_logger
from .gaze import (
    UNAVAILABLE_MESSAGE,
    EyeBox,
    EyeEdit,
    FacePlan,
    GazeReport,
    GazeUnavailableError,
    Planner,
    build_warp_maps,
    yunet_eye_pairs,
)

log = get_logger("media_studio.features.gaze_backend")

#: Intermediate (silent) file prefix — greppable if a run is interrupted.
WORK_PREFIX = "gaze_"
#: YuNet confidence floor. The SAME value the ASD front-end uses, deliberately:
#: two different floors on one shared detector would be a silent inconsistency.
YUNET_SCORE_THRESHOLD = 0.6


class RealGazeBackend:  # pragma: no cover - requires the heavy native stack + the ONNX
    """YuNet detect -> pure plan -> per-eye ``cv2.remap`` -> re-muxed clip."""

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._detector: Any = None

    def release(self) -> None:
        """Drop the detector (the only resident model this backend holds)."""
        self._detector = None

    def _resolve_model(self) -> str:
        from .reframe_claudeshorts import resolve_yunet_model_path  # noqa: PLC0415 - heavy seam

        path = resolve_yunet_model_path(self._settings)
        if not path:
            raise GazeUnavailableError(UNAVAILABLE_MESSAGE)
        return str(path)

    def _apply_edit(self, frame: Any, edit: EyeEdit) -> int:
        """Warp one eye in place. Returns 1 if a warp was applied, else 0.

        A zero shift is skipped OUTRIGHT rather than remapped: an identity remap
        still resamples, which visibly softens the eye for no benefit.
        """
        import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)

        if edit.shift == (0.0, 0.0):
            return 0
        box = edit.box
        crop = frame[box.y : box.y + box.h, box.x : box.x + box.w]
        map_x, map_y = build_warp_maps(box.w, box.h, iris=edit.iris, radius=edit.radius, shift=edit.shift)
        frame[box.y : box.y + box.h, box.x : box.x + box.w] = cv2.remap(
            crop, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101
        )
        return 1

    def _plan_frame(self, frame: Any, plan: Planner, width: int, height: int) -> list[FacePlan]:
        """Detect every face and ask the PURE planner what to do with each."""
        self._detector.setInputSize((width, height))
        _retval, faces = self._detector.detect(frame)

        def read_patch(box: EyeBox) -> Any:
            return frame[box.y : box.y + box.h, box.x : box.x + box.w]

        return [plan(pair, frame_w=width, frame_h=height, read_patch=read_patch) for pair in yunet_eye_pairs(faces)]

    def process(
        self,
        in_path: str,
        out_path: str,
        *,
        plan: Planner,
        on_progress: Callable[[float, str], None],
        should_cancel: Callable[[], bool],
    ) -> GazeReport:
        """Warp every detected eye and write ``out_path`` with the source audio."""
        import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)

        model = self._resolve_model()
        self._detector = cv2.FaceDetectorYN.create(  # pyright: ignore[reportAttributeAccessIssue]
            model, "", (0, 0), score_threshold=YUNET_SCORE_THRESHOLD
        )
        cap = cv2.VideoCapture(in_path)
        if not cap.isOpened():
            cap.release()
            raise GazeUnavailableError(f"gaze correction could not open the source video: {in_path}")

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        fd, silent_path = tempfile.mkstemp(prefix=WORK_PREFIX, suffix=".mp4")
        os.close(fd)
        # ``cv2.VideoWriter.fourcc`` (the static method), NOT the legacy module-level
        # ``cv2.VideoWriter_fourcc`` alias: the alias is GONE in OpenCV 5.x, and this
        # repo's gate installs opencv-python-headless UNPINNED, so it resolves to 5.x.
        # Both spellings exist on 4.x (measured on 4.13.0), so this form is correct on
        # both. Only the types gate can catch this — the class is ``# pragma: no
        # cover``, so no test executes this line.
        writer = cv2.VideoWriter(silent_path, cv2.VideoWriter.fourcc(*"mp4v"), fps, (width, height))

        frames_total = 0
        frames_corrected = 0
        eyes_corrected = 0
        skipped: dict[str, int] = {}
        try:
            while True:
                if should_cancel():
                    log.info("gaze: cancelled after %d frames", frames_total)
                    break
                ok, frame = cap.read()
                if not ok:
                    break
                frames_total += 1
                warped_here = 0
                for face in self._plan_frame(frame, plan, width, height):
                    if face.skipped is not None:
                        key = str(face.skipped)
                        skipped[key] = skipped.get(key, 0) + 1
                        continue
                    for edit in face.eyes:
                        warped_here += self._apply_edit(frame, edit)
                writer.write(frame)
                if warped_here:
                    frames_corrected += 1
                    eyes_corrected += warped_here
                if total > 0:
                    on_progress(90.0 * frames_total / total, "correcting gaze")
        finally:
            writer.release()
            cap.release()
            self.release()

        try:
            on_progress(95.0, "re-attaching audio")
            self._mux(silent_path, in_path, out_path)
        finally:
            with contextlib.suppress(OSError):
                os.remove(silent_path)

        on_progress(100.0, "done")
        return GazeReport(
            frames_total=frames_total,
            frames_corrected=frames_corrected,
            eyes_corrected=eyes_corrected,
            skipped=skipped,
        )

    def _mux(self, silent_path: str, source_path: str, out_path: str) -> None:
        """Encode the warped video and copy the SOURCE audio stream verbatim.

        ``-map 1:a?`` makes the audio OPTIONAL, so a silent source still produces
        a valid output instead of failing the whole run.
        """
        argv = [
            ffmpeg.ffmpeg_path(self._settings),
            "-y",
            "-i",
            silent_path,
            "-i",
            source_path,
            "-map",
            "0:v:0",
            "-map",
            "1:a?",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-shortest",
            out_path,
        ]
        subprocess.run(  # noqa: S603 - argv list, no shell
            argv, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )


__all__ = ["WORK_PREFIX", "YUNET_SCORE_THRESHOLD", "RealGazeBackend"]
