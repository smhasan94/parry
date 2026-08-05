# Continuous deployment

Push to `main` → CI runs → if CI is green, images build on a GitHub-hosted
runner and ship to the host over SSH → the stack rolls → a health gate decides
whether it stays.

This is the automated path. For the manual one (build on the host, `make
deploy`), see [DROPLET.md](DROPLET.md) — both remain supported and they share
the same compose files.

## Why no container registry

The workflow builds images on the runner, `docker save`s them into a gzipped
tarball, and scps it. That looks roundabout next to pushing to GHCR, and it is
deliberate.

`backend/Dockerfile` ends with `COPY --from=builder /app /app`, which collapses
the virtualenv and the application into a single ~1.5 GB layer. Because the
application is copied *before* `uv sync` runs, that layer's digest changes on
every commit. A registry would therefore re-transfer ~1.9 GB per deploy — on
GHCR's private-package pricing ($0.50/GB egress beyond 1 GB/month) that costs
more than the droplet does.

Shipping the tarball straight to the host costs nothing, needs no registry
account, and means the host holds no credentials beyond its own `.env`. It also
means the host needs **no git clone and no deploy key** — CI ships the compose
files and the deploy script alongside the images.

The alternative worth doing eventually is restructuring the Dockerfile so the
dependency layer and the application layer are separate. Then a registry
becomes cheap and deploys get faster. Not required to ship.

## What you need on the host

Docker, a `.env`, and an SSH user. Follow [DROPLET.md](DROPLET.md) steps 3 and
5 — create the `deploy` user, install Docker, configure ufw, write `.env` —
then stop. Skip the `git clone` step; this path does not use it.

The host's `.env` still needs the `VITE_*` variables even though it no longer
builds the dashboard. Compose interpolates the whole file when it loads,
including the `build.args` block, and
`VITE_CLERK_PUBLISHABLE_KEY` is declared with `:?` so a missing value aborts.

### You do not need a domain

Caddy needs a hostname to get a certificate, not a purchased one:

```env
DOMAIN=203-0-113-42.sslip.io
CADDY_EMAIL=you@example.com
```

`sslip.io` resolves `203-0-113-42.sslip.io` to `203.0.113.42`, and it sits on
the Public Suffix List, so Let's Encrypt treats each host as its own registered
domain for rate-limiting. You get a real certificate, no warnings. Swap `DOMAIN`
for a purchased name later and nothing else changes.

## Repository secrets

| Secret | What it is |
|---|---|
| `DEPLOY_HOST` | Host IP or DNS name |
| `DEPLOY_USER` | SSH user, e.g. `deploy` |
| `DEPLOY_SSH_KEY` | Private key, full PEM including header/footer |
| `DEPLOY_KNOWN_HOSTS` | Output of `ssh-keyscan <host>` |
| `VITE_CLERK_PUBLISHABLE_KEY` | Inlined into the JS bundle at build time |
| `VITE_API_URL` | Optional |
| `VITE_SENTRY_DSN` | Optional |
| `VITE_STRIPE_PRICE_GROWTH` | Optional |

Generate a deploy-only keypair rather than reusing your personal one:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/parry_deploy -C "github-actions-deploy" -N ""
ssh-copy-id -i ~/.ssh/parry_deploy.pub deploy@<host>
gh secret set DEPLOY_SSH_KEY < ~/.ssh/parry_deploy
ssh-keyscan <host> | gh secret set DEPLOY_KNOWN_HOSTS
```

`DEPLOY_KNOWN_HOSTS` is not optional decoration. The workflow does not set
`StrictHostKeyChecking=no`, so without a pinned host key the deploy fails rather
than handing the payload to whoever answers on port 22.

## The health gate

`scripts/deploy-remote.sh` tags the running images `:rollback` before loading
the new ones. After `up -d` it polls until `db`, `redis`, `backend`, `worker`
and `dashboard` all report healthy — using each service's own compose
healthcheck — for up to 300 seconds. `beat` is not gated: celery beat exposes
nothing pollable.

On timeout it prints `compose ps` and the last 50 backend log lines, retags
`:rollback` back to `:latest`, and rolls the previous containers up again.

### Rollback does not cover migrations

The backend entrypoint runs `alembic upgrade head` at container start. Nothing
in this pipeline downgrades. A deploy whose migration applied but whose
application then failed its health gate will roll the *code* back and leave the
*schema* forward.

For additive migrations that is harmless. For a destructive one it is not.
Take a backup before deploying anything that drops or rewrites a column:

```bash
make backup    # on the host — writes ./backups/parry_<date>.dump
```

## Running it

Automatic on every green CI run against `main`. Manually:

```bash
gh workflow run deploy.yml -f ref=main
```

The `ref` input is validated against `^[A-Za-z0-9._/-]{1,100}$` before it
reaches `actions/checkout` or the SSH command, so it cannot carry shell
metacharacters.

Deploys are serialized by a `concurrency` group — a second one queues rather
than loading images into a stack the first is still gating.

## Small hosts

On a 2 GB box, layer `docker-compose.small.yml` over the production file. The
deploy script does this by default; set `PARRY_SMALL_BOX=0` on a 4 GB+ host to
use the stock limits.

It drops the worker to `--concurrency=1`, pins Postgres' `shared_buffers`, and
caps every service including `redis` and `caddy`, which the production file
leaves unbounded. Measured steady-state is ~1.45 GB against 2208 MiB of
ceilings — deliberate mild over-commit, since `mem_limit` is a ceiling rather
than a reservation.

**Add swap regardless.** Postgres and the worker can both spike past
steady-state, and a 2 GB box has nowhere to put that:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

2 GB is genuinely tight — it fits, with roughly 600 MB of headroom and no room
for the caps to also act as partitions. A 4 GB host removes the whole
discussion for about $12/month more.

## Cost

Roughly 4 minutes of hosted runner time per deploy, against 2,000 free minutes
per month on a private repo. Build cache lives in GitHub Actions cache
(`type=gha`), so unchanged dependency layers are not rebuilt.

## Troubleshooting

**Deploy succeeded, discovery never runs.** `PROBE_ENCRYPTION_KEY` is unset in
the host's `.env`. Credential storage fails closed and the scheduled sync
no-ops. `.env.example` carries the generation command.

**`no :rollback images exist`.** First deploy to this host failed its health
gate. Nothing is retagged; the stack is left up for inspection. `docker compose
-f docker-compose.prod.yml -f docker-compose.small.yml logs backend`.

**Health gate times out on a cold host.** The first deploy runs the full
migration chain on a 1 vCPU box. Raise the budget:
`HEALTH_TIMEOUT_SECONDS=600 ./scripts/deploy-remote.sh ...`

**Disk fills up.** Each backend image is ~1.9 GB. The script prunes dangling
images after a successful deploy, but the `:rollback` tag pins one older image
by design. `docker system df` to check, `docker image prune -a` to reset — at
the cost of your rollback target.
