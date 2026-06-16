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


def test_vlm_backbone_backend_surface_imports_light() -> None:
    import media_studio.features.vlm_backbone_backend as be

    assert be.RealBackboneBackend.__name__ == "RealBackboneBackend"
    assert "RealBackboneBackend" in be.__all__
