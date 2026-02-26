from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def test_project_share_links_allow_access_to_project_asset(test_client):
    client, _enqueued, _worker, _media_root = test_client

    create_project = client.post("/api/v1/projects", json={"name": "Shareable"})
    assert create_project.status_code == 201, create_project.text
    project = create_project.json()

    upload = client.post(
        "/api/v1/assets/upload",
        data={"kind": "subtitle", "project_id": project["id"]},
        files={"file": ("captions.srt", b"1\n00:00:00,000 --> 00:00:01,000\nhello\n", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    asset = upload.json()

    links_resp = client.post(
        f"/api/v1/projects/{project['id']}/share-links",
        json={"asset_ids": [asset["id"]], "expires_in_hours": 1},
    )
    assert links_resp.status_code == 200, links_resp.text
    links = links_resp.json()["links"]
    assert len(links) == 1

    shared_url = links[0]["url"]
    ok = client.get(shared_url)
    assert ok.status_code == 200, ok.text
    assert b"hello" in ok.content

    parsed = urlparse(shared_url)
    query = parse_qs(parsed.query)
    tampered_token = (query.get("token", [""])[0] + "tamper") if query.get("token") else ""
    bad = client.get(f"{parsed.path}?token={tampered_token}")
    assert bad.status_code == 403, bad.text
