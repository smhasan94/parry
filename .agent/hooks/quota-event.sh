#!/usr/bin/env bash
# Notification hook, registered against the quota_* matchers.
#
#   quota_auto_resume_fired     Claude Code resumed on its own. Nothing to do but log.
#   quota_auto_resume_stale     Machine slept >30m across the reset; the session is
#                               waiting for a literal Enter keypress. Flag it so the
#                               supervisor presses it.
#   quota_auto_resume_disabled  Claude Code gave up waiting. Flag for re-dispatch.
#
# The supervisor acts on the flags; a hook pressing keys into its own pane races
# with the session's own input handling.

set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../bin/_common.sh"

INPUT="$(cat)"
KIND="$(jq -r '.notification_type // .matcher // "unknown"' <<<"$INPUT" 2>/dev/null)"

case "$KIND" in
  *stale*)
    log "quota: resume went stale after sleep, asking supervisor to press Enter"
    date +%s > "$STATE_DIR/$WORKER.needs-enter"
    ;;
  *disabled*)
    log "quota: automatic continue ended without resuming, flagging for re-dispatch"
    SID="$(jq -r '.session_id // empty' <<<"$INPUT")"
    read -r _ _ RESETS <<<"$(usage_snapshot "$SID" || echo "0 0 0")"
    echo "${RESETS:-0}" > "$STATE_DIR/$WORKER.needs-redispatch"
    echo "quota_wait" > "$STATE_DIR/$WORKER.status"
    ;;
  *fired*)
    log "quota: resumed automatically"
    rm -f "$STATE_DIR/$WORKER.needs-enter" "$STATE_DIR/$WORKER.needs-redispatch" \
          "$STATE_DIR/$WORKER.quota-parked"
    echo "busy" > "$STATE_DIR/$WORKER.status"
    ;;
  *)
    log "quota: unrecognised notification '$KIND'"
    ;;
esac
exit 0
