"""Community detection rule pack marketplace service.

Handles publishing, discovery, installation, and uninstallation of
shared rule packs. Published packs are visible to all orgs; installing
a pack copies its rules into the subscriber's detector_config.
"""

import re
import uuid

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import CommunityRulePack, CommunityRuleSubscription

log = structlog.get_logger()

VALID_CATEGORIES = [
    "healthcare",
    "finance",
    "pii",
    "compliance",
    "prompt-injection",
    "data-exfiltration",
    "tool-misuse",
    "general",
]

MAX_RULES_PER_PACK = 30


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:100]


def _validate_rules(rules: list[dict]) -> None:
    """Validate rule list shape and regex patterns."""
    if len(rules) > MAX_RULES_PER_PACK:
        raise ValueError(f"Pack can have at most {MAX_RULES_PER_PACK} rules")
    if not rules:
        raise ValueError("Pack must have at least one rule")
    for i, rule in enumerate(rules):
        if not rule.get("name") or not rule.get("pattern"):
            raise ValueError(f"Rule {i}: name and pattern are required")
        try:
            re.compile(rule["pattern"])
        except re.error as e:
            raise ValueError(f"Rule {i}: invalid regex: {e}")
        if rule.get("target") and rule["target"] not in ("prompt", "response", "both"):
            raise ValueError(f"Rule {i}: target must be prompt, response, or both")
        if rule.get("severity") and rule["severity"] not in ("low", "medium", "high", "critical"):
            raise ValueError(f"Rule {i}: invalid severity")


async def list_packs(
    db: AsyncSession,
    *,
    category: str | None = None,
    search: str | None = None,
) -> list[CommunityRulePack]:
    """List all public community rule packs."""
    stmt = select(CommunityRulePack).where(CommunityRulePack.is_public.is_(True))
    if category:
        stmt = stmt.where(CommunityRulePack.category == category)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            CommunityRulePack.name.ilike(pattern)
            | CommunityRulePack.description.ilike(pattern)
        )
    stmt = stmt.order_by(CommunityRulePack.install_count.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_pack(db: AsyncSession, pack_id: uuid.UUID) -> CommunityRulePack:
    stmt = select(CommunityRulePack).where(CommunityRulePack.id == pack_id)
    result = await db.execute(stmt)
    pack = result.scalar_one_or_none()
    if not pack:
        raise NotFoundError("Rule pack not found")
    return pack


async def publish_pack(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
    description: str | None,
    category: str,
    rules: list[dict],
) -> CommunityRulePack:
    """Publish a new community rule pack."""
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Invalid category. Must be one of: {', '.join(VALID_CATEGORIES)}")
    _validate_rules(rules)

    slug = _slugify(name)
    existing = await db.execute(
        select(CommunityRulePack).where(CommunityRulePack.slug == slug)
    )
    if existing.scalar_one_or_none():
        raise ConflictError(f"A pack with slug '{slug}' already exists")

    # Normalize rules to standard shape
    normalized = []
    for rule in rules:
        normalized.append({
            "name": rule["name"],
            "pattern": rule["pattern"],
            "target": rule.get("target", "both"),
            "severity": rule.get("severity", "medium"),
            "enabled": True,
        })

    pack = CommunityRulePack(
        org_id=org_id,
        name=name,
        slug=slug,
        description=description,
        category=category,
        rules=normalized,
    )
    db.add(pack)
    return pack


async def update_pack(
    db: AsyncSession,
    *,
    pack_id: uuid.UUID,
    org_id: uuid.UUID,
    rules: list[dict],
) -> CommunityRulePack:
    """Update a pack's rules (bumps version)."""
    pack = await get_pack(db, pack_id)
    if pack.org_id != org_id:
        raise NotFoundError("Rule pack not found")
    _validate_rules(rules)

    normalized = []
    for rule in rules:
        normalized.append({
            "name": rule["name"],
            "pattern": rule["pattern"],
            "target": rule.get("target", "both"),
            "severity": rule.get("severity", "medium"),
            "enabled": True,
        })

    pack.rules = normalized
    pack.version = pack.version + 1
    return pack


async def install_pack(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
) -> CommunityRuleSubscription:
    """Subscribe an org to a community rule pack."""
    pack = await get_pack(db, pack_id)
    if not pack.is_public:
        raise NotFoundError("Rule pack not found")

    # Check for existing subscription
    existing = await db.execute(
        select(CommunityRuleSubscription).where(
            CommunityRuleSubscription.org_id == org_id,
            CommunityRuleSubscription.pack_id == pack_id,
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError("Already subscribed to this pack")

    sub = CommunityRuleSubscription(
        org_id=org_id,
        pack_id=pack_id,
        installed_version=pack.version,
    )
    db.add(sub)

    # Increment install count
    await db.execute(
        update(CommunityRulePack)
        .where(CommunityRulePack.id == pack_id)
        .values(install_count=CommunityRulePack.install_count + 1)
    )

    return sub


async def uninstall_pack(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    pack_id: uuid.UUID,
) -> None:
    """Unsubscribe from a community rule pack."""
    result = await db.execute(
        select(CommunityRuleSubscription).where(
            CommunityRuleSubscription.org_id == org_id,
            CommunityRuleSubscription.pack_id == pack_id,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise NotFoundError("Not subscribed to this pack")
    await db.delete(sub)

    # Decrement install count
    await db.execute(
        update(CommunityRulePack)
        .where(CommunityRulePack.id == pack_id)
        .values(install_count=func.greatest(CommunityRulePack.install_count - 1, 0))
    )


async def list_subscriptions(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> list[CommunityRuleSubscription]:
    """List all packs an org is subscribed to."""
    stmt = (
        select(CommunityRuleSubscription)
        .where(CommunityRuleSubscription.org_id == org_id)
        .order_by(CommunityRuleSubscription.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_published(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> list[CommunityRulePack]:
    """List packs published by an org."""
    stmt = (
        select(CommunityRulePack)
        .where(CommunityRulePack.org_id == org_id)
        .order_by(CommunityRulePack.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
