"""Filler-word removal — cut-list building + ffmpeg segment-concat argv (P3-B).

Word timings already exist on the transcript (CONTRACTS.md §3 ``Word``), so
filler removal is pure timeline math:

    build_cutlist(words, lang, *, fillers=DEFAULT_SETS, merge_gap_ms=120)
        -> [(keep_start, keep_end), ...]

* **Per-language filler sets** (:data:`DEFAULT_SETS`, incl. ``"ro"`` basics).
  Each set has two tiers: ``"always"`` tokens (um/uh/ăă — pure disfluencies,
  dropped wherever they appear) and ``"standalone"`` tokens (like / you know /
  deci / gen — real words that are only fillers when they stand alone, i.e.
  bounded by a pause on at least one side).
* **Never cut mid-sentence per word boundaries:** every cut edge lands EXACTLY
  on a word start/end timestamp (never inside a word), and a filler whose raw
  token carries sentence-final punctuation (``. ! ? …``) is NOT dropped — it
  owns the sentence boundary, and removing it would splice two sentences.
* **Merge adjacent keeps** (``merge_gap_ms``): a removed span shorter than the
  merge gap is restored (no jarring sub-120 ms micro-cuts), and an interior
  keep sliver shorter than the gap between two removals is absorbed into the
  cut. Adjacent/overlapping keeps coalesce.

The module also owns the ffmpeg **apply** half: :func:`build_segment_cut_argv`
builds the frame-accurate ``filter_complex`` trim/atrim + concat argv (argv
LIST only, A6.4 — never a shell string), and :func:`remap_cues` re-times
caption cues onto the concatenated (compressed) clip-local timeline so
captions stay in sync after the fillers are gone.

Pure logic + an argv builder: NO heavy imports, no subprocess here — the
shortmaker CUT stage runs the argv through the shared drained ``ffmpeg.run``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# A keep segment in ORIGINAL-video seconds: [keep_start, keep_end).
KeepSpan = Tuple[float, float]
WordLike = Mapping[str, Any]

# Default merge window (ms): removals shorter than this are not worth a cut,
# and keep slivers shorter than this between two cuts are absorbed.
DEFAULT_MERGE_GAP_MS: int = 120

# A "standalone" filler must be bounded by a pause of at least this many
# seconds on one side (or sit at the words' edge) to be treated as a filler.
STANDALONE_GAP_SEC: float = 0.15

# Punctuation stripped when normalizing a token for set lookup.
_STRIP_CHARS = ".,!?;:…\"'`´“”‘’()[]{}«»—–-"
# Sentence-final punctuation: a filler carrying one of these is never cut.
_SENTENCE_END = (".", "!", "?", "…")

# ---------------------------------------------------------------------------
# Per-language filler sets (P3-B: configurable; 'ro' basics included).
# CONTRACT-NOTE: the mini-contract freezes the build_cutlist signature, not the
# set contents — tune freely. Multi-word phrases are spelled with single spaces.
# ---------------------------------------------------------------------------
DEFAULT_SETS: Dict[str, Dict[str, frozenset]] = {
    "en": {
        "always": frozenset({"um", "uh", "uhm", "erm", "hmm", "mmm", "uhh", "umm"}),
        "standalone": frozenset(
            {"like", "so", "well", "right", "okay", "you know", "i mean",
             "sort of", "kind of", "basically", "actually", "literally"}
        ),
    },
    "ro": {
        "always": frozenset({"ăă", "ăăă", "îî", "îîî", "ăm", "mm", "eee", "ee"}),
        "standalone": frozenset(
            {"deci", "gen", "adică", "practic", "păi", "na", "mă rog",
             "cum să zic", "știi", "stii"}
        ),
    },
}


def normalize_token(text: Any) -> str:
    """Lowercase a word token and strip surrounding punctuation/whitespace."""
    return str(text or "").strip().strip(_STRIP_CHARS).strip().lower()


def _lang_sets(
    lang: Optional[str], fillers: Mapping[str, Mapping[str, frozenset]]
) -> Tuple[frozenset, frozenset]:
    """Resolve (always, standalone) sets for ``lang`` (base-lang fallback)."""
    key = (lang or "").strip().lower()
    entry = fillers.get(key) or fillers.get(key.split("-")[0])
    if entry is None:
        entry = fillers.get("en") or {}
    return (
        frozenset(entry.get("always") or ()),
        frozenset(entry.get("standalone") or ()),
    )


def _phrase_lengths(*sets: frozenset) -> List[int]:
    """Distinct word counts of all entries, longest first (greedy matching)."""
    lengths = {len(entry.split()) for s in sets for entry in s}
    return sorted(lengths, reverse=True)


def _valid_words(words: Sequence[WordLike]) -> List[Dict[str, Any]]:
    """Keep words with usable text + numeric, ordered timings."""
    out: List[Dict[str, Any]] = []
    for w in words or []:
        try:
            start = float(w.get("start"))  # type: ignore[arg-type]
            end = float(w.get("end"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        text = str(w.get("text", "") or "")
        if not text.strip() or end <= start:
            continue
        out.append({"text": text, "start": start, "end": end})
    out.sort(key=lambda w: (w["start"], w["end"]))
    return out


def _is_pause_bounded(
    words: Sequence[Dict[str, Any]], i: int, j: int, gap_sec: float
) -> bool:
    """True when words[i..j] have a >= gap_sec pause on at least one side.

    The sequence edge (no previous/next word) counts as a pause — a clip
    opening on "like ..." treats the lead-in as the bounding pause.
    """
    before = (words[i]["start"] - words[i - 1]["end"]) if i > 0 else gap_sec
    after = (
        (words[j + 1]["start"] - words[j]["end"]) if j + 1 < len(words) else gap_sec
    )
    return before >= gap_sec or after >= gap_sec


def _mark_filler_words(
    words: List[Dict[str, Any]],
    always: frozenset,
    standalone: frozenset,
) -> List[bool]:
    """Flag each word that belongs to a dropped filler (single or phrase).

    Greedy longest-phrase-first scan. A match is skipped when its LAST raw
    token carries sentence-final punctuation (never cut a sentence boundary).
    """
    n = len(words)
    drop = [False] * n
    norms = [normalize_token(w["text"]) for w in words]
    lengths = _phrase_lengths(always, standalone) or [1]
    i = 0
    while i < n:
        matched = False
        for length in lengths:
            j = i + length - 1
            if j >= n:
                continue
            phrase = " ".join(norms[i : j + 1])
            if not phrase:
                continue
            in_always = phrase in always
            in_standalone = phrase in standalone
            if not (in_always or in_standalone):
                continue
            # Sentence guard: the phrase's last raw token ends the sentence.
            raw_tail = str(words[j]["text"]).strip()
            if raw_tail.endswith(_SENTENCE_END):
                continue
            if in_standalone and not in_always and not _is_pause_bounded(
                words, i, j, STANDALONE_GAP_SEC
            ):
                continue
            for k in range(i, j + 1):
                drop[k] = True
            i = j + 1
            matched = True
            break
        if not matched:
            i += 1
    return drop


def _drop_spans(
    words: Sequence[Dict[str, Any]], drop: Sequence[bool]
) -> List[Tuple[float, float, int]]:
    """Coalesce consecutive dropped words into (start, end, word_count) spans."""
    spans: List[Tuple[float, float, int]] = []
    i = 0
    n = len(words)
    while i < n:
        if not drop[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and drop[j + 1]:
            j += 1
        spans.append((words[i]["start"], words[j]["end"], j - i + 1))
        i = j + 1
    return spans


def build_cutlist_with_stats(
    words: Sequence[WordLike],
    lang: Optional[str],
    *,
    fillers: Mapping[str, Mapping[str, frozenset]] = DEFAULT_SETS,
    merge_gap_ms: int = DEFAULT_MERGE_GAP_MS,
    window: Optional[Tuple[float, float]] = None,
) -> Tuple[List[KeepSpan], Dict[str, Any]]:
    """:func:`build_cutlist` plus per-clip stats (the P3-B contract fields).

    Returns ``(keeps, {"fillersRemoved": int, "fillerSeconds": float})`` where
    ``fillersRemoved`` counts the filler WORDS actually removed and
    ``fillerSeconds`` is the total removed duration within the window.
    """
    clean = _valid_words(words)
    if window is not None:
        win_start, win_end = float(window[0]), float(window[1])
        clean = [w for w in clean if w["end"] > win_start and w["start"] < win_end]
    elif clean:
        win_start, win_end = clean[0]["start"], clean[-1]["end"]
    else:
        win_start, win_end = 0.0, 0.0

    if win_end <= win_start:
        return [], {"fillersRemoved": 0, "fillerSeconds": 0.0}
    if not clean:
        return (
            [(round(win_start, 3), round(win_end, 3))],
            {"fillersRemoved": 0, "fillerSeconds": 0.0},
        )

    always, standalone = _lang_sets(lang, fillers)
    drop_flags = _mark_filler_words(clean, always, standalone)
    if all(drop_flags):
        # Degenerate: every word is a filler — keep the window whole rather
        # than emitting a content-free clip.
        return (
            [(round(win_start, 3), round(win_end, 3))],
            {"fillersRemoved": 0, "fillerSeconds": 0.0},
        )
    spans = _drop_spans(clean, drop_flags)

    min_gap = max(0.0, float(merge_gap_ms) / 1000.0)
    # Restore removals shorter than the merge gap (no micro-cuts), clamp to
    # the window, and absorb keep slivers between two removals.
    kept_spans: List[Tuple[float, float, int]] = []
    for start, end, count in spans:
        start = max(start, win_start)
        end = min(end, win_end)
        if end - start < min_gap or end <= start:
            continue  # too short to be worth a cut: merge the adjacent keeps
        if kept_spans and start - kept_spans[-1][1] < min_gap:
            # The keep between two removals is a sliver: absorb it.
            prev = kept_spans[-1]
            kept_spans[-1] = (prev[0], end, prev[2] + count)
        else:
            kept_spans.append((start, end, count))

    keeps: List[KeepSpan] = []
    cursor = win_start
    removed_words = 0
    removed_sec = 0.0
    for start, end, count in kept_spans:
        if start > cursor:
            keeps.append((round(cursor, 3), round(start, 3)))
        removed_words += count
        removed_sec += end - start
        cursor = max(cursor, end)
    if cursor < win_end:
        keeps.append((round(cursor, 3), round(win_end, 3)))

    if not keeps:
        # Degenerate: everything was a filler — keep the window whole rather
        # than emitting an empty clip.
        return (
            [(round(win_start, 3), round(win_end, 3))],
            {"fillersRemoved": 0, "fillerSeconds": 0.0},
        )

    stats = {"fillersRemoved": int(removed_words),
             "fillerSeconds": round(removed_sec, 3)}
    return keeps, stats


def build_cutlist(
    words: Sequence[WordLike],
    lang: Optional[str],
    *,
    fillers: Mapping[str, Mapping[str, frozenset]] = DEFAULT_SETS,
    merge_gap_ms: int = DEFAULT_MERGE_GAP_MS,
    window: Optional[Tuple[float, float]] = None,
) -> List[KeepSpan]:
    """Build the keep-list for filler removal (the frozen P3-B entry point).

    ``words`` are §3 Words (original-video seconds); ``lang`` picks the filler
    set ('en' fallback). Returns ``[(keep_start, keep_end), ...]`` covering the
    window (default: the words' own span) minus the removed filler spans.
    """
    keeps, _stats = build_cutlist_with_stats(
        words, lang, fillers=fillers, merge_gap_ms=merge_gap_ms, window=window
    )
    return keeps


# ---------------------------------------------------------------------------
# cue re-timing onto the concatenated clip timeline
# ---------------------------------------------------------------------------
def remap_time(t: float, keeps: Sequence[KeepSpan]) -> float:
    """Map an ORIGINAL-video time onto the concatenated keeps' local timeline.

    Time inside the n-th keep lands at (sum of previous keep durations +
    offset into that keep); time inside a removed span collapses onto the cut
    point (the end of the material kept so far). Times before the first keep
    clamp to 0.
    """
    t = float(t)
    elapsed = 0.0
    for start, end in keeps:
        if t < start:
            return elapsed
        if t <= end:
            return elapsed + (t - start)
        elapsed += end - start
    return elapsed


def remap_cues(
    cues: Sequence[Mapping[str, Any]], keeps: Sequence[KeepSpan]
) -> List[Dict[str, Any]]:
    """Re-time caption cues (original-video seconds) onto the cut clip.

    Cues that collapse to zero length (they lived entirely inside a removed
    filler span) are dropped; indexes are renumbered 1..N. The result is
    clip-local — callers pass ``source_start=0`` to the caption stage.
    """
    out: List[Dict[str, Any]] = []
    for cue in cues or []:
        start = remap_time(cue.get("start", 0.0), keeps)
        end = remap_time(cue.get("end", 0.0), keeps)
        if end - start <= 1e-6:
            continue
        out.append(
            {
                "index": len(out) + 1,
                "start": round(start, 3),
                "end": round(end, 3),
                "text": str(cue.get("text", "") or ""),
            }
        )
    return out


# ---------------------------------------------------------------------------
# ffmpeg apply: frame-accurate segment select/concat (argv list, A6.4)
# ---------------------------------------------------------------------------
def build_segment_cut_argv(
    in_path: str,
    out_path: str,
    keeps: Sequence[KeepSpan],
    settings: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """argv carving ``keeps`` out of ``in_path`` and concatenating them.

    One ``filter_complex`` with a trim/atrim pair per keep segment (decode-side
    trims are frame-accurate) followed by ``concat=n=N:v=1:a=1``; encodes with
    libx264 + aac like the plain CUT stage. argv LIST only — paths with spaces
    stay intact; reuses ffmpeg.py's resolver and the drained ``run`` seam.
    """
    spans = [(float(a), float(b)) for a, b in keeps or [] if float(b) > float(a)]
    if not spans:
        raise ValueError("segment cut requires at least one keep span")
    from .. import ffmpeg as _ffmpeg  # lazy: keeps module import-light

    parts: List[str] = []
    labels: List[str] = []
    for i, (start, end) in enumerate(spans):
        parts.append(
            f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{i}]"
        )
        parts.append(
            f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{i}]"
        )
        labels.append(f"[v{i}][a{i}]")
    parts.append(f"{''.join(labels)}concat=n={len(spans)}:v=1:a=1[v][a]")

    return [
        _ffmpeg.ffmpeg_path(settings),
        "-hide_banner", "-nostdin", "-y",
        "-i", in_path,
        "-filter_complex", ";".join(parts),
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264", "-c:a", "aac",
        "-progress", "pipe:1", "-nostats",
        out_path,
    ]


__all__ = [
    "DEFAULT_SETS",
    "DEFAULT_MERGE_GAP_MS",
    "STANDALONE_GAP_SEC",
    "build_cutlist",
    "build_cutlist_with_stats",
    "build_segment_cut_argv",
    "normalize_token",
    "remap_cues",
    "remap_time",
]
