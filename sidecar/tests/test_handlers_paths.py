"""WU-1 — ``paths.describe`` RPC (read-only data-layout) tests.

The handler returns the resolved on-disk layout so the renderer can SHOW where
everything lives. It is a pure path-join: no I/O, no secrets, idempotent. These
tests pin the §WU-1 falsifiable acceptance criteria.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers
from media_studio.handlers import Services
from media_studio.protocol import RpcContext


@pytest.fixture
def services(tmp_path: Path) -> Services:
    return Services(data_dir=tmp_path / "data")


@pytest.fixture
def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def test_paths_describe_top_level_dirs_are_children_of_data_dir(services: Services, ctx: RpcContext) -> None:
    result = services.paths_describe({}, ctx)
    data_dir = result["dataDir"]
    assert data_dir == str(services.data_dir)
    for key in ("projectsDir", "exportsDir", "settingsPath", "libraryPath"):
        assert result[key].startswith(data_dir + os.sep)


def test_paths_describe_projects_dir_matches_services(services: Services, ctx: RpcContext) -> None:
    result = services.paths_describe({}, ctx)
    assert result["projectsDir"] == os.path.join(result["dataDir"], "projects")
    assert result["projectsDir"] == str(services.projects_dir)
    assert result["exportsDir"] == str(services.exports_dir)


def test_paths_describe_settings_and_library_paths(services: Services, ctx: RpcContext) -> None:
    result = services.paths_describe({}, ctx)
    assert result["settingsPath"] == str(services.settings.config_path)
    assert result["libraryPath"] == str(services.library.index_path)


def test_paths_describe_subdirs_cover_required_features(services: Services, ctx: RpcContext) -> None:
    result = services.paths_describe({}, ctx)
    sub = result["subDirs"]
    assert {"shorts", "dubs", "stabilized", "audiomix", "trimmed"} <= set(sub)
    # dubs lives under the data dir; the exports-rooted ones under exports.
    assert sub["dubs"] == str(services.data_dir / "dubs")
    assert sub["stabilized"] == str(services.exports_dir / "stabilized")
    assert sub["audiomix"] == str(services.exports_dir / "audiomix")
    assert sub["trimmed"] == str(services.exports_dir / "trimmed")
    # Shorts are written PER-VIDEO under exports as ``shorts-<videoId>`` (see
    # register_all's ``out_dir_for=lambda vid: exports_dir / f"shorts-{vid}"``);
    # there is no flat ``exports_dir/shorts`` dir, so report the honest pattern.
    assert sub["shorts"] == str(services.exports_dir / "shorts-*")


def test_paths_describe_leaks_no_secrets(services: Services, ctx: RpcContext) -> None:
    result = services.paths_describe({}, ctx)
    # No provider/key surface ever rides this read-only layout payload.
    assert "providers" not in result
    assert "keys" not in result

    def _walk(obj: Any) -> list[str]:
        if isinstance(obj, dict):
            return [s for v in obj.values() for s in _walk(v)]
        if isinstance(obj, str):
            return [obj]
        return []  # pragma: no cover - defensive; payload is str/dict only

    for value in _walk(result):
        lowered = value.lower()
        assert "key" not in lowered or "key" in str(services.data_dir).lower()
        assert "token" not in lowered or "token" in str(services.data_dir).lower()


def test_paths_describe_is_idempotent_and_writes_nothing(services: Services, ctx: RpcContext, tmp_path: Path) -> None:
    # The data dir need not exist for a pure path-join; describe must not create it.
    assert not services.data_dir.exists()
    first = services.paths_describe({}, ctx)
    second = services.paths_describe({}, ctx)
    assert first == second
    assert not services.data_dir.exists()


def test_paths_describe_is_registered(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "paths.describe" in registered
