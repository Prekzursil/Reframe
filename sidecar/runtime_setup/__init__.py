"""First-run runtime setup for the packaged app (CONTRACTS.md A7 / T5).

``bootstrap.py`` is run BY FILE PATH with the shipped embeddable CPython:

    <resources>/python/python.exe <resources>/sidecar/runtime_setup/bootstrap.py

It installs the heavy sidecar wheels into ``%APPDATA%/media-studio/envs/``,
activates them for the embeddable interpreter (``python312._pth``), then
delegates model/tool downloads to the U4 asset manager.
"""
