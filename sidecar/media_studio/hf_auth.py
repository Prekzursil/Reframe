"""Hugging Face credential handling — because an EXPIRED token is worse than none.

``huggingface_hub`` reads ``HF_TOKEN`` (and three aliases) straight from the ambient
environment and attaches it to every request, with no opt-in from the caller. When that
token is expired the Hub answers **401** for a repo that downloads fine anonymously, and
renders that 401 as the deliberately vague *"Repository Not Found"* — so the user is told
the model does not exist when in fact their credential is stale.

MEASURED on the shipped app, 2026-08-08 (both-states, one variable):

    google/siglip2-so400m-patch16-384   WITH ambient token: HTTP 401   ANONYMOUS: HTTP 200
    teowu/DOVER                         WITH ambient token: HTTP 401   ANONYMOUS: HTTP 200

Both repos report ``gated=False, private=False``. The user's machine had an expired token
exported at User *and* Machine scope, so every Reframe process inherited it and two model
downloads failed during first-run provisioning with the Hub's misleading error.

The policy here: attempt with whatever ambient credential exists (a genuinely GATED repo
needs one), and on an auth refusal retry ONCE with ``token=False`` — huggingface_hub's
explicit "send no credential". If the anonymous retry also fails, the repo really is gated
or absent and THAT is the error worth showing, named precisely so the user knows which
variable to fix.

This lives in its own module rather than inside ``assets/manager.py`` because there are TWO
download call sites — the asset manager and ``features/parakeet_asr_backend.py`` — and
fixing only the one that happened to fail would leave the same defect live in the other
(AGENTS.md 9b: remediate the whole blast radius, not the first symptom).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from .util import get_logger

log = get_logger("media_studio.hf_auth")

#: Env vars huggingface_hub reads a token from, in the order it prefers them.
HF_TOKEN_ENV_VARS: tuple[str, ...] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HF_HUB_TOKEN",
)

#: Exception class names huggingface_hub raises when it is the CREDENTIAL that was
#: refused, not the repo that is missing. Matched by name so this module never has to
#: import huggingface_hub (it stays import-light; the hub import is a lazy seam).
_AUTH_EXC_NAMES = frozenset({"RepositoryNotFoundError", "GatedRepoError"})


def hf_token_env_var(env: Mapping[str, str] | None = None) -> str | None:
    """The NAME of the first HF-token env var that is set, or ``None``.

    Returns the NAME, never the value — this string reaches user-facing error text and a
    log line, and a token must never land in either.
    """
    environ = os.environ if env is None else env
    for name in HF_TOKEN_ENV_VARS:
        if (environ.get(name) or "").strip():
            return name
    return None


def is_hf_auth_failure(exc: BaseException) -> bool:
    """Whether ``exc`` is the Hub refusing our credential rather than lacking the repo."""
    if any(cls.__name__ in _AUTH_EXC_NAMES for cls in type(exc).__mro__):
        return True
    text = str(exc)
    return "401" in text or "403" in text


class HfAuthError(RuntimeError):
    """An HF fetch that failed WITH a token and still failed without one."""


def fetch_with_anonymous_retry(
    fetch: Callable[..., Any],
    *,
    repo_id: str,
    env: Mapping[str, str] | None = None,
    **kwargs: Any,
) -> Any:
    """Call ``fetch(**kwargs)``, retrying once WITHOUT a credential on an auth refusal.

    ``fetch`` is the huggingface_hub callable (``snapshot_download`` / ``hf_hub_download``),
    injected so this stays testable with no network and no hub import.

    Retries only when BOTH are true: an ambient token exists (so there is something to
    blame) and the failure looks like an auth refusal. A disk-full or connection-reset
    error is re-raised untouched — masking it behind a retry would be worse than the bug
    this fixes.

    ``repo_id`` is FORWARDED as well as used for the log line. It is a named parameter here
    so the message can name the repo, and a first draft therefore swallowed it — the wrapper
    called ``fetch(**kwargs)`` with no ``repo_id`` at all. The pre-existing
    ``test_default_hf_fetch_calls_snapshot_download`` caught that immediately, which is the
    argument for leaving such a test in place when refactoring under it.
    """
    call = {"repo_id": repo_id, **kwargs}
    try:
        return fetch(**call)
    except Exception as exc:
        var = hf_token_env_var(env)
        if var is None or not is_hf_auth_failure(exc):
            raise
        log.warning("hf: %s refused the credential in %s; retrying anonymously", repo_id, var)
        try:
            return fetch(**call, token=False)
        except Exception as anon_exc:
            raise HfAuthError(
                f"{repo_id}: the Hugging Face token in {var} is expired or invalid, and an "
                f"anonymous retry also failed — so this repo is gated or missing, not just "
                f"an auth problem. Unset {var} (or replace it with a valid token) and retry. "
                f"Anonymous error: {anon_exc}"
            ) from anon_exc
