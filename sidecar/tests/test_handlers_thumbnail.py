"""Tests for the WU-C3 ``thumbnail.select`` handler (AI best-frame picker).

Heavy-free: the frame loader, the frame scorer, and the cv2 writer are injected
as fakes (no cv2, no model, no network). The job runs on a real JobRegistry and
its ``job.done.result`` is asserted. The frame-egress consent path reuses the
SAME vision pool + fake transport idiom as test_handlers_phase8.py, so a
non-consented run is proven to never touch the (fake) vision transport.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers
from media_studio.features import shorts as sh
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.protocol import ErrorCode, RpcContext, RpcError


# --------------------------------------------------------------------------- #
# fakes / seams
# --------------------------------------------------------------------------- #
class FakeProvider:
    def chat(self, *args: Any, **kwargs: Any) -> str:
        return "[]"

    def exemplar_block(self, language: str | None = None) -> str | None:
        return None

    def calibrated_pct(self, raw: float) -> int | None:
        return None


def _fake_loader(path: str, spans: Any) -> list[Any]:
    """One synthetic 3-frame stack for the single requested span (no cv2)."""
    return [[f"f0@{lo}-{hi}", f"f1@{lo}-{hi}", f"f2@{lo}-{hi}"] for lo, hi in spans]


class RecordingScorer:
    """A FrameScorer recording its calls; returns canned per-frame scores."""

    def __init__(self, scores: list[float]) -> None:
        self._scores = scores
        self.calls: list[tuple[int, str]] = []

    def __call__(self, frames: Any, prompt: str) -> list[float]:
        self.calls.append((len(list(frames)), prompt))
        return list(self._scores)


class RecordingWriter:
    """A ThumbnailWriter recording every ``(frame, path)`` it is asked to write."""

    def __init__(self) -> None:
        self.writes: list[tuple[Any, str]] = []

    def __call__(self, frame: Any, path: str) -> None:
        self.writes.append((frame, path))


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    p = tmp_path / "talk.mp4"
    p.write_bytes(b"\x00fake")
    return p


def _services(tmp_path: Path, **over: Any) -> Services:
    base: dict[str, Any] = {
        "data_dir": tmp_path / "data",
        "ffmpeg_run": lambda argv, **k: 0,
        "ffprobe_duration": lambda p: 12.0,
        "provider": FakeProvider(),
        "vlm_clip_frame_loader": _fake_loader,
        "vlm_frame_encoder": lambda frame: f"ENC<{frame}>",
        "vlm_models_present": lambda s: False,
    }
    base.update(over)
    return Services(**base)


def _ctx() -> RpcContext:
    events: list[Any] = []
    jobs = JobRegistry(
        emit_progress=lambda jid, pct, msg: events.append(("progress", jid, pct, msg)),
        emit_done=lambda jid, result: events.append(("done", jid, result)),
    )
    context = RpcContext(emit_notification=lambda obj: None, jobs=jobs)
    context.events = events  # type: ignore[attr-defined]
    return context


def _add_video(services: Services, video_file: Path) -> str:
    from media_studio import library as _library

    services.library = _library.Library(services.data_dir / "library.json", probe_duration=lambda _p: 12.0)
    video = services.library.add(str(video_file))
    return video["id"]


def _done_result(ctx: RpcContext) -> dict[str, Any]:
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    assert done, "job never completed"
    return done[-1][2]


# --------------------------------------------------------------------------- #
# registration (AC a)
# --------------------------------------------------------------------------- #
def test_register_all_wires_thumbnail_select(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "thumbnail.select" in registered


# --------------------------------------------------------------------------- #
# happy path: explicit span, scorer picks argmax, writer + metadata recorded
# --------------------------------------------------------------------------- #
def test_thumbnail_select_picks_argmax_writes_and_records(tmp_path: Path, video_file: Path) -> None:
    scorer = RecordingScorer([0.1, 0.9, 0.3])  # argmax index 1
    writer = RecordingWriter()
    svc = _services(tmp_path, frame_scorer=scorer, thumbnail_writer=writer)
    ctx = _ctx()
    vid = _add_video(svc, video_file)
    out = svc.thumbnail_select({"videoId": vid, "path": str(video_file), "start": 0.0, "end": 6.0}, ctx)
    assert "jobId" in out
    ctx.jobs.join(timeout=5)
    result = _done_result(ctx)
    assert set(result) == {"frameTimeSec", "thumbnailPath", "score", "degraded"}
    assert result["degraded"] is False
    # 3 frames over [0,6): times [0,2,4]; argmax index 1 -> 2.0
    assert result["frameTimeSec"] == 2.0
    assert result["score"] == 0.9
    assert result["thumbnailPath"] == str(sh.thumbnail_path(str(video_file)))
    # the argmax frame was written to the thumbnail target
    assert len(writer.writes) == 1
    assert writer.writes[0][1] == str(sh.thumbnail_path(str(video_file)))
    # thumbnailFrameSec persisted on the clip metadata
    assert sh.read_metadata(str(video_file))["thumbnailFrameSec"] == 2.0


# --------------------------------------------------------------------------- #
# AC (b): degrade-to-midpoint — no consent + no weights -> midpoint, no scorer
# --------------------------------------------------------------------------- #
def test_thumbnail_select_degrades_to_midpoint_zero_egress(tmp_path: Path, video_file: Path) -> None:
    # No frame_scorer injected + vlm_models_present False + no vision provider ->
    # _resolve_frame_scorer returns None -> deterministic midpoint, no scorer call.
    writer = RecordingWriter()
    svc = _services(tmp_path, thumbnail_writer=writer)
    ctx = _ctx()
    vid = _add_video(svc, video_file)
    svc.thumbnail_select({"videoId": vid, "path": str(video_file), "start": 2.0, "end": 8.0}, ctx)
    ctx.jobs.join(timeout=5)
    result = _done_result(ctx)
    assert result["degraded"] is True
    assert result["frameTimeSec"] == 5.0  # midpoint of [2,8]
    assert result["score"] == 0.0
    # zero egress: nothing written (no frame chosen), midpoint persisted anyway
    assert writer.writes == []
    assert sh.read_metadata(str(video_file))["thumbnailFrameSec"] == 5.0


# --------------------------------------------------------------------------- #
# AC (d): a second identical call is a cache hit (scorer NOT invoked twice)
# --------------------------------------------------------------------------- #
def test_thumbnail_select_second_call_is_cache_hit(tmp_path: Path, video_file: Path) -> None:
    scorer = RecordingScorer([0.2, 0.2, 0.8])
    writer = RecordingWriter()
    svc = _services(tmp_path, frame_scorer=scorer, thumbnail_writer=writer)
    ctx = _ctx()
    vid = _add_video(svc, video_file)
    params = {"videoId": vid, "path": str(video_file), "start": 0.0, "end": 3.0}
    svc.thumbnail_select(dict(params), ctx)
    ctx.jobs.join(timeout=5)
    first = _done_result(ctx)
    assert len(scorer.calls) == 1
    # second identical call -> cache hit: scorer not invoked again, same payload.
    ctx2 = _ctx()
    svc.thumbnail_select(dict(params), ctx2)
    ctx2.jobs.join(timeout=5)
    second = _done_result(ctx2)
    assert len(scorer.calls) == 1, "scorer re-invoked on a cache hit"
    assert second == first


# --------------------------------------------------------------------------- #
# AC (f): cancel before scoring leaves no thumbnail written
# --------------------------------------------------------------------------- #
def test_thumbnail_select_cancel_before_scoring_writes_nothing(tmp_path: Path, video_file: Path) -> None:
    import threading

    scorer = RecordingScorer([0.5, 0.5, 0.5])
    writer = RecordingWriter()
    entered = threading.Event()
    released = threading.Event()

    def _blocking_loader(path: str, spans: Any) -> list[Any]:
        # Block inside the loader so the test can cancel the job AFTER sampling
        # starts but BEFORE the post-load cancel checkpoint runs (deterministic).
        entered.set()
        released.wait(timeout=5)
        return _fake_loader(path, spans)

    svc = _services(
        tmp_path,
        frame_scorer=scorer,
        thumbnail_writer=writer,
        vlm_clip_frame_loader=_blocking_loader,
    )
    ctx = _ctx()
    vid = _add_video(svc, video_file)
    res = svc.thumbnail_select({"videoId": vid, "path": str(video_file), "start": 0.0, "end": 3.0}, ctx)
    entered.wait(timeout=5)  # the loader has begun
    ctx.jobs.cancel(res["jobId"])  # cancel WHILE the loader is blocked
    released.set()  # let the loader return; the post-load check sees cancelled
    ctx.jobs.join(timeout=5)
    # cancelled before scoring -> scorer never called, nothing written.
    assert scorer.calls == []
    assert writer.writes == []


# --------------------------------------------------------------------------- #
# candidate-id resolution (vs explicit span)
# --------------------------------------------------------------------------- #
def test_thumbnail_select_resolves_candidate_id_from_cache(tmp_path: Path, video_file: Path) -> None:
    scorer = RecordingScorer([0.9, 0.1, 0.1])  # argmax index 0
    writer = RecordingWriter()
    svc = _services(tmp_path, frame_scorer=scorer, thumbnail_writer=writer)
    ctx = _ctx()
    vid = _add_video(svc, video_file)
    cand = {"rank": 1, "sourceStart": 4.0, "start": 0.0, "end": 10.0}
    cid = svc.candidate_id(cand)
    svc._cache_candidates(vid, [cand])
    svc.thumbnail_select({"videoId": vid, "candidateId": cid}, ctx)
    ctx.jobs.join(timeout=5)
    result = _done_result(ctx)
    # span [4,10): 3 frames -> times [4,6,8]; argmax index 0 -> 4.0
    assert result["frameTimeSec"] == 4.0
    assert len(writer.writes) == 1


def test_thumbnail_select_unknown_candidate_id_raises(tmp_path: Path, video_file: Path) -> None:
    svc = _services(tmp_path, frame_scorer=RecordingScorer([1.0]))
    ctx = _ctx()
    vid = _add_video(svc, video_file)
    with pytest.raises(RpcError) as ei:
        svc.thumbnail_select({"videoId": vid, "candidateId": "9@9.0"}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_thumbnail_select_candidate_id_unknown_video_raises(tmp_path: Path) -> None:
    svc = _services(tmp_path, frame_scorer=RecordingScorer([1.0]))
    ctx = _ctx()
    # cache a candidate under a video id whose library entry does not exist, so the
    # candidate resolves but the media path does not.
    cand = {"rank": 1, "sourceStart": 0.0, "start": 0.0, "end": 2.0}
    cid = svc.candidate_id(cand)
    svc._cache_candidates("ghost", [cand])
    with pytest.raises(RpcError) as ei:
        svc.thumbnail_select({"videoId": "ghost", "candidateId": cid}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_thumbnail_select_requires_span_or_candidate(tmp_path: Path, video_file: Path) -> None:
    svc = _services(tmp_path)
    ctx = _ctx()
    vid = _add_video(svc, video_file)
    with pytest.raises(RpcError) as ei:
        svc.thumbnail_select({"videoId": vid}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_thumbnail_select_requires_jobs(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    nojobs = RpcContext(emit_notification=lambda obj: None, jobs=None)
    with pytest.raises(RpcError) as ei:
        svc.thumbnail_select({"videoId": "x", "path": "/v.mp4"}, nojobs)
    assert ei.value.code == ErrorCode.INTERNAL_ERROR


# --------------------------------------------------------------------------- #
# no frames sampled -> picker degrades to a zero-time result (no write)
# --------------------------------------------------------------------------- #
def test_thumbnail_select_no_frames_zero_result(tmp_path: Path, video_file: Path) -> None:
    scorer = RecordingScorer([])
    writer = RecordingWriter()
    svc = _services(
        tmp_path,
        frame_scorer=scorer,
        thumbnail_writer=writer,
        vlm_clip_frame_loader=lambda path, spans: [[]],  # one empty frame stack
    )
    ctx = _ctx()
    vid = _add_video(svc, video_file)
    svc.thumbnail_select({"videoId": vid, "path": str(video_file), "start": 0.0, "end": 4.0}, ctx)
    ctx.jobs.join(timeout=5)
    result = _done_result(ctx)
    assert result["frameTimeSec"] == 0.0
    assert result["score"] == 0.0
    assert writer.writes == []  # no frame to write


def test_thumbnail_select_loader_returns_no_stacks(tmp_path: Path, video_file: Path) -> None:
    # The loader returns an EMPTY list (no stack at all) -> stack=[] branch.
    scorer = RecordingScorer([])
    writer = RecordingWriter()
    svc = _services(
        tmp_path,
        frame_scorer=scorer,
        thumbnail_writer=writer,
        vlm_clip_frame_loader=lambda path, spans: [],
    )
    ctx = _ctx()
    vid = _add_video(svc, video_file)
    svc.thumbnail_select({"videoId": vid, "path": str(video_file), "start": 0.0, "end": 4.0}, ctx)
    ctx.jobs.join(timeout=5)
    result = _done_result(ctx)
    assert result["frameTimeSec"] == 0.0
    assert writer.writes == []


# --------------------------------------------------------------------------- #
# WU-C3 scorer resolution decision tree (mirrors _resolve_vlm_reranker)
# --------------------------------------------------------------------------- #
def _vision_provider_settings(*, with_consent: bool) -> dict[str, Any]:
    return {
        "confirmCloudBudget": False,
        "providers": [
            {
                "id": "gemini",
                "provider": "Gemini",
                "kind": "cloud",
                "baseUrl": "https://example/v1",
                "model": "gemini-flash",
                "apiKeys": ["sk-vision-key-9999"],
                "enabled": True,
                "capabilities": ["text", "vision"],
                "unit": "req",
            }
        ],
        "routing": {"perFunction": {"vision": {"provider": "gemini", "fallback": []}}},
        "consent": {"perProvider": {"Gemini": {"frames": with_consent}}},
    }


class VisionTransport:
    """Fake chat transport; records base64 frame egress (mirrors phase8 test)."""

    def __init__(self, content: str = "1") -> None:
        self.content = content
        self.calls: list[dict[str, Any]] = []
        self.saw_base64 = False

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        self.calls.append({"url": url, "body": body})
        for msg in body.get("messages", []):
            content = msg.get("content")
            if isinstance(content, list):
                for part in content:
                    is_image = isinstance(part, dict) and part.get("type") == "image_url"
                    if is_image and "base64," in str(part.get("image_url", {}).get("url", "")):
                        self.saw_base64 = True
        return {"choices": [{"message": {"role": "assistant", "content": self.content}}]}


def test_resolve_frame_scorer_cloud_when_consent_granted(tmp_path: Path) -> None:
    transport = VisionTransport(content="2")  # model picks frame #2 (1-based)
    svc = _services(
        tmp_path,
        provider=None,
        vlm_chat_transport=transport,
        vlm_models_present=lambda s: False,
    )
    svc.settings.set(_vision_provider_settings(with_consent=True))
    scorer = svc._resolve_frame_scorer(svc.settings.get())
    assert scorer is not None
    # invoking the resolved scorer drives the consented cloud vision pool -> frames egress.
    scores = scorer(["frameA", "frameB", "frameC"], "best?")
    assert transport.calls, "cloud vision pool was never called"
    assert transport.saw_base64 is True
    assert len(scores) == 3


def test_resolve_frame_scorer_off_without_consent(tmp_path: Path) -> None:
    transport = VisionTransport()
    svc = _services(
        tmp_path,
        provider=None,
        vlm_chat_transport=transport,
        vlm_models_present=lambda s: False,
    )
    svc.settings.set(_vision_provider_settings(with_consent=False))
    # no consent + no local weights -> None (degrade), the vision transport untouched.
    assert svc._resolve_frame_scorer(svc.settings.get()) is None
    assert transport.calls == []


# --------------------------------------------------------------------------- #
# OFFLINE ENFORCEMENT (bug fix): offline forbids cloud frame egress even when the
# provider is fully frame-consented. The cloud branch is skipped so the resolver
# degrades to the local scorer (weights present) or None (degrade-to-midpoint).
# --------------------------------------------------------------------------- #
def test_resolve_frame_scorer_offline_skips_cloud_uses_local(tmp_path: Path) -> None:
    transport = VisionTransport(content="2")

    class _LocalBackend:
        """A fake LOCAL vlm backend: scores frames without any network."""

        def __init__(self) -> None:
            self.calls = 0

        def rank_clips(self, stacks: Any, prompt: str) -> list[float]:
            self.calls += 1
            return [0.5 for _ in list(stacks)]

    local_backend = _LocalBackend()
    svc = _services(
        tmp_path,
        provider=None,
        vlm_chat_transport=transport,
        vlm_models_present=lambda s: True,  # local weights present
        frame_backend_factory=lambda _s: local_backend,
    )
    svc.settings.set({**_vision_provider_settings(with_consent=True), "offline": True})
    scorer = svc._resolve_frame_scorer(svc.settings.get())
    assert scorer is not None
    # Invoke it: the LOCAL backend scores, the CLOUD vision transport stays untouched.
    scores = scorer(["a", "b"], "best?")
    assert local_backend.calls == 1, "offline did not route to the local backend"
    assert transport.calls == [], "frames egressed to cloud while offline"
    assert len(scores) == 2


def test_resolve_frame_scorer_offline_no_weights_is_none(tmp_path: Path) -> None:
    transport = VisionTransport(content="2")
    svc = _services(
        tmp_path,
        provider=None,
        vlm_chat_transport=transport,
        vlm_models_present=lambda s: False,
    )
    svc.settings.set({**_vision_provider_settings(with_consent=True), "offline": True})
    # offline + consented cloud + no local weights -> None (degrade-to-midpoint).
    assert svc._resolve_frame_scorer(svc.settings.get()) is None
    assert transport.calls == []


def test_thumbnail_select_offline_no_frame_egress(tmp_path: Path, video_file: Path) -> None:
    # End-to-end: offline + a fully frame-consented cloud vision provider + no
    # local weights -> degrade-to-midpoint, the cloud vision transport NEVER hit.
    transport = VisionTransport(content="2")
    svc = _services(
        tmp_path,
        provider=None,
        vlm_chat_transport=transport,
        vlm_models_present=lambda s: False,
    )
    svc.settings.set({**_vision_provider_settings(with_consent=True), "offline": True})
    vid = _add_video(svc, video_file)
    ctx = _ctx()
    svc.thumbnail_select({"videoId": vid, "path": str(video_file), "start": 0.0, "end": 4.0}, ctx)
    ctx.jobs.join(timeout=5)
    result = _done_result(ctx)
    assert transport.calls == [], "frames egressed while offline"
    assert result["degraded"] is True


def _two_vision_provider_settings(*, first_consent: bool, second_consent: bool) -> dict[str, Any]:
    """Two vision-capable cloud providers, each with its OWN frame-consent flag.

    Mirrors the phase8 rotation-bypass fixture: Gemini (routed first) and OpenAI
    are both vision-capable; the regression case is the FIRST frame-consented but
    429-ing, the SECOND NOT frame-consented — proving frame rotation can never
    reach the non-consented one (the consent filter drops it at pool build).
    """
    return {
        "confirmCloudBudget": False,
        "providers": [
            {
                "id": "gemini",
                "provider": "Gemini",
                "kind": "cloud",
                "baseUrl": "https://gemini.example/v1",
                "model": "gemini-flash",
                "apiKeys": ["sk-gemini-1111"],
                "enabled": True,
                "capabilities": ["text", "vision"],
                "unit": "req",
            },
            {
                "id": "openai",
                "provider": "OpenAI",
                "kind": "cloud",
                "baseUrl": "https://openai.example/v1",
                "model": "gpt-4o-mini",
                "apiKeys": ["sk-openai-2222"],
                "enabled": True,
                "capabilities": ["text", "vision"],
                "unit": "req",
            },
        ],
        "routing": {"perFunction": {"vision": {"provider": "gemini", "fallback": []}}},
        "consent": {
            "perProvider": {
                "Gemini": {"frames": first_consent},
                "OpenAI": {"frames": second_consent},
            }
        },
    }


class RotatingVisionTransport:
    """Fake chat transport that 429s the consented provider and records ALL targets.

    Raises ``ProviderError("LLM HTTP 429: ...")`` for any request whose URL contains
    ``fail_host`` (forcing the pool to rotate). Every request's target host is
    recorded, and the hosts that received base64 FRAMES are recorded separately, so
    a test can assert a non-consented host NEVER received a frame (AC c).
    """

    def __init__(self, *, fail_host: str) -> None:
        self._fail_host = fail_host
        self.hosts: list[str] = []
        self.frame_hosts: list[str] = []

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        self.hosts.append(url)
        saw_base64 = any(
            isinstance(part, dict)
            and part.get("type") == "image_url"
            and "base64," in str(part.get("image_url", {}).get("url", ""))
            for msg in body.get("messages", [])
            if isinstance(msg.get("content"), list)
            for part in msg["content"]
        )
        if saw_base64:
            self.frame_hosts.append(url)
        if self._fail_host in url:
            from media_studio.models.provider import ProviderError

            raise ProviderError("LLM HTTP 429: rate limited; retry-after=60")
        return {"choices": [{"message": {"role": "assistant", "content": "0"}}]}


def test_resolve_frame_scorer_never_egresses_to_non_consented_provider(tmp_path: Path) -> None:
    # AC (c) — privacy CRITICAL: two vision-capable cloud providers — Gemini (routed
    # first, frame-consented) and OpenAI (vision-capable, NO frame consent). Gemini
    # 429s; the frame scorer's pool must NOT fail over to OpenAI with frames, because
    # OpenAI's frame consent was never granted. The consent filter drops OpenAI at
    # pool build, so it is never even a rotation candidate. Mirrors the proven
    # phase8 rotation-bypass test for the re-ranker.
    transport = RotatingVisionTransport(fail_host="gemini.example")
    svc = _services(
        tmp_path,
        provider=None,
        vlm_chat_transport=transport,
        vlm_models_present=lambda s: False,
    )
    svc.settings.set(_two_vision_provider_settings(first_consent=True, second_consent=False))

    from media_studio.models.provider import ProviderError

    scorer = svc._resolve_frame_scorer(svc.settings.get())
    assert scorer is not None
    # invoking the resolved scorer drives the vision pool; Gemini 429s, then the pool
    # exhausts (no eligible consented fallback) — a ProviderError surfaces, but the
    # invariant under test is WHERE frames went, asserted on the recorded hosts.
    with pytest.raises(ProviderError):
        scorer(["frameA", "frameB", "frameC"], "best?")

    # the non-consented provider (OpenAI) was NEVER reached at all, with or w/o frames.
    assert not any("openai.example" in h for h in transport.hosts), "rotated to a non-consented provider"
    assert all("gemini.example" in h for h in transport.frame_hosts), "frame egress reached a non-consented host"
    # and the consented Gemini WAS attempted with frames (the leak path is otherwise vacuous).
    assert any("gemini.example" in h for h in transport.frame_hosts), "consented provider was never tried"


def test_resolve_frame_scorer_pool_contains_only_frame_consented_cloud_entries(tmp_path: Path) -> None:
    # AC (c) direct: with Gemini consented and OpenAI not, the cloud egress pool the
    # frame scorer builds has EXACTLY {Gemini} as its vision-capable cloud entries.
    svc = _services(tmp_path, provider=None, vlm_chat_transport=RotatingVisionTransport(fail_host="none"))
    svc.settings.set(_two_vision_provider_settings(first_consent=True, second_consent=False))
    raw = svc.settings.get_raw()
    pool = svc._vision_pool(svc._frame_consented_vision_settings(raw))
    cloud_vision = [e.provider for e in pool.entries if not e.local and "vision" in e.capabilities]
    assert cloud_vision == ["Gemini"], "non-consented vision provider leaked into the pool"


def test_resolve_frame_scorer_local_when_weights_present(tmp_path: Path) -> None:
    class FakeBackend:
        def __init__(self) -> None:
            self.calls = 0

        def rank_clips(self, frames_per_clip: Any, prompt: str) -> list[float]:
            self.calls += 1
            return [float(i) for i in range(len(list(frames_per_clip)))]

    backend = FakeBackend()
    svc = _services(
        tmp_path,
        provider=None,
        vlm_models_present=lambda s: True,  # local weights present
        frame_backend_factory=lambda settings: backend,
    )
    scorer = svc._resolve_frame_scorer(svc.settings.get())
    assert scorer is not None
    scores = scorer(["a", "b"], "p")
    assert backend.calls == 1
    assert scores == [0.0, 1.0]


def test_resolve_frame_scorer_injected_seam_wins(tmp_path: Path) -> None:
    injected = RecordingScorer([1.0])
    svc = _services(tmp_path, frame_scorer=injected)
    assert svc._resolve_frame_scorer(svc.settings.get()) is injected


# --------------------------------------------------------------------------- #
# default heavy seams resolve to the native impls (not exercised under the gate)
# --------------------------------------------------------------------------- #
def test_default_frame_seams_are_lazy(tmp_path: Path) -> None:
    # With no injection the loader/writer resolvers return the native default
    # callables (coverage-excluded prod seams) — assert identity without calling.
    svc = Services(data_dir=tmp_path / "d")
    from media_studio.features import best_frame as _bf
    from media_studio.features import smolvlm2 as _sv

    assert svc._frame_clip_loader() is _sv._default_clip_frame_loader
    assert svc._frame_thumbnail_writer() is _bf._default_thumbnail_writer


# --------------------------------------------------------------------------- #
# _evenly_spaced pure helper
# --------------------------------------------------------------------------- #
def test_evenly_spaced_distributes_and_degrades() -> None:
    assert handlers._evenly_spaced(0.0, 6.0, 3) == [0.0, 2.0, 4.0]
    assert handlers._evenly_spaced(0.0, 4.0, 0) == []
    assert handlers._evenly_spaced(5.0, 5.0, 2) == [5.0, 5.0]  # zero-length span
    assert handlers._evenly_spaced(2.0, 4.0, 1) == [2.0]
