# Deploying Parry on a DigitalOcean Droplet

Self-hosted deployment on a single Linux VPS using Docker Compose. **This is the simplest production setup** — one machine, one IP, one SSL cert, no managed services to configure. The full stack (backend, worker, dashboard, TimescaleDB, Redis, Caddy reverse proxy with auto-HTTPS) runs in containers on a single droplet.

> Works with any VPS provider (Hetzner, Linode, AWS Lightsail, etc.) — DigitalOcean is just the example. Anywhere that runs Ubuntu and Docker.

## Sizing

| Droplet               | RAM    | vCPU | Disk  | $/mo  | Good for                          |
|-----------------------|--------|------|-------|-------|-----------------------------------|
| Basic Regular         | 2 GB   | 1    | 50 GB | $12   | Demo, dev, single-tenant          |
| Basic Premium AMD     | 4 GB   | 2    | 80 GB | $24   | Light production (recommended)    |
| Basic Premium AMD     | 8 GB   | 4    | 160 GB| $48   | Active production / multi-tenant  |

The 4 GB tier is the sweet spot — TimescaleDB and the worker like a bit of headroom.

## Prerequisites

- DigitalOcean account (or any VPS provider)
- A domain name with DNS you can edit (Cloudflare, Namecheap, Route 53, etc.)
- A [Clerk](https://clerk.com) project (publishable + secret keys + webhook signing secret)
- An [Anthropic API key](https://console.anthropic.com) (optional, for the LLM fallback detector)

## Step-by-step

### 1. Create the droplet

In the DigitalOcean control panel:

- **Image:** Ubuntu 24.04 LTS x64
- **Plan:** Basic Premium AMD, 4 GB / 2 vCPU
- **Region:** closest to your users
- **Authentication:** SSH key (paste your public key)
- **Hostname:** `parry-prod`

Click **Create Droplet**, wait ~30s for the IP to appear, copy it.

### 2. Point your domain at the droplet

In your DNS provider, create an **A record**:

```
parry.yourdomain.com   →   <droplet-ip>
```

Set TTL to 300s. Wait a couple minutes for propagation (`dig parry.yourdomain.com` should return the IP).

### 3. Initial server setup

SSH in as root:

```bash
ssh root@<droplet-ip>
```

Create a non-root user, install Docker, configure the firewall:

```bash
# Create deploy user
adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh
cp ~/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys

# Install Docker (official one-liner)
curl -fsSL https://get.docker.com | sh
usermod -aG docker deploy

# Firewall — allow SSH + HTTP + HTTPS only
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Optional: install fail2ban for SSH brute-force protection
apt-get update && apt-get install -y fail2ban
systemctl enable --now fail2ban
```

Reconnect as the deploy user (close the root session, log back in as `deploy@<ip>`).

### 4. Clone the repo

```bash
git clone https://github.com/smhasan94/parry.git
cd parry
```

### 5. Create the .env file

```bash
cp .env.example .env
nano .env  # or vim
```

Set at minimum:

```env
APP_ENV=production
APP_SECRET_KEY=<run: openssl rand -hex 32>
PARRY_INTERNAL_SECRET=<run: openssl rand -hex 32>

# Database — only POSTGRES_PASSWORD matters; the rest default to "parry"
POSTGRES_PASSWORD=<run: openssl rand -hex 16>

# Caddy / HTTPS
DOMAIN=parry.yourdomain.com
CADDY_EMAIL=ops@yourdomain.com   # for Let's Encrypt expiry notices

# Clerk — paste from https://dashboard.clerk.com
CLERK_SECRET_KEY=sk_live_...
CLERK_PUBLISHABLE_KEY=pk_live_...
CLERK_WEBHOOK_SECRET=          # Set after step 8 below
VITE_CLERK_PUBLISHABLE_KEY=pk_live_...

# CORS — match your dashboard URL
ALLOWED_ORIGINS=https://parry.yourdomain.com
DASHBOARD_URL=https://parry.yourdomain.com

# Optional: LLM fallback detector
ANTHROPIC_API_KEY=sk-ant-...

# Optional: email alerts
SMTP_HOST=smtp.sendgrid.net
SMTP_USER=apikey
SMTP_PASSWORD=SG....
SMTP_FROM=alerts@yourdomain.com
```

> **About `VITE_*` vars:** the dashboard is a static SPA built by Vite,
> which inlines `VITE_*` env vars into the JS bundle **at build time**.
> Those values must be present when `docker compose ... build` runs, not
> just when it starts. The prod compose file plumbs them as build args
> from this `.env`, so setting `VITE_CLERK_PUBLISHABLE_KEY` here is
> sufficient — you do **not** need a separate `dashboard/.env` file
> (it's gitignored anyway). If you ever change a `VITE_*` value, you
> must `docker compose -f docker-compose.prod.yml build --no-cache
> dashboard` and recreate the container; restarting alone won't pick up
> the change.

### 6. Start everything

```bash
docker compose -f docker-compose.prod.yml up -d
```

Watch the boot:

```bash
docker compose -f docker-compose.prod.yml logs -f
```

You should see:
- `db` come up first
- `redis` come up
- `backend` run `alembic upgrade head` then start uvicorn
- `worker` start celery
- `dashboard` start nginx
- `caddy` request a Let's Encrypt cert (this takes ~10s on first boot)

Once Caddy logs `certificate obtained successfully`, hit:

```bash
curl https://parry.yourdomain.com/health
# {"status": "ok", "version": "0.1.0", "checks": {"database": "ok", "redis": "ok"}}
```

### 7. Sign up

Visit `https://parry.yourdomain.com` in your browser. Clerk's sign-in screen appears. Sign up. The dashboard's welcome banner should appear with a "Get Started" button — that opens the onboarding wizard.

### 8. Configure the Clerk webhook

1. In the [Clerk dashboard](https://dashboard.clerk.com), go to **Webhooks → Add Endpoint**
2. URL: `https://parry.yourdomain.com/api/v1/webhooks/clerk`
3. Subscribe to: `organization.created`, `organization.updated`, `organization.deleted`, `user.created`
4. Copy the **Signing Secret**
5. On the droplet:
   ```bash
   nano .env
   # Paste it as CLERK_WEBHOOK_SECRET=whsec_...
   docker compose -f docker-compose.prod.yml up -d backend worker
   ```

That's it. You're live.

## Updating Parry

Subsequent deploys are one command:

```bash
cd ~/parry
make deploy        # or: ./scripts/deploy.sh
```

The `Makefile` (run `make help` for the full list) wraps the most common ops:

```bash
make prod-status   # see what's running
make prod-logs     # tail all logs
make prod-psql     # psql shell into the DB
make backup        # dump DB to ./backups/parry_<timestamp>.dump
make prod-health   # curl /health via Caddy
```

The script:
1. Pulls latest from `origin/main`
2. Skips if you're already at HEAD
3. Rebuilds only changed images
4. Restarts services (the entrypoint runs `alembic upgrade head` automatically)
5. Prunes dangling images

For a clean rebuild from scratch:

```bash
./scripts/deploy.sh --force
```

## Backups

TimescaleDB data lives in the `postgres-data` volume. Back it up nightly with a one-line cron job:

```bash
sudo crontab -e
```

Add:

```cron
0 3 * * * cd /home/deploy/parry && docker compose -f docker-compose.prod.yml exec -T db pg_dump -U parry -Fc parry > /home/deploy/backups/parry_$(date +\%Y\%m\%d).dump 2>&1
```

For offsite backups, sync `/home/deploy/backups/` to a DigitalOcean Space (S3-compatible) with `s3cmd` or `rclone`.

To restore:

```bash
docker compose -f docker-compose.prod.yml exec -T db pg_restore -U parry -d parry --clean < parry_20260407.dump
```

## Monitoring

The `/health` endpoint is enough for most uptime monitors (UptimeRobot, BetterUptime, Pingdom — all free tiers work). Point them at:

```
https://parry.yourdomain.com/health
```

For metrics, see [OPERATIONS.md → Metrics (Prometheus)](./OPERATIONS.md#metrics-prometheus). The `/metrics` endpoint is exposed via Caddy at `https://parry.yourdomain.com/metrics`. **Firewall it** if you don't want it public — easiest path is to add an IP allowlist directive in `Caddyfile` for the `/metrics` route.

## Common operations

```bash
# Tail logs from one service
docker compose -f docker-compose.prod.yml logs -f backend

# Restart a single service
docker compose -f docker-compose.prod.yml restart worker

# Open a Postgres shell
docker compose -f docker-compose.prod.yml exec db psql -U parry parry

# Check Celery worker status
docker compose -f docker-compose.prod.yml exec worker uv run celery -A app.workers.celery_app inspect active

# Run migrations manually (normally not needed — entrypoint does this)
docker compose -f docker-compose.prod.yml exec backend uv run alembic upgrade head

# Disk usage
docker system df
```

## Troubleshooting

**Caddy keeps trying to get a cert and failing**
DNS hasn't propagated yet. Wait a couple minutes and check `dig $DOMAIN` returns the droplet IP. Let's Encrypt has a rate limit of 5 failures per hour per domain — if you hit it, switch to the staging environment in `Caddyfile`:

```caddyfile
{$DOMAIN} {
  tls {
    issuer acme {
      ca https://acme-staging-v02.api.letsencrypt.org/directory
    }
  }
  ...
}
```

Once it succeeds in staging, remove the override.

**`backend` container exits immediately on first deploy**
Most often: `DATABASE_URL` is wrong or `db` isn't healthy yet. Check with:

```bash
docker compose -f docker-compose.prod.yml logs db
docker compose -f docker-compose.prod.yml logs backend
```

The `depends_on: condition: service_healthy` should handle ordering, but if you customized the password, make sure `.env` is in sync.

**Dashboard loads but `/api` returns 502**
The `backend` container isn't running, or Caddy can't reach it on the internal network. Check:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml exec caddy wget -qO- http://backend:8000/health
```

**Out of disk**
Old Docker images and build cache pile up. Clean:

```bash
docker system prune -af --volumes
```

(Don't run `--volumes` if you care about your DB — it will nuke `postgres-data`. Skip the flag in that case.)

**Worker isn't processing events**
Check Redis connectivity and worker logs:

```bash
docker compose -f docker-compose.prod.yml exec redis redis-cli ping
docker compose -f docker-compose.prod.yml logs worker
```

Both `backend` and `worker` must point to the same `REDIS_URL` and broker DB index — they're set automatically by the prod compose file, so this should only break if you've customized them.

## Cost (DigitalOcean reference pricing)

| Item                          | Cost/mo |
|-------------------------------|---------|
| 4 GB / 2 vCPU droplet         | $24     |
| Backups add-on (recommended)  | $4.80   |
| **Total**                     | **~$29**|

For most demos and small production deployments this is significantly cheaper than the equivalent setup on Railway or Fly.io once you account for managed Postgres pricing.

## When to outgrow this

A single droplet handles surprising load — think tens of thousands of events per minute. You'd want to break things out when:

- **DB is the bottleneck** — move TimescaleDB to a managed instance ([Timescale Cloud](https://www.tigerdata.com/) free tier supports 25 GB)
- **You need HA** — run two droplets behind a managed load balancer with shared Postgres + Redis
- **You need horizontal worker scaling** — bump `--concurrency` first, then add more droplets

When you hit any of these, the same `docker-compose.prod.yml` becomes a `kubectl` manifest with minimal changes. Don't optimize for it before you need it.
