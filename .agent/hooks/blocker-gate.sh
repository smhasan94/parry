#!/usr/bin/env bash
# Stop hook. If the turn produced commits but added no blocker entry and left no
# explicit "no blocker" marker, block once and ask for one.
#
# Deterministic and cheap: compares HEAD and the blocker line count against the
# snapshot taken by turn-state.sh at UserPromptSubmit.

set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../bin/_common.sh"

INPUT="$(cat)"
[ "$(jq -r '.stop_hook_active // false' <<<"$INPUT")" = "true" ] && exit 0

SNAP="$STATE_DIR/$WORKER.turn"
[ -f "$SNAP" ] || exit 0            # no snapshot, nothing to compare
# shellcheck source=/dev/null
. "$SNAP"

NOW_SHA="$(git rev-parse HEAD 2>/dev/null || echo none)"
BLOCKER_LOG="${BLOCKER_LOG:-$AGENT_DIR/blockers.jsonl}"
NOW_LINES="$(wc -l < "$BLOCKER_LOG" 2>/dev/null || echo 0)"

# No commits this turn: nothing to account for.
[ "$NOW_SHA" = "${TURN_START_SHA:-none}" ] && exit 0

# A blocker was logged: satisfied.
[ "${NOW_LINES:-0}" -gt "${TURN_START_BLOCKERS:-0}" ] && exit 0

# Worker explicitly declared this turn clean: satisfied, consume the marker.
if [ -f "$STATE_DIR/$WORKER.no-blocker" ]; then
  rm -f "$STATE_DIR/$WORKER.no-blocker"
  log "blocker-gate: turn declared clean by worker"
  exit 0
fi

log "blocker-gate: blocking, commits present with no blocker accounting"
COUNT="$(git rev-list --count "${TURN_START_SHA:-HEAD}"..HEAD 2>/dev/null || echo '?')"

jq -nc --arg n "$COUNT" '{
  decision: "block",
  reason: ("This turn produced \($n) commit(s) but added nothing to .agent/blockers.jsonl.\n\n" +
           "If any gap, ambiguity, workaround, or judgement call came up — including anything " +
           "you decided on your own because the task did not say — log it now:\n\n" +
           "  .agent/bin/log-blocker \"<what was blocking>\" \"<resolution chosen>\" <low|medium|high> \"<what would make this wrong>\"\n\n" +
           "Risk is your confidence in the RESOLUTION, not the severity of the blocker. " +
           "See .agent/docs/blocker-schema.md.\n\n" +
           "If the turn genuinely involved none, say so explicitly and then stop:\n\n" +
           "  touch .agent/state/$CC_WORKER.no-blocker")
}'
exit 0
