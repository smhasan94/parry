#!/usr/bin/env bash
#
# Runs ON the deploy target, invoked over SSH by .github/workflows/deploy.yml.
# Not something you run from your laptop — use `make deploy` for that.
#
# CI builds the images on a hosted runner and ships two archives:
#
#   parry-images.tar.gz  — `docker save` of parry-backend + parry-dashboard
#   parry-config.tar.gz  — compose files, Caddyfile, and this script
#
# So the host needs docker, a populated .env, and nothing else: no git clone,
# no deploy key for the private repo, no build toolchain, and no registry
# account. That last one is deliberate — the backend Dockerfile's
# `COPY --from=builder /app /app` produces a fresh ~1.5 GB layer on every
# commit, so a registry would re-transfer the whole image each deploy.
#
# Usage:
#   ./scripts/deploy-remote.sh <images.tar.gz> <git-sha>
#
# Rollback: the currently-running images are retagged :rollback before the new
# ones load. If the stack misses its health gate we retag back and roll the old
# containers up again.
#
# IMPORTANT: rollback covers images only. The backend entrypoint runs
# `alembic upgrade head` on start, and nothing here downgrades. A deploy whose
# migration succeeded but whose app failed will roll back to code running
# against a newer schema. See docs/DEPLOY.md.

set -euo pipefail

IMAGES_ARCHIVE=${1:?usage: deploy-remote.sh <images.tar.gz> <git-sha>}
GIT_SHA=${2:?usage: deploy-remote.sh <images.tar.gz> <git-sha>}

# Seconds to wait for every gated service to report healthy. The backend's
# own healthcheck allows a 30s start_period and the worker 30s, so this needs
# comfortable headroom on a 1 vCPU box where migrations run at boot.
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-300}"
HEALTH_POLL_SECONDS=5

# Services that declare a healthcheck. `beat` is deliberately absent — celery
# beat exposes nothing pollable, so gating on it would just time out.
GATED_SERVICES=(db redis backend worker dashboard)

IMAGES=(parry-backend parry-dashboard)

# Set PARRY_SMALL_BOX=0 on a 4 GB+ host to use the stock resource limits.
COMPOSE_FILES=(-f docker-compose.prod.yml)
if [[ "${PARRY_SMALL_BOX:-1}" == "1" && -f docker-compose.small.yml ]]; then
  COMPOSE_FILES+=(-f docker-compose.small.yml)
fi

log() { printf '▸ %s\n' "$*"; }
warn() { printf '! %s\n' "$*" >&2; }
fail() { printf '✗ %s\n' "$*" >&2; exit 1; }

compose() { docker compose "${COMPOSE_FILES[@]}" "$@"; }

save_rollback_tags() {
  local image
  for image in "${IMAGES[@]}"; do
    if docker image inspect "$image:latest" >/dev/null 2>&1; then
      docker tag "$image:latest" "$image:rollback"
    else
      log "no existing $image:latest — first deploy, nothing to roll back to"
    fi
  done
}

# Returns 1 when there is nothing to restore, so the caller can tell the
# difference between "rolled back" and "the first deploy failed".
restore_rollback_tags() {
  local image restored=0
  for image in "${IMAGES[@]}"; do
    if docker image inspect "$image:rollback" >/dev/null 2>&1; then
      docker tag "$image:rollback" "$image:latest"
      restored=1
    fi
  done
  [[ "$restored" == "1" ]]
}

# A service with a healthcheck reports starting/healthy/unhealthy; one without
# reports its plain container state. Treating "running" as acceptable means an
# unhealthchecked service only has to be up, which is all we can assert.
service_status() {
  local cid
  cid=$(compose ps -q "$1" 2>/dev/null || true)
  if [[ -z "$cid" ]]; then
    echo "missing"
    return
  fi
  docker inspect \
    --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
    "$cid" 2>/dev/null || echo "unknown"
}

wait_for_health() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
  local service status pending

  while ((SECONDS < deadline)); do
    pending=()
    for service in "${GATED_SERVICES[@]}"; do
      status=$(service_status "$service")
      case "$status" in
        healthy | running) ;;
        *) pending+=("$service=$status") ;;
      esac
    done

    if ((${#pending[@]} == 0)); then
      return 0
    fi

    log "waiting on ${pending[*]}"
    sleep "$HEALTH_POLL_SECONDS"
  done

  return 1
}

roll_back() {
  warn "health gate failed after ${HEALTH_TIMEOUT_SECONDS}s"
  compose ps >&2 || true
  warn "last 50 lines of backend logs:"
  compose logs --tail 50 backend >&2 || true

  if ! restore_rollback_tags; then
    fail "no :rollback images exist — this host has never had a good deploy. Stack left as-is for inspection."
  fi

  warn "restoring previous images"
  compose up -d --no-build --remove-orphans >&2 || true

  if wait_for_health; then
    fail "rolled back to the previous images successfully. Deploy $GIT_SHA rejected."
  fi
  fail "ROLLBACK IS ALSO UNHEALTHY — manual intervention needed on this host."
}

[[ -f .env ]] || fail ".env not found in $PWD — see docs/DROPLET.md step 5"
[[ -f "$IMAGES_ARCHIVE" ]] || fail "image bundle $IMAGES_ARCHIVE not found in $PWD"

log "deploying $GIT_SHA"
save_rollback_tags

log "loading images"
gunzip -c "$IMAGES_ARCHIVE" | docker load

log "rolling services (migrations run from the backend entrypoint)"
compose up -d --no-build --remove-orphans

if ! wait_for_health; then
  roll_back
fi

log "all gated services healthy"
printf '%s\n' "$GIT_SHA" > .deployed-sha

# Reclaim the layers the previous image was holding. Keeps a 50 GB disk from
# filling after a few dozen deploys — each backend image is ~1.9 GB.
docker image prune -f >/dev/null
rm -f "$IMAGES_ARCHIVE"

compose ps
log "deployed $GIT_SHA"
