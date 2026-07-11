"""Audio-track management — ``tracks.audio.*`` (CONTRACTS.md A2/A3, T2).

Wire surface (names FROZEN by A2)::

    tracks.audio.list({videoId})                       -> {audioTracks:[AudioTrack]}
    tracks.audio.mux({videoId, path, lang, name, kind}) -> {audioTrack}
    tracks.audio.replace({videoId, audioTrackId, path}) -> {audioTrack}
    tracks.audio.strip({videoId, audioTrackId})         -> {path}

Schema (A3, field names FROZEN)::

    AudioTrack {id, lang, name, kind:"original"|"dub", voice?, path}
    Project.audioTracks: [AudioTrack]

Design rules straight from the contract + A6 lessons:

* **mux PRESERVES existing subtitle + audio streams** — the argv maps ALL of
  input 0 (``-map 0``) plus the new audio (``-map 1:a``) under stream copy;
  nothing is re-encoded and nothing is dropped.
* argv LISTS only (lesson 4); the ffmpeg run goes through the injectable
  :func:`media_studio.ffmpeg.run` seam (stderr drained on a thread, lesson 2).
* the manifest entries persist on the video's Project (``audioTracks``) via
  an injected project store, so the list survives restarts (round-tripped in
  tests).

CONTRACT-NOTE (paths): a *dub* AudioTrack's ``path`` is the standalone audio
file (the AAC the dub pipeline produced); an *original* row's ``path`` is the
container itself. Registering a track (``mux`` / ``mux_for_dub``) is a MANIFEST
edit only — the dub's audio is muxed into each exported clip on demand by the
export MUX-AUDIO stage (``shortmaker._lazy_mux_audio``, reading
``audioTrack.path``), so no derivative container is written here (a prior remux
produced an orphaned copy no consumer ever read). ``replace``/``strip`` DO write
a new container beside the source, but only for *originals* (real container
streams); the source file is never modified — refs are by path.

CONTRACT-NOTE (stream indices): only *original* rows correspond to real audio
streams inside the resolved container — they are seeded from an ffprobe sniff in
stream order, so an original's ``a:<n>`` index is its position AMONG THE
ORIGINALS (:func:`original_stream_index`), NOT its position in the full
``audioTracks`` list (which also counts dubs). A *dub* is NOT a container stream
at all (its audio lives in a standalone file), so ``replace``/``strip`` on a dub
are manifest-only edits — never a container remux against a stream that is not
there.
"""

from __future__ import annotations

import builtins
import json
import subprocess  # noqa: S404 - argv-list ffprobe sniff only, never shell=True
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import ffmpeg, protocol
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import get_logger

log = get_logger("media_studio.tracks_audio")

#: A3 AudioTrack (frozen field names)
AudioTrack = dict[str, Any]

KIND_ORIGINAL = "original"
KIND_DUB = "dub"
_KINDS = (KIND_ORIGINAL, KIND_DUB)

# Injectable seams (mirroring the sibling feature modules):
RunFn = Callable[..., int]
DurationFn = Callable[..., float]
# (path, settings) -> the parsed ffprobe JSON dict ({} on failure).
ProbeFn = Callable[..., dict[str, Any]]
# videoId -> absolute media path (or None when unknown).
Resolver = Callable[[str], str | None]
# Project persistence seam: load(videoId) -> manifest dict; save(videoId, dict).
LoadProject = Callable[[str], dict[str, Any]]
SaveProject = Callable[[str, dict[str, Any]], None]


class AudioTrackError(Exception):
    """An audio-track operation failed (bad input, missing track, ffmpeg exit)."""


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


# --------------------------------------------------------------------------- #
# pure: the A3 model + manifest edits
# --------------------------------------------------------------------------- #
def normalize_audio_track(track: dict[str, Any]) -> AudioTrack:
    """Backfill a dict to the full A3 AudioTrack schema (frozen field names).

    ``kind`` must be ``"original"`` or ``"dub"``; a typo never produces an
    untyped row. ``voice`` is optional and kept only when present (A3's
    ``voice?``).
    """
    if not isinstance(track, dict):
        raise AudioTrackError("audio track must be an object")
    kind = track.get("kind", KIND_DUB)
    if kind not in _KINDS:
        raise AudioTrackError(f"audioTrack.kind must be 'original' or 'dub', got {kind!r}")
    normalized: AudioTrack = {
        "id": str(track.get("id") or _new_id()),
        "lang": str(track.get("lang") or "und"),
        "name": str(track.get("name") or "Audio"),
        "kind": kind,
        "path": str(track.get("path") or ""),
    }
    if track.get("voice"):
        normalized["voice"] = str(track["voice"])
    return normalized


def audio_tracks_of(project: dict[str, Any]) -> list[AudioTrack]:
    """The project's ``audioTracks`` list, created when absent (A3)."""
    tracks = project.setdefault("audioTracks", [])
    if not isinstance(tracks, list):
        raise AudioTrackError("project.audioTracks must be a list")
    return tracks


def find_audio_track(project: dict[str, Any], track_id: str) -> AudioTrack:
    """The track whose ``id == track_id`` or raise."""
    for track in audio_tracks_of(project):
        if isinstance(track, dict) and track.get("id") == track_id:
            return track
    raise AudioTrackError(f"no such audio track: {track_id}")


def audio_track_index(project: dict[str, Any], track_id: str) -> int:
    """The track's position in ``audioTracks`` == its container ``a:<n>`` index."""
    for i, track in enumerate(audio_tracks_of(project)):
        if isinstance(track, dict) and track.get("id") == track_id:
            return i
    raise AudioTrackError(f"no such audio track: {track_id}")


def original_audio_count(project: dict[str, Any]) -> int:
    """The number of ``KIND_ORIGINAL`` rows == the resolved container's real
    audio-stream count.

    Only originals correspond to actual audio streams inside the resolved
    container (dubs live in standalone files, delivered by the export re-mux —
    see the module note). So this — NOT ``len(audioTracks)`` — is the true input
    audio-stream count that ffmpeg sees on the container.
    """
    return sum(
        1
        for t in audio_tracks_of(project)
        if isinstance(t, dict) and t.get("kind") == KIND_ORIGINAL
    )


def original_stream_index(project: dict[str, Any], track_id: str) -> int:
    """The original track's TRUE ``a:<n>`` index among the container's streams.

    An original's real container index is its position *among the originals*
    (seeded from ffprobe in container order), NOT its position in the full
    ``audioTracks`` list — which also counts dubs that are NOT container streams.
    Raises when ``track_id`` is not an original row.
    """
    n = 0
    for t in audio_tracks_of(project):
        if isinstance(t, dict) and t.get("kind") == KIND_ORIGINAL:
            if t.get("id") == track_id:
                return n
            n += 1
    raise AudioTrackError(f"no such original audio track: {track_id}")


def add_audio_track(project: dict[str, Any], track: dict[str, Any]) -> AudioTrack:
    """Append a normalized track (idempotent on an existing id)."""
    normalized = normalize_audio_track(track)
    tracks = audio_tracks_of(project)
    for existing in tracks:
        if isinstance(existing, dict) and existing.get("id") == normalized["id"]:
            return existing
    tracks.append(normalized)
    return normalized


def remove_audio_track(project: dict[str, Any], track_id: str) -> AudioTrack:
    """Remove + return the track (raises when absent)."""
    track = find_audio_track(project, track_id)
    project["audioTracks"] = [
        t for t in audio_tracks_of(project) if not (isinstance(t, dict) and t.get("id") == track_id)
    ]
    return track


# --------------------------------------------------------------------------- #
# pure: ffmpeg argv builders (A6 lesson 4 — argv lists, spaces safe)
# --------------------------------------------------------------------------- #
def build_mux_argv(
    in_video: str,
    in_audio: str,
    out_path: str,
    *,
    lang: str | None = None,
    existing_audio_count: int = 0,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """argv ADDING ``in_audio`` as a new audio stream (A2 ``tracks.audio.mux``).

    ``-map 0`` keeps EVERY stream of the source — video, all existing audio
    AND all subtitle streams (the contract's "mux preserves existing
    subtitle+audio streams"); ``-map 1:a`` appends the new audio; ``-c copy``
    re-encodes nothing. The new stream (audio index ``existing_audio_count``)
    gets its language tag when ``lang`` is given.
    """
    argv: list[str] = [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_video,
        "-i",
        in_audio,
        "-map",
        "0",
        "-map",
        "1:a",
        "-c",
        "copy",
    ]
    if lang:
        argv += [f"-metadata:s:a:{int(existing_audio_count)}", f"language={lang}"]
    argv += ["-progress", "pipe:1", "-nostats", out_path]
    return argv


def build_replace_argv(
    in_video: str,
    in_audio: str,
    out_path: str,
    *,
    stream_index: int,
    lang: str | None = None,
    existing_audio_count: int = 0,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """argv swapping audio stream ``a:<stream_index>`` for ``in_audio``.

    Everything else (video, other audio, subtitles) is preserved via
    ``-map 0`` + the negative map of the one replaced stream; the new audio
    is appended under stream copy.

    ``existing_audio_count`` is the container's real audio-stream count. The
    replaced stream is dropped and the new audio is appended LAST, so the
    replacement lands at output audio index ``existing_audio_count - 1``; the
    language tag targets ONLY that stream (a blanket ``-metadata:s:a`` would
    relabel every surviving audio stream's language — CONTRACTS.md A3).
    """
    if stream_index < 0:
        raise AudioTrackError("stream_index must be >= 0")
    argv: list[str] = [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_video,
        "-i",
        in_audio,
        "-map",
        "0",
        "-map",
        f"-0:a:{int(stream_index)}",
        "-map",
        "1:a",
        "-c",
        "copy",
    ]
    if lang:
        out_index = max(int(existing_audio_count) - 1, 0)
        argv += [f"-metadata:s:a:{out_index}", f"language={lang}"]
    argv += ["-progress", "pipe:1", "-nostats", out_path]
    return argv


def build_strip_audio_argv(
    in_video: str,
    out_path: str,
    *,
    stream_index: int,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """argv re-muxing the container WITHOUT audio stream ``a:<stream_index>``.

    All other streams (video, remaining audio, subtitles) are copied — the
    audio twin of ``tracks.strip`` (A2 ``tracks.audio.strip`` -> ``{path}``).
    """
    if stream_index < 0:
        raise AudioTrackError("stream_index must be >= 0")
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_video,
        "-map",
        "0",
        "-map",
        f"-0:a:{int(stream_index)}",
        "-c",
        "copy",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]


# --------------------------------------------------------------------------- #
# ffprobe sniff for seeding "original" rows (injectable; mirrors media_compat)
# --------------------------------------------------------------------------- #
def probe_streams(
    in_path: str,
    settings: dict[str, Any] | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """ffprobe ``-show_streams`` JSON for ``in_path`` (``{}`` on any failure)."""
    argv = [
        ffmpeg.ffprobe_path(settings),
        "-v",
        "error",
        "-show_streams",
        "-of",
        "json",
        in_path,
    ]
    completed = runner(argv, capture_output=True, text=True, check=False)
    if getattr(completed, "returncode", 1) != 0:
        log.warning(
            "ffprobe stream sniff failed for %s (exit %s): %s",
            in_path,
            getattr(completed, "returncode", None),
            (getattr(completed, "stderr", "") or "").strip(),
        )
        return {}
    try:
        data = json.loads(getattr(completed, "stdout", "") or "")
    except ValueError:
        log.warning("ffprobe stream sniff returned unparseable JSON for %s", in_path)
        return {}
    return data if isinstance(data, dict) else {}


def original_tracks_from_probe(probe: dict[str, Any], video_path: str) -> list[AudioTrack]:
    """Seed A3 'original' rows from an ffprobe result (pure, container order)."""
    out: list[AudioTrack] = []
    streams = probe.get("streams")
    if not isinstance(streams, list):
        return out
    n = 0
    for stream in streams:
        if not isinstance(stream, dict) or stream.get("codec_type") != "audio":
            continue
        n += 1
        tags = stream.get("tags") or {}
        lang = tags.get("language") if isinstance(tags, dict) else None
        title = tags.get("title") if isinstance(tags, dict) else None
        out.append(
            normalize_audio_track(
                {
                    "id": _new_id(),
                    "lang": lang or "und",
                    "name": title or f"Audio {n}",
                    "kind": KIND_ORIGINAL,
                    "path": video_path,
                }
            )
        )
    return out


# --------------------------------------------------------------------------- #
# the service
# --------------------------------------------------------------------------- #
class AudioTracksService:
    """Owns the four A2 methods + the manifest persistence around them."""

    def __init__(
        self,
        *,
        resolver: Resolver,
        load_project: LoadProject,
        save_project: SaveProject,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        run: RunFn | None = None,
        duration: DurationFn | None = None,
        probe: ProbeFn | None = None,
    ) -> None:
        self._resolver = resolver
        self._load_project = load_project
        self._save_project = save_project
        self._settings_provider = settings_provider or (lambda: {})
        self._run: RunFn = run or ffmpeg.run
        self._duration: DurationFn = duration or ffmpeg.ffprobe_duration
        self._probe: ProbeFn = probe or probe_streams
        # Per-video locks guard the reload->mutate->save critical section so a
        # job-thread mux and a concurrent main-loop replace/strip on the SAME
        # video can't clobber each other's manifest write (never held across the
        # long ffmpeg run — see replace/strip).
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # -- internals --------------------------------------------------------------
    def _lock_for(self, video_id: str) -> threading.Lock:
        """Return (creating on first use) the per-video manifest lock."""
        with self._locks_guard:
            lock = self._locks.get(video_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[video_id] = lock
            return lock

    def _settings(self) -> dict[str, Any]:
        try:
            return dict(self._settings_provider() or {})
        except Exception:  # noqa: BLE001 - settings must never break an op
            return {}

    def _resolve(self, video_id: str) -> str:
        path = self._resolver(video_id)
        if not path:
            raise _invalid(f"unknown video: {video_id}")
        return str(path)

    def _seed_originals(self, project: dict[str, Any], video_id: str, video_path: str) -> bool:
        """Seed 'original' rows from ffprobe on first contact. Returns changed?"""
        tracks = audio_tracks_of(project)
        if any(isinstance(t, dict) and t.get("kind") == KIND_ORIGINAL for t in tracks):
            return False
        try:
            probe = self._probe(video_path, self._settings()) or {}
        except Exception:  # noqa: BLE001 - a probe crash means no originals, not a 500
            log.warning("audio stream sniff failed for %s", video_path)
            return False
        if not probe:
            # An empty probe is a SILENT ffprobe failure (bad path / transient),
            # NOT the same as a video that genuinely has no audio streams (a
            # non-empty probe with zero audio rows). Make the failure observable
            # so tracks.audio.list isn't wrongly reported as an audio-less video.
            log.warning("audio stream sniff produced no data for %s", video_path)
        originals = original_tracks_from_probe(probe, video_path)
        if not originals:
            return False
        # Originals come FIRST (container stream order — see module note).
        project["audioTracks"] = originals + tracks
        return True

    def _run_or_raise(self, argv: builtins.list[str], in_path: str, what: str) -> None:
        total = 0.0
        try:
            total = float(self._duration(in_path, self._settings()))
        except Exception:  # noqa: BLE001 - probe failure only coarsens progress
            pass
        code = self._run(argv, total_sec=total)
        if code != 0:
            raise RpcError(f"{what} failed (ffmpeg exit {code})", ErrorCode.INTERNAL_ERROR)

    @staticmethod
    def _derived_path(video_path: str, suffix: str) -> str:
        p = Path(video_path)
        stamp = int(time.time())
        return str(p.with_name(f"{p.stem}-{suffix}-{stamp}{p.suffix}"))

    # -- A2 handlers --------------------------------------------------------------
    def list(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.audio.list({videoId})`` -> ``{audioTracks}`` (A2)."""
        video_id = _require_str(params, "videoId")
        video_path = self._resolve(video_id)
        project = self._load_project(video_id)
        if self._seed_originals(project, video_id, video_path):
            self._save_project(video_id, project)
        return {"audioTracks": [dict(t) for t in audio_tracks_of(project)]}

    def mux(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.audio.mux({videoId, path, lang, name, kind})`` -> ``{audioTrack}``."""
        video_id = _require_str(params, "videoId")
        audio_path = _require_str(params, "path")
        lang = _require_str(params, "lang")
        name = _require_str(params, "name")
        kind = params.get("kind", KIND_DUB)
        if not Path(audio_path).is_file():
            raise _invalid(f"audio file not found: {audio_path}")
        try:
            track = self._mux_impl(video_id, audio_path, lang, name, kind, voice=None)
        except AudioTrackError as exc:
            raise _invalid(str(exc)) from exc
        return {"audioTrack": track}

    def replace(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.audio.replace({videoId, audioTrackId, path})`` -> ``{audioTrack}``.

        A DUB's audio is a standalone file (delivered at export), NOT a stream in
        the resolved container — so replacing it is a manifest edit (swap the
        path). Only an ORIGINAL is a real container stream; that path re-muxes
        the container, swapping its TRUE ``a:<n>`` index (:func:`original_stream_index`
        — NOT the dub-inclusive list index) and tagging only the appended stream.
        """
        video_id = _require_str(params, "videoId")
        track_id = _require_str(params, "audioTrackId")
        audio_path = _require_str(params, "path")
        if not Path(audio_path).is_file():
            raise _invalid(f"audio file not found: {audio_path}")
        video_path = self._resolve(video_id)
        with self._lock_for(video_id):
            project = self._load_project(video_id)
            try:
                track = find_audio_track(project, track_id)
            except AudioTrackError as exc:
                raise _invalid(str(exc)) from exc
            if track.get("kind") == KIND_DUB:
                # Dub: swap the standalone-file reference; no container remux.
                track["path"] = audio_path
                self._save_project(video_id, project)
                return {"audioTrack": dict(track)}
            index = original_stream_index(project, track_id)
            lang = track.get("lang")
            existing = original_audio_count(project)
        out_path = self._derived_path(video_path, f"aud-replace-{track_id}")
        argv = build_replace_argv(
            video_path,
            audio_path,
            out_path,
            stream_index=index,
            lang=lang,
            existing_audio_count=existing,
            settings=self._settings(),
        )
        self._run_or_raise(argv, video_path, "audio replace")
        # RE-LOAD after the (unlocked) ffmpeg run so a concurrent manifest write
        # that landed during it is not clobbered — apply only this op's delta.
        with self._lock_for(video_id):
            project = self._load_project(video_id)
            fresh = find_audio_track(project, track_id)
            fresh["path"] = audio_path
            self._save_project(video_id, project)
            return {"audioTrack": dict(fresh)}

    def strip(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.audio.strip({videoId, audioTrackId})`` -> ``{path}`` (A2).

        A DUB is not a container stream (its audio is a standalone file), so
        dropping it is a manifest edit and the container is returned unchanged.
        An ORIGINAL is re-muxed out by its TRUE container ``a:<n>`` index.
        """
        video_id = _require_str(params, "videoId")
        track_id = _require_str(params, "audioTrackId")
        video_path = self._resolve(video_id)
        with self._lock_for(video_id):
            project = self._load_project(video_id)
            try:
                track = find_audio_track(project, track_id)
            except AudioTrackError as exc:
                raise _invalid(str(exc)) from exc
            if track.get("kind") == KIND_DUB:
                # Dub: not in the container -> manifest-only removal; the
                # container (resolved source) is unchanged, so return it as-is.
                remove_audio_track(project, track_id)
                self._save_project(video_id, project)
                return {"path": video_path}
            index = original_stream_index(project, track_id)
        out_path = self._derived_path(video_path, f"noaud-{track_id}")
        argv = build_strip_audio_argv(video_path, out_path, stream_index=index, settings=self._settings())
        self._run_or_raise(argv, video_path, "audio strip")
        # RE-LOAD after the (unlocked) ffmpeg run so a concurrent manifest write
        # is not clobbered — apply only this op's delta (the row removal).
        with self._lock_for(video_id):
            project = self._load_project(video_id)
            remove_audio_track(project, track_id)
            self._save_project(video_id, project)
            return {"path": out_path}

    # -- the dub pipeline's entry (NOT a wire method) ------------------------------
    def mux_for_dub(
        self,
        video_id: str,
        audio_path: str,
        *,
        lang: str,
        name: str,
        voice: str | None = None,
    ) -> AudioTrack:
        """Mux a finished dub + persist its AudioTrack (used by tts.dub.start)."""
        return self._mux_impl(video_id, audio_path, lang, name, KIND_DUB, voice=voice)

    def _mux_impl(
        self,
        video_id: str,
        audio_path: str,
        lang: str,
        name: str,
        kind: str,
        *,
        voice: str | None,
    ) -> AudioTrack:
        video_path = self._resolve(video_id)
        track = normalize_audio_track(
            {
                "id": _new_id(),
                "lang": lang,
                "name": name,
                "kind": kind,
                "path": audio_path,
                "voice": voice,
            }
        )
        # Registering an audio track is a MANIFEST edit only: the dub's audio
        # lives in ``audio_path`` (a standalone AAC) and is muxed into each
        # exported clip on demand by the export MUX-AUDIO stage
        # (shortmaker._lazy_mux_audio, from ``audioTrack.path``). A full-container
        # remux here produced a derivative that no consumer ever read — an
        # orphaned, unbounded, untracked copy beside every source (wasted compute
        # + a leak). So no ffmpeg runs; delivery happens at export.
        with self._lock_for(video_id):
            project = self._load_project(video_id)
            self._seed_originals(project, video_id, video_path)
            add_audio_track(project, track)
            self._save_project(video_id, project)
        log.info("registered audio track %s (path=%s)", track["id"], audio_path)
        return dict(track)


# --------------------------------------------------------------------------- #
# registration (the wiring agent calls this from handlers.register_all)
# --------------------------------------------------------------------------- #
def register(
    *,
    resolver: Resolver,
    load_project: LoadProject,
    save_project: SaveProject,
    settings_provider: Callable[[], dict[str, Any]] | None = None,
    run: RunFn | None = None,
    duration: DurationFn | None = None,
    probe: ProbeFn | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> AudioTracksService:
    """Create the service and register the four frozen A2 methods.

    ``register_fn`` defaults to :func:`protocol.register` (duplicates fail
    loudly); tests inject a fake. Returns the service — the wiring agent
    passes it on to ``features.tts.register(audio_tracks=...)``.
    """
    service = AudioTracksService(
        resolver=resolver,
        load_project=load_project,
        save_project=save_project,
        settings_provider=settings_provider,
        run=run,
        duration=duration,
        probe=probe,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("tracks.audio.list", service.list)
    reg("tracks.audio.mux", service.mux)
    reg("tracks.audio.replace", service.replace)
    reg("tracks.audio.strip", service.strip)
    log.info("registered tracks.audio.list / mux / replace / strip")
    return service


__all__ = [
    "KIND_ORIGINAL",
    "KIND_DUB",
    "AudioTrack",
    "AudioTrackError",
    "AudioTracksService",
    "add_audio_track",
    "audio_track_index",
    "audio_tracks_of",
    "build_mux_argv",
    "build_replace_argv",
    "build_strip_audio_argv",
    "find_audio_track",
    "normalize_audio_track",
    "original_audio_count",
    "original_stream_index",
    "original_tracks_from_probe",
    "probe_streams",
    "register",
    "remove_audio_track",
]
