"""Seed script — creates a demo org, API key, sample agent, and policy.

Usage:
    cd backend
    uv run python scripts/seed.py

    # Or inside Docker:
    docker compose exec backend uv run python scripts/seed.py
"""

import asyncio
import hashlib
import secrets

from sqlalchemy import select


async def seed() -> None:
    from app.db.models import Agent, ApiKey, Org, Policy
    from app.db.session import async_session_factory

    async with async_session_factory() as db:
        # Check if already seeded
        result = await db.execute(select(Org).limit(1))
        if result.scalar_one_or_none():
            print("Database already has data — skipping seed.")
            print("To re-seed, run: docker compose down -v && docker compose up -d")
            return

        # Create demo org
        org = Org(
            name="Parry Demo",
            clerk_org_id="demo_org_local",
            is_active=True,
        )
        db.add(org)
        await db.flush()
        print(f"Created org: {org.name} (id: {org.id})")

        # Create API key
        random_part = secrets.token_urlsafe(32)
        raw_key = f"sk-parry-{random_part}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        api_key = ApiKey(
            org_id=org.id,
            name="Demo Key",
            key_hash=key_hash,
            key_prefix=raw_key[:16],
            is_active=True,
        )
        db.add(api_key)
        print(f"Created API key: {api_key.name}")

        # Create sample agent
        agent = Agent(
            org_id=org.id,
            name="demo-agent",
            description="Sample agent for testing the Parry demo",
            is_active=True,
        )
        db.add(agent)
        print(f"Created agent: {agent.name}")

        # Create sample policy
        policy = Policy(
            org_id=org.id,
            name="default-policy",
            description="Default security policy — blocks dangerous tools",
            is_active=True,
            allowed_tools=["search", "read_file", "calculate", "web_browse"],
            blocked_tools=["exec_code", "shell", "delete_file", "send_email"],
            max_token_budget=500000,
            forbidden_patterns=["ignore previous instructions", "system prompt"],
        )
        db.add(policy)
        print(f"Created policy: {policy.name}")

        await db.commit()

        print()
        print("=" * 60)
        print("SEED COMPLETE")
        print("=" * 60)
        print()
        print("API Key (save this — shown only once):")
        print(f"  {raw_key}")
        print()
        print("Use in SDK:")
        print(f'  parry.init(api_key="{raw_key}")')
        print()
        print("Use in curl:")
        print(f'  curl -H "Authorization: Bearer {raw_key}" http://localhost:8000/api/v1/agents')
        print()
        print("Dashboard: http://localhost:5173")
        print("API docs:  http://localhost:8000/docs")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(seed())
