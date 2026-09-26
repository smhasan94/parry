"""Celery task: deliver a single webhook with HMAC signing and retry."""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import structlog

from app.workers.celery_app import celery_app

log = structlog.get_logger()

DELIVERY_TIMEOUT_SECONDS = 10


@celery_app.task(  # type: ignore[untyped-decorator]
    name="deliver_webhook",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
    soft_time_limit=15,
    time_limit=30,
)
def deliver_webhook(
    self: Any,
    endpoint_id: str,
    event_type: str,
    payload_json: str,
) -> dict[str, Any]:
    """Deliver a webhook payload to an endpoint with HMAC signing."""
    try:
        return asyncio.run(
            _deliver(endpoint_id, event_type, payload_json, self.request.retries + 1)
        )
    except Exception:
        log.error(
            "webhook.delivery_failed",
            endpoint_id=endpoint_id,
            event_type=event_type,
            attempt=self.request.retries + 1,
            exc_info=True,
        )
        raise


async def _deliver(
    endpoint_id: str,
    event_type: str,
    payload_json: str,
    attempt: int,
) -> dict[str, Any]:
    import uuid

    import httpx

    from app.core.url_safety import assert_public_https_url_async
    from app.db.models import WebhookDelivery, WebhookEndpoint
    from app.db.session import make_task_session_factory
    from app.services.webhook_dispatch_service import compute_signature

    factory = make_task_session_factory()
    task_engine = factory.kw["bind"]

    try:
        async with factory() as db:
            endpoint = await db.get(WebhookEndpoint, uuid.UUID(endpoint_id))
            if endpoint is None:
                return {"error": "endpoint_not_found"}

            if not endpoint.is_active:
                return {"error": "endpoint_disabled"}

            # Build signed payload
            body = json.dumps({
                "event_type": event_type,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": json.loads(payload_json),
            }, default=str)

            signature = compute_signature(body, endpoint.secret)

            # Deliver
            status_code = None
            response_body = None
            error = None

            try:
                await assert_public_https_url_async(endpoint.url)
                async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_SECONDS) as client:
                    resp = await client.post(
                        endpoint.url,
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Parry-Signature": signature,
                            "X-Parry-Event": event_type,
                            "User-Agent": "Parry-Webhook/1.0",
                        },
                    )
                    status_code = resp.status_code
                    response_body = resp.text[:500] if resp.text else None

                    if resp.is_success:
                        endpoint.failure_count = 0
                    else:
                        endpoint.failure_count += 1
                        error = f"HTTP {status_code}"

            except Exception as e:
                endpoint.failure_count += 1
                error = str(e)[:500]

            endpoint.last_triggered_at = datetime.now(UTC)

            # Record delivery
            delivery = WebhookDelivery(
                endpoint_id=endpoint.id,
                event_type=event_type,
                payload=json.loads(payload_json),
                status_code=status_code,
                response_body=response_body,
                error=error,
                attempt=attempt,
            )
            db.add(delivery)
            await db.commit()

            if error:
                log.warning(
                    "webhook.delivery_error",
                    endpoint_id=endpoint_id,
                    error=error,
                    attempt=attempt,
                )
                raise Exception(f"Webhook delivery failed: {error}")

            log.info(
                "webhook.delivered",
                endpoint_id=endpoint_id,
                event_type=event_type,
                status_code=status_code,
            )
            return {
                "endpoint_id": endpoint_id,
                "status_code": status_code,
                "attempt": attempt,
            }
    finally:
        await task_engine.dispose()
