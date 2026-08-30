#!/usr/bin/env bash
# Stop hook, registered last. Marks the worker idle once every other Stop gate
# has allowed the turn to end. Never blocks.

set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../bin/_common.sh"

INPUT="$(cat)"
# If another gate is mid-block, the turn is not really over.
[ "$(jq -r '.stop_hook_active // false' <<<"$INPUT")" = "true" ] && exit 0

echo "idle" > "$STATE_DIR/$WORKER.status"
date +%s > "$STATE_DIR/$WORKER.idle-since"
touch "$STATE_DIR/$WORKER.lease" 2>/dev/null || true
exit 0
