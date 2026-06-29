"""LR-ASD visual active-speaker inference for the multi-speaker reframe backend.

Produces the per-frame contract the pure director consumes:
``(boxes_per_frame, visual_scores_per_frame, vad_per_frame)`` — boxes as
``(x, y, w, h)`` source-pixel tuples, per-box ASD scores index-aligned to the
boxes, and a per-frame RMS voice-activity value; every array has length
``total_frames``.

Pipeline (ported from Junhua-Liao/LR-ASD ``Columbia_test.py``, validated on the
GPU): extract @25 fps frames + 16 kHz mono audio -> S3FD face detect ->
IoU face-track linking -> per-track 112x112 crop + MFCC -> windowed audio-visual
ASD scoring -> map per-track 25 fps scores back to the source-fps frame grid.

PRODUCTION VENDORED (R1): the heavy S3FD + LR-ASD code is the numpy-2-clean copy
vendored into :mod:`media_studio.features._lightasd` (MIT — see that package's
``LICENSE``), NOT a ``$HOME`` checkout. LR-ASD (IJCV 2025) is the strictly-better
successor of Light-ASD; the inference pipeline is identical (shared
``Columbia_test.py`` lineage), only the model weights/architecture changed. The
``sys.path`` + ``chdir`` seam is GONE; the two weight files are resolved by
PATH via :func:`_resolve_weights` (a ``settings['lightAsdWeightsDir']`` override,
else the sha256-pinned asset-manager install paths registered in
``assets/manifest.py``).

Coverage: the torch/cv2/ffmpeg seam functions are ``# pragma: no cover`` (they
need the heavy native stack + real weights); the PURE helpers (:func:`_bb_iou`,
:func:`_source_frame_index`, :func:`_vad_per_frame`) are unit-tested for real in
``test_lightasd_infer_helpers.py``, and the pure director this module feeds is
covered exhaustively in ``test_reframe_multispeaker.py``.
"""

from __future__ import annotations

import math
import os
import subprocess  # noqa: S404 - argv lists only, no shell=True (see _run)
import tempfile
from typing import Any

from ..util import get_logger

log = get_logger("media_studio.features._lightasd_infer")

Box = tuple[float, float, float, float]  # (x, y, w, h) source px — matches reframe_multispeaker.Box

ASD_FPS = 25  # LR-ASD operates at 25 fps (its trained temporal regime)
AUDIO_SR = 16000
IOU_THRES = 0.5
NUM_FAILED_DET = 10
MIN_TRACK = 10
MIN_FACE = 10
CROP_SCALE = 0.40
DET_CONF = 0.9
DET_SCALE = 0.25
DURATIONS = (1, 1, 1, 2, 2, 2, 3, 3, 4, 5, 6)


def _resolve_weights(settings: dict[str, Any]) -> tuple[str, str]:  # pragma: no cover - heavy native seam
    """Resolve ``(s3fd_weight_path, asd_weight_path)`` for the vendored loaders.

    Order: an explicit operator override ``settings['lightAsdWeightsDir']`` (a dir
    holding ``sfd_face.pth`` + ``finetuning_TalkSet.model``) wins; otherwise the
    paths come from the sha256-pinned asset manager (the two weights registered in
    ``assets/manifest.py``). Raises if a weight cannot be located (never silently
    falls back to a missing file).
    """
    from ._lightasd import ASD_WEIGHT_NAME, S3FD_WEIGHT_NAME  # noqa: PLC0415

    override = settings.get("lightAsdWeightsDir")
    if override:
        wdir = os.path.expanduser(str(override))
        return os.path.join(wdir, S3FD_WEIGHT_NAME), os.path.join(wdir, ASD_WEIGHT_NAME)

    from ..assets import manifest  # noqa: PLC0415
    from ..assets.manager import AssetManager  # noqa: PLC0415

    mgr = AssetManager(settings_provider=lambda: settings)
    paths: list[str] = []
    for name in (manifest.LIGHTASD_S3FD_ASSET_NAME, manifest.LIGHTASD_ASD_ASSET_NAME):
        entry = manifest.get_asset(name)
        path = mgr.installed_path(entry) if entry is not None else None
        if path is None:
            raise RuntimeError(f"Light-ASD weight asset {name!r} is not installed")
        paths.append(path)
    return paths[0], paths[1]


def _run(argv: list[str]) -> None:  # pragma: no cover - heavy native seam
    """ffmpeg/argv runner — list form, never shell=True (injection-safe)."""
    subprocess.run(argv, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603


def _source_frame_index(frame: int, fps: float, n25: int) -> int:
    """Map a source-fps frame index onto the 25-fps ASD grid (clamped to range).

    The visual pipeline runs at :data:`ASD_FPS` (25); this maps source frame
    ``frame`` (at ``fps``) to the nearest 25-fps grid index, clamped to the last
    extracted frame ``n25 - 1`` so trailing source frames never index past the
    grid. PURE (stdlib only) so it is unit-tested for real.
    """
    return min(n25 - 1, int(round(frame / max(fps, 1e-6) * ASD_FPS)))


def _bb_iou(a: Any, b: Any) -> float:
    """IoU of two ``(x1, y1, x2, y2)`` corner boxes (0.0 when disjoint).

    PURE (stdlib only) so it is unit-tested for real; used by the face-track
    linker :func:`_track_shot`.
    """
    xa, ya, xb, yb = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, xb - xa) * max(0.0, yb - ya)
    if inter <= 0.0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / float(area_a + area_b - inter)


def _track_shot(
    scene_faces: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:  # pragma: no cover - heavy native seam
    """Link per-frame detections into interpolated face tracks (IoU greedy)."""
    import numpy as np  # noqa: PLC0415
    from scipy.interpolate import interp1d  # noqa: PLC0415

    faces = [list(f) for f in scene_faces]
    tracks: list[dict[str, Any]] = []
    while True:
        track: list[dict[str, Any]] = []
        for frame_faces in faces:
            for face in frame_faces:
                if not track:
                    track.append(face)
                    frame_faces.remove(face)
                elif face["frame"] - track[-1]["frame"] <= NUM_FAILED_DET:
                    if _bb_iou(face["bbox"], track[-1]["bbox"]) > IOU_THRES:
                        track.append(face)
                        frame_faces.remove(face)
                        continue
                else:
                    break
        if not track:
            break
        if len(track) <= MIN_TRACK:
            continue
        fnum = np.array([f["frame"] for f in track])
        bb = np.array([np.array(f["bbox"]) for f in track])
        fi = np.arange(fnum[0], fnum[-1] + 1)
        bbi = np.stack([interp1d(fnum, bb[:, j])(fi) for j in range(4)], axis=1)
        if max(np.mean(bbi[:, 2] - bbi[:, 0]), np.mean(bbi[:, 3] - bbi[:, 1])) > MIN_FACE:
            tracks.append({"frame": fi, "bbox": bbi})
    return tracks


def _crop_track(
    track: dict[str, Any], flist: list[str], crop_file: str
) -> None:  # pragma: no cover - heavy native seam
    """Write a 224x224 stabilised face clip + its audio slice for one track."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    from scipy import signal  # noqa: PLC0415

    vout = cv2.VideoWriter(crop_file + ".avi", cv2.VideoWriter.fourcc(*"XVID"), ASD_FPS, (224, 224))
    dx, dy, ds = [], [], []
    for det in track["bbox"]:
        ds.append(max(det[3] - det[1], det[2] - det[0]) / 2)
        dy.append((det[1] + det[3]) / 2)
        dx.append((det[0] + det[2]) / 2)
    ds = signal.medfilt(ds, 13)
    dx = signal.medfilt(dx, 13)
    dy = signal.medfilt(dy, 13)
    for i, fr in enumerate(track["frame"]):
        bs = ds[i]
        bsi = int(bs * (1 + 2 * CROP_SCALE))
        src = cv2.imread(flist[int(fr)])
        if src is None:
            raise RuntimeError(f"failed to read frame: {flist[int(fr)]}")
        img = np.pad(src, ((bsi, bsi), (bsi, bsi), (0, 0)), "constant", constant_values=110)
        my, mx = dy[i] + bsi, dx[i] + bsi
        face = img[
            int(my - bs) : int(my + bs * (1 + 2 * CROP_SCALE)),
            int(mx - bs * (1 + CROP_SCALE)) : int(mx + bs * (1 + CROP_SCALE)),
        ]
        vout.write(cv2.resize(face, (224, 224)))
    vout.release()
    start = int(track["frame"][0]) / ASD_FPS
    end = (int(track["frame"][-1]) + 1) / ASD_FPS
    _run(
        ["ffmpeg", "-y", "-i", crop_file + ".__src.wav", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", crop_file + ".wav"]
    )


def _score_track(asd: Any, crop_file: str) -> Any:  # pragma: no cover - heavy native seam
    """Windowed audio-visual ASD scoring for one cropped track -> per-frame score."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    import python_speech_features  # noqa: PLC0415
    import torch  # noqa: PLC0415
    from scipy.io import wavfile  # noqa: PLC0415

    _, audio = wavfile.read(crop_file + ".wav")
    af = python_speech_features.mfcc(audio, AUDIO_SR, numcep=13, winlen=0.025, winstep=0.010)
    cap = cv2.VideoCapture(crop_file + ".avi")
    vf = []
    while cap.isOpened():
        ret, fr = cap.read()
        if not ret:
            break
        g = cv2.resize(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), (224, 224))
        vf.append(g[56:168, 56:168])
    cap.release()
    if not vf:
        return np.array([])
    vf = np.array(vf)
    length = min((af.shape[0] - af.shape[0] % 4) / 100, vf.shape[0] / ASD_FPS)
    if length <= 0:
        return np.array([])
    af = af[: int(round(length * 100)), :]
    vf = vf[: int(round(length * ASD_FPS)), :, :]
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    all_score = []
    for dur in DURATIONS:
        batch = int(math.ceil(length / dur))
        sc: list[float] = []
        with torch.no_grad():
            for i in range(batch):
                ia = torch.FloatTensor(af[i * dur * 100 : (i + 1) * dur * 100, :]).unsqueeze(0).to(dev)
                iv = torch.FloatTensor(vf[i * dur * ASD_FPS : (i + 1) * dur * ASD_FPS, :, :]).unsqueeze(0).to(dev)
                ea = asd.model.forward_audio_frontend(ia)
                ev = asd.model.forward_visual_frontend(iv)
                out = asd.model.forward_audio_visual_backend(ea, ev)
                sc.extend(asd.lossAV.forward(out, labels=None))
        all_score.append(sc)
    n = min(len(s) for s in all_score)
    return np.round(np.mean(np.array([s[:n] for s in all_score]), axis=0), 1)


def analyze_visual(  # pragma: no cover - heavy native seam
    media_path: str,
    total_frames: int,
    fps: float,
    *,
    settings: dict[str, Any],
) -> tuple[tuple[tuple[Box, ...], ...], tuple[tuple[float, ...], ...], tuple[float, ...]]:
    """S3FD + LR-ASD -> per-(source)-frame boxes, aligned ASD scores, VAD.

    Returns three tuples each of length ``total_frames``. Boxes are ``(x,y,w,h)``
    in source pixels; ``visual_scores_per_frame[f][i]`` is the speaking score of
    ``boxes_per_frame[f][i]``; ``vad_per_frame[f]`` is normalised RMS energy.
    """
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    from scipy.io import wavfile  # noqa: PLC0415

    from ._lightasd.asd import ASD  # noqa: PLC0415
    from ._lightasd.s3fd import S3FD  # noqa: PLC0415

    s3fd_weight, asd_weight = _resolve_weights(settings)
    dev = "cuda" if _cuda() else "cpu"

    work = tempfile.mkdtemp(prefix="msreframe_")
    frames_dir = os.path.join(work, "f")
    os.makedirs(frames_dir, exist_ok=True)
    audio_wav = os.path.join(work, "a.wav")
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            media_path,
            "-qscale:v",
            "2",
            "-r",
            str(ASD_FPS),
            "-async",
            "1",
            os.path.join(frames_dir, "%06d.jpg"),
        ]
    )
    _run(["ffmpeg", "-y", "-i", media_path, "-ac", "1", "-vn", "-ar", str(AUDIO_SR), audio_wav])
    flist = sorted(os.path.join(frames_dir, f) for f in os.listdir(frames_dir) if f.endswith(".jpg"))
    n25 = len(flist)
    if n25 == 0:
        raise RuntimeError("no frames extracted for visual ASD")

    det = S3FD(s3fd_weight, device=dev)
    scene: list[list[dict[str, Any]]] = []
    for fidx, fn in enumerate(flist):
        raw = cv2.imread(fn)
        if raw is None:
            raise RuntimeError(f"failed to read frame: {fn}")
        img = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
        bboxes = det.detect_faces(img, conf_th=DET_CONF, scales=[DET_SCALE])
        scene.append([{"frame": fidx, "bbox": b[:-1].tolist(), "conf": float(b[-1])} for b in bboxes])

    tracks = _track_shot(scene)

    # per-track audio source for slicing
    for i in range(len(tracks)):
        _link_audio(audio_wav, os.path.join(work, f"t{i}.__src.wav"))

    asd = ASD(device=dev)
    asd.loadParameters(asd_weight)
    asd.eval()

    # 25 fps grid: per-frame list of (box_xywh, score)
    boxes25: list[list[Box]] = [[] for _ in range(n25)]
    scores25: list[list[float]] = [[] for _ in range(n25)]
    for i, tr in enumerate(tracks):
        cf = os.path.join(work, f"t{i}")
        _crop_track(tr, flist, cf)
        sc = _score_track(asd, cf)
        frames = [int(f) for f in tr["frame"]]
        for j, fr in enumerate(frames):
            if 0 <= fr < n25:
                x1, y1, x2, y2 = tr["bbox"][j]
                boxes25[fr].append((float(x1), float(y1), float(x2 - x1), float(y2 - y1)))
                scores25[fr].append(float(sc[j]) if j < len(sc) else 0.0)

    # per-source-frame VAD (normalised RMS over each frame window)
    sr, wav = wavfile.read(audio_wav)
    wav = wav.astype(np.float32)
    vad_src = _vad_per_frame(wav, sr, total_frames, fps)

    # map 25 fps grid -> source-fps grid (length total_frames)
    boxes_pf: list[tuple[Box, ...]] = []
    scores_pf: list[tuple[float, ...]] = []
    for f in range(total_frames):
        g = _source_frame_index(f, fps, n25)
        boxes_pf.append(tuple(boxes25[g]))
        scores_pf.append(tuple(scores25[g]))
    log.info("visual ASD: %d frames, %d tracks", total_frames, len(tracks))
    return tuple(boxes_pf), tuple(scores_pf), vad_src


def _cuda() -> bool:  # pragma: no cover - heavy native seam
    try:
        import torch  # noqa: PLC0415

        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


def _link_audio(src: str, dst: str) -> None:  # pragma: no cover - heavy native seam
    if not os.path.exists(dst):
        try:
            os.symlink(src, dst)
        except OSError:
            import shutil  # noqa: PLC0415

            shutil.copyfile(src, dst)


def _vad_per_frame(wav: Any, sr: int, total_frames: int, fps: float) -> tuple[float, ...]:
    """Normalised per-frame RMS voice-activity (0..1).

    ``wav`` is a numpy 1-D (mono) or 2-D (multi-channel, averaged) sample array.
    Each source frame's window RMS is normalised by 3x the clip RMS and clamped to
    ``[0, 1]``. Uses only numpy (available in the CI gate env) so it is
    unit-tested for real.
    """
    import numpy as np  # noqa: PLC0415

    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    out = []
    win = max(1, int(sr / max(fps, 1e-6)))
    peak = float(np.sqrt(np.mean(np.square(wav)))) * 3.0 + 1e-6
    for f in range(total_frames):
        a = int(f / max(fps, 1e-6) * sr)
        seg = wav[a : a + win]
        rms = float(np.sqrt(np.mean(np.square(seg)))) if len(seg) else 0.0
        out.append(min(1.0, rms / peak))
    return tuple(out)


__all__ = ["analyze_visual"]
