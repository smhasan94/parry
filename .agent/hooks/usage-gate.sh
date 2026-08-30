#!/usr/bin/env bash
# Stop hook. When the 5-hour or weekly window crosses the checkpoint threshold,
# block once to force a fresh CHECKPOINT.md, then let the session stop.
#
# Reads the usage snapshot the status line writes; that is the only place
# rate_limits.* is exposed to a script.

set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../bin/_common.sh"

INPUT="$(cat)"

# Guard against the 8-block cap: if we already blocked this turn, let it stop.
[ "$(jq -r '.stop_hook_active // false' <<<"$INPUT")" = "true" ] && exit 0

SID="$(jq -r '.session_id // empty' <<<"$INPUT")"
read -r FIVE WEEK RESETS <<<"$(usage_snapshot "$SID" || echo "0 0 0")"
FIVE="$(pct "$FIVE")"; WEEK="$(pct "$WEEK")"

CHK_5H="${USAGE_CHECKPOINT_PCT:-95}"
CHK_7D="${WEEKLY_CHECKPOINT_PCT:-95}"

WINDOW=""
[ "$FIVE" -ge "$CHK_5H" ] && WINDOW="5-hour window at ${FIVE}%"
[ "$WEEK" -ge "$CHK_7D" ] && WINDOW="${WINDOW:+$WINDOW; }weekly window at ${WEEK}%"
[ -n "$WINDOW" ] || exit 0

# Already checkpointed in the last 3 minutes? Then this turn did the work.
CHK="$(git rev-parse --show-toplevel 2>/dev/null || echo .)/.agent/CHECKPOINT.md"
[ -f "$CHK" ] || CHK="$AGENT_DIR/CHECKPOINT.md"
if [ -f "$CHK" ] && [ -n "$(find "$CHK" -mmin -3 2>/dev/null)" ]; then
  log "usage-gate: ${WINDOW}, checkpoint is fresh, allowing stop"
  touch "$STATE_DIR/$WORKER.quota-parked"
  exit 0
fi

log "usage-gate: blocking once to force checkpoint (${WINDOW})"
RESET_H="unknown"
[ "${RESETS:-0}" -gt 0 ] 2>/dev/null && RESET_H="$(date -r "$RESETS" '+%H:%M' 2>/dev/null || date -d "@$RESETS" '+%H:%M' 2>/dev/null || echo unknown)"

jq -nc --arg w "$WINDOW" --arg r "$RESET_H" --arg c "$CHK" '{
  decision: "block",
  reason: ("Usage checkpoint reached (\($w)). The limit resets around \($r).\n\n" +
           "Do exactly this and nothing else:\n" +
           "1. Commit any work in progress with a WIP message if it is not already committed.\n" +
           "2. Rewrite \($c) with: current task id, files touched, last commit sha, the exact next step, and anything you were part-way through.\n" +
           "3. Stop. Do not start new work, do not claim another task, do not begin a refactor.\n\n" +
           "The supervisor will wake you after the reset and hand you this checkpoint.")
}'
exit 0
