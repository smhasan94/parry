#!/usr/bin/env bash
# StopFailure hook, matcher "rate_limit". Fires when the turn ends on an API
# error rather than normally. Records the parked state so the supervisor waits
# for the reset instead of re-dispatching into the same wall.

set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../bin/_common.sh"

INPUT="$(cat)"
SID="$(jq -r '.session_id // empty' <<<"$INPUT")"
read -r FIVE WEEK RESETS <<<"$(usage_snapshot "$SID" || echo "0 0 0")"

log "ratelimit-stop: turn ended on rate limit (5h=${FIVE}% 7d=${WEEK}%), parking until ${RESETS:-unknown}"
echo "${RESETS:-0}" > "$STATE_DIR/$WORKER.needs-redispatch"
echo "quota_wait" > "$STATE_DIR/$WORKER.status"
touch "$STATE_DIR/$WORKER.quota-parked"
exit 0
