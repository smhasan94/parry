#!/usr/bin/env bash
#
# Parry deploy script — pulls latest from main, rebuilds changed images,
# and rolls services with minimal downtime. Run from the repo root on the
# production host.
#
# Usage:
#   ./scripts/deploy.sh           # pull, build changed, restart
#   ./scripts/deploy.sh --force   # rebuild everything from scratch
#
# Assumes:
#   - .env file is present and has DOMAIN, CADDY_EMAIL, POSTGRES_PASSWORD set
#   - docker compose v2 is installed
#   - You're on the main branch
#
# The backend Dockerfile entrypoint runs `alembic upgrade head` automatically
# on container start, so migrations apply during the rolling restart.

set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE_FILE="docker-compose.prod.yml"
FORCE=0

if [[ "${1:-}" == "--force" ]]; then
  FORCE=1
fi

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill in required values."
  exit 1
fi

echo "▸ Fetching latest from origin..."
git fetch origin
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [[ "$LOCAL" == "$REMOTE" && "$FORCE" -eq 0 ]]; then
  echo "▸ Already at $LOCAL — nothing to deploy. Use --force to rebuild anyway."
  exit 0
fi

echo "▸ Pulling main..."
git pull --ff-only origin main

if [[ "$FORCE" -eq 1 ]]; then
  echo "▸ Force rebuild requested — building all images with --no-cache"
  docker compose -f "$COMPOSE_FILE" build --no-cache
else
  echo "▸ Building changed images..."
  docker compose -f "$COMPOSE_FILE" build
fi

echo "▸ Rolling services (migrations run automatically via entrypoint)..."
docker compose -f "$COMPOSE_FILE" up -d

echo "▸ Pruning dangling images..."
docker image prune -f >/dev/null

echo "▸ Service status:"
docker compose -f "$COMPOSE_FILE" ps

echo
echo "✔ Deploy complete. Verify at: https://$(grep ^DOMAIN= .env | cut -d= -f2)/health"
