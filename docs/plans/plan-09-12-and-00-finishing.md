# Plan 09 — Real-Time Blocking Dashboard Feedback

**Priority:** 9 of 12. Requires Plan 01 (blocking mode) to be complete first.

**Goal:** When Parry blocks an LLM call, surface that block event in the dashboard in
real time — within 2 seconds. The dashboard live feed shows blocked calls differently
from detected-but-allowed events: red badge, the exact blocked prompt (first 200 chars),
which detector fired, and why.

**Architecture:**
```
SDK → POST /proxy/check → blocked=true
  └─► Backend writes a "blocked_event" record to Redis pubsub channel: org:{org_id}:blocks
  └─► SSE endpoint reads from Redis pubsub and streams to dashboard
  └─► Dashboard renders blocked event in live feed with red "BLOCKED" badge
```

**New files:**
- `backend/app/db/models.py` — add `BlockedEvent` model (or store in existing `Detection`)
- `backend/app/api/v1/blocked_events.py` — SSE stream endpoint
- `dashboard/src/hooks/useBlockedEventStream.ts`
- `dashboard/src/components/BlockedEventFeed.tsx`

**Files to modify:**
- `backend/app/proxy/check.py` — publish to Redis on block
- `backend/app/api/v1/router.py` — register blocked events router
- `dashboard/src/pages/DashboardPage.tsx` — add BlockedEventFeed

---

### Task 1: Publish blocked events to Redis

**File:** `backend/app/proxy/check.py`

After `run_blocking_check()` returns `allowed=False`, publish to Redis:
```python
import json, redis as redis_lib
from app.core.config import settings

def _publish_block(org_id: str, result: ProxyCheckResult, prompt_preview: str):
    try:
        r = redis_lib.Redis.from_url(settings.redis_url)
        payload = json.dumps({
            "type": "blocked",
            "org_id": org_id,
            "detector": result.detector,
            "reason": result.reason,
            "severity": result.severity.value if result.severity else "high",
            "confidence": result.confidence,
            "prompt_preview": prompt_preview[:200],
            "ts": datetime.now(UTC).isoformat(),
        })
        r.publish(f"org:{org_id}:events", payload)
        r.close()
    except Exception:
        pass  # Never let pubsub failure affect the blocking response
```

---

### Task 2: SSE stream for blocked events

**File:** `backend/app/api/v1/blocked_events.py`

`GET /api/v1/events/live-stream` (extend existing stream or add new endpoint)

Uses Redis pubsub (`SUBSCRIBE org:{org_id}:events`) to stream events to the dashboard.
Both normal detected events AND blocked events flow through this channel.

Each SSE message has a `type` field: `"event"`, `"blocked"`, or `"keepalive"`.

---

### Task 3: Dashboard — BlockedEventFeed

**File:** `dashboard/src/components/BlockedEventFeed.tsx`

- Shows last 50 events in reverse chronological order
- Blocked events: red left border, "BLOCKED" badge, detector name, prompt preview, reason
- Detected (but allowed) events: yellow left border, "DETECTED" badge
- Clean events: no border, dimmed
- Auto-scrolls to new events
- "Pause" button to freeze the feed for inspection

Add to `DashboardPage.tsx` as a full-width panel below the metric cards.

---

### Notes

- **Keep Redis pubsub messages small.** Never include full prompt text — 200 char preview only.
- **SSE keepalive every 15 seconds** to prevent proxy timeouts on long-lived connections.
- **Max 5 concurrent SSE connections per org** to prevent resource exhaustion.

---
---

# Plan 10 — PagerDuty and Opsgenie Integrations

**Priority:** 10 of 12.

**Goal:** Send CRITICAL incident alerts to PagerDuty and Opsgenie in addition to the
existing Slack and email channels. Configuration is per-org in `alert_config`.

**Files to modify:**
- `backend/app/services/alert_service.py` — add PagerDuty and Opsgenie senders
- `backend/app/api/v1/alerts.py` — add pagerduty_routing_key and opsgenie_api_key fields
- `dashboard/src/pages/SettingsPage.tsx` — add PagerDuty and Opsgenie config fields

---

### Task 1: PagerDuty sender

**File:** `backend/app/services/alert_service.py`

```python
async def send_pagerduty_alert(incident: Incident, routing_key: str) -> None:
    """Send to PagerDuty Events API v2."""
    severity_map = {
        Severity.CRITICAL: "critical",
        Severity.HIGH: "error",
        Severity.MEDIUM: "warning",
        Severity.LOW: "info",
    }
    payload = {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": f"parry-incident-{incident.id}",
        "payload": {
            "summary": incident.title,
            "severity": severity_map[incident.severity],
            "source": "Parry AI Security",
            "custom_details": {
                "incident_id": str(incident.id),
                "agent_id": str(incident.agent_id),
                "org_id": str(incident.org_id),
            }
        }
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://events.pagerduty.com/v2/enqueue",
            json=payload, timeout=10.0
        )
        resp.raise_for_status()
    record_alert_sent(channel="pagerduty")
```

Only send to PagerDuty for `CRITICAL` and `HIGH` incidents. `MEDIUM` and `LOW` go to
Slack only (configurable via `min_severity` in `alert_config`).

---

### Task 2: Opsgenie sender

```python
async def send_opsgenie_alert(incident: Incident, api_key: str) -> None:
    """Send to Opsgenie Alerts API."""
    priority_map = {
        Severity.CRITICAL: "P1",
        Severity.HIGH: "P2",
        Severity.MEDIUM: "P3",
        Severity.LOW: "P5",
    }
    payload = {
        "message": incident.title,
        "alias": f"parry-{incident.id}",
        "priority": priority_map[incident.severity],
        "source": "Parry",
        "tags": ["parry", "ai-security", incident.severity.value],
        "details": {
            "incident_id": str(incident.id),
            "agent_id": str(incident.agent_id),
        }
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.opsgenie.com/v2/alerts",
            json=payload,
            headers={"Authorization": f"GenieKey {api_key}"},
            timeout=10.0,
        )
        resp.raise_for_status()
    record_alert_sent(channel="opsgenie")
```

---

### Task 3: Wire into dispatch_incident_alert

In `alert_service.dispatch_incident_alert()`, add:
```python
if config.get("pagerduty_routing_key") and _meets_min_severity(config, incident.severity):
    await send_pagerduty_alert(incident, config["pagerduty_routing_key"])

if config.get("opsgenie_api_key") and _meets_min_severity(config, incident.severity):
    await send_opsgenie_alert(incident, config["opsgenie_api_key"])
```

---

### Task 4: Alert config schema update

Add to `AlertConfigUpdate` schema:
```python
pagerduty_routing_key: str | None = None
opsgenie_api_key: str | None = None
```

Store in `org.alert_config` JSONB alongside existing Slack/email config.

---

### Task 5: Test endpoint

Add `POST /api/v1/alerts/test` with a `channel` param (`slack|email|pagerduty|opsgenie`).
Creates a synthetic low-severity test incident and sends it through the specified channel.
Useful for validating config without waiting for a real incident.

---

### Task 6: Dashboard — Settings update

In `SettingsPage.tsx`, add fields for:
- PagerDuty: "Routing Key" input (masked), with link to PagerDuty integration setup docs
- Opsgenie: "API Key" input (masked), with link to Opsgenie docs
- Test button per channel: "Send test alert"

---
---

# Plan 11 — Billing Plan Enforcement

**Priority:** 11 of 12.

**Goal:** Enforce free tier limits and report metered usage to Stripe. Without this,
Parry has no revenue protection — free users can run unlimited agents and events.

**Free tier limits:**
- Max 1 agent per org
- Max 10,000 events per rolling 30-day window
- Max 30-day data retention
- No custom detection rules (Plan 05)
- No compliance report export (Plan 06)

**Metered usage:** Report event count to Stripe daily via a Celery Beat task.

**Files to modify:**
- `backend/app/db/models.py` — add `plan` column to `Org`
- `backend/app/services/billing_service.py` — add `handle_subscription_event` logic, metered reporting
- `backend/app/api/v1/events.py` — check event quota before ingest
- `backend/app/api/v1/agents.py` — check agent limit before create
- `backend/app/workers/celery_app.py` — add daily metered usage task

---

### Task 1: Add plan to Org model

```python
class Plan(enum.StrEnum):
    FREE = "free"
    GROWTH = "growth"
    PRO = "pro"
    ENTERPRISE = "enterprise"
```

Add to `Org`:
```python
plan: Mapped[Plan] = mapped_column(Enum(Plan), default=Plan.FREE, nullable=False)
```

Migration: `009_add_plan_to_orgs.py`

---

### Task 2: Plan limits service

**File:** `backend/app/services/plan_service.py`

```python
PLAN_LIMITS = {
    Plan.FREE: {
        "max_agents": 1,
        "max_events_per_month": 10_000,
        "retention_days": 30,
        "custom_rules": False,
        "compliance_export": False,
    },
    Plan.GROWTH: {
        "max_agents": 10,
        "max_events_per_month": 100_000,
        "retention_days": 365,
        "custom_rules": True,
        "compliance_export": True,
    },
    Plan.PRO: {
        "max_agents": 50,
        "max_events_per_month": 1_000_000,
        "retention_days": 365,
        "custom_rules": True,
        "compliance_export": True,
    },
    Plan.ENTERPRISE: {
        "max_agents": None,  # unlimited
        "max_events_per_month": None,
        "retention_days": None,
        "custom_rules": True,
        "compliance_export": True,
    },
}

async def check_agent_limit(db: AsyncSession, org: Org) -> None:
    """Raise HTTP 402 if org is at agent limit."""
    limits = PLAN_LIMITS[org.plan]
    if limits["max_agents"] is None:
        return
    count = await _count_agents(db, org.id)
    if count >= limits["max_agents"]:
        raise HTTPException(
            status_code=402,
            detail=f"Agent limit reached for {org.plan} plan. Upgrade to add more agents.",
            headers={"X-Upgrade-Required": "true"},
        )

async def check_event_quota(db: AsyncSession, org: Org) -> None:
    """Raise HTTP 402 if org has exceeded monthly event quota."""
    limits = PLAN_LIMITS[org.plan]
    if limits["max_events_per_month"] is None:
        return
    count = await _count_events_this_month(db, org.id)
    if count >= limits["max_events_per_month"]:
        raise HTTPException(
            status_code=402,
            detail=f"Monthly event limit reached. Upgrade to continue.",
            headers={"X-Upgrade-Required": "true"},
        )
```

---

### Task 3: Enforce limits at ingest and agent creation

In `backend/app/api/v1/events.py` → `ingest_event()`:
```python
await plan_service.check_event_quota(db, org)
```

In `backend/app/api/v1/agents.py` → `create_agent()`:
```python
await plan_service.check_agent_limit(db, org)
```

---

### Task 4: Stripe subscription → plan sync

In `billing_service.handle_subscription_event()`, resolve the plan from the Stripe price ID:

```python
PRICE_TO_PLAN = {
    settings.stripe_price_id_growth: Plan.GROWTH,
    settings.stripe_price_id_pro: Plan.PRO,
}

if event_type in ("customer.subscription.created", "customer.subscription.updated"):
    price_id = subscription.get("items", {}).get("data", [{}])[0].get("price", {}).get("id")
    plan = PRICE_TO_PLAN.get(price_id, Plan.FREE)
    org.plan = plan
    await db.flush()

elif event_type == "customer.subscription.deleted":
    org.plan = Plan.FREE
    await db.flush()
```

---

### Task 5: Daily metered usage reporting to Stripe

**File:** `backend/app/workers/metered_usage_task.py`

Daily Celery Beat task:
1. For each org with a Stripe customer ID and non-free plan
2. Count events ingested in the last 24 hours
3. Report to Stripe via `stripe.SubscriptionItem.create_usage_record()`
4. Write audit log entry

Add to celery_app beat_schedule:
```python
"report-metered-usage": {
    "task": "report_metered_usage",
    "schedule": crontab(hour=1, minute=0),  # daily at 1am UTC
}
```

---

### Task 6: Dashboard — upgrade prompts

When an API returns 402:
- Show a modal: "You've reached your plan limit. Upgrade to continue."
- "Upgrade" button links to Stripe checkout (`POST /api/v1/billing/checkout`)
- Show current plan and limits in SettingsPage

---
---

# Plan 12 — Session Replay

**Priority:** 12 of 12.

**Goal:** Reconstruct a full agent session — every LLM call in order, with detection
results inline — so a security analyst can understand exactly what happened during an
incident. Think of it as a "DVR for agent behaviour."

**New files:**
- `backend/app/api/v1/sessions.py` — session detail endpoint
- `backend/app/services/session_service.py`
- `dashboard/src/pages/SessionReplayPage.tsx`
- `dashboard/src/hooks/useSession.ts`

**Files to modify:**
- `backend/app/api/v1/router.py`
- `dashboard/src/routes/router.tsx` — add `/sessions/:sessionId` route
- `dashboard/src/pages/AgentDetailPage.tsx` — link sessions to replay page
- `dashboard/src/pages/IncidentsPage.tsx` — link incident to session replay

---

### Task 1: Session detail API

**Route:** `GET /api/v1/sessions/{session_id}`

Response:
```json
{
  "session": {
    "id": "...",
    "agent_id": "...",
    "agent_name": "...",
    "started_at": "...",
    "ended_at": "...",
    "event_count": 14
  },
  "events": [
    {
      "id": "...",
      "timestamp": "...",
      "model": "gpt-4o",
      "prompt_preview": "first 200 chars...",
      "response_preview": "first 200 chars...",
      "tool_calls": [...],
      "latency_ms": 1234,
      "token_count": 450,
      "detections": [
        {
          "detector": "prompt_injection",
          "triggered": true,
          "severity": "high",
          "confidence": 0.92,
          "reason": "Instruction override attempt"
        }
      ]
    }
  ]
}
```

**Service:** `session_service.get_session_with_events(db, session_id, org_id)`

Joins `agent_sessions` → `agent_events` → `detections`. Returns events ordered by
`timestamp ASC`. Verifies session belongs to org (tenant isolation).

---

### Task 2: SessionReplayPage

**File:** `dashboard/src/pages/SessionReplayPage.tsx`

Layout: timeline view — vertical list of events, oldest at top, newest at bottom.

Each event card shows:
- Timestamp and relative time ("2 minutes into session")
- Model used
- Prompt preview (expandable to full)
- Response preview (expandable to full)
- Tool calls as expandable chips
- Token count and latency
- Detection badges (one per triggered detector, colour-coded by severity)

Events with triggered detections are highlighted — red left border for CRITICAL/HIGH,
orange for MEDIUM.

At the top: session metadata card — agent name, session duration, total events, incident
count linked from this session.

**Navigation:** "← Back to Agent" and "View Incident" (if applicable) buttons.

---

### Task 3: Link sessions from incidents and agent detail

**`IncidentsPage.tsx`:** Each incident row and detail view shows "View Session" button
if the triggering event has a `session_id`.

**`AgentDetailPage.tsx`:** Add a "Sessions" tab listing recent sessions for this agent,
each with event count, duration, and incident count. Each row links to the replay page.

---

### Task 4: Session list API

**Route:** `GET /api/v1/agents/{agent_id}/sessions?cursor=...&limit=20`

Returns paginated list of sessions for an agent, ordered by `created_at DESC`.
Each session includes: id, started_at, ended_at (or null if ongoing), event_count,
incident_count (join from incidents via agent_id + time overlap).

---

### Notes

- **Prompt content in session replay is viewer-accessible.** This is intentional — security
  analysts need to see what was said. However, RBAC (Plan 03) must be in place so viewers
  without the `admin` role see only metadata, not raw prompt/response content. Implement a
  `include_content: bool` flag in the service that checks the caller's role.
- **Full prompt/response storage.** Currently `AgentEvent` stores the full prompt and response
  as `Text` columns. Session replay uses this directly. Ensure the async ingest pipeline
  is not truncating to preview-only — check `event_service.ingest_event()` to confirm the
  full text is being saved (the SDK truncates to 4000 chars client-side, which is fine).
- **Ongoing sessions** (no `ended_at`) are shown as "Live" with a pulsing indicator.
  Poll for new events every 5 seconds while the session is open.
- **Performance:** Sessions with 1000+ events should paginate within the replay. Load
  the first 50 events and lazy-load more on scroll. The TimescaleDB index on
  `(agent_id, timestamp)` makes this efficient.

---
---

# Plan 00 — Finish Incomplete Items (Do Before Plans 01–12)

**Priority:** Do this first — these are finishing touches on already-started work, not
new features. Complete these before starting any new plan.

---

### Item A: Stripe subscription → plan sync (stub is broken)

**File:** `backend/app/services/billing_service.py`

`handle_subscription_event()` currently logs but never updates the org. This means
subscription upgrades and cancellations have zero effect. Fix before Plan 11 adds the
full plan enforcement system.

Minimal fix:
1. Add `plan` column to `Org` (see Plan 11 Task 1)
2. In `handle_subscription_event()`, resolve plan from price ID and update `org.plan`

---

### Item B: CI — spin up test DB for E2E tests

**File:** `.github/workflows/ci.yml`

E2E tests currently skip entirely in CI because port 5434 is never open. Add a
`services` block to the GitHub Actions workflow:

```yaml
services:
  postgres:
    image: timescale/timescaledb:latest-pg16
    env:
      POSTGRES_USER: parry
      POSTGRES_PASSWORD: parry
      POSTGRES_DB: parry_test
    ports:
      - 5434:5432
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5
```

Add `TEST_DATABASE_URL` to the CI env and remove the skip guard from `e2e/conftest.py`
(or keep it but ensure the port is open in CI).

---

### Item C: SDK — publish to PyPI

**File:** `sdk/pyproject.toml`, `.github/workflows/`

1. Bump version to `0.1.0`
2. Create `.github/workflows/publish-sdk.yml` — trigger on git tag `sdk/v*`, runs
   `uv build && uv publish` with a PyPI API token stored in GitHub secrets
3. Verify `pip install parry` works from a clean environment

---

### Item D: Missing reference docs

Create placeholder files that `CLAUDE.md` references but don't exist:
- `docs/api-spec.md` — FastAPI's auto-generated OpenAPI JSON is available at `/openapi.json`
  in dev. Export it and document the key endpoints with examples.
- `docs/schema.md` — copy the schema tables from `docs/architecture.md` and expand with
  all columns, constraints, and indexes.

---

### Item E: MVP checklist — mark completed items

**File:** `docs/mvp-checklist.md`

Go through and check off everything that's actually built. The checklist currently shows
all items unchecked. Accurate status tracking matters when handing off to Claude Code.
