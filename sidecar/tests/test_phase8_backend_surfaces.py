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


def test_lightasd_infer_surface_imports_light() -> None:
    # The Light-ASD inference helpers are ``# pragma: no cover`` (they need
    # torch / cv2 + real weights); the module SURFACE (imports, constants,
    # ``__all__``) imports light — cover it so the gate stays 100% without the
    # heavy stack (mirrors the Real*Backend surface-test convention).
    import media_studio.features._lightasd_infer as li

    assert callable(li.analyze_visual)
    assert "analyze_visual" in li.__all__
    assert li.ASD_FPS == 25
    assert li.AUDIO_SR == 16000


def test_lightasd_vendored_package_imports_light() -> None:
    # The vendored Light-ASD package __init__ is LIGHT (no torch/cv2); it carries
    # the upstream provenance + the weight basenames. The heavy model modules
    # (model / asd / s3fd) import torch at module top, so they are imported lazily
    # only inside analyze_visual and are NEVER imported here — we assert they SHIP
    # (importable spec) without executing them, so the coverage run never needs
    # torch (their statements are all ``# pragma: no cover``).
    import importlib.util

    import media_studio.features._lightasd as pkg

    assert pkg.LIGHT_ASD_LICENSE == "MIT"
    assert pkg.S3FD_WEIGHT_NAME == "sfd_face.pth"
    assert pkg.ASD_WEIGHT_NAME == "finetuning_TalkSet.model"
    assert len(pkg.LIGHT_ASD_COMMIT) == 40
    for mod in (
        "media_studio.features._lightasd.model",
        "media_studio.features._lightasd.asd",
        "media_studio.features._lightasd.s3fd",
        "media_studio.features._lightasd.s3fd.nets",
        "media_studio.features._lightasd.s3fd.box_utils",
    ):
        assert importlib.util.find_spec(mod) is not None


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
