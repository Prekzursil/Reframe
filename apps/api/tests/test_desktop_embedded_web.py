from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _reset_settings_caches() -> None:
    from app.api import get_celery_app
    from app.config import get_settings
    from app.database import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_celery_app.cache_clear()


def test_desktop_embedded_web_mount_serves_index_and_assets(monkeypatch, tmp_path: Path):
    web_dist = tmp_path / "web-dist"
    assets = web_dist / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (web_dist / "index.html").write_text("<html><body>desktop studio</body></html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ok');", encoding="utf-8")

    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    monkeypatch.setenv("REFRAME_MEDIA_ROOT", str(media_root))
    monkeypatch.setenv("REFRAME_DESKTOP_WEB_DIST", str(web_dist))

    _reset_settings_caches()

    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert "desktop studio" in root.text

        js = client.get("/assets/app.js")
        assert js.status_code == 200
        assert "console.log" in js.text

        spa = client.get("/projects/123")
        assert spa.status_code == 200
        assert "desktop studio" in spa.text

        traversal = client.get("/%2e%2e/%2e%2e/secret.txt")
        assert traversal.status_code == 404

        reserved = client.get("/api/_desktop_shell_test")
        assert reserved.status_code == 404


def test_desktop_embedded_web_mount_skips_when_dist_missing(monkeypatch, tmp_path: Path):
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    monkeypatch.setenv("REFRAME_MEDIA_ROOT", str(media_root))
    monkeypatch.setenv("REFRAME_DESKTOP_WEB_DIST", str(tmp_path / "does-not-exist"))

    _reset_settings_caches()

    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        assert client.get("/").status_code == 404
        assert client.get("/health").status_code == 200
