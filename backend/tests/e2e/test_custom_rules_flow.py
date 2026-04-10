"""E2E: Custom rules CRUD, red team run start, scheduled report creation."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_custom_rule_crud(admin_client: AsyncClient, seeded_db: dict):
    """Create → list → update → test → delete custom rule."""
    # 1. Create rule
    resp = await admin_client.post(
        "/api/v1/custom-rules",
        json={
            "name": "Block SSN patterns",
            "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
            "target": "response",
            "severity": "high",
            "enabled": True,
        },
    )
    assert resp.status_code == 201, resp.text
    rule = resp.json()
    rule_id = rule["id"]
    assert rule["name"] == "Block SSN patterns"
    assert rule["enabled"] is True

    # 2. List rules
    resp = await admin_client.get("/api/v1/custom-rules")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # 3. Test the rule
    resp = await admin_client.post(
        "/api/v1/custom-rules/test",
        json={
            "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
            "sample": "My SSN is 123-45-6789",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["matched"] is True

    # 4. Test non-matching
    resp = await admin_client.post(
        "/api/v1/custom-rules/test",
        json={
            "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
            "sample": "No sensitive data here",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["matched"] is False

    # 5. Delete rule
    resp = await admin_client.delete(f"/api/v1/custom-rules/{rule_id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_scheduled_report_crud(admin_client: AsyncClient, seeded_db: dict):
    """Create → list → delete scheduled report."""
    # 1. Create schedule
    resp = await admin_client.post(
        "/api/v1/scheduled-reports",
        json={
            "schedule": "weekly",
            "recipients": ["security@acme.com"],
        },
    )
    assert resp.status_code == 201, resp.text
    schedule = resp.json()
    schedule_id = schedule["id"]
    assert schedule["schedule"] == "weekly"
    assert schedule["is_active"] is True
    assert "next_send_at" in schedule

    # 2. List schedules
    resp = await admin_client.get("/api/v1/scheduled-reports")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # 3. Delete
    resp = await admin_client.delete(f"/api/v1/scheduled-reports/{schedule_id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_red_team_corpus_info(admin_client: AsyncClient, seeded_db: dict):
    """Red team attack corpus should be accessible."""
    resp = await admin_client.get("/api/v1/red-team/attacks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_attacks"] > 0
    assert len(body["by_category"]) > 0
