"""Real LightGBM LambdaMART backend for the learned re-ranker (LAZY-imported).

Imported ONLY inside ``ranker._default_ranker_factory`` at run-time — never at
package import, never by the tests (which inject a fake
:class:`~media_studio.features.ranker.RankerBackend`). It is therefore the one
place allowed to import ``lightgbm``, and that import lives inside the methods so
even importing THIS module stays light.

:class:`LgbmRankerBackend` wraps ``lightgbm.LGBMRanker(objective='lambdarank')``
trained on the local ``feedback.jsonl`` flywheel (manifest row #14: lightgbm
4.6.0, MIT, ~1-3 MB, CPU, zero model download). Coverage of this module is
excluded (it requires the native ``lightgbm`` stack absent from the test venv);
the pure feature/training/rerank logic it serves is covered exhaustively in
``test_ranker.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..util import get_logger
from .ranker import FeatureVector

log = get_logger("media_studio.features.ranker_backend")

#: Default LGBMRanker hyper-parameters — small, CPU, LambdaMART (manifest #14).
DEFAULT_PARAMS: dict[str, Any] = {
    "objective": "lambdarank",
    "n_estimators": 200,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_child_samples": 5,
    "n_jobs": -1,
    "verbose": -1,
}


class LgbmRankerBackend:  # pragma: no cover - requires the native lightgbm stack
    """LambdaMART ranker over the feedback flywheel (lazy ``lightgbm`` import).

    Constructed lazily per training run (``settings`` may override params). The
    model is built on first :meth:`fit` so an import failure surfaces to
    ``ranker.train_ranker`` as the graceful-fallback signal (it swallows the
    exception and returns ``None``).
    """

    def __init__(self, settings: Mapping[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._model: Any = None

    def _params(self) -> dict[str, Any]:
        params = dict(DEFAULT_PARAMS)
        override = self._settings.get("rankerParams")
        if isinstance(override, Mapping):
            params.update(override)
        return params

    def fit(self, x: Sequence[FeatureVector], y: Sequence[int], groups: Sequence[int]) -> None:
        """Train ``LGBMRanker`` on feature rows, labels, and query groups."""
        from lightgbm import LGBMRanker  # type: ignore[import-not-found]  # noqa: PLC0415 - heavy seam, runtime only

        self._model = LGBMRanker(**self._params())
        self._model.fit(list(x), list(y), group=list(groups))
        log.info("lgbm ranker trained on %d rows / %d groups", len(x), len(groups))

    def predict(self, x: Sequence[FeatureVector]) -> list[float]:
        """Score each feature row (raise if called before :meth:`fit`)."""
        if self._model is None:
            raise RuntimeError("LgbmRankerBackend.predict called before fit")
        return [float(score) for score in self._model.predict(list(x))]


__all__ = ["DEFAULT_PARAMS", "LgbmRankerBackend"]
