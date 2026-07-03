"""Light surface-import tests for the Phase 8 heavy-dep backend modules.

The ``Real*Backend`` classes are ``# pragma: no cover`` (they need the heavy native
stack — torch / transformers / transnetv2 — loaded lazily inside their methods),
but each module's SURFACE (imports + ``__all__``) imports light. These tests cover
that surface so the aggregate sidecar coverage stays 100% without ever touching the
heavy ML stack — mirroring the ``diarize_backend`` surface-test convention.
"""

from __future__ import annotations


def test_scene_transnet_backend_surface_imports_light() -> None:
    import media_studio.features.scene_transnet_backend as be

    assert be.RealTransNetBackend.__name__ == "RealTransNetBackend"
    assert "RealTransNetBackend" in be.__all__


def test_reframe_multispeaker_backend_surface_imports_light() -> None:
    import media_studio.features.reframe_multispeaker_backend as be

    assert be.RealMultiSpeakerBackend.__name__ == "RealMultiSpeakerBackend"
    assert "RealMultiSpeakerBackend" in be.__all__


def test_reframe_edgetam_backend_surface_imports_light() -> None:
    # v1.2.0 WU2: the RealEdgeTamTracker class is ``# pragma: no cover`` (it needs
    # torch + the EdgeTAM package + real weights, loaded lazily inside its methods);
    # the module SURFACE (imports + constants + ``__all__``) imports light — cover
    # it so the gate stays 100% without ever touching the heavy stack.
    import media_studio.features.reframe_edgetam_backend as be

    assert be.RealEdgeTamTracker.__name__ == "RealEdgeTamTracker"
    assert "RealEdgeTamTracker" in be.__all__
    assert be.EDGETAM_CONFIG.endswith("edgetam.yaml")
    assert 0.0 < be.MIN_MASK_AREA_FRAC < 1.0


def test_lightasd_infer_surface_imports_light() -> None:
    # The LR-ASD inference helpers are ``# pragma: no cover`` (they need
    # torch / cv2 + real weights); the module SURFACE (imports, constants,
    # ``__all__``) imports light — cover it so the gate stays 100% without the
    # heavy stack (mirrors the Real*Backend surface-test convention).
    import media_studio.features._lightasd_infer as li

    assert callable(li.analyze_visual)
    assert "analyze_visual" in li.__all__
    assert li.ASD_FPS == 25
    assert li.AUDIO_SR == 16000


def test_lightasd_vendored_package_imports_light() -> None:
    # The vendored LR-ASD package __init__ is LIGHT (no torch/cv2); it carries
    # the upstream provenance + the weight basenames. The heavy model modules
    # (model / asd / s3fd) import torch at module top, so they are imported lazily
    # only inside analyze_visual and are NEVER imported here — we assert they SHIP
    # (importable spec) without executing them, so the coverage run never needs
    # torch (their statements are all ``# pragma: no cover``).
    import importlib.util
    import os

    import media_studio.features._lightasd as pkg

    assert pkg.LR_ASD_LICENSE == "MIT"
    assert pkg.S3FD_WEIGHT_NAME == "sfd_face.pth"
    assert pkg.ASD_WEIGHT_NAME == "finetuning_TalkSet.model"
    assert len(pkg.LR_ASD_COMMIT) == 40
    assert "LR-ASD" in pkg.LR_ASD_UPSTREAM
    # ``find_spec`` on the LIGHT package + the top-level torch model modules locates
    # them WITHOUT executing them (it never imports the leaf), so no torch is needed.
    for mod in (
        "media_studio.features._lightasd.model",
        "media_studio.features._lightasd.asd",
        "media_studio.features._lightasd.s3fd",
    ):
        assert importlib.util.find_spec(mod) is not None
    # The s3fd SUBMODULES (nets / box_utils) sit under the s3fd package whose
    # ``__init__`` imports torch at module top; ``find_spec("...s3fd.nets")`` would
    # have to EXECUTE that ``__init__`` (no torch in the coverage-gate env). Assert
    # they SHIP via the filesystem instead — proves they are vendored, no import.
    s3fd_dir = os.path.join(os.path.dirname(pkg.__file__), "s3fd")
    for fname in ("__init__.py", "nets.py", "box_utils.py"):
        assert os.path.isfile(os.path.join(s3fd_dir, fname))


def test_vlm_backbone_backend_surface_imports_light() -> None:
    import media_studio.features.vlm_backbone_backend as be

    assert be.RealBackboneBackend.__name__ == "RealBackboneBackend"
    assert "RealBackboneBackend" in be.__all__


def test_ctc_align_backend_surface_imports_light() -> None:
    import media_studio.features.ctc_align_backend as be

    assert be.RealCtcAlignBackend.__name__ == "RealCtcAlignBackend"
    assert "RealCtcAlignBackend" in be.__all__


def test_smolvlm2_backend_surface_imports_light() -> None:
    import media_studio.features.smolvlm2_backend as be

    assert be.RealSmolVlmBackend.__name__ == "RealSmolVlmBackend"
    assert "RealSmolVlmBackend" in be.__all__


def test_ocr_list_backend_surface_imports_light() -> None:
    import media_studio.features.ocr_list_backend as be

    assert be.RealOcrBackend.__name__ == "RealOcrBackend"
    assert "RealOcrBackend" in be.__all__
