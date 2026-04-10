"""Daily task: scan agent_events for model usage, upsert ai_system_suppliers.

Links suppliers to AI systems via the ai_systems.agent_ids column — a
supplier record is created for each unique (system, supplier_name, model_id)
tuple observed in events from that system's linked agents.
"""

import asyncio
from datetime import datetime

import structlog
from sqlalchemy import func, select, text

from app.compliance.supplier_metadata import get_supplier_info, supplier_name_for_model
from app.db.models import AgentEvent, AISystem, AISystemSupplier
from app.db.session import make_task_session_factory
from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(
    name="refresh_supplier_register",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
    soft_time_limit=300,
    time_limit=600,
)
def refresh_supplier_register(self) -> dict:  # type: ignore[no-untyped-def]
    """Scan events per AI system and upsert supplier records."""
    try:
        return asyncio.run(_refresh_all())
    except Exception:
        log.error(
            "supplier_refresh.failed",
            attempt=self.request.retries + 1,
            exc_info=True,
        )
        raise


async def _refresh_all() -> dict:
    factory = make_task_session_factory()
    task_engine = factory.kw["bind"]
    total_upserted = 0
    systems_processed = 0
    try:
        async with factory() as db:
            # Get all AI systems that have linked agents
            result = await db.execute(
                select(AISystem).where(AISystem.agent_ids != text("'{}'"))
            )
            systems = list(result.scalars().all())

            for system in systems:
                count = await _refresh_system_suppliers(db, system)
                total_upserted += count
                systems_processed += 1

            await db.commit()

        log.info(
            "supplier_refresh.completed",
            systems_processed=systems_processed,
            total_upserted=total_upserted,
        )
        return {
            "systems_processed": systems_processed,
            "total_upserted": total_upserted,
        }
    finally:
        await task_engine.dispose()


async def _refresh_system_suppliers(
    db: "AsyncSession",  # type: ignore[name-defined]
    system: AISystem,
) -> int:
    """Scan events for a single system's linked agents, upsert supplier rows."""
    if not system.agent_ids:
        return 0

    # Aggregate model usage from agent_events for this system's agents
    stmt = (
        select(
            AgentEvent.model,
            func.min(AgentEvent.timestamp).label("first_used"),
            func.max(AgentEvent.timestamp).label("last_used"),
            func.count().label("event_count"),
        )
        .where(
            AgentEvent.agent_id.in_(system.agent_ids),
            AgentEvent.model.is_not(None),
        )
        .group_by(AgentEvent.model)
    )
    result = await db.execute(stmt)
    rows = result.all()

    upserted = 0
    for row in rows:
        model_id = row.model
        supplier_name = supplier_name_for_model(model_id)
        supplier_info = get_supplier_info(model_id)

        # Check if supplier record exists
        existing = await db.execute(
            select(AISystemSupplier).where(
                AISystemSupplier.system_id == system.id,
                AISystemSupplier.supplier_name == supplier_name,
                AISystemSupplier.model_id == model_id,
            )
        )
        supplier = existing.scalar_one_or_none()

        if supplier:
            supplier.last_used_at = row.last_used
            supplier.event_count = row.event_count
            if row.first_used < supplier.first_used_at:
                supplier.first_used_at = row.first_used
        else:
            supplier = AISystemSupplier(
                system_id=system.id,
                supplier_name=supplier_name,
                model_id=model_id,
                first_used_at=row.first_used,
                last_used_at=row.last_used,
                event_count=row.event_count,
                jurisdiction=supplier_info.jurisdiction if supplier_info else None,
                provider_url=supplier_info.provider_url if supplier_info else None,
            )
            db.add(supplier)

        upserted += 1

    await db.flush()
    return upserted
