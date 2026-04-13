"""E2E: EU AI Act compliance — register system, generate FRIA, check posture."""

import pytest
from httpx import AsyncClient

from app.db.models import Plan


@pytest.mark.asyncio
async def test_compliance_full_flow(admin_client: AsyncClient, seeded_db: dict):
    """Register a high-risk AI system → generate FRIA → check posture."""
    # Compliance features (FRIA, posture) require Enterprise tier.
    # The admin_client overrides get_current_org to return this object,
    # and require_feature reads .plan from the in-memory org.
    seeded_db["org"].plan = Plan.ENTERPRISE

    # 1. Create an AI system
    resp = await admin_client.post(
        "/api/v1/compliance/systems",
        json={
            "name": "Customer Scoring AI",
            "risk_level": "high",
            "intended_purpose": "Automated credit scoring for loan applications",
            "deployer_name": "E2E Test Corp",
            "agent_ids": [str(seeded_db["agent"].id)],
        },
    )
    assert resp.status_code == 201, resp.text
    system = resp.json()
    system_id = system["id"]
    assert system["risk_level"] == "high"
    assert system["fria_required"] is True
    assert system["fria_status"] == "missing"

    # 2. List systems
    resp = await admin_client.get("/api/v1/compliance/systems")
    assert resp.status_code == 200
    systems = resp.json()
    assert len(systems) >= 1
    assert any(s["id"] == system_id for s in systems)

    # 3. Get single system
    resp = await admin_client.get(f"/api/v1/compliance/systems/{system_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Customer Scoring AI"

    # 4. Generate FRIA draft
    resp = await admin_client.post(
        f"/api/v1/compliance/systems/{system_id}/fria",
        json={},
    )
    assert resp.status_code == 201, resp.text
    fria = resp.json()
    fria_id = fria["id"]
    assert fria["status"] == "draft"
    assert fria["version"] == 1
    assert "sections" in fria["content"]

    # 5. List FRIAs for system
    resp = await admin_client.get(
        f"/api/v1/compliance/systems/{system_id}/fria"
    )
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # 6. Get FRIA detail
    resp = await admin_client.get(f"/api/v1/compliance/fria/{fria_id}")
    assert resp.status_code == 200
    assert resp.json()["version"] == 1

    # 7. Check posture
    resp = await admin_client.get("/api/v1/compliance/posture")
    assert resp.status_code == 200
    posture = resp.json()
    assert "overall_status" in posture
    assert "obligations" in posture
    assert len(posture["obligations"]) >= 5

    # 8. Delete system
    resp = await admin_client.delete(f"/api/v1/compliance/systems/{system_id}")
    assert resp.status_code == 204

    # 9. Verify deleted
    resp = await admin_client.get(f"/api/v1/compliance/systems/{system_id}")
    assert resp.status_code == 404
