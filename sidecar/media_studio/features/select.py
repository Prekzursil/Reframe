"""Prompt-driven clip SELECTION — the short-maker's heart (CONTRACTS.md §5).

Ports the *proven* selection recipe from ``spike/select.py`` into a pure,
provider-agnostic function:

    select(transcript, prompt, controls, provider) -> list[Candidate]

Recipe (frozen — do not soften, see §5):
  * Provider chat call with **reasoning ON** (we NEVER inject ``/no_think``),
    ``temperature 0.4``.
  * A **two-pass** system prompt: pass 1 makes the model state the talk's single
    THESIS and list the 6-8 most-quotable lines (weighting ``(Applause)`` markers
    and finding the COMPLETE thought — setup + payoff — around each); pass 2 picks
    N clips, **each 20-60 s** (hard), opening on a hook, and the single
    most-quotable line of the whole talk MUST be included in one of them.
  * Strip ``<think>...</think>`` reasoning blocks before JSON parsing.
  * Parse the JSON into :data:`Candidate` dicts (§3), including ``sourceStart``
    (the clip's start in the ORIGINAL video).
  * **Map-reduce** for long transcripts: chunk the transcript, shortlist
    candidates per chunk, then do a single global re-rank pass to pick the final N.

This module is pure logic: it has NO heavy-ML imports. The LLM is reached only
through a small :class:`Provider` seam (a ``chat`` method), so tests drive it with
a fake provider returning canned JSON. ``boundary.py`` consumes the returned
Candidates and snaps their start/end to sentence/silence/scene-cut boundaries.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, NotRequired, Protocol, TypedDict

# ---------------------------------------------------------------------------
# Recipe constants (frozen — CONTRACTS.md §5). Centralized so the prompt text,
# the duration clamp, and the tests all read from ONE source of truth.
# ---------------------------------------------------------------------------

# CONTRACT-NOTE: §5 fixes temperature at 0.4 and reasoning ON (no /no_think).
TEMPERATURE: float = 0.4

# §5: each clip is a hard 20-60 seconds.
MIN_CLIP_SEC: float = 20.0
MAX_CLIP_SEC: float = 60.0

# §2 controls default count when the caller omits it.
DEFAULT_COUNT: int = 5

# CONTRACT-NOTE: §7 default model is Qwen3-4B with a large reasoning budget; a
# generous token ceiling keeps the (often long) <think> block + JSON from being
# truncated. Kept as a module constant rather than hard-coded in the call.
MAX_TOKENS: int = 6000

# Map-reduce kicks in only for transcripts longer than this many timestamped
# lines; short talks go straight through a single pass (matches the spike).
CHUNK_LINE_THRESHOLD: int = 240
# Lines per map chunk and how many candidates each chunk shortlists.
CHUNK_LINE_SIZE: int = 200
CHUNK_SHORTLIST_COUNT: int = 6

# Strips Qwen3-style reasoning so JSON parsing sees only the answer (spike line 60).
_THINK_RE = re.compile(r"<think>.*?</think>", re.S)
# Greedy outer-brace match to pull the JSON object out of any surrounding prose.
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.S)

# P3-C virality v2: the four factor names (wire field names FROZEN — kept in
# sync with app/renderer/src/lib/rpc.ts CandidateFactors + features.feedback).
FACTOR_NAMES = ("hookStrength", "emotionalFlow", "perceivedValue", "shareability")

# One-line meaning per factor, embedded into the prompt schema (P3-C).
FACTOR_GUIDE = (
    "Also score FOUR virality factors for each clip, 0-100 each, plus a "
    "one-line note per factor: hookStrength (how arresting the first 3 "
    "seconds are), emotionalFlow (does the emotion build without dead "
    "spots), perceivedValue (does the viewer walk away with something), "
    "shareability (would someone send this to a friend)."
)
# Maximum stored length of a per-factor note (keep payloads one-line compact).
_FACTOR_NOTE_MAX_CHARS = 200


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class Candidate(TypedDict):
    """A selected clip (CONTRACTS.md §3 + the P3 mini-contract, names frozen).

    ``start``/``end``/``sourceStart`` are floats in **seconds** in the ORIGINAL
    video's timeline. ``sourceStart`` equals ``start`` here; captions later
    subtract it to re-base cue times to the clip's local t=0 (§3).

    P3-C additions: ``factors`` (the four 0-100 virality factors),
    ``factorNotes`` (one-line rationale per factor) and ``viralityPct`` (the
    batch-percentile-normalized 0-100 rank within the candidate set; replaced
    by the calibrated percentage once the P3-D flywheel has >= 50 labels).
    ``score`` stays as the legacy 0-100 LLM score.
    """

    rank: int
    start: float
    end: float
    durationSec: float
    hook: str
    why: str
    score: int
    sourceStart: float
    # P3-C/P3-D: set AFTER construction (parse_factors / _finalize percentile),
    # so they are NotRequired at build time — the Candidate ctor sets only the
    # core §3 fields, then attaches these via item assignment.
    factors: NotRequired[dict[str, int]]
    factorNotes: NotRequired[dict[str, str]]
    viralityPct: NotRequired[int]


class Word(TypedDict, total=False):
    text: str
    start: float
    end: float


class Segment(TypedDict, total=False):
    start: float
    end: float
    text: str
    words: list[Word]


class Transcript(TypedDict, total=False):
    """CONTRACTS.md §3 Transcript shape (``words`` optional for selection)."""

    language: str
    segments: list[Segment]
    durationSec: float


class Controls(TypedDict, total=False):
    """``shortmaker.select`` controls (CONTRACTS.md §2 + the P3 mini-contract).

    ``hookTitle`` (default true) / ``removeFillers`` (default false) ride the
    controls like ``captionStyle`` does; selection itself ignores them — they
    take effect in the shortmaker CAPTION / CUT stages.
    """

    count: int
    minSec: float
    maxSec: float
    aspect: str
    language: str
    captionStyle: str
    hookTitle: bool
    removeFillers: bool


class FeedbackSeam(Protocol):
    """The P3-D flywheel seam selection consumes (features.feedback satisfies it).

    ``exemplar_block`` returns the taste-exemplar prompt block (or ``None``
    below the 20-label threshold); ``calibrated_pct`` maps a raw factor-average
    through the empirical approval table (or ``None`` below 50 labels).
    """

    def exemplar_block(self, language: str | None = None) -> str | None: ...

    def calibrated_pct(self, raw: float) -> int | None: ...


class Provider(Protocol):
    """The LLM seam (CONTRACTS.md §4: ``Provider interface (complete/chat)``).

    Selection only needs ``chat``: given system+user messages it returns the raw
    assistant message **content** string (which may still contain a ``<think>``
    block — this module strips it). Tests pass a fake implementing just this.
    """

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float = ...,
        max_tokens: int = ...,
    ) -> str: ...


# ---------------------------------------------------------------------------
# Transcript rendering
# ---------------------------------------------------------------------------


def _fmt_ts(seconds: float) -> str:
    """Render a second offset as ``mm:ss`` (the spike's timestamp format)."""
    total = max(0, int(round(seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"


def _parse_ts(value: Any) -> float | None:
    """Parse a timestamp into float seconds.

    Accepts ``"mm:ss"``, ``"hh:mm:ss"``, a bare number, or a numeric string.
    Returns ``None`` when it cannot be interpreted (the row is then skipped).
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return None
        seconds = 0.0
        for num in nums:  # hh:mm:ss or mm:ss -> seconds (base-60 left-to-right)
            seconds = seconds * 60.0 + num
        return seconds
    try:
        return float(text)
    except ValueError:
        return None


def render_lines(transcript: Transcript) -> list[str]:
    """Render a Transcript into ``[mm:ss] text`` lines (one per segment).

    Mirrors the spike's flat timestamped transcript so the model can cite
    ``[mm:ss]`` markers. ``(Applause)`` and similar markers stay inline so the
    prompt's weighting rule still fires. Empty-text segments are dropped.
    """
    lines: list[str] = []
    for seg in transcript.get("segments", []) or []:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = seg.get("start")
        ts = _fmt_ts(float(start)) if isinstance(start, (int, float)) else "00:00"
        lines.append(f"[{ts}] {text}")
    return lines


# ---------------------------------------------------------------------------
# Prompt construction (the frozen recipe text)
# ---------------------------------------------------------------------------


def build_system_prompt(count: int, min_sec: float, max_sec: float) -> str:
    """Build the two-pass system prompt (CONTRACTS.md §5).

    Pass 1 (THINK): state the single THESIS, then list the 6-8 most quotable /
    counterintuitive / emotional lines, weighting ``(Applause)`` markers, and find
    the COMPLETE thought (setup + payoff) around each. Pass 2 (THEN): select
    ``count`` clips, each ``min_sec``-``max_sec`` seconds (hard), opening on a hook,
    with the single most-quotable line of the talk included in one of them. Output
    ONLY the JSON object after thinking.
    """
    n = int(count)
    lo = int(round(min_sec))
    hi = int(round(max_sec))
    return (
        "You are an elite short-form video editor. Think step by step FIRST, "
        "then output JSON.\n"
        "THINK: (1) State the talk's single core THESIS in one sentence. "
        "(2) List its 6-8 most quotable / counterintuitive / emotional lines "
        "(the transcript may contain '(Applause)' markers - those mark "
        "high-impact moments; weight them). (3) For each, find the COMPLETE "
        "thought around it - the setup AND the payoff - not just one sentence.\n"
        f"THEN select the {n} best clips for vertical shorts. HARD RULES: each "
        "clip is a self-contained complete thought; each runs "
        f"{lo}-{hi} SECONDS (end minus start MUST be >= {lo} and <= {hi} - "
        "extend to include the surrounding setup/payoff, NEVER a 3-second "
        "fragment); opens on a hook, ends on a satisfying or curiosity beat. "
        "The single most quotable line of the whole talk MUST be one of the "
        f"{n}. Use the [mm:ss] timestamps. After thinking, output ONLY the "
        "JSON object."
    )


def _schema_line(min_sec: float, max_sec: float) -> str:
    """The exact JSON-schema instruction (P3-C: factors + factorNotes added).

    Pins every wire field name — the §3 base Candidate fields plus the four
    frozen virality factors with a one-line note each — and re-states the
    duration clamp.
    """
    lo = int(round(min_sec))
    hi = int(round(max_sec))
    return (
        'Return JSON exactly: {"clips":[{"rank":1,"start":"mm:ss","end":"mm:ss",'
        '"duration_sec":40,"hook":"opening words","why":"one-line reason it '
        'will perform","score":0-100,'
        '"factors":{"hookStrength":0-100,"emotionalFlow":0-100,'
        '"perceivedValue":0-100,"shareability":0-100},'
        '"factorNotes":{"hookStrength":"one line","emotionalFlow":"one line",'
        '"perceivedValue":"one line","shareability":"one line"}}]}  '
        f"{FACTOR_GUIDE} "
        "(duration_sec = end minus start in seconds; it MUST be between "
        f"{lo} and {hi})."
    )


def build_user_prompt(user_prompt: str, count: int, min_sec: float, max_sec: float, body: str) -> str:
    """Build the user message: the request + the exact JSON schema + transcript.

    The JSON schema line pins the field names and re-states the duration clamp
    (``duration_sec = end minus start in seconds; MUST be between min and max``).
    ``body`` is the rendered timestamped transcript (or a per-chunk slice).
    """
    n = int(count)
    schema = _schema_line(min_sec, max_sec)
    return f"{user_prompt}\n\nSelect the {n} best clips.\n{schema}\n\nTranscript:\n{body}"


def build_rerank_user_prompt(user_prompt: str, count: int, min_sec: float, max_sec: float, shortlist_body: str) -> str:
    """Build the global re-rank user message for the map-reduce reduce step.

    Hands the model the union of per-chunk shortlisted clips and asks it to pick
    the final ``count`` under the same duration clamp + most-quotable rule.
    """
    n = int(count)
    schema = _schema_line(min_sec, max_sec)
    return (
        f"{user_prompt}\n\n"
        f"These are shortlisted clip candidates from across a long talk. "
        f"Globally re-rank them and return the {n} best for vertical shorts, "
        "keeping the single most-quotable line of the talk in the set.\n"
        f"{schema}\n\n"
        f"Candidates:\n{shortlist_body}"
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def strip_think(content: str) -> str:
    """Remove ``<think>...</think>`` reasoning blocks (spike line 60)."""
    return _THINK_RE.sub("", content).strip()


def extract_clips(content: str) -> list[dict[str, Any]]:
    """Strip reasoning, locate the JSON object, and return its ``clips`` list.

    Returns ``[]`` when no JSON object is present or it fails to parse / lacks a
    ``clips`` array (the spike treated a missing match as zero clips).
    """
    cleaned = strip_think(content)
    match = _JSON_OBJ_RE.search(cleaned)
    if not match:
        return []
    try:
        obj = json.loads(match.group(0))
    except (ValueError, json.JSONDecodeError):
        return []
    clips = obj.get("clips") if isinstance(obj, dict) else None
    return clips if isinstance(clips, list) else []


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _clamp_0_100(value: Any, default: int = 0) -> int:
    """Coerce to int and clamp into [0, 100] (factor/score hygiene)."""
    return max(0, min(100, _coerce_int(value, default)))


def parse_factors(clip: dict[str, Any], score: int) -> dict[str, int]:
    """Parse + clamp the P3-C factor dict from a raw LLM clip row.

    Each factor is clamped into 0-100. CONTRACT-NOTE: a missing/unparseable
    factor degrades to the clip's (clamped) legacy ``score`` rather than 0 —
    a parse hiccup must not crater the candidate's batch percentile.
    """
    raw = clip.get("factors")
    raw = raw if isinstance(raw, dict) else {}
    fallback = _clamp_0_100(score)
    return {name: _clamp_0_100(raw.get(name, fallback), fallback) for name in FACTOR_NAMES}


def parse_factor_notes(clip: dict[str, Any]) -> dict[str, str]:
    """Parse the one-line per-factor notes (missing notes become ``""``)."""
    raw = clip.get("factorNotes")
    raw = raw if isinstance(raw, dict) else {}
    return {name: str(raw.get(name, "") or "")[:_FACTOR_NOTE_MAX_CHARS] for name in FACTOR_NAMES}


def factor_average(candidate: Mapping[str, Any]) -> float:
    """Mean of the four factor scores (the raw virality value)."""
    factors = candidate.get("factors") or {}
    values = [_clamp_0_100(factors.get(name, 0)) for name in FACTOR_NAMES]
    return sum(values) / float(len(FACTOR_NAMES))


def apply_virality_pct(candidates: list[Candidate]) -> list[Candidate]:
    """Set each candidate's ``viralityPct`` = percentile rank within the batch.

    Percentile of the raw factor-average within THIS candidate set: the best
    clip lands at 100, the worst at 0 (``100 * #strictly-below / (n-1)``);
    ties share the same percentile and ordering is stable (P3-C). A singleton
    batch sits at the 50 midpoint. Mutates in place and returns the list.
    """
    n = len(candidates)
    if n == 0:
        return candidates
    raws = [factor_average(c) for c in candidates]
    if n == 1:
        # A singleton batch has no distribution to rank within — carry the raw
        # factor average (real signal) rather than a meaningless 50 sentinel.
        candidates[0]["viralityPct"] = int(round(raws[0]))
        return candidates
    sorted_raws = sorted(raws)
    for cand, raw in zip(candidates, raws, strict=False):
        below = _count_strictly_below(sorted_raws, raw)
        cand["viralityPct"] = int(round(100.0 * below / (n - 1)))
    return candidates


def _count_strictly_below(sorted_values: list[float], value: float) -> int:
    """#entries strictly below ``value`` (bisect_left on a sorted list)."""
    lo, hi = 0, len(sorted_values)
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_values[mid] < value:
            lo = mid + 1
        else:
            hi = mid
    return lo


def to_candidates(
    clips: Sequence[dict[str, Any]],
    min_sec: float,
    max_sec: float,
    duration_total: float | None = None,
) -> list[Candidate]:
    """Convert raw LLM clip dicts into validated :data:`Candidate` records (§3).

    For each clip: parse ``start``/``end`` (``mm:ss`` or seconds) into float
    seconds; compute ``durationSec`` from end-minus-start and **clamp** it into
    the hard ``[min_sec, max_sec]`` window (extending ``end`` if too short,
    trimming it if too long) so no out-of-range clip ever leaves selection;
    set ``sourceStart = start`` (clip start in the original video, §3); re-rank
    1..N by descending score (ties keep input order). Rows missing both a start
    and an end are dropped.
    """
    parsed: list[Candidate] = []
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        start = _parse_ts(clip.get("start"))
        end = _parse_ts(clip.get("end"))
        if start is None and end is None:
            continue
        if start is None:
            # Only an end given: anchor a min-length window ending there.
            start = max(0.0, (end or 0.0) - min_sec)
        if end is None:
            end = start + min_sec
        if end < start:
            start, end = end, start
        # Hard duration clamp into [min_sec, max_sec] (§5). Extend/trim the END
        # so the clip start (the hook + sourceStart) is preserved.
        duration = end - start
        if duration < min_sec:
            end = start + min_sec
        elif duration > max_sec:
            end = start + max_sec
        if duration_total is not None and end > duration_total:
            # Don't run past the source; pull the whole window left if possible.
            overshoot = end - duration_total
            start = max(0.0, start - overshoot)
            end = duration_total
        duration = round(end - start, 3)
        score = _coerce_int(clip.get("score"), 0)
        cand = Candidate(
            rank=_coerce_int(clip.get("rank"), len(parsed) + 1),
            start=round(start, 3),
            end=round(end, 3),
            durationSec=duration,
            hook=str(clip.get("hook", "")),
            why=str(clip.get("why", "")),
            score=score,
            sourceStart=round(start, 3),
        )
        # P3-C: attach the four virality factors + per-factor notes (degrade to
        # the legacy score on a parse miss). viralityPct is NOT set here — it is
        # a BATCH percentile, computed by _finalize() over the returned set only.
        cand["factors"] = parse_factors(clip, score)
        cand["factorNotes"] = parse_factor_notes(clip)
        parsed.append(cand)
    # Global re-rank: highest score first, stable for ties; renumber 1..N.
    ordered = sorted(enumerate(parsed), key=lambda iv: (-iv[1]["score"], iv[0]))
    result: list[Candidate] = []
    for new_rank, (_idx, cand) in enumerate(ordered, start=1):
        cand["rank"] = new_rank
        result.append(cand)
    return result


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------


def _resolve_controls(controls: Controls | None) -> dict[str, Any]:
    """Resolve count/min/max from controls, applying §5 defaults + clamps.

    ``count`` defaults to 5 (§2); ``minSec``/``maxSec`` default to the hard
    20/60 window and are themselves clamped so a caller cannot request a clip
    shorter than 20 s or longer than 60 s.
    """
    controls = controls or {}
    count = _coerce_int(controls.get("count"), DEFAULT_COUNT)
    if count < 1:
        count = DEFAULT_COUNT
    try:
        min_sec = float(controls.get("minSec", MIN_CLIP_SEC))
    except (TypeError, ValueError):
        min_sec = MIN_CLIP_SEC
    try:
        max_sec = float(controls.get("maxSec", MAX_CLIP_SEC))
    except (TypeError, ValueError):
        max_sec = MAX_CLIP_SEC
    # Keep the requested window inside the hard 20-60 s envelope (§5).
    min_sec = max(MIN_CLIP_SEC, min(min_sec, MAX_CLIP_SEC))
    max_sec = max(MIN_CLIP_SEC, min(max_sec, MAX_CLIP_SEC))
    if max_sec < min_sec:
        min_sec, max_sec = max_sec, min_sec
    return {"count": count, "min_sec": min_sec, "max_sec": max_sec}


# ---------------------------------------------------------------------------
# Map-reduce
# ---------------------------------------------------------------------------


def _chunk_lines(lines: Sequence[str], size: int) -> list[list[str]]:
    """Split rendered transcript lines into ``size``-line chunks."""
    return [list(lines[i : i + size]) for i in range(0, len(lines), size)]


def _candidate_to_shortlist_row(cand: Candidate) -> str:
    """Render a candidate as a compact ``[mm:ss-mm:ss]`` shortlist row.

    Used as the body of the reduce step so the model re-ranks across chunks with
    the original timeline preserved.
    """
    return (
        f"[{_fmt_ts(cand['start'])}-{_fmt_ts(cand['end'])}] "
        f"score={cand['score']} hook={cand['hook']!r} why={cand['why']!r}"
    )


def _ask(
    provider: Provider,
    system: str,
    user: str,
) -> list[dict[str, Any]]:
    """One provider round-trip: send system+user, return parsed raw clip dicts.

    Reasoning stays ON (no ``/no_think``); temperature is the frozen 0.4 (§5).
    """
    content = provider.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
    )
    return extract_clips(content)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _finalize(cands: list[Candidate], count: int) -> list[Candidate]:
    """Trim to ``count`` then stamp viralityPct over EXACTLY the returned set.

    P3-C: the batch percentile must rank within the clips the user actually
    receives, not the wider pre-trim pool (reviewer finding) — so trim first.
    """
    return apply_virality_pct(list(cands[:count]))


def select(
    transcript: Transcript,
    prompt: str,
    controls: Controls | None,
    provider: Provider,
) -> list[Candidate]:
    """Select ranked clip Candidates from a transcript (CONTRACTS.md §5).

    Single pass for short transcripts; **map-reduce** for long ones (chunk →
    per-chunk shortlist → global re-rank). Returns at most ``controls.count``
    :data:`Candidate` records, each within the hard 20-60 s window, re-ranked
    1..N by score, carrying ``sourceStart`` for caption re-basing.
    """
    cfg = _resolve_controls(controls)
    count, min_sec, max_sec = cfg["count"], cfg["min_sec"], cfg["max_sec"]
    user_prompt = (prompt or "").strip() or ("Find the most share-worthy clips for vertical short-form.")
    duration_total = transcript.get("durationSec")
    if not isinstance(duration_total, (int, float)):
        duration_total = None

    lines = render_lines(transcript)
    system = build_system_prompt(count, min_sec, max_sec)

    if len(lines) <= CHUNK_LINE_THRESHOLD:
        body = "\n".join(lines)
        clips = _ask(provider, system, build_user_prompt(user_prompt, count, min_sec, max_sec, body))
        return _finalize(to_candidates(clips, min_sec, max_sec, duration_total), count)

    # --- MAP: shortlist candidates per chunk -------------------------------
    chunk_system = build_system_prompt(CHUNK_SHORTLIST_COUNT, min_sec, max_sec)
    shortlist: list[Candidate] = []
    for chunk in _chunk_lines(lines, CHUNK_LINE_SIZE):
        body = "\n".join(chunk)
        clips = _ask(
            provider, chunk_system, build_user_prompt(user_prompt, CHUNK_SHORTLIST_COUNT, min_sec, max_sec, body)
        )
        shortlist.extend(to_candidates(clips, min_sec, max_sec, duration_total))

    if not shortlist:
        return []

    # --- REDUCE: one global re-rank over the union shortlist ---------------
    shortlist_body = "\n".join(_candidate_to_shortlist_row(c) for c in shortlist)
    rerank_clips = _ask(
        provider, system, build_rerank_user_prompt(user_prompt, count, min_sec, max_sec, shortlist_body)
    )
    final = to_candidates(rerank_clips, min_sec, max_sec, duration_total)
    if final:
        return _finalize(final, count)
    # CONTRACT-NOTE: §5 — if the reduce pass returns no parseable JSON, fall back
    # to the already-validated map shortlist (best-effort, never empty-on-error
    # when we have real candidates) rather than dropping the whole selection.
    return _finalize(
        to_candidates(
            [
                {
                    "start": c["start"],
                    "end": c["end"],
                    "hook": c["hook"],
                    "why": c["why"],
                    "score": c["score"],
                    "rank": c["rank"],
                    # carry the already-parsed P3-C factors through the fallback
                    "factors": c.get("factors"),
                    "factorNotes": c.get("factorNotes"),
                }
                for c in shortlist
            ],
            min_sec,
            max_sec,
            duration_total,
        ),
        count,
    )
