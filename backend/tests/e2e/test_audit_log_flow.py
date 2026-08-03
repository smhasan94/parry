"""E2E: Audit log — GET /audit-log, filtering, and CSV export.

Covers:
1. An action (agent create) is recorded and visible in the audit log.
2. Filtering by action= returns only matching entries.
3. Filtering by resource_type= narrows results correctly.
4. A viewer-role client is rejected with 403.
5. CSV export returns a file with the correct Content-Type and chain headers.
6. Export with end <= start returns 400.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_audit_log_records_alert_config_update(admin_client: AsyncClient, seeded_db: dict):
    """Updating alert config generates an audit entry visible in the log."""
    # PUT /alerts is audit-logged with action=alert_config.updated
    resp = await admin_client.put(
        "/api/v1/alerts",
        json={"min_severity": "medium"},
    )
    assert resp.status_code == 200, resp.text

    # Audit log should now contain at least one entry
    resp = await admin_client.get("/api/v1/audit-log")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "entries" in body
    assert isinstance(body["entries"], list)
    assert len(body["entries"]) >= 1


@pytest.mark.asyncio
async def test_audit_log_filter_by_action(admin_client: AsyncClient, seeded_db: dict):
    """action= query param returns only entries matching that action."""
    # Update alert config to generate an auditable action
    await admin_client.put(
        "/api/v1/alerts",
        json={"min_severity": "high"},
    )

    resp = await admin_client.get("/api/v1/audit-log?action=alert_config.updated")
    assert resp.status_code == 200
    body = resp.json()
    # All returned entries must match the filter
    for entry in body["entries"]:
        assert entry["action"] == "alert_config.updated"


@pytest.mark.asyncio
async def test_audit_log_filter_by_resource_type(admin_client: AsyncClient, seeded_db: dict):
    """resource_type= query param narrows results to the given resource."""
    # Mutate alert config to produce an audit entry with resource_type=alert_config
    await admin_client.put(
        "/api/v1/alerts",
        json={"min_severity": "medium"},
    )

    resp = await admin_client.get("/api/v1/audit-log?resource_type=alert_config")
    assert resp.status_code == 200
    body = resp.json()
    for entry in body["entries"]:
        assert entry["resource_type"] == "alert_config"


@pytest.mark.asyncio
async def test_audit_log_viewer_role_rejected(client: AsyncClient, seeded_db: dict):
    """Viewer-role client (Bearer API key) should be rejected from the audit log."""
    resp = await client.get(
        "/api/v1/audit-log",
        headers={"Authorization": f"Bearer {seeded_db['api_key_raw']}"},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_audit_log_csv_export(admin_client: AsyncClient, seeded_db: dict):
    """GET /audit-log/export returns CSV with chain-tip headers."""
    resp = await admin_client.get(
        "/api/v1/audit-log/export",
        params={"start": "2025-01-01", "end": "2026-01-01", "format": "csv"},
    )
    assert resp.status_code == 200, resp.text
    assert "text/csv" in resp.headers.get("content-type", "")
    assert "X-Parry-Chain-Tip" in resp.headers
    assert "X-Parry-Entry-Count" in resp.headers
    # Content-Disposition should reference the org ID
    cd = resp.headers.get("content-disposition", "")
    assert "parry-audit" in cd
    assert ".csv" in cd


@pytest.mark.asyncio
async def test_audit_log_export_invalid_range(admin_client: AsyncClient, seeded_db: dict):
    """Export with end <= start should return 400."""
    resp = await admin_client.get(
        "/api/v1/audit-log/export",
        params={"start": "2025-06-01", "end": "2025-01-01", "format": "csv"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_audit_log_pagination(admin_client: AsyncClient, seeded_db: dict):
    """Audit log response has has_more and next_cursor fields."""
    resp = await admin_client.get("/api/v1/audit-log?limit=1")
    assert resp.status_code == 200
    body = resp.json()
    assert "has_more" in body
    assert "next_cursor" in body
