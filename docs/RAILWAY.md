# Deploying Parry to Railway

End-to-end guide for getting Parry running on [Railway](https://railway.app) — backend, worker, dashboard, TimescaleDB, and Redis as separate services in one Railway project.

## Prerequisites

- A Railway account (Hobby plan is enough; ~$5/mo)
- A [Clerk](https://clerk.com) project with publishable + secret keys
- An [Anthropic API key](https://console.anthropic.com) (optional — only for the LLM fallback detector)
- Your forked or cloned repo on GitHub, connected to Railway

## Architecture on Railway

Parry runs as **5 services** in a single Railway project:

| Service       | Source                              | Purpose                              |
|---------------|-------------------------------------|--------------------------------------|
| `timescaledb` | `railway/timescaledb/Dockerfile`    | Postgres 16 + TimescaleDB extension  |
| `redis`       | Railway Redis template              | Celery broker + rate-limit cache     |
| `backend`     | `backend/Dockerfile` (uvicorn)      | FastAPI API + `/health` + `/metrics` |
| `worker`      | `backend/Dockerfile` (celery)       | Detection pipeline async tasks       |
| `dashboard`   | `dashboard/Dockerfile` (nginx)      | React UI + `/api` proxy              |

Services communicate over Railway's private network (`<service>.railway.internal`). Only the dashboard is exposed publicly.

## Step-by-step setup

### 1. Create the project

```bash
# From your fork's directory
railway login
railway init
```

Or create the project from the Railway dashboard and connect your GitHub repo.

### 2. Add the TimescaleDB service

1. **New Service → Empty Service**
2. **Settings → Source** → connect this repo, set **Root Directory** to `railway/timescaledb`
3. **Settings → Variables** — set:
   - `POSTGRES_USER=parry`
   - `POSTGRES_PASSWORD=<generate a strong password>`
   - `POSTGRES_DB=parry`
4. **Settings → Volumes** → add a volume mounted at `/var/lib/postgresql/data` (so data survives redeploys)
5. **Networking → Private Networking** is on by default — note the internal hostname (e.g. `timescaledb.railway.internal`)
6. Deploy. The service should boot and be reachable on port `5432` over the private network.

### 3. Add Redis

1. **New → Database → Add Redis**
2. Note the `REDIS_URL` Railway provides (e.g. `redis://default:<password>@redis.railway.internal:6379`)

### 4. Add the backend service

1. **New Service → GitHub Repo** → same repo, **Root Directory** = `backend`
2. **Settings → Variables**:

   | Variable | Value |
   |----------|-------|
   | `APP_ENV` | `production` |
   | `APP_SECRET_KEY` | _generate a 32-char random string_ |
   | `PARRY_INTERNAL_SECRET` | _generate a 32-char random string_ |
   | `DATABASE_URL` | `postgresql+asyncpg://parry:${{timescaledb.POSTGRES_PASSWORD}}@timescaledb.railway.internal:5432/parry` |
   | `REDIS_URL` | `${{Redis.REDIS_URL}}` |
   | `CELERY_BROKER_URL` | `${{Redis.REDIS_URL}}` |
   | `CELERY_RESULT_BACKEND` | `${{Redis.REDIS_URL}}` |
   | `ANTHROPIC_API_KEY` | `sk-ant-...` (optional) |
   | `CLERK_SECRET_KEY` | `sk_live_...` |
   | `CLERK_PUBLISHABLE_KEY` | `pk_live_...` |
   | `CLERK_WEBHOOK_SECRET` | `whsec_...` (set after step 7) |
   | `ALLOWED_ORIGINS` | `https://<your-dashboard-domain>` |
   | `DASHBOARD_URL` | `https://<your-dashboard-domain>` |

   `${{ServiceName.VAR}}` is Railway's reference syntax — it pulls values from sibling services automatically.

3. **Settings → Networking** → enable a public URL only if you want to hit the API directly. Otherwise leave it private and let the dashboard proxy do the work.
4. Deploy. The Dockerfile entrypoint runs `alembic upgrade head` automatically before starting uvicorn — your DB schema should be ready on the first deploy.
5. Verify: `curl https://<backend-public-url>/health` should return `{"status": "ok", ...}`.

### 5. Add the worker service

1. **New Service → GitHub Repo** → same repo, **Root Directory** = `backend`
2. **Settings → Deploy → Custom Start Command**:
   ```
   uv run celery -A app.workers.celery_app worker --loglevel=info --concurrency=2
   ```
3. **Variables** → click "Add Reference" and link the same env vars as the backend service (`DATABASE_URL`, `REDIS_URL`, `CELERY_*`, `ANTHROPIC_API_KEY`, `APP_ENV`).
4. Deploy.

### 6. Add the dashboard service

1. **New Service → GitHub Repo** → same repo, **Root Directory** = `dashboard`
2. **Settings → Variables**:

   | Variable | Value |
   |----------|-------|
   | `VITE_CLERK_PUBLISHABLE_KEY` | `pk_live_...` (build-time, baked into bundle) |
   | `BACKEND_URL` | `http://backend.railway.internal:8000` (runtime, used by nginx) |
   | `PORT` | `80` |

3. **Settings → Networking → Generate Domain** to get a public URL.
4. Deploy. The nginx config templates `BACKEND_URL` at container start — `/api` requests are proxied to the backend over Railway's private network.

### 7. Configure Clerk webhooks

1. In the [Clerk dashboard](https://dashboard.clerk.com), go to **Webhooks → Add Endpoint**
2. URL: `https://<dashboard-domain>/api/v1/webhooks/clerk` (the dashboard's nginx forwards `/api/*` to the backend)
3. Subscribe to: `organization.created`, `organization.updated`, `organization.deleted`, `user.created`
4. Copy the **Signing Secret** and set it as `CLERK_WEBHOOK_SECRET` in the **backend** service variables, then redeploy.

See [CLERK_SETUP.md](./CLERK_SETUP.md) for more detail on the auth flow.

### 8. (Optional) Add SMTP and Sentry

If you want email alerts and error tracking, also set on the **backend** and **worker** services:

```env
SMTP_HOST=smtp.sendgrid.net
SMTP_USER=apikey
SMTP_PASSWORD=SG....
SMTP_FROM=alerts@yourdomain.com

SENTRY_DSN=https://...@o0.ingest.sentry.io/0
```

And on the **dashboard** service for frontend error tracking:

```env
VITE_SENTRY_DSN=https://...@o0.ingest.sentry.io/0
```

## Verification checklist

- [ ] `https://<dashboard-domain>` loads and shows the Clerk sign-in
- [ ] After signing up, the welcome banner appears and clicking it opens `/setup`
- [ ] You can create an API key and revoke it from Settings
- [ ] `https://<dashboard-domain>/api/v1/health` returns `"status": "ok"` with `database: "ok"` and `redis: "ok"`
- [ ] Sending a test event with the SDK creates an event row visible in the dashboard
- [ ] If you trip an injection prompt, an incident shows up at HIGH severity within ~5s
- [ ] Slack/email/webhook test buttons in Settings → Alerts succeed

## Cost expectations

On Railway's Hobby plan ($5/mo includes $5 of usage):

| Service       | Approx idle  | Approx with light traffic |
|---------------|--------------|---------------------------|
| timescaledb   | $3–5/mo      | $5–8/mo                   |
| redis         | $1–2/mo      | $1–3/mo                   |
| backend       | $1–2/mo      | $2–5/mo                   |
| worker        | $1–2/mo      | $2–5/mo                   |
| dashboard     | <$1/mo       | <$1/mo                    |
| **Total**     | **~$8/mo**   | **~$15–20/mo**            |

If costs become a concern, the biggest savings come from moving TimescaleDB to [Timescale Cloud](https://www.tigerdata.com/) (free tier supports 25GB).

## Migrating to managed Timescale later

1. Create a Timescale Cloud service, copy its connection string
2. Pause the Railway `timescaledb` service
3. Restore a `pg_dump` to the new instance
4. Update `DATABASE_URL` in `backend` and `worker` to point at the cloud connection string
5. Redeploy — Alembic will see the schema is current and skip migrations
6. Delete the Railway `timescaledb` service once you've verified the cutover

## Troubleshooting

**Backend boots but `/health` reports `database: "error"`**
Check that `DATABASE_URL` uses `postgresql+asyncpg://`, not `postgres://`. Railway often auto-injects the latter for Postgres templates.

**Migrations fail with "extension timescaledb does not exist"**
Your DB service is running stock Postgres, not TimescaleDB. Make sure the `timescaledb` service is using `railway/timescaledb/Dockerfile`, not the Railway Postgres template.

**Dashboard loads but API calls 404**
The nginx proxy can't reach the backend. Verify the dashboard service has `BACKEND_URL` set to `http://backend.railway.internal:8000` (the internal port, not the public one).

**Clerk webhook returns 400 "Invalid webhook signature"**
`CLERK_WEBHOOK_SECRET` is wrong or missing. Re-copy it from the Clerk dashboard and redeploy the backend.

**Worker is running but events stay "pending"**
Check the worker logs for the broker URL. Both `backend` and `worker` must point to the same Redis instance and the same broker DB index.
