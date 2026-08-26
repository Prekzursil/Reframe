from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from media_studio.features import scrollshot as ss
from media_studio.features.scrollshot_markdown import ScrollshotMarkdownService, register
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext, RpcError


class FakeExporter:
    def __init__(self, coverage_verdict: str = "complete", coverage_issues: tuple[str, ...] = ()) -> None:
        self.calls: list[tuple[str, ss.ScrollshotConfig]] = []
        self.coverage_verdict = coverage_verdict
        self.coverage_issues = coverage_issues

    def export(self, *, source_path: str, config: ss.ScrollshotConfig, job_ctx: Any) -> ss.ScrollshotBundle:
        self.calls.append((source_path, config))
        Path("C:/tmp").mkdir(exist_ok=True)
        job_ctx.progress(100, "done")
        return ss.ScrollshotBundle(
            bundle_id="bundle-1",
            bundle_dir="C:/tmp/bundle-1",
            manifest_path="C:/tmp/bundle-1/manifest.json",
            markdown_path="C:/tmp/bundle-1/scrollshot.md",
            image_path="C:/tmp/bundle-1/long-screenshot.png",
            observations_path="C:/tmp/bundle-1/observations.json",
            conflicts_path="C:/tmp/bundle-1/conflicts.json",
            coverage_verdict=self.coverage_verdict,
            coverage_issues=self.coverage_issues,
            source_sha256="source",
            markdown_sha256="markdown",
            image_sha256="image",
        )


def ctx(registry: JobRegistry | None) -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=registry)


def test_service_returns_job_handle_and_terminal_payload(registry: JobRegistry, tmp_path: Path) -> None:
    exporter = FakeExporter()
    service = ScrollshotMarkdownService(
        resolver=lambda video_id: str(tmp_path / f"{video_id}.mp4"),
        title_resolver=lambda video_id: f"title-{video_id}",
        out_root=tmp_path / "exports",
        exporter=exporter,
    )
    source = tmp_path / "video-1.mp4"
    source.write_bytes(b"clip")
    out = service.export_markdown({"videoId": "video-1", "language": "eng", "assurance": "strict"}, ctx(registry))
    assert out == {"jobId": out["jobId"], "kind": ss.KIND}
    job = registry.get(out["jobId"])
    job.wait(timeout=5)
    assert job.result["schemaVersion"] == "reframe.scrollshot-result/v1"
    assert job.result["runId"] == "bundle-1"
    assert job.result["verdict"] == "RECORDED_SPAN_COMPLETE"
    assert job.result["reviewRequired"] is False
    assert job.result["warnings"] == []
    assert job.result["panoramaPaths"] == ["C:/tmp/bundle-1/long-screenshot.png"]
    assert job.result["kind"] == ss.KIND
    assert job.result["coverageVerdict"] == "complete"
    assert exporter.calls[0][0] == str(source)
    assert exporter.calls[0][1].title == "title-video-1"


def test_service_emits_review_required_shape_for_incomplete_runs(registry: JobRegistry, tmp_path: Path) -> None:
    exporter = FakeExporter(coverage_verdict="incomplete", coverage_issues=("coverage gap from 10 to 20",))
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"clip")
    service = ScrollshotMarkdownService(
        resolver=lambda video_id: None,
        title_resolver=None,
        out_root=tmp_path / "exports",
        exporter=exporter,
    )
    out = service.export_markdown({"path": str(source)}, ctx(registry))
    job = registry.get(out["jobId"])
    job.wait(timeout=5)
    assert job.result["verdict"] == "INCOMPLETE"
    assert job.result["reviewRequired"] is True
    assert job.result["warnings"] == ["coverage gap from 10 to 20"]


def test_service_accepts_direct_path_and_explicit_title(registry: JobRegistry, tmp_path: Path) -> None:
    exporter = FakeExporter()
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"clip")
    service = ScrollshotMarkdownService(
        resolver=lambda video_id: None,
        title_resolver=None,
        out_root=tmp_path / "exports",
        exporter=exporter,
    )
    out = service.export_markdown({"path": str(source), "title": "Explicit"}, ctx(registry))
    registry.get(out["jobId"]).wait(timeout=5)
    assert exporter.calls[0][1].title == "Explicit"
    named_service = ScrollshotMarkdownService(
        resolver=lambda video_id: str(source),
        title_resolver=lambda video_id: "Resolver title",
        out_root=tmp_path / "exports-named",
        exporter=exporter,
    )
    out = named_service.export_markdown({"videoId": "clip", "title": "Named"}, ctx(registry))
    registry.get(out["jobId"]).wait(timeout=5)
    assert exporter.calls[-1][1].title == "Named"
    stem_service = ScrollshotMarkdownService(
        resolver=lambda video_id: str(source),
        title_resolver=None,
        out_root=tmp_path / "exports-stem",
        exporter=exporter,
    )
    out = stem_service.export_markdown({"videoId": "clip"}, ctx(registry))
    registry.get(out["jobId"]).wait(timeout=5)
    assert exporter.calls[-1][1].title == "clip"


def test_service_rejects_missing_registry_unknown_video_and_bad_params(tmp_path: Path) -> None:
    service = ScrollshotMarkdownService(
        resolver=lambda video_id: None,
        title_resolver=None,
        out_root=tmp_path / "exports",
        exporter=FakeExporter(),
    )
    with pytest.raises(RpcError, match="no job registry"):
        service.export_markdown({"videoId": "ghost"}, ctx(None))
    registry = JobRegistry(emit_progress=lambda *_: None, emit_done=lambda *_: None)
    with pytest.raises(RpcError, match="unknown video"):
        service.export_markdown({"videoId": "ghost"}, ctx(registry))
    with pytest.raises(RpcError, match="videoId"):
        service.export_markdown({}, ctx(registry))


def test_register_binds_rpc_name(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    service = register(
        resolver=lambda video_id: None,
        title_resolver=None,
        out_root=tmp_path / "exports",
        exporter=FakeExporter(),
        register_fn=lambda name, handler: captured.__setitem__(name, handler),
    )
    assert captured["scrollshot.exportMarkdown"] == service.export_markdown
