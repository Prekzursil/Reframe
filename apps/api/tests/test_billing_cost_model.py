from __future__ import annotations


def test_billing_cost_model_exposes_metrics_and_plans(test_client):
    client, _, _, _ = test_client

    resp = client.get("/api/v1/billing/cost-model")
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert payload["currency"] == "usd"
    assert payload["billable_metrics"]
    assert any(item["metric"] == "job_minutes" for item in payload["billable_metrics"])
    assert payload["plans"]
    codes = {plan["code"] for plan in payload["plans"]}
    assert {"free", "pro", "enterprise"}.issubset(codes)
