"""Tests for media_studio.features.diversity (pure NumPy DPP-MAP + MMR).

Heavy-ML-free by construction: this module has NO heavy dependency — its "seam"
is the embeddings argument. Every test uses hand-built numpy arrays so the
numeric assertions are exact. 100% line + branch coverage.
"""

from __future__ import annotations

import numpy as np
import pytest
from media_studio.features import diversity
from media_studio.features.diversity import (
    cosine_kernel,
    dedupe_candidates,
    dpp_greedy_map,
    mmr_select,
)


# --------------------------------------------------------------------------- #
# cosine_kernel
# --------------------------------------------------------------------------- #
def test_cosine_kernel_psd_unit_diagonal() -> None:
    emb = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    k = cosine_kernel(emb)
    assert k.shape == (3, 3)
    # Unit diagonal for every non-zero row.
    assert np.allclose(np.diag(k), 1.0)
    # Symmetric.
    assert np.allclose(k, k.T)
    # Orthogonal rows -> 0 similarity; the 45-degree row -> 1/sqrt(2).
    assert k[0, 1] == pytest.approx(0.0)
    assert k[0, 2] == pytest.approx(1.0 / np.sqrt(2.0))
    # PSD: all eigenvalues >= 0 (within FP tolerance).
    assert np.min(np.linalg.eigvalsh(k)) >= -1e-9


def test_cosine_kernel_near_identical_rows_have_similarity_one() -> None:
    emb = np.array([[2.0, 0.0], [4.0, 0.0], [0.0, 5.0]])  # rows 0,1 same direction
    k = cosine_kernel(emb)
    assert k[0, 1] == pytest.approx(1.0)
    assert k[0, 2] == pytest.approx(0.0)


def test_cosine_kernel_zero_row_stays_zero() -> None:
    # The all-zero row exercises the div-by-zero guard: its row/col is all zeros,
    # including the diagonal (no direction to compare to itself).
    emb = np.array([[0.0, 0.0], [1.0, 0.0]])
    k = cosine_kernel(emb)
    assert np.allclose(k[0, :], 0.0)
    assert k[0, 0] == pytest.approx(0.0)
    assert k[1, 1] == pytest.approx(1.0)


def test_cosine_kernel_empty_returns_empty() -> None:
    k = cosine_kernel(np.zeros((0, 4)))
    assert k.shape == (0, 0)


def test_cosine_kernel_rejects_non_2d() -> None:
    with pytest.raises(ValueError, match="2-D"):
        cosine_kernel(np.array([1.0, 2.0, 3.0]))


# --------------------------------------------------------------------------- #
# dpp_greedy_map
# --------------------------------------------------------------------------- #
def test_dpp_drops_near_duplicate_picks_orthogonal_pair() -> None:
    # rows 0 and 1 near-identical, row 2 orthogonal.
    emb = np.array([[1.0, 0.0], [1.0, 0.001], [0.0, 1.0]])
    kernel = cosine_kernel(emb)
    chosen = dpp_greedy_map(kernel, k=2)
    assert len(chosen) == 2
    # Must include the orthogonal item; must NOT keep both near-dups.
    assert 2 in chosen
    assert not ({0, 1} <= set(chosen))


def test_dpp_first_pick_is_largest_diagonal() -> None:
    kernel = np.array([[0.5, 0.0, 0.0], [0.0, 0.9, 0.0], [0.0, 0.0, 0.2]])
    chosen = dpp_greedy_map(kernel, k=1)
    assert chosen == [1]  # diagonal 0.9 is the largest quality


def test_dpp_k_clamped_above_n() -> None:
    kernel = np.eye(3)
    chosen = dpp_greedy_map(kernel, k=10)
    # Identity kernel: every item is orthogonal -> all 3 selectable.
    assert sorted(chosen) == [0, 1, 2]


def test_dpp_k_zero_and_negative_return_empty() -> None:
    kernel = np.eye(3)
    assert dpp_greedy_map(kernel, k=0) == []
    assert dpp_greedy_map(kernel, k=-5) == []


def test_dpp_empty_kernel_returns_empty() -> None:
    assert dpp_greedy_map(np.zeros((0, 0)), k=3) == []


def test_dpp_rejects_non_square() -> None:
    with pytest.raises(ValueError, match="square"):
        dpp_greedy_map(np.zeros((2, 3)), k=1)


def test_dpp_early_stop_on_saturated_set() -> None:
    # Two IDENTICAL directions: after picking one, the second adds ~zero
    # diversity -> greedy stops early before reaching k. This drives the
    # ``di2[cand] <= _DPP_EPS`` break branch.
    emb = np.array([[1.0, 0.0], [1.0, 0.0]])
    kernel = cosine_kernel(emb)
    chosen = dpp_greedy_map(kernel, k=2)
    assert len(chosen) == 1


def test_dpp_break_when_chosen_item_has_no_gain() -> None:
    # A zero-diagonal kernel makes the FIRST pick carry d_prev == 0, driving the
    # ``d_prev <= _DPP_EPS`` break at the top of the loop on step 1.
    kernel = np.zeros((3, 3))
    chosen = dpp_greedy_map(kernel, k=3)
    assert len(chosen) == 1  # only the (zero-quality) first pick, then break


# --------------------------------------------------------------------------- #
# mmr_select
# --------------------------------------------------------------------------- #
def test_mmr_first_pick_is_most_relevant() -> None:
    sim = np.eye(3)
    chosen = mmr_select([0.1, 0.9, 0.4], sim, k=1)
    assert chosen == [1]


def test_mmr_drops_near_duplicate() -> None:
    # Items 0,1 near-identical; item 2 orthogonal. Equal relevance so diversity
    # decides: after picking 0, item 1 is penalized, item 2 is not.
    emb = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    sim = cosine_kernel(emb)
    chosen = mmr_select([0.5, 0.5, 0.5], sim, k=2, lambda_=0.5)
    assert chosen[0] in (0, 1)
    assert chosen[1] == 2


def test_mmr_lambda_one_is_pure_relevance() -> None:
    # lambda=1 ignores diversity entirely -> ranks by relevance alone.
    emb = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    sim = cosine_kernel(emb)
    chosen = mmr_select([0.9, 0.8, 0.1], sim, k=3, lambda_=1.0)
    assert chosen == [0, 1, 2]


def test_mmr_lambda_zero_is_pure_diversity() -> None:
    # lambda=0 ignores relevance -> only the similarity penalty matters. After
    # the (tie-broken-first) pick, the most-dissimilar item wins.
    emb = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    sim = cosine_kernel(emb)
    chosen = mmr_select([0.9, 0.8, 0.1], sim, k=2, lambda_=0.0)
    # First pick: all scores equal (0) -> index 0 wins the > comparison.
    assert chosen[0] == 0
    # Second pick: item 2 (orthogonal) has zero penalty vs item 1's penalty 1.0.
    assert chosen[1] == 2


def test_mmr_lambda_clamped_out_of_range() -> None:
    sim = np.eye(2)
    # lambda > 1 clamps to 1.0; lambda < 0 clamps to 0.0. Both must not raise.
    assert mmr_select([0.2, 0.8], sim, k=1, lambda_=5.0) == [1]
    assert mmr_select([0.2, 0.8], sim, k=2, lambda_=-3.0) in ([0, 1], [1, 0])


def test_mmr_k_zero_returns_empty() -> None:
    assert mmr_select([0.1, 0.2], np.eye(2), k=0) == []


def test_mmr_k_clamped_above_n() -> None:
    chosen = mmr_select([0.1, 0.2, 0.3], np.eye(3), k=99)
    assert sorted(chosen) == [0, 1, 2]


def test_mmr_rejects_mismatched_similarity_shape() -> None:
    with pytest.raises(ValueError, match="similarity must be"):
        mmr_select([0.1, 0.2, 0.3], np.eye(2), k=1)


# --------------------------------------------------------------------------- #
# dedupe_candidates (the candidate-shape facade)
# --------------------------------------------------------------------------- #
def _cand(rank: int, score: float) -> diversity.Candidate:
    return {"rank": rank, "start": 0.0, "end": 1.0, "score": score}


def test_dedupe_empty_candidates_returns_empty() -> None:
    assert dedupe_candidates([], np.zeros((0, 3))) == []


def test_dedupe_mmr_drops_near_dup_preserves_identity() -> None:
    cands = [_cand(1, 0.9), _cand(2, 0.8), _cand(3, 0.5)]
    emb = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])  # 0,1 dup; 2 distinct
    kept = dedupe_candidates(cands, emb, method="mmr", k=2, lambda_=0.5)
    assert len(kept) == 2
    # The distinct candidate (rank 3) survives; the dict identity is preserved.
    ranks = {c["rank"] for c in kept}
    assert 3 in ranks
    assert kept[1] is cands[2]


def test_dedupe_dpp_drops_near_dup() -> None:
    cands = [_cand(1, 0.9), _cand(2, 0.85), _cand(3, 0.4)]
    emb = np.array([[1.0, 0.0], [1.0, 0.001], [0.0, 1.0]])
    kept = dedupe_candidates(cands, emb, method="dpp", k=2)
    ranks = {c["rank"] for c in kept}
    assert 3 in ranks
    assert not ({1, 2} <= ranks)


def test_dedupe_default_k_keeps_all_deduped() -> None:
    cands = [_cand(1, 0.5), _cand(2, 0.5)]
    emb = np.array([[1.0, 0.0], [0.0, 1.0]])  # distinct -> both kept
    kept = dedupe_candidates(cands, emb)  # default k=None, method='mmr'
    assert len(kept) == 2


def test_dedupe_default_score_when_missing() -> None:
    # Candidates with no 'score' key -> relevance defaults to 0.0 (no KeyError).
    cands = [{"rank": 1}, {"rank": 2}]
    emb = np.array([[1.0, 0.0], [0.0, 1.0]])
    kept = dedupe_candidates(cands, emb, method="mmr")
    assert len(kept) == 2


def test_dedupe_k_zero_returns_empty() -> None:
    cands = [_cand(1, 0.5)]
    emb = np.array([[1.0, 0.0]])
    assert dedupe_candidates(cands, emb, k=0) == []


def test_dedupe_dpp_singleton() -> None:
    cands = [_cand(1, 0.7)]
    emb = np.array([[1.0, 0.0]])
    kept = dedupe_candidates(cands, emb, method="dpp")
    assert len(kept) == 1
    assert kept[0] is cands[0]


def test_dedupe_rejects_embedding_shape_mismatch() -> None:
    cands = [_cand(1, 0.5), _cand(2, 0.5)]
    with pytest.raises(ValueError, match="embeddings must be"):
        dedupe_candidates(cands, np.array([[1.0, 0.0]]))  # only 1 row for 2 cands


def test_module_surface_imports_without_heavy_deps() -> None:
    # The module must import with only numpy present (no torch/lightgbm/etc.).
    assert set(diversity.__all__) >= {
        "cosine_kernel",
        "dedupe_candidates",
        "dpp_greedy_map",
        "mmr_select",
    }
