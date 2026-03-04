from __future__ import absolute_import, annotations


def test_media_core_package_init_exports_all():
    import media_core

    if not hasattr(media_core, "__all__"):
        raise AssertionError("media_core must define __all__")
    if not isinstance(media_core.__all__, list):
        raise AssertionError("media_core.__all__ must be a list")
