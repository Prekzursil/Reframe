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
    # the upstream provenance + the weight basename. The heavy model modules
    # (model / asd) import torch at module top, so they are imported lazily only
    # inside analyze_visual and are NEVER imported here — we assert they SHIP
    # (importable spec) without executing them, so the coverage run never needs
    # torch (their statements are all ``# pragma: no cover``).
    # WU-L1: the no-license S3FD detector package (s3fd/*) + its S3FD_WEIGHT_NAME
    # were REMOVED — face detection is MIT YuNet via cv2.FaceDetectorYN now.
    import importlib.util
    import os

    import media_studio.features._lightasd as pkg

    assert pkg.LR_ASD_LICENSE == "MIT"
    assert not hasattr(pkg, "S3FD_WEIGHT_NAME")
    assert pkg.ASD_WEIGHT_NAME == "finetuning_TalkSet.model"
    assert len(pkg.LR_ASD_COMMIT) == 40
    assert "LR-ASD" in pkg.LR_ASD_UPSTREAM
    # ``find_spec`` on the LIGHT package + the top-level torch model modules locates
    # them WITHOUT executing them (it never imports the leaf), so no torch is needed.
    for mod in (
        "media_studio.features._lightasd.model",
        "media_studio.features._lightasd.asd",
    ):
        assert importlib.util.find_spec(mod) is not None
    # WU-L1: the removed S3FD detector package no longer ships.
    s3fd_dir = os.path.join(os.path.dirname(pkg.__file__), "s3fd")
    assert not os.path.isdir(s3fd_dir)


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


def test_saliency_backend_surface_imports_light() -> None:
    # WU B4: the RealViNetSaliencyBackend needs torch + the vendored ViNet-S arch +
    # the real weight (all loaded lazily inside its methods); the module SURFACE
    # (imports + constants + ``__all__``) imports light — cover it so the gate stays
    # 100% without ever touching torch (mirrors the Real*Backend convention).
    import media_studio.features.saliency_backend as be

    assert be.ViNetSaliencyBackend.__name__ == "ViNetSaliencyBackend"
    assert "ViNetSaliencyBackend" in be.__all__
    assert be._CLIP_LEN == 32
    assert (be._INPUT_H, be._INPUT_W) == (224, 384)


def test_vinet_s_vendored_package_imports_light() -> None:
    # WU B4: the vendored ViNet-S package __init__ is LIGHT (no torch); it carries
    # the upstream provenance + license + weight basename. The heavy model modules
    # (model / model_utils) import torch at module top, so they are NEVER imported
    # here — assert they SHIP on disk (filesystem check, no import) so the coverage
    # run never needs torch (their statements are all ``# pragma: no cover``).
    import os

    import media_studio.features._vinet_s as pkg

    assert pkg.VINET_S_LICENSE == "CC-BY-NC-SA-4.0"
    assert pkg.VINET_S_WEIGHT_NAME == "vinet-s-saliency.safetensors"
    assert "vinet_v2" in pkg.VINET_S_UPSTREAM
    assert pkg.VINET_S_PAPER == "arXiv:2502.00397"
    pkg_dir = os.path.dirname(pkg.__file__)
    for fname in ("model.py", "model_utils.py", "LICENSE"):
        assert os.path.isfile(os.path.join(pkg_dir, fname))


def test_transnetv2_vendored_package_imports_light() -> None:
    # WU B4: the vendored TransNetV2 package __init__ is LIGHT (no torch); the heavy
    # model module imports torch at module top and is NEVER imported here — assert it
    # SHIPS on disk (no import) so the coverage run never needs torch.
    import os

    import media_studio.features._transnetv2 as pkg

    assert pkg.TRANSNETV2_LICENSE == "MIT"
    assert pkg.TRANSNETV2_WEIGHT_NAME == "transnetv2.safetensors"
    assert "soCzech/TransNetV2" in pkg.TRANSNETV2_UPSTREAM
    pkg_dir = os.path.dirname(pkg.__file__)
    for fname in ("transnetv2_pytorch.py", "LICENSE"):
        assert os.path.isfile(os.path.join(pkg_dir, fname))
