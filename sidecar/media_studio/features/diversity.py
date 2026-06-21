"""Tier-0 selection diversity — DPP-MAP + MMR over candidate embeddings (pure NumPy).

The LLM selection pass (``select.py``) returns a ranked ``[Candidate]`` set that
often contains *near-duplicate* clips (the same beat phrased twice, two shots of
the same moment). This module re-ranks that set into a **diverse, near-dup-free**
subset using two classic, model-free algorithms:

* **DPP-MAP fast greedy** (Chen/Zhang/Zhou, NeurIPS 2018, arXiv 1709.05135) — a
  determinantal point process maximizes a balance of *quality* (the kernel
  diagonal) and *diversity* (off-diagonal similarity). Exact MAP is NP-hard;
  :func:`dpp_greedy_map` is the O(k·n²) incremental-Cholesky greedy approximation
  that adds, at each step, the item maximizing the marginal gain in
  ``log det(L_S)``.
* **MMR** (Carbonell & Goldstein, SIGIR 1998) — at each step pick the item
  maximizing ``lambda * relevance - (1 - lambda) * max_sim_to_selected``.

There is **NO heavy seam and zero downloads**: everything is pure ``numpy`` (which
IS in the venv). The "seam" is the *embeddings argument itself* — the caller
supplies the per-candidate feature vectors (from the WU4 SigLIP-2 ``novelty``
embeddings, or any fallback hash/feature vector). This module never loads a model.

Pure-logic, frozen-style, fully unit-testable with hand-built numpy arrays.
Mirrors the ``boundary.Candidate = dict[str, Any]`` shape so Wave-2 can wire it
into the ``select() -> diversity -> blend`` pipeline without reshaping anything.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

import numpy as np

from ..util import get_logger

log = get_logger("media_studio.diversity")

# A Candidate per §3 / boundary.py: a plain mapping with at least the §3 keys.
Candidate = dict[str, Any]

# Selection method discriminator (matches the design-spec signature).
Method = Literal["dpp", "mmr"]

# Numerical floor for the incremental-Cholesky update: a marginal gain at or below
# this is treated as "no diversity left to add" (near-linearly-dependent vector),
# so greedy DPP stops early rather than emit a numerically-degenerate pick.
_DPP_EPS: float = 1e-10
# L2-norm floor: a zero (or near-zero) embedding row cannot be normalized, so its
# cosine row/column is left as zeros (orthogonal-to-everything in cosine space).
_NORM_EPS: float = 1e-12


# --------------------------------------------------------------------------- #
# kernels (pure numpy)
# --------------------------------------------------------------------------- #
def cosine_kernel(embeddings: np.ndarray) -> np.ndarray:
    """L2-normalized Gram matrix (cosine-similarity kernel), PSD with unit diagonal.

    Each row of ``embeddings`` (shape ``(n, d)``) is L2-normalized, then the
    matrix is ``N @ N.T`` — a positive-semidefinite cosine-similarity kernel
    whose diagonal is 1.0 for every non-zero row (and 0.0 for an all-zero row,
    which has no direction to compare). Returns an ``(n, n)`` float64 array; an
    empty input returns an empty ``(0, 0)`` matrix.
    """
    mat = np.asarray(embeddings, dtype=np.float64)
    if mat.ndim != 2:
        raise ValueError(f"embeddings must be 2-D (n, d), got shape {mat.shape}")
    n = mat.shape[0]
    if n == 0:
        return np.zeros((0, 0), dtype=np.float64)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    # Avoid div-by-zero: a zero row stays zero (its cosine row/col is all zeros).
    safe = np.where(norms < _NORM_EPS, 1.0, norms)
    normed = mat / safe
    gram = normed @ normed.T
    # Numerical hygiene: cosine values live in [-1, 1]; clamp tiny FP overshoot.
    return np.clip(gram, -1.0, 1.0)


# --------------------------------------------------------------------------- #
# DPP-MAP fast greedy (incremental Cholesky, arXiv 1709.05135)
# --------------------------------------------------------------------------- #
def dpp_greedy_map(kernel: np.ndarray, k: int) -> list[int]:
    """Greedy MAP inference for a DPP with kernel ``L`` (Chen et al. 2018).

    Returns up to ``k`` item indices that approximately maximize ``log det(L_S)``
    — a set that is simultaneously high-quality (large diagonal) and diverse
    (low pairwise similarity). The incremental-Cholesky update keeps each
    marginal-gain step O(n) after an O(n²) bookkeeping pass, i.e. O(k·n²) total.

    ``k`` is clamped to ``[0, n]``; ``k <= 0`` (or an empty kernel) returns an
    empty list. The loop stops early when the best remaining marginal gain falls
    to ``_DPP_EPS`` (every remaining item is ~linearly dependent on the chosen
    set — adding it would not increase diversity).
    """
    mat = np.asarray(kernel, dtype=np.float64)
    if mat.ndim != 2 or mat.shape[0] != mat.shape[1]:
        raise ValueError(f"kernel must be square (n, n), got shape {mat.shape}")
    n = mat.shape[0]
    budget = min(max(int(k), 0), n)
    if budget == 0:
        return []

    # cis[j] holds the current Cholesky row for item j; di2[j] its marginal gain
    # d_j^2 = L_jj - || c_j ||^2 (Algorithm 1 of the paper).
    cis = np.zeros((budget, n), dtype=np.float64)
    di2 = np.diagonal(mat).astype(np.float64).copy()
    selected: list[int] = []
    # First pick = the largest-quality item (max diagonal).
    best = int(np.argmax(di2))
    selected.append(best)

    for step in range(1, budget):
        prev = selected[-1]
        d_prev = di2[prev]
        if d_prev <= _DPP_EPS:
            break  # the chosen item already carries no gain -> set is saturated
        # Update every candidate's marginal gain given the newly-chosen ``prev``.
        sqrt_d = np.sqrt(d_prev)
        # e_i = (L_{prev,i} - <c_prev, c_i>) / sqrt(d_prev)
        eis = (mat[prev, :] - cis[:step, prev] @ cis[:step, :]) / sqrt_d
        cis[step, :] = eis
        di2 = di2 - np.square(eis)
        # Never re-pick an already-selected item.
        di2[selected] = -np.inf
        cand = int(np.argmax(di2))
        if di2[cand] <= _DPP_EPS:
            break  # no remaining item adds diversity
        selected.append(cand)

    return selected


# --------------------------------------------------------------------------- #
# MMR (Carbonell & Goldstein, SIGIR 1998)
# --------------------------------------------------------------------------- #
def mmr_select(
    relevance: Sequence[float],
    similarity: np.ndarray,
    k: int,
    lambda_: float = 0.7,
) -> list[int]:
    """Maximal Marginal Relevance selection (Carbonell & Goldstein 1998).

    Greedily picks, at each step, the item maximizing
    ``lambda_ * relevance[i] - (1 - lambda_) * max_{j in selected} sim(i, j)``.

    * ``relevance`` — per-item relevance scores (length ``n``).
    * ``similarity`` — an ``(n, n)`` pairwise-similarity matrix (e.g.
      :func:`cosine_kernel`).
    * ``lambda_`` — diversity/relevance trade-off, clamped to ``[0, 1]``: ``1.0``
      is pure relevance (no diversity penalty), ``0.0`` is pure diversity.

    The first pick (empty selected set, no similarity term) is the most-relevant
    item. ``k`` is clamped to ``[0, n]``.
    """
    rel = np.asarray(relevance, dtype=np.float64).ravel()
    sim = np.asarray(similarity, dtype=np.float64)
    n = rel.shape[0]
    if sim.shape != (n, n):
        raise ValueError(f"similarity must be ({n}, {n}) to match relevance, got {sim.shape}")
    budget = min(max(int(k), 0), n)
    if budget == 0:
        return []
    lam = float(np.clip(lambda_, 0.0, 1.0))

    selected: list[int] = []
    remaining = list(range(n))
    # Running max similarity of each item to the selected set (none selected yet).
    max_sim = np.full(n, -np.inf, dtype=np.float64)

    for _ in range(budget):
        best_idx = -1
        best_score = -np.inf
        for i in remaining:
            penalty = 0.0 if max_sim[i] == -np.inf else max_sim[i]
            score = lam * rel[i] - (1.0 - lam) * penalty
            if score > best_score:
                best_score = score
                best_idx = i
        selected.append(best_idx)
        remaining.remove(best_idx)
        # Fold the new pick into every remaining item's running max similarity.
        max_sim = np.maximum(max_sim, sim[best_idx, :])

    return selected


# --------------------------------------------------------------------------- #
# candidate-shape facade
# --------------------------------------------------------------------------- #
def dedupe_candidates(
    candidates: list[Candidate],
    embeddings: np.ndarray,
    *,
    method: Method = "mmr",
    k: int | None = None,
    lambda_: float = 0.7,
) -> list[Candidate]:
    """Re-rank ``candidates`` into a diverse, near-dup-free subset.

    ``embeddings`` is the per-candidate feature matrix (shape ``(n, d)``, one row
    per candidate, caller-supplied — the WU4 ``novelty`` embeddings or any
    fallback). The two candidates whose embeddings are near-identical are treated
    as duplicates and only one survives.

    * ``method='mmr'`` (default) uses :func:`mmr_select` with each candidate's
      ``score`` (default 0.0 when absent) as relevance.
    * ``method='dpp'`` uses :func:`dpp_greedy_map` over a quality-scaled cosine
      kernel ``L = diag(q) @ S @ diag(q)`` where ``q`` is the per-candidate
      relevance (so the DPP balances that quality against diversity).

    ``k`` is the target subset size (default = keep all, deduped); it is clamped
    to ``[0, n]``. Returns the chosen candidates **in selection order** (the
    diversity ranking), with their original dict identity preserved. An empty
    input (or empty embeddings) returns an empty list.
    """
    n = len(candidates)
    if n == 0:
        return []
    mat = np.asarray(embeddings, dtype=np.float64)
    if mat.ndim != 2 or mat.shape[0] != n:
        raise ValueError(f"embeddings must be (n={n}, d), got shape {mat.shape}")

    budget = n if k is None else min(max(int(k), 0), n)
    if budget == 0:
        return []

    similarity = cosine_kernel(mat)
    relevance = [float(c.get("score", 0.0)) for c in candidates]

    if method == "mmr":
        order = mmr_select(relevance, similarity, budget, lambda_=lambda_)
    elif method == "dpp":
        # Quality-scale the cosine kernel so the DPP trades quality vs diversity.
        # Shift relevance to be strictly positive so the diagonal stays > 0
        # (an all-equal/zero relevance collapses to a pure-diversity kernel).
        q = np.asarray(relevance, dtype=np.float64)
        q = q - q.min() + 1.0
        kernel = (q[:, None] * similarity) * q[None, :]
        order = dpp_greedy_map(kernel, budget)
    else:  # pragma: no cover - Method is a closed Literal; defensive guard only
        raise ValueError(f"unknown method {method!r} (expected 'dpp' or 'mmr')")

    log.info("dedupe_candidates: method=%s n=%d -> kept=%d", method, n, len(order))
    return [candidates[i] for i in order]


__all__ = [
    "Candidate",
    "Method",
    "cosine_kernel",
    "dedupe_candidates",
    "dpp_greedy_map",
    "mmr_select",
]
