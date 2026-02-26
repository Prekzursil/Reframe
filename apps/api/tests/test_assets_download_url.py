def test_asset_download_url_returns_uri(test_client):
    client, _, _, _ = test_client

    upload = client.post(
        "/api/v1/assets/upload",
        files={"file": ("hello.txt", b"hello", "text/plain")},
        data={"kind": "subtitle"},
    )
    assert upload.status_code == 201
    asset = upload.json()

    resp = client.get(f"/api/v1/assets/{asset['id']}/download-url")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["url"] == asset["uri"]
