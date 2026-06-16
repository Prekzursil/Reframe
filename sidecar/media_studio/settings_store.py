"""Persistent settings store for the sidecar (CONTRACTS.md §2 ``settings.*``).

The §2 settings object is ``{useCloud:bool, cloudApiKey?, modelsDir, ffmpegPath,
...}``. ``settings.get`` returns it; ``settings.set`` merges a partial update into
it and persists. The store is a single JSON document in a **per-user config dir**
(never inside a project folder — §0/§6 keep the key out of portable projects).

Pure logic + filesystem I/O: no heavy-ML imports. The config directory is
resolved with stdlib only (``%APPDATA%`` on Windows, ``$XDG_CONFIG_HOME``/``~``
elsewhere) and is overridable via the constructor so tests point it at a tmp dir.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .util import get_logger

log = get_logger("media_studio.settings")

# CONTRACT-NOTE: §2 names {useCloud, cloudApiKey?, modelsDir, ffmpegPath}. These
# defaults are the lean baseline the UI reads on first launch (App.tsx reads
# useCloud). cloudApiKey is intentionally absent until the user sets one; we never
# write a key into a project folder (it lives only in the per-user config file).
#
# P4 §8d / C12: the brand-kit keys are free-form (settings.set blindly merges any
# values), but we list them here for discoverability so the UI sees them on first
# launch. They are pure data — there is intentionally NO ``outputDir`` HERE: the
# user-facing "output/data folder" is the relocatable DATA ROOT, set via the
# ``MEDIA_STUDIO_CONFIG_DIR`` env override (or the Electron ``data-dir.txt`` marker
# the app writes, which the supervisor turns into that env var on launch). Every
# data path — including exports — derives from ``default_config_dir()`` below, so
# relocating the data root moves exports too; exports still live at
# ``<data root>/exports`` (``Services.exports_dir``). No per-key redirection is
# added — one root relocates everything.
DEFAULT_SETTINGS: dict[str, Any] = {
    "useCloud": False,
    "modelsDir": "",
    "ffmpegPath": "",
    # Brand kit (P4 §8d): a logo watermark + default caption template/font.
    "brandLogoPath": "",
    "brandCaptionTemplate": "",
    "brandFontFamily": "",
}

# The config file name inside the resolved app config directory.
_CONFIG_FILENAME = "settings.json"
# The per-user config subdirectory for this app.
_APP_DIR_NAME = "media-studio"


def default_config_dir() -> Path:
    """Resolve the per-user config directory for media-studio (stdlib only).

    Order: ``MEDIA_STUDIO_CONFIG_DIR`` env override -> ``%APPDATA%`` on Windows ->
    ``$XDG_CONFIG_HOME`` -> ``~/.config``. The directory is NOT created here; the
    store creates it lazily on first write.
    """
    override = os.environ.get("MEDIA_STUDIO_CONFIG_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return Path(base) / _APP_DIR_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path(os.path.expanduser("~")) / ".config"
    return base / _APP_DIR_NAME


class SettingsStore:
    """A JSON-backed settings document in the per-user config directory.

    ``get`` returns the full §2 settings object (defaults backfilled). ``set``
    merges a partial dict over the current settings and persists atomically.
    """

    def __init__(self, config_path: str | os.PathLike | None = None) -> None:
        self.config_path = Path(config_path) if config_path is not None else default_config_dir() / _CONFIG_FILENAME

    # ---- I/O ---------------------------------------------------------------
    def _read(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            # CONTRACT-NOTE: a corrupt/unreadable settings file must not brick the
            # app; fall back to defaults rather than crashing the sidecar.
            log.warning("settings file unreadable (%s); using defaults", exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        """Atomically persist ``data`` (temp file + os.replace)."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_name(self.config_path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.config_path)

    # ---- public surface (matches settings.* methods) ----------------------
    def get(self) -> dict[str, Any]:
        """Return the full §2 settings object (defaults backfilled)."""
        merged = dict(DEFAULT_SETTINGS)
        merged.update(self._read())
        return merged

    def set(self, values: dict[str, Any]) -> dict[str, Any]:
        """Merge ``values`` over the stored settings, persist, and return the result.

        Only the keys present in ``values`` are updated (a partial update); the
        rest of the stored settings are preserved. Returns the full merged object
        so the caller (and the UI) always sees the complete current state.
        """
        if not isinstance(values, dict):
            raise ValueError("settings.set expects an object of values")
        current = dict(self._read())
        current.update(values)
        self._write(current)
        merged = dict(DEFAULT_SETTINGS)
        merged.update(current)
        return merged
