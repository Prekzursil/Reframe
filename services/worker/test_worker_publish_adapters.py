from __future__ import annotations

from pathlib import Path


def test_publish_adapters_and_task_complete_for_all_supported_providers(monkeypatch, tmp_path: Path):
    from app.config import get_settings
    from app.database import create_db_and_tables, get_engine
    from app.models import MediaAsset, Organization, PublishConnection, PublishJob, User
    from services.worker import worker
    from sqlmodel import Session, select

    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)

    db_path = tmp_path / "reframe-test.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("REFRAME_MEDIA_ROOT", str(media_root))

    get_settings.cache_clear()
    get_engine.cache_clear()
    worker._engine = None
    worker._media_tmp = None
    create_db_and_tables()

    provider_rows: list[tuple[str, str, str]] = []
    with Session(get_engine()) as session:
        user = User(email="publish-worker@test.dev")
        session.add(user)
        session.commit()
        session.refresh(user)

        org = Organization(name="Publish Worker Org", slug="publish-worker-org", seat_limit=4)
        session.add(org)
        session.commit()
        session.refresh(org)

        for provider in ["youtube", "tiktok", "instagram", "facebook"]:
            asset = MediaAsset(
                kind="video",
                uri=f"tmp://{provider}-asset.mp4",
                mime_type="video/mp4",
                org_id=org.id,
                owner_user_id=user.id,
            )
            session.add(asset)
            session.commit()
            session.refresh(asset)

            connection = PublishConnection(
                org_id=org.id,
                user_id=user.id,
                provider=provider,
                account_label=f"{provider}-account",
                external_account_id=f"{provider}-acct-1",
            )
            session.add(connection)
            session.commit()
            session.refresh(connection)

            provider_rows.append((provider, str(connection.id), str(asset.id)))

    for provider, connection_id, asset_id in provider_rows:
        result = worker.publish_asset.run(
            None,
            provider,
            connection_id,
            asset_id,
            None,
            {"title": f"{provider} publish"},
        )
        assert result["status"] == "completed"
        assert result["provider"] == provider
        assert result["published_url"].startswith("https://")

    with Session(get_engine()) as session:
        jobs = session.exec(select(PublishJob)).all()
        assert len(jobs) == 4
        assert all(item.status == "completed" for item in jobs)
