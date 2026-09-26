"""Delivery-time SSRF revalidation.

This inserts a WebhookEndpoint directly (bypassing the service-layer
check from Task 2) to prove the send-time check in _deliver is a real,
independent second gate — not just a reflection of the write-time one.
A row can carry an unsafe URL today from data written before this
plan shipped, or from any future write path that forgets the check;
this test protects against both.
"""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import WebhookDelivery, WebhookEndpoint
from tests.e2e.conftest import TEST_DB_URL


@pytest.mark.asyncio
async def test_delivery_refuses_a_private_target_and_records_it(
    db: AsyncSession, seeded_db: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workers.webhook_delivery_task import _deliver

    endpoint = WebhookEndpoint(
        org_id=seeded_db["org"].id,
        url="https://169.254.169.254/hook",
        secret="whsec_test",
        event_types=["detection.triggered"],
    )
    db.add(endpoint)
    await db.commit()
    await db.refresh(endpoint)

    task_engine = create_async_engine(TEST_DB_URL, echo=False)
    task_factory = async_sessionmaker(task_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.db.session.make_task_session_factory", lambda: task_factory)

    try:
        with pytest.raises(Exception, match="Webhook delivery failed"):
            await _deliver(str(endpoint.id), "test", json.dumps({"test": True}), 1)
    finally:
        await task_engine.dispose()

    deliveries = (
        await db.execute(
            select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id)
        )
    ).scalars().all()
    assert len(deliveries) == 1
    assert "link-local" in deliveries[0].error

    await db.refresh(endpoint)
    assert endpoint.failure_count == 1
