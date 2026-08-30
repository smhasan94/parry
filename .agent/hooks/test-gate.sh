#!/usr/bin/env bash
# Stop hook. Runs TEST_CMD when the turn produced commits. Blocks on failure and
# hands the tail of the output back to Claude.
#
# Skipped entirely for turns with no commits, so exploration is not charged the
# cost of a test run.

set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../bin/_common.sh"

INPUT="$(cat)"
[ "$(jq -r '.stop_hook_active // false' <<<"$INPUT")" = "true" ] && exit 0

SNAP="$STATE_DIR/$WORKER.turn"
[ -f "$SNAP" ] || exit 0
# shellcheck source=/dev/null
. "$SNAP"

NOW_SHA="$(git rev-parse HEAD 2>/dev/null || echo none)"
[ "$NOW_SHA" = "${TURN_START_SHA:-none}" ] && exit 0

[ -n "${TEST_CMD:-}" ] || exit 0

OUT="$STATE_DIR/$WORKER.test.out"
log "test-gate: running: $TEST_CMD"

# Portable timeout: prefer coreutils timeout, fall back to a watchdog.
if have timeout; then
  timeout "${TEST_TIMEOUT:-300}" bash -lc "$TEST_CMD" > "$OUT" 2>&1
  RC=$?
elif have gtimeout; then
  gtimeout "${TEST_TIMEOUT:-300}" bash -lc "$TEST_CMD" > "$OUT" 2>&1
  RC=$?
else
  bash -lc "$TEST_CMD" > "$OUT" 2>&1 &
  TPID=$!
  ( sleep "${TEST_TIMEOUT:-300}"; kill -TERM "$TPID" 2>/dev/null ) & WPID=$!
  wait "$TPID"; RC=$?
  kill "$WPID" 2>/dev/null
fi

if [ "$RC" -eq 0 ]; then
  log "test-gate: green"
  exit 0
fi

if [ "$RC" -eq 124 ] || [ "$RC" -eq 143 ]; then
  log "test-gate: TIMED OUT after ${TEST_TIMEOUT:-300}s"
  jq -nc --arg t "${TEST_TIMEOUT:-300}" --arg c "${TEST_CMD:-}" '{
    decision: "block",
    reason: ("The test gate (\($c)) timed out after \($t)s. Either something you " +
             "changed hangs, or the suite is too slow for the gate. Investigate the hang " +
             "first. If the suite is simply slow, that is a blocker: log it with " +
             ".agent/bin/log-blocker and narrow TEST_CMD in .agent/config.sh is NOT your call " +
             "to make — log it and stop.")
  }'
  exit 0
fi

log "test-gate: FAILED rc=$RC"
TAIL="$(tail -c 4000 "$OUT")"
jq -nc --arg c "${TEST_CMD:-}" --arg rc "$RC" --arg out "$TAIL" '{
  decision: "block",
  reason: ("The test gate failed: \($c) exited \($rc). Fix it before stopping.\n\n" +
           "Do not skip, xfail, or delete the failing test, and do not change an assertion " +
           "to match observed output without understanding why the output changed. If you " +
           "cannot fix it, log a blocker with .agent/bin/log-blocker and leave it failing.\n\n" +
           "Last 4000 bytes of output:\n\n\($out)")
}'
exit 0
