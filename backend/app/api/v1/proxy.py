"""Synchronous blocking proxy — pre-call check endpoint.

This route sits in the hot path of every LLM call made through the
Parry SDK when blocking mode is enabled. Budget: p99 < 10ms.

Contract:
- Always returns 200. The allow/block decision lives in the response
  body so the SDK never has to distinguish transport errors from
  policy decisions.
- Authentication via the same X-Parry-Secret header the event ingest
  route uses, so orgs don't need a second credential for the proxy.
- Org policies are cached in Redis with a short TTL to avoid hitting
  Postgres on every call. Cache miss is quiet — we just fall through
  to the DB. Redis down is quiet — we just skip the cache.
"""
import json

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import Actor, get_current_actor, get_org_from_sdk_key
from app.core.event_bus import publish_blocked_event
from app.db.models import Org, Policy, ResponseScanMode
from app.db.session import get_db
from app.proxy.check import run_blocking_check
from app.proxy.response_scan import scan_response
from app.schemas.base import ParrySchema
from app.services import audit_service

log = structlog.get_logger()

router = APIRouter()

POLICY_CACHE_TTL_SECONDS = 30
POLICY_CACHE_PREFIX = "policy:"

# Single shared sync Redis handle, lazily initialized. The proxy check
# is called synchronously inside a hot path, so we deliberately use the
# sync client — no event loop handoff on cache hits.
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis

            _redis_client = redis.Redis.from_url(
                settings.redis_url, decode_responses=True, socket_timeout=0.5
            )
        except Exception:
            log.warning("proxy.redis_unavailable", exc_info=True)
            return None
    return _redis_client


def _merge_policies(policies: list[Policy]) -> dict:
    """Flatten active policies into a single policy dict for detectors.

    Mirrors detection_service._merge_policies so the blocking path
    enforces the same rules as the async ingest path.
    """
    merged: dict = {
        "allowed_tools": [],
        "blocked_tools": [],
        "allowed_domains": [],
        "blocked_domains": [],
        "forbidden_patterns": [],
    }
    for p in policies:
        if p.allowed_tools:
            merged["allowed_tools"].extend(p.allowed_tools)
        if p.blocked_tools:
            merged["blocked_tools"].extend(p.blocked_tools)
        if p.allowed_domains:
            merged["allowed_domains"].extend(p.allowed_domains)
        if p.blocked_domains:
            merged["blocked_domains"].extend(p.blocked_domains)
        if p.forbidden_patterns:
            merged["forbidden_patterns"].extend(p.forbidden_patterns)
        if p.max_token_budget:
            existing = merged.get("max_token_budget")
            if existing is None or p.max_token_budget < existing:
                merged["max_token_budget"] = p.max_token_budget
    for key in ("allowed_tools", "blocked_tools", "allowed_domains", "blocked_domains"):
        merged[key] = list(set(merged[key])) if merged[key] else []
    return merged


async def _load_policy_for_org(db: AsyncSession, org_id) -> dict:
    """Return the merged policy dict, using Redis as a 30s cache."""
    cache_key = f"{POLICY_CACHE_PREFIX}{org_id}"

    r = _get_redis()
    if r is not None:
        try:
            cached = r.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            log.debug("proxy.policy_cache_read_failed", exc_info=True)

    result = await db.execute(
        select(Policy).where(Policy.org_id == org_id, Policy.is_active.is_(True))
    )
    policies = list(result.scalars().all())
    merged = _merge_policies(policies)

    if r is not None:
        try:
            r.setex(cache_key, POLICY_CACHE_TTL_SECONDS, json.dumps(merged))
        except Exception:
            log.debug("proxy.policy_cache_write_failed", exc_info=True)

    return merged


class ProxyCheckRequest(ParrySchema):
    agent_id: str | None = None
    session_id: str | None = None
    prompt: str | None = None
    model: str | None = None
    tool_calls: list[dict] | None = None


class ProxyCheckResponse(ParrySchema):
    allowed: bool
    reason: str = ""
    detector: str = ""
    severity: str | None = None
    confidence: float = 0.0


class BlockingSettingsResponse(ParrySchema):
    blocking_enabled: bool


class BlockingSettingsUpdate(ParrySchema):
    blocking_enabled: bool


class ResponseScanSettingsResponse(ParrySchema):
    response_scan_mode: str


class ResponseScanSettingsUpdate(ParrySchema):
    response_scan_mode: ResponseScanMode


@router.get("/settings", response_model=BlockingSettingsResponse)
async def get_blocking_settings(
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
) -> BlockingSettingsResponse:
    org, _ = org_actor
    return BlockingSettingsResponse(blocking_enabled=org.blocking_enabled)


@router.put("/settings", response_model=BlockingSettingsResponse)
async def update_blocking_settings(
    body: BlockingSettingsUpdate,
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> BlockingSettingsResponse:
    """Flip the blocking toggle. Audit-logged so the org has a paper
    trail of when the security posture changed and who did it."""
    org, actor = org_actor
    before = org.blocking_enabled
    org.blocking_enabled = body.blocking_enabled
    await db.flush()

    await audit_service.log_action(
        db,
        org_id=org.id,
        action="blocking_mode.updated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="org",
        resource_id=str(org.id),
        details={"before": before, "after": body.blocking_enabled},
    )
    await db.commit()

    # Invalidate the policy cache so a flip takes effect immediately
    # across workers rather than waiting out the 30s TTL.
    r = _get_redis()
    if r is not None:
        try:
            r.delete(f"{POLICY_CACHE_PREFIX}{org.id}")
        except Exception:
            log.debug("proxy.cache_invalidate_failed", exc_info=True)

    log.info(
        "blocking_mode.updated",
        org_id=str(org.id),
        enabled=body.blocking_enabled,
    )
    return BlockingSettingsResponse(blocking_enabled=org.blocking_enabled)


@router.get("/scan-settings", response_model=ResponseScanSettingsResponse)
async def get_scan_settings(
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
) -> ResponseScanSettingsResponse:
    org, _ = org_actor
    return ResponseScanSettingsResponse(response_scan_mode=org.response_scan_mode.value)


@router.put("/scan-settings", response_model=ResponseScanSettingsResponse)
async def update_scan_settings(
    body: ResponseScanSettingsUpdate,
    org_actor: tuple[Org, Actor] = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> ResponseScanSettingsResponse:
    """Flip the response scan mode. Audit-logged with before/after
    so security posture changes are traceable."""
    org, actor = org_actor
    before = org.response_scan_mode.value
    org.response_scan_mode = body.response_scan_mode
    await db.flush()

    await audit_service.log_action(
        db,
        org_id=org.id,
        action="response_scan_mode.updated",
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.label,
        resource_type="org",
        resource_id=str(org.id),
        details={"before": before, "after": body.response_scan_mode.value},
    )
    await db.commit()

    log.info(
        "response_scan_mode.updated",
        org_id=str(org.id),
        mode=body.response_scan_mode.value,
    )
    return ResponseScanSettingsResponse(response_scan_mode=org.response_scan_mode.value)


class ScanResponseRequest(ParrySchema):
    response: str
    agent_id: str | None = None
    session_id: str | None = None


class ScanResponseBody(ParrySchema):
    blocked: bool
    response: str | None  # None when blocked
    findings: list[dict]
    mode: str


@router.post("/scan-response", response_model=ScanResponseBody)
async def proxy_scan_response(
    body: ScanResponseRequest,
    org: Org = Depends(get_org_from_sdk_key),
) -> ScanResponseBody:
    """Post-LLM response scan. Runs data-exfil detection against the
    response text and either passes it through, redacts sensitive
    patterns in line, or blocks the whole response depending on the
    org's configured mode. Always 200 — the decision is in the body."""
    result = scan_response(body.response, org.response_scan_mode)
    return ScanResponseBody(
        blocked=result.blocked,
        response=result.redacted_response,
        findings=result.findings,
        mode=org.response_scan_mode.value,
    )


@router.post("/check", response_model=ProxyCheckResponse)
async def proxy_check(
    body: ProxyCheckRequest,
    org: Org = Depends(get_org_from_sdk_key),
    db: AsyncSession = Depends(get_db),
) -> ProxyCheckResponse:
    """Pre-flight check before the SDK calls the LLM. Returns allow/block.

    Never raises — errors surface as {allowed: true, reason: "error"}
    since the SDK is expected to fail open on any unexpected response.
    """
    policy = await _load_policy_for_org(db, org.id)
    event_data = {
        "prompt": body.prompt,
        "response": None,  # no response yet — we're pre-call
        "model": body.model,
        "tool_calls": body.tool_calls or [],
        "policy": policy,
    }

    check = run_blocking_check(event_data, org.blocking_enabled)
    if not check.allowed:
        publish_blocked_event(
            org_id=str(org.id),
            detector=check.detector,
            reason=check.reason,
            severity=check.severity.value if check.severity else "high",
            confidence=check.confidence,
            prompt=body.prompt,
            model=body.model,
            agent_id=body.agent_id,
        )
    return ProxyCheckResponse(
        allowed=check.allowed,
        reason=check.reason,
        detector=check.detector,
        severity=check.severity.value if check.severity else None,
        confidence=check.confidence,
    )
