def test_system_status_endpoint_returns_payload(test_client):
    client, _enqueued, _worker, _media_root = test_client

    resp = client.get("/api/v1/system/status")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["api_version"]
    assert "offline_mode" in payload
    assert payload["storage_backend"]
    assert payload["broker_url"]
    assert payload["result_backend"]
    assert "worker" in payload
