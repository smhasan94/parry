"""Daily Celery Beat task that reports metered usage to Stripe.

For every org that has a Stripe customer ID and a non-free plan,
counts events ingested in the last 24 hours and calls Stripe's
subscription-item usage-record API. Failures per-org are logged but
never raise — one broken customer can't be allowed to block the run.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import stripe
import structlog
from sqlalchemy import select

from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(
    name="report_metered_usage",
    soft_time_limit=600,
    time_limit=660,
)
def report_metered_usage() -> dict[str, int]:
    return asyncio.run(_report_metered_usage())


async def _report_metered_usage() -> dict[str, int]:
    from app.core import on_prem
    from app.core.config import settings
    from app.db.models import Org, Plan
    from app.db.session import async_session_factory
    from app.services import plan_service

    if on_prem.is_on_prem():
        log.info("metered.skipped_on_prem")
        return {"reported": 0, "skipped": 0, "errored": 0}

    stripe.api_key = settings.stripe_secret_key
    since = datetime.now(UTC) - timedelta(days=1)

    reported = 0
    skipped = 0
    errored = 0

    async with async_session_factory() as db:
        orgs = (
            (
                await db.execute(
                    select(Org).where(
                        Org.stripe_customer_id.is_not(None),
                        Org.plan != Plan.FREE,
                    )
                )
            )
            .scalars()
            .all()
        )

        for org in orgs:
            try:
                count = await plan_service.count_events_since(db, org.id, since)
                if count == 0:
                    skipped += 1
                    continue

                subscription_item_id = _find_subscription_item(org.stripe_customer_id)
                if subscription_item_id is None:
                    log.warning(
                        "metered.no_subscription_item",
                        org_id=str(org.id),
                        customer_id=org.stripe_customer_id,
                    )
                    skipped += 1
                    continue

                stripe.SubscriptionItem.create_usage_record(
                    subscription_item_id,
                    quantity=count,
                    timestamp=int(datetime.now(UTC).timestamp()),
                    action="increment",
                )
                reported += 1
                log.info(
                    "metered.usage_reported",
                    org_id=str(org.id),
                    count=count,
                    subscription_item=subscription_item_id,
                )
            except Exception:
                errored += 1
                log.error(
                    "metered.report_failed",
                    org_id=str(org.id),
                    exc_info=True,
                )

    log.info(
        "metered.run_complete",
        reported=reported,
        skipped=skipped,
        errored=errored,
    )
    return {"reported": reported, "skipped": skipped, "errored": errored}


def _find_subscription_item(customer_id: str) -> str | None:
    """Return the first active subscription item id for a customer.

    For Parry's single-line metered product this is sufficient; if
    customers ever carry multiple subscription items we'll need to tag
    the metered one explicitly.
    """
    try:
        subs = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
        for sub in subs.auto_paging_iter():
            items = sub.get("items", {}).get("data", [])
            if items:
                return items[0].get("id")
    except Exception:
        log.debug("metered.subscription_lookup_failed", exc_info=True)
    return None
