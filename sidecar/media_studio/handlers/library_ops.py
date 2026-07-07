# The only inter-module cycle is the TYPE_CHECKING-only Services ref below
# (no runtime cycle); silence the type-only back-edge warning.
# pyright: reportImportCycles=false
"""Composition-root handlers (F4b split): Library / project / settings / paths / readiness handlers.

Each function is a Services method body extracted verbatim from the former
monolithic handlers.py; `self` is typed against the composed `Services` (bound
in services.py). Behaviour + the RPC surface are byte-identical to pre-split.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import keepcopy as _keepcopy
from .. import library as _library
from .. import relink as _relink
from ..features import offline as _offline
from ..features import shorts as _shorts_meta
from ..protocol import ErrorCode, RpcContext, RpcError
from . import _capabilities
from ._shared import (
    _invalid,
    _require_str,
)
from ._wire import (
    _function_readiness_items,
    _self_ffmpeg_run,
    _tier_readiness_items,
)

if TYPE_CHECKING:  # pragma: no cover - typing-only import, never executed at runtime
    from ._services import Services


def _resolve_video_path(self: Services, video_id: str) -> str | None:
    """videoId -> absolute media path (or None if unknown)."""
    video = self.library.get(video_id)
    if video is None:
        return None
    return video.get("path") or None


def _video_title(self: Services, video_id: str) -> str:
    """videoId -> human title for a progress message (the id when unknown).

    The batch runner's title seam (WU10): falls back to the ``videoId`` when
    the library has no record or no ``title``, so a progress line is always
    readable even for a stale id.
    """
    video = self.library.get(video_id)
    if video is None:
        return video_id
    return str(video.get("title") or video_id)


def _project_path(self: Services, video_id: str) -> Path:
    """The manifest path for a video's project (one project per video)."""
    return self.projects_dir / f"{video_id}.json"


def _load_or_create_project(self: Services, video_id: str) -> _library.Project:
    """Open the video's project manifest, creating a fresh one if absent."""
    path = self._project_path(video_id)
    if path.exists():
        return _library.Project.open(path)
    video = self.library.get(video_id)
    if video is None:
        raise _invalid(f"unknown video: {video_id}")
    project = _library.Project.new(video, settings=self.settings.get())
    project.save(path)
    return project


def _find_project_for_track(self: Services, track_id: str) -> _library.Project:
    """Find the project whose tracks contain ``track_id`` (scan manifests).

    CONTRACT-NOTE: tracks.rename / tracks.relabel send only a ``trackId`` (no
    ``videoId``), so we locate the owning project by scanning the per-video
    manifests. Other tracks.* methods carry ``videoId`` and use the direct
    path. Raises INVALID_PARAMS when no project owns the id.
    """
    if self.projects_dir.exists():
        for manifest in sorted(self.projects_dir.glob("*.json")):
            try:
                project = _library.Project.open(manifest)
            except Exception:  # noqa: BLE001 - skip an unreadable manifest
                continue
            for track in project.data.get("tracks") or []:
                if isinstance(track, dict) and track.get("id") == track_id:
                    return project
    raise _invalid(f"unknown track: {track_id}")


def library_list(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``library.list`` -> ``{videos:[Video]}`` (§2). Direct-return."""
    return {"videos": self.library.list()}


def library_add(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``library.add({path})`` -> ``{video}`` (§2). Direct-return."""
    path = _require_str(params, "path")
    title = params.get("title")
    try:
        video = self.library.add(path, title if isinstance(title, str) else None)
    except FileNotFoundError as exc:
        raise _invalid(str(exc)) from exc
    return {"video": video}


def library_remove(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``library.remove({id})`` -> ``{ok:true}`` (§2). Direct-return."""
    video_id = _require_str(params, "id")
    ok = self.library.remove(video_id)
    return {"ok": bool(ok)}


def library_thumbnail(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``library.thumbnail({id})`` -> ``{thumbnailPath}``. Direct-return.

    WU-2: extract a poster from a SOURCE library video by reusing the shorts
    ffmpeg poster engine, persist ``thumbnailPath`` onto the Video, and return
    it. Idempotent: an existing ``data_dir/thumbnails/<id>.jpg`` short-circuits
    (the runner is NOT invoked again). The ffmpeg ``run`` seam is the SAME
    injectable one ``shorts.thumbnail`` uses — never ``subprocess`` directly —
    so tests fake it (no real ffmpeg).
    """
    video_id = _require_str(params, "id")
    in_path = self._resolve_video_path(video_id)
    if not in_path:
        raise _invalid(f"unknown video: {video_id}")
    out = self.data_dir / "thumbnails" / f"{video_id}.jpg"
    if out.exists():
        self.library.set_thumbnail(video_id, str(out))
        return {"thumbnailPath": str(out)}
    out.parent.mkdir(parents=True, exist_ok=True)
    run = self._ffmpeg_run or _self_ffmpeg_run()
    argv = _shorts_meta.build_thumbnail_argv(in_path, str(out), self.settings.get())
    code = run(argv, total_sec=0.0)
    if code != 0:
        raise RpcError(
            f"ffmpeg exited with code {code} extracting a thumbnail for {video_id}",
            ErrorCode.INTERNAL_ERROR,
        )
    self.library.set_thumbnail(video_id, str(out))
    return {"thumbnailPath": str(out)}


def library_lineage(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``library.lineage({id})`` -> ``{id, entity, ancestors, descendants}`` (L3).

    Direct-return. Surfaces an asset's PROV provenance: ``ancestors`` (what it was
    made from) + ``descendants`` (what was made from it), each a list of full
    entity dicts (or a ``missing`` stub for a referenced-but-absent node). A
    purely-read query — an unknown id returns the empty structure (``entity`` is
    ``None``), never an error (the renderer just shows "no history").
    """
    entity_id = _require_str(params, "id")
    return self.library.lineage(entity_id)


def library_reveal(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``library.reveal({id})`` -> ``{id, sources:[{id,path,title,exists}], missing}`` (L5).

    Direct-return. Resolves an asset to its by-path SOURCE file(s) so the renderer
    can reveal them in the OS file explorer (via the existing ``openInFolder``
    bridge). ``missing`` surfaces any source whose file is gone (loud — never a
    silent skip), so the UI can offer a hash-verified relink. An unknown id is an
    INVALID_PARAMS error.
    """
    entity_id = _require_str(params, "id")
    try:
        return self.library.reveal_source(entity_id)
    except _relink.RelinkError as exc:
        raise _invalid(str(exc)) from exc


def library_regenerate(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``library.regenerate({id})`` -> ``{id, op, params, missing, ready}`` (L5, DESIGN §3.3.3).

    Direct-return. Builds the replay descriptor (the producing op + its redacted
    params) for an asset. ``ready`` is ``false`` (and ``missing`` is populated) when
    any source file is gone — the renderer must relink before re-running the op,
    never regenerate from a missing source. Unknown id / a raw (un-produced) asset
    are INVALID_PARAMS errors.
    """
    entity_id = _require_str(params, "id")
    try:
        return self.library.regenerate(entity_id)
    except _relink.RelinkError as exc:
        raise _invalid(str(exc)) from exc


def library_pin_hash(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``library.pinHash({id})`` -> ``{entity}`` (L5).

    Direct-return. Records the asset's whole-file BLAKE3 ``content_hash`` while its
    file is present — the baseline a later ``library.relink`` verifies against. A
    missing source file or unknown id is an INVALID_PARAMS error (loud).
    """
    entity_id = _require_str(params, "id")
    try:
        return {"entity": self.library.pin_source_hash(entity_id)}
    except (_relink.RelinkError, FileNotFoundError) as exc:
        raise _invalid(str(exc)) from exc


def library_relink(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``library.relink({id, path})`` -> ``{entity}`` (L5, hash-verified re-point).

    Direct-return. Re-points a moved source ONLY when the new file's whole-file
    BLAKE3 matches the recorded ``content_hash`` (a ``(size,mtime)`` stat is NOT
    accepted). A mismatch, an unverifiable asset (no recorded hash), a missing new
    file, or an unknown id all raise INVALID_PARAMS with a loud message.
    """
    entity_id = _require_str(params, "id")
    new_path = _require_str(params, "path")
    try:
        return {"entity": self.library.relink(entity_id, new_path)}
    except (_relink.RelinkError, FileNotFoundError) as exc:
        raise _invalid(str(exc)) from exc


def library_keep_copy(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``library.keepCopy({id})`` -> ``{managed}`` (WU-3b1). Direct-return.

    OPT-IN: copies the video's ORIGINAL bytes into the app-managed store under the
    data-root (atomic temp+replace, free-space preflight, cap+LRU eviction, content
    dedup) and re-points lineage so the managed copy is the AUTHORITATIVE source
    while the original path is recorded as provenance. An unknown/missing source, a
    failed preflight, or an over-cap file all raise INVALID_PARAMS (loud).
    """
    entity_id = _require_str(params, "id")
    try:
        return {"managed": self.library.keep_copy(entity_id)}
    except _keepcopy.KeepCopyError as exc:
        raise _invalid(str(exc)) from exc


def library_managed_status(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``library.managedStatus()`` -> ``{sizeBytes, capBytes, count, entries}`` (WU-3b1). Direct-return.

    Read-only: exposes the managed store's current size + the cap ceiling + the kept
    entries (each with its original path as provenance), so the UI can show "used / cap".
    """
    return self.library.managed_status()


def library_managed_evict(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``library.managedEvict({id})`` -> ``{ok, entityId}`` (WU-3b1). Direct-return.

    Evicts ONE video's managed copy: re-points its entity BACK to the original source
    (provenance) and frees the managed bytes (unless another entity shares them). An
    entity with no managed copy raises INVALID_PARAMS (loud).
    """
    entity_id = _require_str(params, "id")
    try:
        return self.library.managed_evict(entity_id)
    except _keepcopy.KeepCopyError as exc:
        raise _invalid(str(exc)) from exc


def library_managed_clear(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``library.managedClear()`` -> ``{ok, cleared}`` (WU-3b1). Direct-return.

    Evicts EVERY managed copy (re-points each entity to its original path). Idempotent
    on an empty store (``cleared`` is 0).
    """
    return self.library.managed_clear()


def project_open(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``project.open({id})`` -> ``{project}`` (§2). Direct-return.

    CONTRACT-NOTE: the UI sends a video ``id``; ``library.Project.open`` takes
    a *manifest path*. We resolve id -> the per-video manifest, creating a
    fresh project on first open so the Workspace always has a project.
    """
    video_id = _require_str(params, "id")
    project = self._load_or_create_project(video_id)
    return {"project": project.data}


def project_save(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``project.save({project})`` -> ``{ok}`` (§2). Direct-return."""
    project_data = params.get("project")
    if not isinstance(project_data, dict):
        raise _invalid("project (object) is required")
    video = project_data.get("video") or {}
    video_id = video.get("id") if isinstance(video, dict) else None
    if not isinstance(video_id, str) or not video_id:
        raise _invalid("project.video.id is required to save")
    proj = _library.Project(dict(project_data), manifest_path=self._project_path(video_id))
    proj.save()
    return {"ok": True}


def project_consolidate(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``project.consolidate({id})`` -> ``{ok, folder}`` (§2). Direct-return."""
    video_id = _require_str(params, "id")
    project = self._load_or_create_project(video_id)
    folder = self.projects_dir / f"{video_id}-consolidated"
    out = project.consolidate(folder)
    return {"ok": True, "folder": out}


def settings_get(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``settings.get()`` -> §2 settings object. Direct-return."""
    return self.settings.get()


def settings_set(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``settings.set({...})`` -> merged §2 settings object. Direct-return.

    CONTRACT-NOTE (WU-keys): ``settings.set`` returns ``self.settings.set``'s
    REDACTED merged view (``SettingsStore.set`` backfills + redacts the same
    way ``get`` does), so the round-tripped response never echoes a full key.
    """
    return self.settings.set(dict(params))


def paths_describe(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``paths.describe()`` -> the resolved on-disk data layout. Direct-return.

    WU-1 (read-only): surfaces WHERE everything lives so the renderer can SHOW
    the data layout (today it can only fetch the root via ``dataFolder.get``).
    A PURE path-join: no I/O, nothing is created, nothing is read from disk, so
    repeated calls are identical. Derives the dirs from
    :attr:`data_dir`/:attr:`projects_dir`/:attr:`exports_dir` and the file
    paths from the injected stores' own path attributes (robust to a custom
    settings/library location). ``subDirs`` names the per-feature derivative
    folders the sidecar writes into — ``dubs`` under the data dir; the
    ffmpeg-derivative folders (``stabilized``/``audiomix``/``trimmed``)
    under the exports root, matching ``register_all``'s wiring. ``shorts`` is
    written PER-VIDEO as ``exports/shorts-<videoId>``, so it is reported as the
    honest ``shorts-*`` pattern (no flat ``exports/shorts`` dir exists). NO key/secret
    string ever appears in this payload (it is layout-only).
    """
    return {
        "dataDir": str(self.data_dir),
        "projectsDir": str(self.projects_dir),
        "exportsDir": str(self.exports_dir),
        "settingsPath": str(self.settings.config_path),
        "libraryPath": str(self.library.index_path),
        "subDirs": {
            "dubs": str(self.data_dir / "dubs"),
            "shorts": str(self.exports_dir / "shorts-*"),
            "stabilized": str(self.exports_dir / "stabilized"),
            "audiomix": str(self.exports_dir / "audiomix"),
            "trimmed": str(self.exports_dir / "trimmed"),
        },
    }


def readiness_summary(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``readiness.summary()`` -> ``{items:[ReadinessItem]}``. Direct-return.

    WU-8 (read-only): rolls the three otherwise-split readiness sources into
    ONE per-capability list the renderer can SHOW as a unified "what works
    right now" view. Two capability families:

      * **Model tiers** — each runnable tier (0/1/2) is ``ready`` when all its
        model weights are installed; ``needsDownload`` when one is missing and
        we are online (the action targets ``assets.ensure`` with the missing
        asset names); ``unavailable`` when one is missing AND Offline mode is on
        (the download is blocked — same rule ``system.advisor`` uses). Tier-0 is
        the zero-download CPU floor and is always ``ready``.
      * **AI functions** — each routed AI function (``select``/``subtitles``/
        ``translation``/``vision``/``editPlan``) routed to a CLOUD provider is
        ``needsKey`` (no key for that provider), then ``needsConsent`` (key
        present but the data-type consent — TEXT for most, FRAMES for vision —
        is not granted), then ``ready``. A function routed to LOCAL (or unrouted
        -> the local-safe default) needs neither and is ``ready``.

    STRICTLY READ-ONLY (§5): it derives everything from the installed-weight map
    (the :meth:`_models_present_map` seam) + the redacted settings view, so it
    performs ZERO network/provider calls and triggers NO ``assets.ensure``. No
    full key ever rides this payload (it reads the already-redacted
    :meth:`providers.list <providers_list>` view for key PRESENCE only).
    """
    settings = self.settings.get()
    models_present = self._models_present_map(settings)
    offline = _offline.is_offline(settings)
    providers = self.providers_list(params, ctx)["providers"]
    items = _tier_readiness_items(models_present, offline=offline)
    items.extend(_function_readiness_items(settings, providers))
    # WU-C2: the per-feature capability family (reframe invariant + the on-demand
    # saliency/scene enhancements) rides the SAME roll-up so each feature's
    # point-of-use "Needs download -> [button]" state renders through the existing
    # ReadinessRollup without a parallel readiness system.
    items.extend(_capabilities.feature_readiness_items(self._installed_asset_names(settings), offline=offline))
    return {"items": items}
