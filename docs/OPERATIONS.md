# Parry Operations Runbook

## Deployment

### Prerequisites

- Docker and Docker Compose v2+
- Domain name with DNS configured
- External services configured:
  - **Clerk** account (authentication) — see [CLERK_SETUP.md](./CLERK_SETUP.md)
  - **Stripe** account (billing, optional)
  - **Anthropic** API key (LLM fallback detector)

### First-time setup

1. Clone the repo and configure environment:

```bash
git clone https://github.com/sharukhhasan/parry.git
cd parry
cp .env.example .env
```

2. Edit `.env` with your secrets:

```env
# Required
APP_ENV=production
APP_SECRET_KEY=<generate-a-random-string>
POSTGRES_PASSWORD=<strong-password>
CLERK_SECRET_KEY=sk_live_...
CLERK_PUBLISHABLE_KEY=pk_live_...
CLERK_WEBHOOK_SECRET=whsec_...
VITE_CLERK_PUBLISHABLE_KEY=pk_live_...
ANTHROPIC_API_KEY=sk-ant-...

# Optional (billing)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Optional (email alerts via SMTP — works with SendGrid, Mailgun, SES, Postmark, etc.)
SMTP_HOST=smtp.sendgrid.net
SMTP_PORT=587
SMTP_USER=apikey
SMTP_PASSWORD=SG....
SMTP_FROM=alerts@yourcompany.com
SMTP_USE_TLS=true

# Used in alert messages as the dashboard link
DASHBOARD_URL=https://parry.yourcompany.com
```

### Alerting

Parry sends incident alerts to Slack and email, configured per org from the dashboard Settings page.

- **Slack**: each org pastes an [incoming webhook URL](https://api.slack.com/messaging/webhooks). No backend setup required.
- **Email**: requires SMTP credentials in the backend `.env` (see above). Each org then adds recipient addresses in Settings.

Alerts only fire for incidents at or above the org's configured severity threshold (default: HIGH). Failed alert deliveries are logged at WARN level but never block detection.

### Error tracking (Sentry)

Both backend and frontend support optional Sentry integration. When `SENTRY_DSN` (backend) and `VITE_SENTRY_DSN` (frontend) are set, errors and 5xx responses are reported with full stack traces.

```env
SENTRY_DSN=https://...@o0.ingest.sentry.io/0
SENTRY_TRACES_SAMPLE_RATE=0.1
SENTRY_ENVIRONMENT=production
VITE_SENTRY_DSN=https://...@o0.ingest.sentry.io/0
```

PII protection: prompt/response bodies, `Authorization`, `X-Parry-Secret`, and `Cookie` headers are stripped before events are sent. Frontend reports only 5xx mutation errors (4xx are user errors and not actionable). Sentry is fully optional — Parry runs identically when both DSNs are unset.

3. Start services:

```bash
docker compose -f docker-compose.prod.yml up -d
```

The backend entrypoint automatically runs database migrations before starting.

4. Verify:

```bash
curl http://localhost/health
# Should return: {"status": "ok", "version": "0.1.0", "checks": {"database": "ok", "redis": "ok"}}
```

5. Configure Clerk webhook URL to `https://your-domain.com/api/v1/webhooks/clerk`

### Updating

```bash
git pull origin main
docker compose -f docker-compose.prod.yml up -d --build
```

Migrations run automatically on backend startup.

## Architecture

```
                    ┌─────────────┐
  Users ───────────▶│  Dashboard  │ (nginx, port 80)
                    │  (React)    │
                    └──────┬──────┘
                           │ /api/*
                    ┌──────▼──────┐
  SDK agents ──────▶│   Backend   │ (FastAPI, port 8000)
  (X-Parry-Secret)  │   (uvicorn) │
                    └──┬──────┬───┘
                       │      │
              ┌────────▼┐  ┌──▼─────┐
              │ Postgres │  │ Redis  │
              │(Timescale│  │        │
              │   DB)    │  └──┬─────┘
              └──────────┘     │
                          ┌────▼─────┐
                          │  Celery  │
                          │  Worker  │
                          └──────────┘
```

## Monitoring

### Health check

```bash
curl https://your-domain.com/health
```

Returns `"status": "ok"` when all dependencies healthy, `"degraded"` if any fail.

### Logs

```bash
# All services
docker compose -f docker-compose.prod.yml logs -f

# Specific service
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml logs -f worker
```

### Common checks

```bash
# Database connectivity
docker compose -f docker-compose.prod.yml exec db pg_isready -U parry

# Redis connectivity
docker compose -f docker-compose.prod.yml exec redis redis-cli ping

# Celery worker status
docker compose -f docker-compose.prod.yml exec worker uv run celery -A app.workers.celery_app inspect active
```

## Troubleshooting

### Backend won't start

```bash
docker compose -f docker-compose.prod.yml logs backend
```

Common causes:
- `DATABASE_URL` is wrong or DB isn't ready
- Missing required env vars
- Migration failed (check migration logs)

### Migrations fail

```bash
# Check current migration state
docker compose -f docker-compose.prod.yml exec backend uv run alembic current

# Apply manually
docker compose -f docker-compose.prod.yml exec backend uv run alembic upgrade head

# Check migration history
docker compose -f docker-compose.prod.yml exec backend uv run alembic history
```

### Events not being processed

1. Check worker is running: `docker compose -f docker-compose.prod.yml ps worker`
2. Check Redis queue: `docker compose -f docker-compose.prod.yml exec redis redis-cli llen celery`
3. Check worker logs: `docker compose -f docker-compose.prod.yml logs worker`

### Dashboard blank after login

- Verify `VITE_CLERK_PUBLISHABLE_KEY` is set
- Check browser console for errors
- Verify backend is reachable from dashboard (nginx proxy)

## Backup & Restore

### Database backup

```bash
docker compose -f docker-compose.prod.yml exec db \
  pg_dump -U parry -Fc parry > backup_$(date +%Y%m%d).dump
```

### Database restore

```bash
docker compose -f docker-compose.prod.yml exec -i db \
  pg_restore -U parry -d parry --clean < backup.dump
```

## Scaling

### Horizontal scaling

- **Backend**: Run multiple instances behind a load balancer
- **Workers**: Increase `--concurrency` or run additional worker containers
- **Database**: Use managed PostgreSQL (e.g., Neon, RDS) with TimescaleDB extension

### Resource recommendations

| Service    | Min RAM | Recommended RAM |
|------------|---------|-----------------|
| Backend    | 256MB   | 512MB           |
| Worker     | 512MB   | 1GB             |
| PostgreSQL | 512MB   | 2GB             |
| Redis      | 64MB    | 256MB           |
| Dashboard  | 64MB    | 128MB           |
