"""Explicit OFFLINE MODE: a single enforced setting that forbids all network.

The contract (this group's feature 2): a user can flip ONE switch — the
``offline`` setting — that *forbids* every network path the app would otherwise
take (cloud LLM/translation, model downloads via ``assets.ensure``, edge-tts,
huggingface snapshots) and degrades them to a local/no-op behaviour with a
**typed, actionable refusal** rather than a silent failure or a hang.

Design (pure logic, dependency-free — no heavy-ML / network imports):

  * :func:`is_offline` reads the setting truthily. Two keys are honoured so the
    intent survives whichever name the UI/settings layer settled on: the
    explicit ``offline`` flag (this feature) is authoritative; absent that, an
    env override ``MEDIA_STUDIO_OFFLINE`` lets the supervisor force offline for
    a whole process (e.g. an air-gapped deployment) without touching settings.
  * :class:`OfflineError` is the typed refusal. It is an ``RpcError``
    (INVALID_PARAMS) so a handler that raises it surfaces a clean, user-readable
    message through the JSON-RPC error channel (or, inside a job body, the
    ``job.done`` error payload) — never a stack trace, never a socket timeout.
  * :func:`guard_network` is the one call every network-touching handler makes
    BEFORE it reaches the network: ``guard_network(settings, "downloading a
    model")`` raises :class:`OfflineError` when offline, naming the blocked
    operation and how to re-enable it. Off (online), it is a no-op.
  * :func:`enforce_offline_env` mutates a *copy* of an env mapping so a child
    process / lazy library that respects ``HF_HUB_OFFLINE`` /
    ``TRANSFORMERS_OFFLINE`` / ``NO_PROXY`` is hard-pinned offline too — defence
    in depth for the seams we cannot wrap with :func:`guard_network`.

CONTRACT-NOTE: §2 settings is an open object; the ``offline`` boolean extends it
exactly the way ``useCloud`` / ``ffmpegPath`` do. ``settings.set({offline:true})``
persists it via the existing store — no new persistence path is added.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from ..protocol import ErrorCode, RpcError
from ..util import get_logger

log = get_logger("media_studio.features.offline")

#: the authoritative settings key (this feature). Truthy -> offline.
SETTING_OFFLINE = "offline"
#: a process-wide env override (supervisor / air-gapped deploys). Truthy -> offline.
ENV_OFFLINE = "MEDIA_STUDIO_OFFLINE"

#: env vars set on a child/library env so offline-aware deps refuse the network
#: too (huggingface_hub + transformers both honour these "1" sentinels).
_OFFLINE_ENV: dict[str, str] = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
}

#: values that count as "truthy offline" for the env override (case-insensitive).
_TRUE = frozenset({"1", "true", "yes", "on"})


class OfflineError(RpcError):
    """Typed refusal raised when a network path is taken in offline mode.

    Subclasses :class:`RpcError` with INVALID_PARAMS so the message reaches the
    UI verbatim through the normal error channel (A6 lesson 3: failures must
    surface a FIX, not vanish or hang).
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, ErrorCode.INVALID_PARAMS)


def _truthy(value: Any) -> bool:
    """Truthiness for a flag that may be a bool, an int, or a string."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in _TRUE
    return bool(value)


def is_offline(
    settings: dict[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return True when offline mode is in force.

    Order: the explicit ``offline`` setting (authoritative) -> the
    ``MEDIA_STUDIO_OFFLINE`` env override. ``env`` is injectable so tests never
    touch ``os.environ``.
    """
    settings = settings or {}
    if SETTING_OFFLINE in settings:
        return _truthy(settings.get(SETTING_OFFLINE))
    env_map = env if env is not None else os.environ
    return _truthy(env_map.get(ENV_OFFLINE))


def guard_network(
    settings: dict[str, Any] | None = None,
    operation: str = "this network operation",
    *,
    env: Mapping[str, str] | None = None,
) -> None:
    """Raise :class:`OfflineError` when offline; no-op when online.

    Every handler that is about to touch the network calls this FIRST, naming
    the operation it is guarding so the refusal is actionable, e.g.::

        guard_network(settings, "downloading the Whisper model")

    -> "Offline mode is on — downloading the Whisper model needs the network.
        Turn off Offline mode in System Health to allow it."
    """
    if is_offline(settings, env=env):
        raise OfflineError(
            f"Offline mode is on — {operation} needs the network. Turn off Offline mode in System Health to allow it."
        )


def enforce_offline_env(
    base_env: Mapping[str, str] | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Return a COPY of ``base_env`` with the offline sentinels set when offline.

    Defence in depth for the seams :func:`guard_network` cannot wrap (a lazily
    imported library that goes to the network on its own): pass the result as a
    child process's ``env`` (or merge into ``os.environ`` before a lazy import)
    so huggingface_hub / transformers refuse to fetch. A no-op copy when online.
    """
    env = dict(base_env if base_env is not None else os.environ)
    if is_offline(settings, env=env):
        env.update(_OFFLINE_ENV)
    return env


__all__ = [
    "ENV_OFFLINE",
    "SETTING_OFFLINE",
    "OfflineError",
    "enforce_offline_env",
    "guard_network",
    "is_offline",
]
