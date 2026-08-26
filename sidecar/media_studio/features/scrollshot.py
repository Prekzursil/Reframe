from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..jobs import JobContext
from ..pathsafe import clean_for_log, ensure_local_media_input, ensure_within

KIND = "scrollshot.exportMarkdown"
_INLINE_MD_SPECIALS = "\\`*_{}[]()#+-.!|>"


class ScrollshotError(RuntimeError):
    def __init__(self, stage: str, code: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.code = code

    def __str__(self) -> str:
        return f"scrollshot {self.stage} {self.code}: {super().__str__()}"


class ScrollshotDependencyError(ScrollshotError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(stage, "dependency", message)


@dataclass(frozen=True)
class ScrollshotConfig:
    title: str
    language: str
    assurance: str
    sample_every: int = 12
    max_skip: int = 2
    revisit_min_gap: int = 3
    cue_tolerance_px: int = 12
    coverage_gap_px: int = 24
    chrome_top_px: int = 0
    cursor_boxes: tuple[tuple[int, int, int, int], ...] = ()


@dataclass(frozen=True)
class SampledFrame:
    index: int
    source_index: int
    path: str
    image: Any
    width: int
    height: int


@dataclass(frozen=True)
class OcrObservation:
    frame_index: int
    text: str
    top: int
    left: int
    width: int
    height: int
    confidence: float

    @property
    def absolute_top(self) -> int:
        return self.top


@dataclass(frozen=True)
class EdgeCue:
    name: str
    delta: int
    confidence: float


@dataclass(frozen=True)
class EdgeProposal:
    src: int
    dst: int
    delta: int
    confidence: float
    cues: tuple[EdgeCue, ...]


@dataclass(frozen=True)
class PoseSolution:
    positions: tuple[int, ...]
    accepted_edges: tuple[EdgeProposal, ...]
    rejected_edges: tuple[EdgeProposal, ...]
    issues: tuple[str, ...]
    coverage_verdict: str


@dataclass(frozen=True)
class MarkdownLine:
    text: str
    absolute_top: int
    source_frames: tuple[int, ...]
    confidence: float


@dataclass(frozen=True)
class ConflictRecord:
    absolute_top: int
    chosen_text: str
    alternate_texts: tuple[str, ...]
    source_frames: tuple[int, ...]


@dataclass(frozen=True)
class ScrollshotBundle:
    bundle_id: str
    bundle_dir: str
    manifest_path: str
    markdown_path: str
    image_path: str
    observations_path: str
    conflicts_path: str
    coverage_verdict: str
    coverage_issues: tuple[str, ...]
    source_sha256: str
    markdown_sha256: str
    image_sha256: str


class FrameSampler(Protocol):
    def __call__(self, video_path: str, frames_dir: str, config: ScrollshotConfig) -> Sequence[SampledFrame]: ...


class OcrReader(Protocol):
    def __call__(self, frames: Sequence[SampledFrame], config: ScrollshotConfig) -> Sequence[OcrObservation]: ...


class EdgeFinder(Protocol):
    def __call__(
        self,
        frames: Sequence[SampledFrame],
        observations: Sequence[OcrObservation],
        config: ScrollshotConfig,
    ) -> Sequence[EdgeProposal]: ...


class Composer(Protocol):
    def __call__(self, frames: Sequence[SampledFrame], positions: Sequence[int], out_path: str) -> str: ...


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return cleaned or "scrollshot"


def load_config(
    *,
    source_path: str,
    title: str | None,
    language: str | None,
    assurance: str | None,
) -> ScrollshotConfig:
    mode = (assurance or "strict").strip().lower()
    if mode not in {"strict", "balanced", "best-effort"}:
        raise ScrollshotError("params", "invalid", f"unsupported assurance {mode!r}")
    lang = (language or "eng").strip() or "eng"
    picked_title = (title or Path(source_path).stem).strip() or Path(source_path).stem
    return ScrollshotConfig(title=picked_title, language=lang, assurance=mode)


def escape_markdown_text(value: str) -> str:
    text = html.escape(value, quote=False)
    escaped: list[str] = []
    for char in text:
        escaped.append(f"\\{char}" if char in _INLINE_MD_SPECIALS else char)
    return "".join(escaped)


def escape_code_value(value: str) -> str:
    return value.replace("`", "\\`")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def apply_masks(image: Any, chrome_top_px: int, cursor_boxes: Sequence[tuple[int, int, int, int]], cv2_mod: Any) -> Any:
    if chrome_top_px > 0:
        cv2_mod.rectangle(image, (0, 0), (99999, chrome_top_px), (0, 0, 0), -1)
    for x, y, width, height in cursor_boxes:
        cv2_mod.rectangle(image, (x, y), (x + width, y + height), (0, 0, 0), -1)
    return image


def _group_observations(observations: Sequence[OcrObservation], positions: Sequence[int]) -> list[tuple[int, list[OcrObservation]]]:
    ordered = sorted(
        (
            OcrObservation(
                frame_index=item.frame_index,
                text=item.text,
                top=int(positions[item.frame_index]) + int(item.top),
                left=item.left,
                width=item.width,
                height=item.height,
                confidence=item.confidence,
            )
            for item in observations
        ),
        key=lambda item: (item.top, item.left, item.frame_index),
    )
    groups: list[tuple[int, list[OcrObservation]]] = []
    for item in ordered:
        if not groups or abs(item.top - groups[-1][0]) > 24:
            groups.append((item.top, [item]))
            continue
        groups[-1][1].append(item)
    return groups


def compose_markdown_lines(
    observations: Sequence[OcrObservation],
    positions: Sequence[int],
) -> tuple[list[MarkdownLine], list[ConflictRecord]]:
    lines: list[MarkdownLine] = []
    conflicts: list[ConflictRecord] = []
    for absolute_top, group in _group_observations(observations, positions):
        by_text: dict[str, list[OcrObservation]] = defaultdict(list)
        for item in group:
            by_text[normalize_text(item.text)].append(item)
        ranked = sorted(
            by_text.values(),
            key=lambda items: (
                len(items),
                max(item.confidence for item in items),
                -min(item.frame_index for item in items),
            ),
            reverse=True,
        )
        chosen_group = ranked[0]
        chosen = max(chosen_group, key=lambda item: (item.confidence, -item.frame_index))
        frame_ids = tuple(sorted({item.frame_index for item in group}))
        lines.append(
            MarkdownLine(
                text=chosen.text,
                absolute_top=absolute_top,
                source_frames=frame_ids,
                confidence=max(item.confidence for item in chosen_group),
            )
        )
        alternate = tuple(
            sorted(
                {
                    max(items, key=lambda item: item.confidence).text
                    for items in ranked[1:]
                    if normalize_text(max(items, key=lambda item: item.confidence).text) != normalize_text(chosen.text)
                }
            )
        )
        if alternate:
            conflicts.append(
                ConflictRecord(
                    absolute_top=absolute_top,
                    chosen_text=chosen.text,
                    alternate_texts=alternate,
                    source_frames=frame_ids,
                )
            )
    return lines, conflicts


def render_markdown(
    *,
    config: ScrollshotConfig,
    source_path: str,
    bundle_id: str,
    coverage_verdict: str,
    issues: Sequence[str],
    lines: Sequence[MarkdownLine],
    conflicts: Sequence[ConflictRecord],
) -> str:
    out = [
        f"# {escape_markdown_text(config.title)}",
        "",
        f"- Source video: `{escape_code_value(source_path)}`",
        f"- Bundle id: `{escape_code_value(bundle_id)}`",
        f"- Language: `{escape_code_value(config.language)}`",
        f"- Assurance: `{escape_code_value(config.assurance)}`",
        f"- Coverage verdict: `{escape_code_value(coverage_verdict)}`",
    ]
    if issues:
        out.append(f"- Coverage notes: {escape_markdown_text('; '.join(issues))}")
    out.extend(["", "## Extract", ""])
    if lines:
        out.extend(f"- {escape_markdown_text(item.text)}" for item in lines)
    else:
        out.append("- No OCR text extracted.")
    if conflicts:
        out.extend(["", "## OCR Conflicts", ""])
        for conflict in conflicts:
            alternates = ", ".join(escape_markdown_text(text) for text in conflict.alternate_texts)
            frames = ", ".join(str(index) for index in conflict.source_frames)
            out.append(
                f"- Kept {escape_markdown_text(conflict.chosen_text)} at y={conflict.absolute_top}; alternates: {alternates}; frames: {frames}"
            )
    out.append("")
    return "\n".join(out)


def _edge_votes(edge: EdgeProposal, tolerance: int) -> tuple[EdgeCue, ...]:
    votes = tuple(cue for cue in edge.cues if abs(int(cue.delta) - int(edge.delta)) <= tolerance and _cue_is_reliable(cue))
    return votes


def _cue_is_reliable(cue: EdgeCue) -> bool:
    thresholds = {"template": 0.65, "phase": 0.15, "ocr": 1.0}
    return cue.confidence >= thresholds.get(cue.name, 0.000001)


def _cluster_cues(cues: Sequence[EdgeCue], tolerance: int) -> tuple[int, tuple[EdgeCue, ...]]:
    if not cues:
        return 0, ()
    best_delta = int(cues[0].delta)
    best_group: tuple[EdgeCue, ...] = ()
    best_score = (-1, float("-inf"))
    for cue in cues:
        group = tuple(item for item in cues if _cue_is_reliable(item) and abs(int(item.delta) - int(cue.delta)) <= tolerance)
        if not group:
            continue
        score = (len(group), sum(item.confidence for item in group))
        if score > best_score:
            best_score = score
            best_delta = round(sum(int(item.delta) for item in group) / len(group))
            best_group = group
    return best_delta, best_group


def solve_pose_graph(frame_count: int, frame_height: int, edges: Sequence[EdgeProposal], config: ScrollshotConfig) -> PoseSolution:
    if frame_count <= 0:
        raise ScrollshotError("graph", "invalid", "frame_count must be positive")
    if frame_height <= 0:
        raise ScrollshotError("graph", "invalid", "frame_height must be positive")
    rejected: list[EdgeProposal] = []
    best_by_pair: dict[tuple[int, int], tuple[int, float, EdgeProposal]] = {}
    for edge in edges:
        if edge.src < 0 or edge.dst >= frame_count or edge.src >= edge.dst:
            rejected.append(edge)
            continue
        votes = _edge_votes(edge, config.cue_tolerance_px)
        frame_gap = edge.dst - edge.src
        needs_semantic_anchor = 1 < frame_gap <= config.max_skip + 1
        semantic_support = max((cue.confidence for cue in votes if cue.name == "ocr"), default=0.0)
        if len(votes) < 2 or (needs_semantic_anchor and semantic_support < 3.0):
            rejected.append(edge)
            continue
        score = (len(votes), sum(cue.confidence for cue in votes))
        key = (edge.src, edge.dst)
        if key not in best_by_pair or score > best_by_pair[key][:2]:
            best_by_pair[key] = (score[0], score[1], edge)
    accepted_pool = [payload[2] for payload in sorted(best_by_pair.values(), key=lambda item: (-item[0], -item[1], item[2].src, item[2].dst))]
    parents = list(range(frame_count))

    def find(node: int) -> int:
        while parents[node] != node:
            parents[node] = parents[parents[node]]
            node = parents[node]
        return node

    def union(left: int, right: int) -> bool:
        root_left = find(left)
        root_right = find(right)
        if root_left == root_right:
            return False
        parents[root_right] = root_left
        return True

    tree_edges: list[EdgeProposal] = []
    adjacency: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for edge in accepted_pool:
        if not union(edge.src, edge.dst):
            continue
        tree_edges.append(edge)
        adjacency[edge.src].append((edge.dst, edge.delta))
        adjacency[edge.dst].append((edge.src, -edge.delta))
    positions: dict[int, int] = {0: 0}
    issues: list[str] = []
    queue: deque[int] = deque([0])
    while queue:
        current = queue.popleft()
        for neighbor, delta in adjacency.get(current, []):
            proposed = positions[current] + delta
            if neighbor not in positions:
                positions[neighbor] = proposed
                queue.append(neighbor)
    missing = sorted(index for index in range(frame_count) if index not in positions)
    if missing:
        issues.append(f"coverage gap: missing frames {', '.join(str(index) for index in missing)}")
    consistent_edges: list[EdgeProposal] = []
    for edge in accepted_pool:
        if edge.src not in positions or edge.dst not in positions:
            continue
        if edge.dst - edge.src > config.max_skip + 1:
            consistent_edges.append(edge)
            continue
        proposed = positions[edge.src] + edge.delta
        if abs(positions[edge.dst] - proposed) > config.cue_tolerance_px:
            rejected.append(edge)
            continue
        consistent_edges.append(edge)
    ordered_positions = [positions.get(index, 0) for index in range(frame_count)]
    min_position = min(ordered_positions) if ordered_positions else 0
    normalized_positions = [value - min_position for value in ordered_positions]
    spans = sorted((start, start + frame_height, index) for index, start in enumerate(normalized_positions) if index not in missing)
    current_end: int | None = None
    for start, end, _index in spans:
        if current_end is None:
            current_end = end
            continue
        if start > current_end + config.coverage_gap_px:
            issues.append(f"coverage gap from {current_end} to {start}")
        current_end = max(current_end, end)
    verdict = "complete" if not issues and len(positions) == frame_count else "incomplete"
    if verdict != "complete" and missing and len(accepted_pool) < frame_count - 1:
        issues.append("insufficient agreeing edges")
    return PoseSolution(
        positions=tuple(normalized_positions),
        accepted_edges=tuple(edge for edge in tree_edges if edge in consistent_edges),
        rejected_edges=tuple(rejected),
        issues=tuple(dict.fromkeys(issues)),
        coverage_verdict=verdict,
    )


def default_frame_sampler(video_path: str, frames_dir: str, config: ScrollshotConfig) -> Sequence[SampledFrame]:
    try:
        import cv2  # type: ignore
    except ImportError as exc:
        raise ScrollshotDependencyError("sample", "opencv-python is required for scrollshot sampling") from exc
    frame_dir = Path(frames_dir)
    frame_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise ScrollshotError("sample", "open", f"could not open video {clean_for_log(video_path)!r}")
    sampled: list[SampledFrame] = []
    last_index = -1
    last_frame: Any = None
    try:
        index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            last_index = index
            current = apply_masks(frame, config.chrome_top_px, config.cursor_boxes, cv2)
            keep = index == 0 or index % config.sample_every == 0
            if keep:
                out_path = frame_dir / f"frame_{index:05d}.png"
                if not cv2.imwrite(str(out_path), current):
                    raise ScrollshotError("sample", "write", f"could not write frame {clean_for_log(str(out_path))!r}")
                sampled.append(
                    SampledFrame(
                        index=len(sampled),
                        source_index=index,
                        path=str(out_path),
                        image=current,
                        width=int(current.shape[1]),
                        height=int(current.shape[0]),
                    )
                )
            last_frame = current
            index += 1
    finally:
        capture.release()
    if last_frame is None:
        raise ScrollshotError("sample", "empty", "scrollshot export requires a non-empty video")
    if sampled and sampled[-1].source_index != last_index:
        out_path = frame_dir / f"frame_{last_index:05d}.png"
        if not cv2.imwrite(str(out_path), last_frame):
            raise ScrollshotError("sample", "write", f"could not write frame {clean_for_log(str(out_path))!r}")
        sampled.append(
            SampledFrame(
                index=len(sampled),
                source_index=last_index,
                path=str(out_path),
                image=last_frame,
                width=int(last_frame.shape[1]),
                height=int(last_frame.shape[0]),
            )
        )
    return sampled


def _detect_fixed_top(frames: Sequence[SampledFrame], configured: int = 0) -> int:
    """Return a conservative viewport-fixed top band shared by moving frames."""
    floor = max(0, int(configured))
    if len(frames) < 2:
        return floor
    try:
        import numpy as np
    except ImportError:
        return floor
    candidates = list(zip(frames, frames[1:], strict=False))
    if len(frames) > 2:
        candidates.append((frames[0], frames[-1]))
    best_rows: Any = None
    best_score = 0.0
    for left, right in candidates:
        left_image = getattr(left, "image", None)
        right_image = getattr(right, "image", None)
        if not hasattr(left_image, "shape") or not hasattr(right_image, "shape") or left_image.shape != right_image.shape:
            continue
        difference = np.abs(left_image.astype("float32") - right_image.astype("float32"))
        axes = tuple(range(1, difference.ndim))
        row_difference = np.mean(difference, axis=axes)
        score = float(np.median(row_difference))
        if score > best_score:
            best_score = score
            best_rows = row_difference
    if best_rows is None or best_score < 0.75:
        return floor
    limit = min(int(best_rows.shape[0]) // 3, max(0, int(best_rows.shape[0]) - 16))
    threshold = max(0.75, best_score * 0.15)
    automatic = 0
    for row in range(limit):
        # Test the current row, not a look-ahead window.  A rolling window
        # crosses the first moving row early and under-crops the fixed band,
        # leaving sticky pixels in the alignment cues and the final mosaic.
        if float(best_rows[row]) > threshold:
            break
        automatic = row + 1
    if automatic < 4:
        automatic = 0
    if automatic <= floor:
        return floor
    first_image = getattr(frames[0], "image", None)
    if not hasattr(first_image, "shape"):
        return automatic
    row_means = np.mean(first_image.astype("float32"), axis=tuple(range(1, first_image.ndim)))
    transitions = np.abs(np.diff(row_means))
    window_start = max(floor, automatic - 16)
    window_stop = min(int(transitions.shape[0]), automatic + 1)
    if window_stop <= window_start:
        return automatic
    window = transitions[window_start:window_stop]
    strongest = float(window.max()) if window.size else 0.0
    if strongest < max(12.0, float(np.median(window)) * 4.0):
        return automatic
    return max(floor, int(np.argmax(window)) + window_start + 1)


def _resolve_tesseract_executable() -> str | None:
    candidates = [
        shutil.which("tesseract"),
        shutil.which("tesseract.exe"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def default_ocr_reader(frames: Sequence[SampledFrame], config: ScrollshotConfig) -> Sequence[OcrObservation]:
    executable = _resolve_tesseract_executable()
    if executable is None:
        raise ScrollshotDependencyError("ocr", "Tesseract executable is required for scrollshot OCR")
    observations: list[OcrObservation] = []
    content_top = _detect_fixed_top(frames, config.chrome_top_px)
    for frame in frames:
        try:
            result = subprocess.run(
                [executable, frame.path, "stdout", "-l", config.language, "tsv"],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            raise ScrollshotError("ocr", "timeout", f"tesseract timed out for frame {clean_for_log(frame.path)!r}") from exc
        if result.returncode != 0:
            raise ScrollshotError("ocr", "run", f"tesseract failed for frame {clean_for_log(frame.path)!r}")
        for row in csv.DictReader(result.stdout.splitlines(), delimiter="\t"):
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            try:
                confidence = float(row.get("conf", "-1"))
            except (TypeError, ValueError):
                confidence = -1.0
            if confidence < 0.0:
                continue
            top = int(row.get("top") or 0)
            if top < content_top:
                continue
            observations.append(
                OcrObservation(
                    frame_index=frame.index,
                    text=text,
                    top=top - content_top,
                    left=int(row.get("left") or 0),
                    width=int(row.get("width") or 0),
                    height=int(row.get("height") or 0),
                    confidence=confidence,
                )
            )
    return observations


def _text_overlap_delta(left: Sequence[OcrObservation], right: Sequence[OcrObservation]) -> EdgeCue | None:
    def anchor_key(item: OcrObservation) -> str | None:
        key = normalize_text(item.text)
        distinctive = "".join(character for character in key if character.isalnum())
        # Tiny/low-confidence glyphs are commonly emitted for icons and colour
        # swatches.  Matching two of those is not independent geometric proof
        # and previously bridged a real non-overlap gap in the H.264 E2E.
        if item.confidence < 40.0 or len(distinctive) < 4:
            return None
        return key

    left_candidates: dict[str, list[OcrObservation]] = defaultdict(list)
    for item in left:
        key = anchor_key(item)
        if key is not None:
            left_candidates[key].append(item)
    right_candidates: dict[str, list[OcrObservation]] = defaultdict(list)
    for item in right:
        key = anchor_key(item)
        if key is not None:
            right_candidates[key].append(item)
    deltas = [
        int(left_items[0].top - right_candidates[key][0].top)
        for key, left_items in left_candidates.items()
        if len(left_items) == 1 and len(right_candidates.get(key, ())) == 1
    ]
    if not deltas:
        return None
    counts = Counter(deltas)
    delta, support = counts.most_common(1)[0]
    return EdgeCue(name="ocr", delta=delta, confidence=float(support))


def _coerce_gray_float32(image: Any, cv2_mod: Any) -> Any:
    if not hasattr(image, "astype"):
        return image
    if getattr(image, "ndim", 0) == 3:
        if hasattr(cv2_mod, "cvtColor") and hasattr(cv2_mod, "COLOR_BGR2GRAY"):
            image = cv2_mod.cvtColor(image, cv2_mod.COLOR_BGR2GRAY)
        else:
            image = image[:, :, 0]
    return image.astype("float32")


def _bottom_strip_delta(source: Any, candidate: Any, cv2_mod: Any) -> EdgeCue | None:
    height = min(int(source.shape[0]), int(candidate.shape[0]))
    if height <= 0:
        return None
    strip_height = max(16, height // 4)
    strip_height = min(strip_height, height)
    template_top = int(source.shape[0]) - strip_height
    template = source[template_top:, :]
    if getattr(template, "size", 0) == 0:
        return None
    result = cv2_mod.matchTemplate(candidate, template, cv2_mod.TM_CCOEFF_NORMED)
    _min_value, max_value, _min_loc, max_loc = cv2_mod.minMaxLoc(result)
    return EdgeCue(name="template", delta=template_top - int(max_loc[1]), confidence=float(max_value))


def _phase_delta(source: Any, candidate: Any, cv2_mod: Any) -> EdgeCue | None:
    shift, score = cv2_mod.phaseCorrelate(source, candidate)
    return EdgeCue(name="phase", delta=int(round(-float(shift[1]))), confidence=float(score))


def default_edge_finder(
    frames: Sequence[SampledFrame],
    observations: Sequence[OcrObservation],
    config: ScrollshotConfig,
) -> Sequence[EdgeProposal]:
    try:
        import cv2  # type: ignore
    except ImportError as exc:
        raise ScrollshotDependencyError("align", "opencv-python is required for scrollshot alignment") from exc
    by_frame: dict[int, list[OcrObservation]] = defaultdict(list)
    for item in observations:
        by_frame[item.frame_index].append(item)
    content_top = _detect_fixed_top(frames, config.chrome_top_px)
    prepared = [_coerce_gray_float32(frame.image, cv2)[content_top:] for frame in frames]
    proposals: list[EdgeProposal] = []
    total = len(frames)
    for left_index, left in enumerate(frames):
        limit = min(total, left_index + config.max_skip + 2)
        for right_index in range(left_index + 1, limit):
            right = frames[right_index]
            left_gray = prepared[left_index]
            right_gray = prepared[right_index]
            forward = _bottom_strip_delta(left_gray, right_gray, cv2)
            reverse = _bottom_strip_delta(right_gray, left_gray, cv2)
            template_cue = forward
            if reverse is not None:
                reverse_cue = EdgeCue(name="template", delta=-reverse.delta, confidence=reverse.confidence)
                if template_cue is None or reverse_cue.confidence > template_cue.confidence:
                    template_cue = reverse_cue
            cues = []
            if template_cue is not None:
                cues.append(template_cue)
            phase_cue = _phase_delta(left_gray, right_gray, cv2)
            cues.append(phase_cue)
            text_cue = _text_overlap_delta(by_frame.get(left.index, []), by_frame.get(right.index, []))
            if text_cue is not None:
                cues.append(text_cue)
            delta, _group = _cluster_cues(cues, config.cue_tolerance_px)
            proposals.append(
                EdgeProposal(
                    src=left_index,
                    dst=right_index,
                    delta=int(delta),
                    confidence=sum(cue.confidence for cue in cues),
                    cues=tuple(cues),
                )
            )
        for right_index in range(left_index + config.revisit_min_gap, total):
            right = frames[right_index]
            text_cue = _text_overlap_delta(by_frame.get(left.index, []), by_frame.get(right.index, []))
            if text_cue is None or text_cue.confidence < 2.0:
                continue
            phase_cue = _phase_delta(prepared[left_index], prepared[right_index], cv2)
            delta, _group = _cluster_cues((text_cue, phase_cue), config.cue_tolerance_px)
            proposals.append(
                EdgeProposal(
                    src=left_index,
                    dst=right_index,
                    delta=delta,
                    confidence=text_cue.confidence + phase_cue.confidence,
                    cues=(text_cue, phase_cue),
                )
            )
            break
    return proposals


def default_composer(frames: Sequence[SampledFrame], positions: Sequence[int], out_path: str) -> str:
    try:
        from PIL import Image
    except ImportError as exc:
        raise ScrollshotDependencyError("compose", "Pillow is required for scrollshot composition") from exc
    opened = [Image.open(frame.path) for frame in frames]
    content_top = _detect_fixed_top(frames)
    separator_height = 4 if content_top >= 8 else 0
    width = max(image.width for image in opened)
    body_heights = [max(1, image.height - content_top) for image in opened]
    document_height = max(position + body_height for position, body_height in zip(positions, body_heights, strict=True))
    height = content_top + separator_height + document_height
    canvas = Image.new(opened[0].mode, (width, height))
    ordered = sorted(
        (
            (int(position), index, image, body_heights[index])
            for index, (position, image) in enumerate(zip(positions, opened, strict=True))
        ),
        key=lambda item: (item[0], item[1]),
    )
    if content_top:
        header_source = min(ordered, key=lambda item: (item[0], item[1]))[2]
        canvas.paste(header_source.crop((0, 0, header_source.width, content_top)), (0, 0))
    seams: list[int] = []
    for current, following in zip(ordered, ordered[1:], strict=False):
        current_start, _current_index, _current_image, current_height = current
        following_start, _following_index, _following_image, following_height = following
        current_end = current_start + current_height
        overlap_start = max(current_start, following_start)
        overlap_end = min(current_end, following_start + following_height)
        if overlap_start < overlap_end:
            seams.append((overlap_start + overlap_end) // 2)
        else:
            seams.append(current_end)
    for order_index, (position, _index, image, body_height) in enumerate(ordered):
        start = position if order_index == 0 else max(position, seams[order_index - 1])
        end = position + body_height if order_index == len(ordered) - 1 else min(position + body_height, seams[order_index])
        if end <= start:
            continue
        crop = image.crop((0, content_top + start - position, image.width, content_top + end - position))
        canvas.paste(crop, (0, content_top + separator_height + start))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(manifest_path: str | os.PathLike[str]) -> list[str]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    root = Path(manifest_path).parent
    mismatches: list[str] = []
    for logical_name, relative_path in manifest["files"].items():
        expected = manifest["hashes"].get(logical_name)
        if expected is None:
            continue
        actual = sha256_file(root / relative_path)
        if actual != expected:
            mismatches.append(logical_name)
    source_expected = manifest["hashes"]["source"]
    source_actual = sha256_file(manifest["source"]["path"])
    if source_actual != source_expected:
        mismatches.append("source")
    return mismatches


@dataclass
class ScrollshotExporter:
    out_root: str | os.PathLike[str]
    sampler: FrameSampler = default_frame_sampler
    ocr_reader: OcrReader = default_ocr_reader
    edge_finder: EdgeFinder = default_edge_finder
    composer: Composer = default_composer
    token_factory: Callable[[], str] = lambda: f"{os.getpid()}-{os.urandom(4).hex()}"
    hasher: Callable[[str | os.PathLike[str]], str] = sha256_file
    replace_dir: Callable[[str | os.PathLike[str], str | os.PathLike[str]], None] = staticmethod(os.replace)

    def export(
        self,
        *,
        source_path: str,
        config: ScrollshotConfig,
        job_ctx: JobContext,
    ) -> ScrollshotBundle:
        safe_source = ensure_local_media_input(source_path)
        source = Path(safe_source)
        if not source.is_file():
            raise ScrollshotError("source", "missing", f"video not found: {clean_for_log(safe_source)!r}")
        out_root = Path(self.out_root)
        out_root.mkdir(parents=True, exist_ok=True)
        bundle_id = f"{_slug(source.stem)}-{self.token_factory()}"
        stage_dir = Path(ensure_within(out_root, f".{bundle_id}.tmp"))
        final_dir = Path(ensure_within(out_root, bundle_id))
        if final_dir.exists():
            raise ScrollshotError("publish", "exists", f"bundle already exists: {final_dir.name}")
        job_ctx.raise_if_cancelled()
        job_ctx.progress(2, "Hashing source")
        source_sha = self.hasher(source)
        if stage_dir.exists():
            shutil.rmtree(stage_dir)
        stage_dir.mkdir(parents=True, exist_ok=False)
        try:
            job_ctx.raise_if_cancelled()
            job_ctx.progress(15, "Sampling frames")
            frames = list(self.sampler(str(source), str(stage_dir / "frames"), config))
            if not frames:
                raise ScrollshotError("sample", "empty", "no sampled frames were produced")
            content_top = _detect_fixed_top(frames, config.chrome_top_px)
            frame_height = max(1, frames[0].height - content_top)
            job_ctx.raise_if_cancelled()
            job_ctx.progress(35, "Reading OCR")
            observations = list(self.ocr_reader(frames, config))
            job_ctx.raise_if_cancelled()
            job_ctx.progress(55, "Finding overlaps")
            edges = list(self.edge_finder(frames, observations, config))
            pose = solve_pose_graph(len(frames), frame_height, edges, config)
            if pose.coverage_verdict != "complete" and config.assurance == "strict":
                raise ScrollshotError("coverage", "incomplete", "; ".join(pose.issues) or "coverage incomplete")
            job_ctx.raise_if_cancelled()
            job_ctx.progress(72, "Composing long screenshot")
            image_name = "long-screenshot.png"
            image_path = self.composer(frames, pose.positions, str(stage_dir / image_name))
            if not isinstance(image_path, str):
                raise ScrollshotError("compose", "invalid", "composer returned a non-path result")
            lines, conflicts = compose_markdown_lines(observations, pose.positions)
            markdown_name = "scrollshot.md"
            markdown_path = stage_dir / markdown_name
            markdown_path.write_text(
                render_markdown(
                    config=config,
                    source_path=str(source),
                    bundle_id=bundle_id,
                    coverage_verdict=pose.coverage_verdict,
                    issues=pose.issues,
                    lines=lines,
                    conflicts=conflicts,
                ),
                encoding="utf-8",
            )
            observations_name = "observations.json"
            observations_path = stage_dir / observations_name
            observations_path.write_text(
                json.dumps(
                    [
                        {
                            "frameIndex": item.frame_index,
                            "text": item.text,
                            "top": item.top,
                            "left": item.left,
                            "width": item.width,
                            "height": item.height,
                            "confidence": item.confidence,
                            "absoluteTop": pose.positions[item.frame_index] + item.top,
                        }
                        for item in observations
                    ],
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            conflicts_name = "conflicts.json"
            conflicts_path = stage_dir / conflicts_name
            conflicts_path.write_text(
                json.dumps(
                    [
                        {
                            "absoluteTop": item.absolute_top,
                            "chosenText": item.chosen_text,
                            "alternateTexts": list(item.alternate_texts),
                            "sourceFrames": list(item.source_frames),
                        }
                        for item in conflicts
                    ],
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manifest_name = "manifest.json"
            manifest_path = stage_dir / manifest_name
            manifest = {
                "kind": KIND,
                "bundleId": bundle_id,
                "source": {"path": str(source)},
                "options": {
                    "title": config.title,
                    "language": config.language,
                    "assurance": config.assurance,
                },
                "coverage": {
                    "verdict": pose.coverage_verdict,
                    "issues": list(pose.issues),
                    "positions": list(pose.positions),
                    "acceptedEdges": [
                        {
                            "src": edge.src,
                            "dst": edge.dst,
                            "delta": edge.delta,
                            "confidence": edge.confidence,
                            "cues": [{"name": cue.name, "delta": cue.delta, "confidence": cue.confidence} for cue in edge.cues],
                        }
                        for edge in pose.accepted_edges
                    ],
                    "rejectedEdges": [
                        {"src": edge.src, "dst": edge.dst, "delta": edge.delta, "confidence": edge.confidence}
                        for edge in pose.rejected_edges
                    ],
                },
                "files": {
                    "markdown": markdown_name,
                    "image": Path(image_path).name,
                    "observations": observations_name,
                    "conflicts": conflicts_name,
                    "manifest": manifest_name,
                },
                "hashes": {
                    "source": source_sha,
                    "markdown": self.hasher(markdown_path),
                    "image": self.hasher(image_path),
                    "observations": self.hasher(observations_path),
                    "conflicts": self.hasher(conflicts_path),
                },
            }
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
            job_ctx.raise_if_cancelled()
            job_ctx.progress(92, "Verifying evidence bundle")
            mismatches = verify_manifest(manifest_path)
            if mismatches:
                raise ScrollshotError("verify", "hash", f"hash mismatch for {', '.join(mismatches)}")
            self.replace_dir(str(stage_dir), str(final_dir))
            final_manifest = final_dir / manifest_name
            mismatches = verify_manifest(final_manifest)
            if mismatches:
                raise ScrollshotError("verify", "hash", f"hash mismatch after publish for {', '.join(mismatches)}")
            job_ctx.progress(100, "Scrollshot export complete")
            return ScrollshotBundle(
                bundle_id=bundle_id,
                bundle_dir=str(final_dir),
                manifest_path=str(final_manifest),
                markdown_path=str(final_dir / markdown_name),
                image_path=str(final_dir / Path(image_path).name),
                observations_path=str(final_dir / observations_name),
                conflicts_path=str(final_dir / conflicts_name),
                coverage_verdict=pose.coverage_verdict,
                coverage_issues=pose.issues,
                source_sha256=source_sha,
                markdown_sha256=manifest["hashes"]["markdown"],
                image_sha256=manifest["hashes"]["image"],
            )
        except Exception:
            if stage_dir.exists():
                shutil.rmtree(stage_dir)
            raise


__all__ = [
    "ConflictRecord",
    "EdgeCue",
    "EdgeProposal",
    "FrameSampler",
    "KIND",
    "MarkdownLine",
    "OcrObservation",
    "PoseSolution",
    "SampledFrame",
    "ScrollshotBundle",
    "ScrollshotConfig",
    "ScrollshotDependencyError",
    "ScrollshotError",
    "ScrollshotExporter",
    "apply_masks",
    "compose_markdown_lines",
    "default_composer",
    "default_edge_finder",
    "default_frame_sampler",
    "default_ocr_reader",
    "escape_markdown_text",
    "load_config",
    "normalize_text",
    "render_markdown",
    "sha256_file",
    "solve_pose_graph",
    "verify_manifest",
]
