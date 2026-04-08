# Parry — On-Call Runbook

This doc is for the person paged at 3am. It assumes the service is
already deployed. For first-time setup, see
[OPERATIONS.md](./OPERATIONS.md), [DROPLET.md](./DROPLET.md), or
[RAILWAY.md](./RAILWAY.md).

**Golden rule:** Parry's detection path is **fail-open by design**.
If you're unsure whether to touch something, check whether user
traffic is currently blocked or failing. If not, investigate before
acting.

---

## 1. Start here — is anything actually broken?

Run these four checks in order. Stop as soon as one fails.

```bash
# 1. API liveness
curl -fsS https://api.parry.dev/health | jq .

# 2. Detection worker liveness (Celery)
docker compose exec worker celery -A app.workers.celery_app inspect ping

# 3. Database reachable + migration head matches
docker compose exec backend uv run alembic current

# 4. Redis reachable
docker compose exec backend uv run python -c "import redis; \
  redis.Redis.from_url('redis://redis:6379/0').ping()"
```

If all four return OK and users are still reporting issues, jump to
**§6 Diagnostic commands**.

---

## 2. Deploy

Parry ships as a Docker Compose stack on Render / DO droplet. Every
deploy touches three images: `backend`, `worker`, and `dashboard`.

### Standard deploy
```bash
git pull origin main
docker compose pull
docker compose up -d
docker compose exec backend uv run alembic upgrade head
```

**Order matters:** migrations run **after** the new images are pulled
but before traffic is meaningfully shifted. Zero-downtime requires the
old container to keep serving while the new one is coming up — Render
handles that for you, self-hosted needs a proxy (Caddy / Traefik).

### Verify the deploy
```bash
# 1. alembic head matches the latest migration file
docker compose exec backend uv run alembic current

# 2. every container is running (not restarting)
docker compose ps

# 3. new version tag visible in /health
curl -s https://api.parry.dev/health | jq .version
```

---

## 3. Rollback

If a deploy breaks prod, **roll back first, diagnose second.**

### Code rollback
```bash
# Find the previous known-good commit
git log --oneline -10

# Reset to it
git checkout <sha>
docker compose pull
docker compose up -d
```

### Migration rollback
Migrations are numbered linearly. If the new deploy's migration is the
problem, downgrade by exactly one step:

```bash
docker compose exec backend uv run alembic downgrade -1
```

Do **not** downgrade more than one step without reading the
intervening migrations first — some drop columns and data loss is
irreversible. If in doubt, restore from the most recent Postgres
backup instead.

### Feature flag rollback
Several plans are runtime-configurable without a redeploy:

| Feature | How to disable |
| --- | --- |
| Active blocking (plan-01) | `UPDATE orgs SET blocking_enabled=false;` |
| Response scanning (plan-02) | `UPDATE orgs SET response_scan_mode='off';` |
| Per-detector toggle | Edit `org.detector_config` JSONB |
| Custom rules | Edit `org.detector_config->'custom_rules'` |
| Alerts (all channels) | `DELETE FROM … UPDATE orgs SET alert_config=NULL;` |

---

## 4. Common failures

### "Detection pipeline is stuck"

Symptoms: new events land in `agent_events` but no `detections` rows
appear for them. Celery queue backlog growing.

```bash
# Queue depth
docker compose exec backend uv run python -c "
import redis
r = redis.Redis.from_url('redis://redis:6379/1')
print('celery queue:', r.llen('celery'))
"

# Restart the worker
docker compose restart worker
docker compose logs -f worker
```

If the queue keeps growing after restart, the worker is crash-looping
on a bad event. Check the last event id in the logs and inspect:

```bash
docker compose exec backend uv run python -c "
import asyncio
from sqlalchemy import select
from app.db.session import async_session_factory
from app.db.models import AgentEvent
async def go():
    async with async_session_factory() as s:
        e = (await s.execute(select(AgentEvent).order_by(AgentEvent.timestamp.desc()).limit(1))).scalar_one()
        print(e.id, e.agent_id, e.model, len(e.prompt or ''))
asyncio.run(go())
"
```

### "Ingest returns 402 Payment Required"

The org hit a plan quota (plan-11). Check:

```sql
SELECT plan FROM orgs WHERE id='<org_id>';
```

Free tier = 1 agent, 10K events / 30d. Either upgrade via Stripe
Checkout or temporarily bump the org's plan:

```sql
UPDATE orgs SET plan='growth' WHERE id='<org_id>';
```

Remember to coordinate with billing — manual plan changes bypass
Stripe reconciliation.

### "Dashboard shows stale health scores"

Health scores are cached in Redis with a 2h TTL and refreshed hourly
by Celery Beat at `:15`. If scores look stale:

```bash
# Force a full refresh
docker compose exec worker celery -A app.workers.celery_app \
  call refresh_health_scores

# Or clear the cache entirely
docker compose exec backend uv run python -c "
import redis
r = redis.Redis.from_url('redis://redis:6379/0')
for key in r.scan_iter('health:*'): r.delete(key)
"
```

Same pattern works for `stats:*` (agent behavioural graph cache, 5m TTL).

### "Live block feed is silent"

The dashboard's live feed (plan-09) uses Redis pubsub on
`org:{org_id}:events`. If the feed shows "Connected" but no messages:

```bash
# Is the pubsub channel actually receiving anything?
docker compose exec redis redis-cli PSUBSCRIBE 'org:*:events'
```

Then fire a blocked call from the SDK. If nothing appears, the
proxy_check publish path is broken — check backend logs for
`event_bus.publish_failed`.

### "Compliance report returns 503"

WeasyPrint's native dependencies (Pango, Cairo, fonts-liberation) are
missing from the backend image. Verify:

```bash
docker compose exec backend dpkg -l | grep -E 'libpango|libcairo|fonts-liberation'
```

If empty, the image was built without the plan-06 Dockerfile changes.
Rebuild with `docker compose build --no-cache backend`.

### "Alerts aren't firing"

Alerts dispatch fire-and-forget inside `detection_service` and never
raise. Check structured logs for the relevant failure:

```bash
docker compose logs worker | grep 'alert\.'
# alert.slack_failed / alert.pagerduty_failed / alert.opsgenie_failed
```

Common causes: expired webhook, rotated API key, org's `min_severity`
set higher than the incident severity, entire `alert_config` cleared
via the dashboard.

---

## 5. Incidents (the security kind)

If Parry **itself** appears to be the target of an attack (not the
agents it's watching):

1. **Rotate** the API keys that authenticated the suspicious traffic
   via `/api/v1/api-keys` (admin+).
2. **Block** the offending org by flipping `is_active=false`.
3. **Snapshot** the audit log before anything else — it's
   append-only but nothing stops a compromised DB user from dropping
   the table:
   ```bash
   docker compose exec postgres pg_dump -U parry \
     -t audit_log parry_test > audit-$(date +%Y%m%d-%H%M).sql
   ```
4. **Page** the backup on-call before making any non-reversible
   changes.

If the issue is **a production prompt injection hitting a real
customer** rather than an attack on Parry itself, the customer's
agent is the victim — point them at the session replay
(`/sessions/:id`) and the incident view in their dashboard. Parry's
logs are the investigation surface.

---

## 6. Diagnostic commands

```bash
# Backend logs (last 200 lines, follow)
docker compose logs -f --tail=200 backend

# Worker logs
docker compose logs -f --tail=200 worker

# Structured log grep — errors only
docker compose logs backend | jq -r 'select(.level=="error")'

# Live event rate (events per minute over last hour)
docker compose exec backend uv run python -c "
import asyncio
from datetime import datetime, timedelta, UTC
from sqlalchemy import select, func
from app.db.session import async_session_factory
from app.db.models import AgentEvent
async def go():
    since = datetime.now(UTC) - timedelta(hours=1)
    async with async_session_factory() as s:
        n = (await s.execute(
            select(func.count()).select_from(AgentEvent)
            .where(AgentEvent.timestamp >= since)
        )).scalar_one()
        print(f'{n} events/hour ({n/60:.1f} / min)')
asyncio.run(go())
"

# Open incidents by severity
docker compose exec postgres psql -U parry parry_test -c "
SELECT severity, count(*) FROM incidents
WHERE status='open' GROUP BY 1 ORDER BY 1;"

# Slow queries (Postgres)
docker compose exec postgres psql -U parry parry_test -c "
SELECT pid, now() - query_start AS duration, query
FROM pg_stat_activity
WHERE state='active' AND query_start < now() - interval '5 seconds'
ORDER BY duration DESC;"
```

---

## 7. Manual task triggers

These Celery tasks normally run on schedule but can be invoked
manually when debugging:

```bash
# Recompute all agent baselines
docker compose exec worker celery -A app.workers.celery_app \
  call refresh_stale_baselines

# Refresh all health scores into Redis
docker compose exec worker celery -A app.workers.celery_app \
  call refresh_health_scores

# Submit yesterday's metered usage to Stripe
docker compose exec worker celery -A app.workers.celery_app \
  call report_metered_usage
```

---

## 8. Who to call

| Surface | Owner | Escalation |
| --- | --- | --- |
| Dashboard / SDK | @sharukh | GitHub issues |
| Infra / DB | @sharukh | — |
| Billing (Stripe) | @sharukh | Stripe support |
| Auth (Clerk) | @sharukh | Clerk support |

Keep this table up to date. A missing owner at 3am is worse than
any outage.
