from __future__ import annotations


def test_media_core_package_init_exports_all():
    import media_core

    assert hasattr(media_core, "__all__")
    assert isinstance(media_core.__all__, list)
