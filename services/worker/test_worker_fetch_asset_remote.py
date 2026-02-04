from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def test_fetch_asset_downloads_remote_http(monkeypatch, tmp_path: Path):
    from app.config import get_settings
    from app.database import create_db_and_tables, get_engine
    from app.models import MediaAsset
    from services.worker import worker
    from sqlmodel import Session

    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)

    db_path = tmp_path / "reframe-test.db"
    db_url = f"sqlite:////{str(db_path).lstrip('/')}"
    monkeypatch.setenv("REFRAME_DATABASE", json.dumps({"url": db_url}))
    monkeypatch.setenv("REFRAME_MEDIA_ROOT", str(media_root))

    get_settings.cache_clear()
    get_engine.cache_clear()
    worker._engine = None
    worker._media_tmp = None
    create_db_and_tables()

    serve_dir = tmp_path / "serve"
    serve_dir.mkdir(parents=True, exist_ok=True)
    subtitle_file = serve_dir / "hello.srt"
    subtitle_contents = "1\n00:00:00,000 --> 00:00:01,000\nhello\n"
    subtitle_file.write_text(subtitle_contents, encoding="utf-8")

    handler = partial(SimpleHTTPRequestHandler, directory=str(serve_dir))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/hello.srt"
        with Session(get_engine()) as session:
            asset = MediaAsset(kind="subtitle", uri=url, mime_type="text/srt")
            session.add(asset)
            session.commit()
            session.refresh(asset)
            asset_id = str(asset.id)

        fetched_asset, fetched_path = worker.fetch_asset(asset_id)
        assert fetched_asset is not None
        assert fetched_path is not None
        assert fetched_path.exists()
        assert fetched_path.read_text(encoding="utf-8") == subtitle_contents
    finally:
        httpd.shutdown()
        httpd.server_close()

