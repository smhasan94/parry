#!/usr/bin/env bash
# UserPromptSubmit hook. Snapshots the state the Stop gates compare against, and
# marks the worker busy so the supervisor does not dispatch on top of it.

set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../bin/_common.sh"

cat > /dev/null   # drain stdin; we do not need the prompt

BLOCKER_LOG="${BLOCKER_LOG:-$AGENT_DIR/blockers.jsonl}"
cat > "$STATE_DIR/$WORKER.turn" <<EOF
TURN_START_SHA="$(git rev-parse HEAD 2>/dev/null || echo none)"
TURN_START_BLOCKERS="$(wc -l < "$BLOCKER_LOG" 2>/dev/null | tr -d ' ' || echo 0)"
TURN_START_AT="$(date -Iseconds)"
EOF

echo "busy" > "$STATE_DIR/$WORKER.status"
rm -f "$STATE_DIR/$WORKER.quota-parked"
exit 0
