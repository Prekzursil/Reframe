"""E2E-AI2: Intelligence + Repurpose + Editing-refine over the REAL stack.

These are integration tests, not unit doubles. The sidecar's real JSON-RPC
dispatch, real handlers, real consent/budget gates, real ffmpeg, and the REAL
provider/embedder HTTP code all run. The ONLY fake is the model endpoint: a local
OpenAI-compatible :class:`MockModelServer` the provider reaches over a real socket
with no cloud key (``e2e_ai2_mock_model``). Where a flow's model is a native
weight that cannot run here (the diarizer's VAD+ECAPA, the VLM frame encoder/
decoder), the heavy seam is faked but the surrounding logic (clustering, label
carry, best-frame pick, jpg write) is exercised for real.

Each flow ASSERTS the model was actually hit (``server.hits``) so a silent
local-fallback can never masquerade as a passing egress test.

Run: ``python -m pytest sidecar/tests/test_e2e_ai2_intel_repurpose.py``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers, protocol
from media_studio import library as _library
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext
from media_studio.settings_store import INJECTED_KEYS_FIELD

from tests.e2e_ai2_mock_model import MockModelServer

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")
# OPT-IN: tagged ``e2e`` so the default sidecar gate (addopts ``-m 'not e2e'``)
# DESELECTS this whole module (never collected/run by the 100%-coverage gate);
# the skipif still guards the explicit ``pytest -m e2e`` run when ffmpeg is absent.
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not (_FFMPEG and _FFPROBE),
        reason="ffmpeg/ffprobe required for the E2E-AI2 real-media flows",
    ),
]


# --------------------------------------------------------------------------- #
# in-process JSON-RPC drive (the REAL parse -> dispatch -> handler path)
# --------------------------------------------------------------------------- #
class Rpc:
    """Drive the real handlers through their RPC service object + a real JobRegistry.

    ``call`` invokes a direct-return method and returns its result. ``run_job``
    invokes a job-returning method and blocks on the registry until ``job.done``,
    returning the done result.
    """

    def __init__(self, svc: Services, *, keys: dict[str, list[str]] | None = None) -> None:
        self.svc = svc
        # WU-D2b-2 CONSUME: this drive STANDS IN for the Electron main process,
        # which persists provider keys only as redacted MARKERS and re-injects the
        # DPAPI-decrypted raw keys under ``_injectedKeys`` on EVERY provider-calling
        # request (``_key_overlay_wrapper`` then makes ``get_raw()`` see them for
        # that request only). We LEARN keys from provider writes and re-inject them.
        self.keys: dict[str, list[str]] = {k: list(v) for k, v in (keys or {}).items()}
        self.events: list[Any] = []
        self.jobs = JobRegistry(
            emit_progress=lambda jid, pct, msg: self.events.append(("progress", jid, pct, msg)),
            emit_done=lambda jid, result: self.events.append(("done", jid, result)),
        )
        self.ctx = RpcContext(emit_notification=lambda obj: None, jobs=self.jobs)

    def _handler(self, method: str) -> Any:
        fn = protocol.METHODS.get(method)
        assert fn is not None, f"method not registered: {method}"
        return fn

    def _learn_keys(self, method: str, params: dict[str, Any]) -> None:
        """Capture raw keys from provider WRITES (as main does on upsert/save)."""
        if not isinstance(params, dict):
            return
        entries: list[Any]
        if method == "providers.upsert":
            nested = params.get("provider")
            entries = [nested if isinstance(nested, dict) else params]
        elif isinstance(params.get("providers"), list):
            entries = [p for p in params["providers"] if isinstance(p, dict)]
        else:
            entries = []
        for entry in entries:
            pid, api_keys = entry.get("id"), entry.get("apiKeys")
            if isinstance(pid, str) and isinstance(api_keys, list):
                self.keys[pid] = [str(k) for k in api_keys]

    def _inject(self, params: dict[str, Any]) -> dict[str, Any]:
        """Attach the learned raw keys as ``_injectedKeys`` (main's per-request path)."""
        if self.keys and isinstance(params, dict) and INJECTED_KEYS_FIELD not in params:
            return {**params, INJECTED_KEYS_FIELD: {"providers": {k: list(v) for k, v in self.keys.items()}}}
        return params

    def call(self, method: str, params: dict[str, Any]) -> Any:
        self._learn_keys(method, params)
        return self._handler(method)(self._inject(params), self.ctx)

    def run_job(self, method: str, params: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
        out = self.call(method, params)
        assert isinstance(out, dict) and "jobId" in out, f"{method} did not return a jobId: {out!r}"
        self.jobs.join(timeout=timeout)
        done = [e for e in self.events if e[0] == "done" and e[1] == out["jobId"]]
        assert done, f"{method} job {out['jobId']} never completed: {self.events!r}"
        return done[-1][2]


# --------------------------------------------------------------------------- #
# real-media fixtures (built with real ffmpeg)
# --------------------------------------------------------------------------- #
def _ffmpeg(args: list[str]) -> None:
    res = subprocess.run([_FFMPEG, "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    assert res.returncode == 0, f"ffmpeg failed: {res.stderr}"


def _make_landscape_clip(path: Path, *, seconds: int = 6) -> None:
    """A real 16:9 1280x720 clip: moving testsrc video + a tone, so ffprobe is happy."""
    _ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=1280x720:rate=24:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ]
    )


def _make_audio_with_silence(path: Path) -> None:
    """Real audio: tone -> silence -> tone, so silencedetect finds a real gap."""
    _ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=660:duration=2",
            "-filter_complex",
            "[0][1][2]concat=n=3:v=0:a=1[a]",
            "-map",
            "[a]",
            "-c:a",
            "aac",
            str(path),
        ]
    )


def _ffprobe_dims(path: str) -> tuple[int, int]:
    res = subprocess.run(
        [
            _FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    stream = json.loads(res.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


# --------------------------------------------------------------------------- #
# settings + project helpers
# --------------------------------------------------------------------------- #
def _cloud_settings(base_url: str, *, capabilities: list[str], model: str = "mock-model") -> dict[str, Any]:
    """A provider entry pointed at the mock, fully consented + routed (no budget gate)."""
    return {
        "confirmCloudBudget": False,
        "cloudModel": model,
        "providers": [
            {
                "id": "mock",
                "provider": "MockAI",
                "kind": "cloud",
                "baseUrl": base_url,
                "model": model,
                "apiKeys": ["sk-e2e-ai2-mock-key"],
                "enabled": True,
                "capabilities": capabilities,
                "unit": "req",
            }
        ],
        "routing": {
            "perFunction": {
                fn: {"provider": "mock", "fallback": []} for fn in ("index", "editPlan", "vision", "select")
            }
        },
        "consent": {"perProvider": {"MockAI": {"text": True, "frames": True}}},
    }


def _keyring(settings: dict[str, Any]) -> dict[str, list[str]]:
    """The ``{providerId: [rawKey, ...]}`` main would DPAPI-inject per request.

    Extracted from a settings dict's provider entries so the :class:`Rpc` drive
    re-injects the raw keys (the at-rest store keeps only redacted markers under
    WU-D2b-2, so the factory seams only egress with a live key when it is
    re-injected — exactly the production main-process behaviour)."""
    providers = settings.get("providers")
    out: dict[str, list[str]] = {}
    for prov in providers if isinstance(providers, list) else []:
        pid, api_keys = prov.get("id"), prov.get("apiKeys")
        if isinstance(pid, str) and isinstance(api_keys, list):
            out[pid] = [str(k) for k in api_keys]
    return out


def _new_services(tmp: Path, **over: Any) -> Services:
    return Services(data_dir=tmp / "data", **over)


def _add_video(svc: Services, media: Path, *, transcript: dict[str, Any] | None = None) -> str:
    svc.library = _library.Library(svc.data_dir / "library.json", probe_duration=lambda _p: 6.0)
    vid = svc.library.add(str(media))["id"]
    if transcript is not None:
        project = svc._load_or_create_project(vid)
        project.data["transcript"] = transcript
        project.save()
    return vid


def _transcript() -> dict[str, Any]:
    return {
        "language": "en",
        "durationSec": 6.0,
        "segments": [
            {
                "start": 0.0,
                "end": 2.0,
                "text": "we talk about pricing and revenue here",
                "words": [
                    {"text": "um", "start": 0.0, "end": 0.2},
                    {"text": "we", "start": 0.2, "end": 0.5},
                    {"text": "talk", "start": 0.5, "end": 0.9},
                    {"text": "about", "start": 0.9, "end": 1.2},
                    {"text": "pricing", "start": 1.2, "end": 1.6},
                    {"text": "and", "start": 1.6, "end": 1.7},
                    {"text": "revenue", "start": 1.7, "end": 1.9},
                    {"text": "here", "start": 1.9, "end": 2.0},
                ],
            },
            {
                "start": 4.0,
                "end": 6.0,
                "text": "now a totally different topic about cats",
                "words": [
                    {"text": "now", "start": 4.0, "end": 4.3},
                    {"text": "a", "start": 4.3, "end": 4.4},
                    {"text": "totally", "start": 4.4, "end": 4.8},
                    {"text": "different", "start": 4.8, "end": 5.2},
                    {"text": "topic", "start": 5.2, "end": 5.5},
                    {"text": "about", "start": 5.5, "end": 5.7},
                    {"text": "cats", "start": 5.7, "end": 6.0},
                ],
            },
        ],
    }


# ========================================================================== #
# INTELLIGENCE (a) — semantic index: embed via /v1/embeddings, cosine search
# ========================================================================== #
def test_intel_semantic_positive_control_real_embedder_over_http(tmp_path: Path) -> None:
    """POSITIVE CONTROL: index.build + index.search over a REAL CloudEmbedder/HTTP.

    The capability itself (real /v1/embeddings egress -> persisted vectors ->
    cosine-ranked search) is proven by injecting a REAL
    :class:`embedder.CloudEmbedder` with a VALID raw key and NO transport (so it
    opens a real socket to the mock). This pins the wire protocol / vector
    persistence / cosine ranking directly at the embedder seam; the sibling
    ``test_intel_semantic_settings_driven_egress_over_http`` proves the SAME egress
    through the full settings-driven resolver (with the per-request key injection).
    """
    from media_studio.models import embedder as _embedder

    media = tmp_path / "talk.mp4"
    _make_landscape_clip(media)
    with MockModelServer() as server:
        real_embedder = _embedder.CloudEmbedder(
            api_key="sk-e2e-ai2-mock-key",
            base_url=server.base_url,
            model="mock-model",
            transport=None,  # real urllib socket to the mock
        )
        svc = _new_services(tmp_path, embedder=real_embedder)
        protocol.clear_methods()
        handlers.register_all(services=svc)
        svc.settings.set(_cloud_settings(server.base_url, capabilities=["text"]))
        vid = _add_video(svc, media, transcript=_transcript())
        rpc = Rpc(svc)

        built = rpc.run_job("index.build", {"videoId": vid})
        assert built["segmentCount"] == 2
        assert built["model"] == "mock-model"  # the routed cloud model, NOT "local"
        assert server.hits["embeddings"] >= 1, "index.build never reached the mock /v1/embeddings"

        hits_after_build = server.hits["embeddings"]
        out = rpc.call("index.search", {"videoId": vid, "query": "pricing revenue", "topK": 2})
        assert server.hits["embeddings"] == hits_after_build + 1, "search did not embed the query via the mock"
        assert len(out["hits"]) == 2
        # cosine-ranked: the pricing/revenue segment outranks the cats segment.
        assert out["hits"][0]["text"] == "we talk about pricing and revenue here"
        assert out["hits"][0]["score"] >= out["hits"][1]["score"]


def test_intel_semantic_settings_driven_egress_over_http(tmp_path: Path) -> None:
    """The settings-DRIVEN index egress (no injected embedder) — the real client path.

    Providers/consent/routing live in settings, no seam override. ``index.build``
    resolves the embedder through :meth:`_resolve_index_embedder`, which reads the
    RAW keys via ``get_raw()`` (handlers ``index_build`` captures ``get_raw()``
    synchronously up front). Under WU-D2b-2 the at-rest store keeps only redacted
    MARKERS, so the RAW key reaches the wire ONLY when main re-injects it per
    request under ``_injectedKeys`` — which the :class:`Rpc` drive replicates (it
    LEARNS the keys the settings carry and re-injects them on every call). With the
    key present the transcript egresses cleanly to /v1/embeddings with the routed
    model; OMITTING the injection is what leaves a corrupt ``Bearer …-key`` marker
    on the wire (the historical "redacted key" symptom), so this test proves the
    real client path egresses correctly when the key is injected as in production.
    """
    media = tmp_path / "talk.mp4"
    _make_landscape_clip(media)
    with MockModelServer() as server:
        svc = _new_services(tmp_path)
        protocol.clear_methods()
        handlers.register_all(services=svc)
        cloud = _cloud_settings(server.base_url, capabilities=["text"])
        svc.settings.set(cloud)
        vid = _add_video(svc, media, transcript=_transcript())
        rpc = Rpc(svc, keys=_keyring(cloud))

        built = rpc.run_job("index.build", {"videoId": vid})
        # A real cloud egress with the routed model (NOT the "local" no-egress fallback).
        assert built["model"] == "mock-model"
        assert server.hits["embeddings"] >= 1
        # The egress carried the RAW key (re-injected per request), never a marker.
        assert server.auth_headers.get("embeddings") == "Bearer sk-e2e-ai2-mock-key", (
            f"index egress did not carry the RAW key: {server.auth_headers.get('embeddings')!r}"
        )


# ========================================================================== #
# INTELLIGENCE (a') — director.plan: REAL chat egress -> valid EditPlan JSON.
# This is the path-SPECIFICITY control for the redacted-key bug above: the chat
# factory (_provider_for_function -> get_provider(get_raw())) uses RAW keys, so
# the SAME settings-driven egress that FAILS for embeddings SUCCEEDS here. That
# proves the embeddings failure is the get()-vs-get_raw() defect, not the mock.
# ========================================================================== #
def test_intel_director_plan_real_chat_editplan_over_http(tmp_path: Path) -> None:
    media = tmp_path / "talk.mp4"
    _make_landscape_clip(media)
    with MockModelServer() as server:
        svc = _new_services(tmp_path)
        protocol.clear_methods()
        handlers.register_all(services=svc)
        cloud = _cloud_settings(server.base_url, capabilities=["text"])
        svc.settings.set(cloud)
        vid = _add_video(svc, media, transcript=_transcript())
        rpc = Rpc(svc, keys=_keyring(cloud))

        done = rpc.run_job("director.plan", {"videoId": vid, "goal": "tighten this into a punchy short"})
        # The mock returned a valid EditPlan JSON; the real parser + validator accepted it.
        assert server.hits["chat"] >= 1, "director.plan never reached the mock /v1/chat/completions"
        assert isinstance(done.get("planId"), str) and done["planId"]
        kinds = [op["kind"] for op in done["editPlan"]["ops"]]
        assert kinds == ["removeSilence", "trim", "caption"], f"EditPlan ops not parsed/validated: {kinds!r}"
        # The Director request carried the structural untrusted-data fence (injection
        # mitigation #1) — proof the real prompt builder, not a shortcut, ran.
        sent = server.last_bodies["chat"]["messages"]
        assert any("UNTRUSTED_MEDIA_DATA" in str(m.get("content", "")) for m in sent)


# ========================================================================== #
# INTELLIGENCE (b) — system.recommend: REAL device-detect + a recommendation
# ========================================================================== #
def test_intel_recommender_real_device_detect(tmp_path: Path) -> None:
    svc = _new_services(tmp_path)
    protocol.clear_methods()
    handlers.register_all(services=svc)
    rpc = Rpc(svc)
    out = rpc.call("system.recommend", {"commercial": False})
    rec = out["recommendation"]
    assert isinstance(rec, dict) and rec, "empty recommendation"
    # The probe ran over the REAL machine (no hardware_probe injected): the
    # advisor picked a concrete preset + a per-function routing plan + an ASR
    # engine, all device-derived. These fields prove a real composed result, not
    # an empty/unavailable fallback.
    assert isinstance(rec.get("preset"), str) and rec["preset"], f"no device-derived preset: {rec!r}"
    per_function = rec.get("routing", {}).get("perFunction", {})
    assert per_function, f"no per-function routing recommended: {rec!r}"
    assert all("provider" in slot for slot in per_function.values()), f"routing slot missing provider: {per_function!r}"
    assert isinstance(rec.get("asrEngine"), str) and rec["asrEngine"], f"no ASR engine recommended: {rec!r}"


# ========================================================================== #
# INTELLIGENCE (c) — thumbnail.select: mock vision scorer + real jpg via ffmpeg
# ========================================================================== #
def test_intel_bestframe_thumbnail_real_jpg(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    _make_landscape_clip(media)
    clip_path = str(media)

    # Frame markers ARE timestamps (seconds). The loader returns one stack of
    # frame-time markers; the encoder turns a marker into a (fake) base64 blob so
    # the REAL vision pool sends real image_url parts to the mock; the writer
    # extracts the chosen marker's frame from the real clip with REAL ffmpeg.
    def frame_loader(path: str, spans: list[tuple[float, float]]) -> list[list[float]]:
        stacks = []
        for start, end in spans:
            n = 4
            stacks.append([start + (end - start) * i / (n - 1) for i in range(n)])
        return stacks

    def frame_encoder(frame: Any) -> str:
        return f"frame-at-{float(frame):.3f}"  # stand-in for a base64 PNG

    def thumbnail_writer(frame: Any, out_path: str) -> None:
        ts = float(frame)
        _ffmpeg(["-ss", f"{ts:.3f}", "-i", clip_path, "-frames:v", "1", "-q:v", "2", out_path])

    with MockModelServer() as server:
        svc = _new_services(
            tmp_path,
            vlm_clip_frame_loader=frame_loader,
            vlm_frame_encoder=frame_encoder,
            thumbnail_writer=thumbnail_writer,
        )
        protocol.clear_methods()
        handlers.register_all(services=svc)
        cloud = _cloud_settings(server.base_url, capabilities=["text", "vision"])
        svc.settings.set(cloud)
        vid = _add_video(svc, media, transcript=_transcript())
        rpc = Rpc(svc, keys=_keyring(cloud))

        done = rpc.run_job(
            "thumbnail.select",
            {"videoId": vid, "path": clip_path, "start": 0.0, "end": 5.0, "prompt": "pick the best thumbnail"},
        )
        assert server.hits["vision"] >= 1, "thumbnail.select never reached the mock vision endpoint"
        assert done.get("degraded") is False, f"degraded to midpoint (no real scoring): {done!r}"
        thumb = done["thumbnailPath"]
        assert Path(thumb).exists(), f"no thumbnail written: {thumb}"
        # The jpg is a real, ffprobe-valid image stream.
        w, h = _ffprobe_dims(thumb)
        assert w > 0 and h > 0, f"invalid thumbnail dims: {w}x{h}"


# ========================================================================== #
# REPURPOSE — exportPresets + templates + convert.batch -> 2 presets (9:16 + 1:1)
# ========================================================================== #
def test_repurpose_batch_two_platform_presets(tmp_path: Path) -> None:
    media = tmp_path / "source.mp4"
    _make_landscape_clip(media)
    svc = _new_services(tmp_path)
    protocol.clear_methods()
    handlers.register_all(services=svc)
    vid = _add_video(svc, media, transcript=_transcript())
    rpc = Rpc(svc)

    # exportPresets: the day-one catalog already ships 9:16 platforms; add a 1:1.
    presets_before = rpc.call("exportPresets.list", {})["presets"]
    assert any(p["aspect"] == "9:16" for p in presets_before), "no shipped 9:16 preset"
    saved = rpc.call(
        "exportPresets.save",
        {
            "preset": {
                "id": "square",
                "label": "Square 1:1",
                "aspect": "1:1",
                "minSec": 20,
                "maxSec": 60,
                "count": 3,
                "captionStyle": "libass",
            }
        },
    )
    assert saved["preset"]["aspect"] == "1:1"
    presets_after = {p["id"]: p for p in rpc.call("exportPresets.list", {})["presets"]}
    assert "square" in presets_after and any(p == "tiktok" for p in presets_after), "preset catalog wrong"

    # templates: a saved repurpose pipeline whose export step fans out over the two
    # platform presets (9:16 tiktok + 1:1 square). The export step uses the
    # allowlisted shortmaker.export method whose exportTargets drive the fan-out.
    tmpl = rpc.call(
        "templates.save",
        {
            "template": {
                "id": "repurpose",
                "name": "Repurpose 9:16 + 1:1",
                "steps": [{"method": "shortmaker.export", "params": {"exportTargets": ["tiktok", "square"]}}],
                "exportTargets": ["tiktok", "square"],
            }
        },
    )["template"]
    assert tmpl["id"] == "repurpose"
    listed = {t["id"]: t for t in rpc.call("templates.list", {})["templates"]}
    assert "repurpose" in listed
    assert {"tiktok", "square"} <= set(listed["repurpose"].get("exportTargets", []))

    # convert.batch: the actual batch export to the 2 aspect ratios via REAL ffmpeg.
    out916 = str(tmp_path / "out_9x16.mp4")
    out11 = str(tmp_path / "out_1x1.mp4")
    done = rpc.run_job(
        "convert.batch",
        {
            "items": [
                {"videoId": vid, "options": {"container": "mp4", "scale": "1080x1920"}, "out": out916},
                {"videoId": vid, "options": {"container": "mp4", "scale": "1080x1080"}, "out": out11},
            ]
        },
        timeout=120.0,
    )
    paths = done["paths"]
    assert len(paths) == 2, f"expected 2 exported clips, got {paths!r}"
    assert _ffprobe_dims(out916) == (1080, 1920), "9:16 export wrong aspect"
    assert _ffprobe_dims(out11) == (1080, 1080), "1:1 export wrong aspect"


# ========================================================================== #
# EDITING-REFINE — refine: filler + silence over REAL audio
# ========================================================================== #
def test_editing_filler_silence_real_audio(tmp_path: Path) -> None:
    audio = tmp_path / "talk.m4a"
    _make_audio_with_silence(audio)
    svc = _new_services(tmp_path)
    protocol.clear_methods()
    handlers.register_all(services=svc)
    vid = _add_video(svc, audio, transcript=_transcript())
    rpc = Rpc(svc)

    out = rpc.call(
        "refine.preview",
        {"videoId": vid, "lang": "en", "removeFillers": True, "removeSilence": True, "totalSec": 6.0},
    )
    plan = out["plan"]
    stats = plan["stats"]
    # Real silencedetect found the 2s mid silence -> a positive silence removal.
    assert stats["silenceRemovedSec"] > 0.5, f"no real silence detected: {stats!r}"
    # The transcript carries a leading "um" filler -> a real filler cut.
    assert stats["fillersRemoved"] >= 1, f"no filler removed: {stats!r}"
    # The keep-list is the union complement -> multiple keep spans (a real cut).
    assert len(plan["keeps"]) >= 2, f"refine produced no cut: {plan['keeps']!r}"


# ========================================================================== #
# EDITING-REFINE — diarize: speaker labels carry into subtitles
# ========================================================================== #
class FakeDiarizer:
    """Stand-in for the heavy VAD+ECAPA backend: two speakers over two regions.

    The MODEL (VAD/ECAPA) is the only fake; the greedy clustering, label
    assignment, and subtitle carry that follow are the REAL sidecar code.
    """

    def detect_and_embed(self, audio_path: str, *, on_progress: Any = None, should_cancel: Any = None) -> Any:
        regions = [{"start": 0.0, "end": 2.0}, {"start": 4.0, "end": 6.0}]
        embeddings = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]  # orthogonal -> two speakers
        return regions, embeddings


def test_editing_diarize_labels_carry_to_subtitles(tmp_path: Path) -> None:
    audio = tmp_path / "two_speakers.m4a"
    _make_audio_with_silence(audio)
    svc = _new_services(tmp_path)
    protocol.clear_methods()
    handlers.register_all(services=svc)
    vid = _add_video(svc, audio, transcript=_transcript())
    # captionSpeakerLabels on -> the export prefixes the diarized speaker.
    svc.settings.set({"captionSpeakerLabels": True})
    # Replace the diarize backend factory with our fake (model-only fake).
    svc._diarize_backend_factory = lambda settings: FakeDiarizer()  # type: ignore[assignment]
    svc._diarize_models_present = lambda settings: True  # type: ignore[assignment]
    protocol.clear_methods()
    handlers.register_all(services=svc)
    rpc = Rpc(svc)

    diarized = rpc.run_job("diarize.start", {"videoId": vid})
    transcript = diarized["transcript"]
    speakers = transcript.get("speakers")
    assert speakers and len(speakers) == 2, f"diarize did not find 2 speakers: {speakers!r}"
    labels = {seg.get("speaker") for seg in transcript["segments"]}
    assert labels == {"SPEAKER_00", "SPEAKER_01"}, f"speaker labels wrong: {labels!r}"

    # Subtitles generated AFTER diarize carry the speaker label onto each cue.
    track = rpc.call("subtitles.generate", {"videoId": vid})["track"]
    cue_speakers = {c.get("speaker") for c in track["cues"]}
    assert cue_speakers == {"SPEAKER_00", "SPEAKER_01"}, f"cues lost speaker labels: {cue_speakers!r}"

    # Export with the label prefix on -> the SRT body carries "SPEAKER_NN:".
    exported = rpc.call("subtitles.export", {"trackId": track["id"], "format": "srt"})
    srt = Path(exported["path"]).read_text(encoding="utf-8")
    assert "SPEAKER_00" in srt and "SPEAKER_01" in srt, f"speaker labels not in SRT:\n{srt}"
