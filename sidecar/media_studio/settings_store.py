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

from .models import budget as _budget
from .models.secrets import redact, redact_keys
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
    # Provider Hub (WU-keys): the user-supplied rotation pool. Each entry is
    # {id, provider, kind, baseUrl, model, apiKeys[], enabled, capabilities[],
    # unit}. apiKeys are stored RAW in the per-user config file (never a project
    # folder) but SettingsStore.get() redacts them to last-4 before they cross
    # RPC — only SettingsStore.get_raw() (the factory path, never registered)
    # returns the live keys.
    "providers": [],
    # Per-data-type consent (WU-keys / SE1): TEXT (transcripts) and FRAMES
    # (vision) are SEPARATE, independently-revocable opt-ins per provider.
    # consent.perProvider[<provider>] = {"text": bool, "frames": bool}.
    "consent": {"perProvider": {}},
    # WU-budget pre-flight gate (PLAN §WU-budget): when True, a cloud run that
    # WOULD egress must be acknowledged via ai.planJob first (the renderer shows
    # the cost/egress budget and the user confirms). Default True = safe-by-
    # default; the user opts out of the per-run confirmation explicitly.
    "confirmCloudBudget": True,
    # WU-budget default target-job-size (PLAN P1 #6, promoted to acceptance): the
    # number of discrete outputs an unsized job produces, used by the budget
    # estimate when the request pins no size. Mirrors budget.DEFAULT_TARGET_JOB_SIZE;
    # a DOCUMENTED placeholder until the user pins N (one 60-min source -> N shorts).
    "defaultTargetJobSize": _budget.DEFAULT_TARGET_JOB_SIZE,
    # WU-spend-cap: persisted monthly cumulative spend ceiling (single-user; no org
    # dimension). The per-run budget gate only sizes ONE run; these caps bound the
    # MONTH-TO-DATE total accumulated across many approved cloud-AI runs (recorded
    # in the spend_ledger at job completion). All three default OFF/0 so the cap is
    # backward-compatible: an existing install caps nothing until the user opts in.
    #   * monthlySoftLimitCents: when month-to-date + this job's estimate exceeds
    #     this, the plan/envelope carries a non-blocking soft WARNING (UI nudge).
    #   * monthlyHardLimitCents: the ceiling the hard gate enforces (cents).
    #   * enforceMonthlyHardLimit: master switch; only when True does an over-cap
    #     cloud run get REFUSED before egress. 0 caps + False = no enforcement.
    "monthlySoftLimitCents": 0,
    "monthlyHardLimitCents": 0,
    "enforceMonthlyHardLimit": False,
    # Provider Hub presets + per-function routing (WU-presets / PH3). ``routing``
    # holds the resolved per-function provider choice; each function's seam prefers
    # its configured provider (pool fallback). ``perFunction[<fn>]`` is a
    # {provider, fallback[]} slot (provider is a catalog model-id or the LOCAL
    # sentinel). ``activePreset`` is the last applied smart preset name.
    "routing": {"perFunction": {}},
    "activePreset": "",
    # WU-presets first-run local-vs-cloud chooser (PLAN P1 #6): False until the
    # user picks; while False the routing default is privacy/all-local (no egress).
    "firstRunChoiceMade": False,
    # ---- UX / QoL bundle (WU-0): additive foundation keys ------------------
    # The renderer's last-opened source video, restored on launch (WU-13). Empty
    # until the user opens a video; the restore path tolerates a stale/deleted id.
    "lastOpenedVideoId": "",
    # Workspace autosave (WU-11/§autosave): the renderer debounces ``project.save``
    # while ``enabled``. Pure config — no sidecar behavior beyond this default key.
    "autosave": {"enabled": True, "debounceMs": 1500},
    # Export defaults (WU-11): the pre-selected subtitle/NLE formats + fps the
    # export UI offers first. ``subtitleFormat`` in {srt,vtt,...}; ``nleFormat`` in
    # {edl,fcpxml,...}; ``nleFps`` the timeline frame rate. Pure data.
    "exportDefaults": {"subtitleFormat": "srt", "nleFormat": "edl", "nleFps": 30},
    # Saved export/pipeline presets (WU-10/WU-11): ``presets`` is a name->preset
    # map; ``active`` is the last-applied preset name. NOTE: ``settings.set`` is a
    # SHALLOW top-level merge — writing ``savePresets`` REPLACES the whole block,
    # so WU-10/WU-11 must read-modify-write the full block to preserve ``presets``.
    "savePresets": {"presets": {}, "active": ""},
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
        """Return the REDACTED §2 settings object (defaults backfilled).

        This is the RPC-facing view: ``settings.providers[].apiKeys`` AND the
        legacy single-cloud ``cloudApiKey`` are redacted to last-4 via
        :func:`secrets.redact` / :func:`secrets.redact_keys` so NO full key ever
        crosses the RPC boundary (PLAN §WU-keys security invariant). The
        provider/translator FACTORY path must call :meth:`get_raw` instead — it is
        the ONLY accessor that returns the live ``cloudApiKey`` (and pool keys),
        and it is never registered over RPC. An empty/absent ``cloudApiKey`` is
        left as-is so the UI does not imply a key exists when none is set.
        """
        merged = self.get_raw()
        providers = merged.get("providers")
        if isinstance(providers, list):
            merged["providers"] = redact_keys(providers)
        cloud_key = merged.get("cloudApiKey")
        if isinstance(cloud_key, str) and cloud_key:
            merged["cloudApiKey"] = redact(cloud_key)
        return merged

    def get_raw(self) -> dict[str, Any]:
        """Return the full §2 settings object with RAW (unredacted) keys.

        NEVER exposed over RPC — this is the provider/translator FACTORY path
        ONLY (PLAN §WU-keys: ``get_provider``, ``TieredTranslator._hosted_provider``,
        the ``RotatingProvider`` pool build, and the handler ``__init__`` /
        ``_get_translator`` construction all consume RAW keys via this accessor).
        Every settings read that crosses RPC must use :meth:`get` instead.
        """
        merged = dict(DEFAULT_SETTINGS)
        merged.update(self._read())
        return merged

    @staticmethod
    def _restore_one(incoming: Any, stored: Any) -> Any:
        """Swap a redacted ``incoming`` value back to the RAW ``stored`` key.

        Returns ``stored`` only when ``incoming`` is exactly the :func:`redact`
        form of a non-empty stored RAW key (a redacted get -> set round-trip);
        otherwise ``incoming`` is a genuinely new value and is returned as-is.
        """
        if isinstance(incoming, str) and isinstance(stored, str) and stored and incoming == redact(stored):
            return stored
        return incoming

    @staticmethod
    def _stored_provider_keys(current: dict[str, Any]) -> dict[str, list[Any]]:
        """Map each stored provider ``id`` -> its RAW ``apiKeys`` list (for restore)."""
        raw_providers = current.get("providers")
        items = raw_providers if isinstance(raw_providers, list) else []
        out: dict[str, list[Any]] = {}
        for raw in items:
            pid = raw.get("id") if isinstance(raw, dict) else None
            keys = raw.get("apiKeys") if isinstance(raw, dict) else None
            if isinstance(pid, str) and isinstance(keys, list):
                out[pid] = keys
        return out

    def _restore_provider(self, prov: Any, stored_by_id: dict[str, list[Any]]) -> Any:
        """Restore each redacted ``apiKeys`` entry of ``prov`` to its stored RAW key.

        Matching is by provider ``id`` then positional index: an incoming key that
        equals the redaction of the same-index stored key is swapped back to RAW;
        a new/changed key (or a key with no stored counterpart) is left untouched.
        """
        if not isinstance(prov, dict):
            return prov
        pid = prov.get("id")
        keys = prov.get("apiKeys")
        stored = stored_by_id.get(pid) if isinstance(pid, str) else None
        if not isinstance(keys, list) or stored is None:
            return prov
        restored = [self._restore_one(k, stored[i]) if i < len(stored) else k for i, k in enumerate(keys)]
        return {**prov, "apiKeys": restored}

    def _restore_redacted_keys(self, values: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
        """Return ``values`` with redacted-placeholder secrets restored to RAW.

        The RPC-facing :meth:`get` returns keys redacted to last-4. A UI that reads
        settings and writes the whole block back would otherwise PERSIST the
        redacted placeholder over the live key, silently destroying it. Every
        incoming ``cloudApiKey`` / ``providers[].apiKeys`` value that is exactly the
        redaction of the stored RAW key is swapped back so a get -> set round-trip
        is a no-op on secrets; genuinely new keys are written as given.
        """
        restored = dict(values)
        if "cloudApiKey" in restored:
            restored["cloudApiKey"] = self._restore_one(restored["cloudApiKey"], current.get("cloudApiKey"))
        providers = restored.get("providers")
        if isinstance(providers, list):
            stored_by_id = self._stored_provider_keys(current)
            restored["providers"] = [self._restore_provider(p, stored_by_id) for p in providers]
        return restored

    def set(self, values: dict[str, Any]) -> dict[str, Any]:
        """Merge ``values`` over the stored settings, persist, and return the result.

        Only the keys present in ``values`` are updated (a partial update); the
        rest of the stored settings are preserved. Returns the full merged object
        so the caller (and the UI) always sees the complete current state.

        A redacted secret in ``values`` (the last-4 placeholder :meth:`get`
        returns) is restored to the stored RAW key before persisting, so a
        get -> set round-trip never overwrites a live key with its placeholder.
        """
        if not isinstance(values, dict):
            raise ValueError("settings.set expects an object of values")
        current = dict(self._read())
        current.update(self._restore_redacted_keys(values, current))
        self._write(current)
        # The on-disk store keeps RAW keys (the factory reads them via get_raw);
        # the RPC-facing return MUST be redacted exactly like get() so the
        # round-tripped settings.set response never echoes a full key (WU-keys).
        return self.get()
