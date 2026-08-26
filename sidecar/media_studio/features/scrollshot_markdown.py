from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import protocol
from ..jobs import JobContext
from ..protocol import ErrorCode, RpcContext, RpcError
from . import scrollshot

Resolver = Callable[[str], str | None]
TitleResolver = Callable[[str], str]
RESULT_SCHEMA = "reframe.scrollshot-result/v1"


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{key} (str) is required")
    return value.strip()


class ScrollshotMarkdownService:
    def __init__(
        self,
        *,
        resolver: Resolver,
        title_resolver: TitleResolver | None,
        out_root: str | os.PathLike[str],
        exporter: scrollshot.ScrollshotExporter | None = None,
    ) -> None:
        self._resolver = resolver
        self._title_resolver = title_resolver
        self._out_root = Path(out_root)
        self._exporter = exporter or scrollshot.ScrollshotExporter(out_root=out_root)

    def _resolve_path(self, params: dict[str, Any]) -> tuple[str, str]:
        direct_path = params.get("path")
        if isinstance(direct_path, str) and direct_path.strip():
            source = direct_path.strip()
            return source, str(params.get("title") or Path(source).stem or "scrollshot")
        video_id = _require_str(params, "videoId")
        resolved = self._resolver(video_id)
        if not resolved:
            raise _invalid(f"unknown video: {video_id}")
        if isinstance(params.get("title"), str) and str(params.get("title")).strip():
            return str(resolved), str(params["title"]).strip()
        if self._title_resolver is not None:
            return str(resolved), self._title_resolver(video_id)
        return str(resolved), Path(str(resolved)).stem or video_id

    def export_markdown(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        source_path, title = self._resolve_path(params)
        language = params.get("language")
        assurance = params.get("assurance")
        config = scrollshot.load_config(
            source_path=source_path,
            title=title,
            language=language if isinstance(language, str) else None,
            assurance=assurance if isinstance(assurance, str) else None,
        )
        exporter = self._exporter
        out_root = self._out_root

        def job_body(job_ctx: JobContext) -> dict[str, Any]:
            bundle = exporter.export(source_path=source_path, config=config, job_ctx=job_ctx)
            complete = bundle.coverage_verdict == "complete"
            warnings = [] if complete else list(bundle.coverage_issues or ("coverage incomplete",))
            return {
                "schemaVersion": RESULT_SCHEMA,
                "runId": bundle.bundle_id,
                "verdict": "RECORDED_SPAN_COMPLETE" if complete else "INCOMPLETE",
                "reviewRequired": not complete,
                "warnings": warnings,
                "panoramaPaths": [bundle.image_path],
                "kind": scrollshot.KIND,
                "bundleId": bundle.bundle_id,
                "bundleDir": bundle.bundle_dir,
                "manifestPath": bundle.manifest_path,
                "markdownPath": bundle.markdown_path,
                "imagePath": bundle.image_path,
                "observationsPath": bundle.observations_path,
                "conflictsPath": bundle.conflicts_path,
                "coverageVerdict": bundle.coverage_verdict,
                "sourceSha256": bundle.source_sha256,
                "markdownSha256": bundle.markdown_sha256,
                "imageSha256": bundle.image_sha256,
            }

        job = ctx.jobs.start(job_body, feature="scrollshot", label="scrollshot.exportMarkdown")
        return {"jobId": job.id, "kind": scrollshot.KIND}


def register(
    *,
    resolver: Resolver,
    title_resolver: TitleResolver | None = None,
    out_root: str | os.PathLike[str],
    exporter: scrollshot.ScrollshotExporter | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> ScrollshotMarkdownService:
    service = ScrollshotMarkdownService(
        resolver=resolver,
        title_resolver=title_resolver,
        out_root=out_root,
        exporter=exporter,
    )
    (register_fn or protocol.register)("scrollshot.exportMarkdown", service.export_markdown)
    return service


__all__ = ["ScrollshotMarkdownService", "register"]
