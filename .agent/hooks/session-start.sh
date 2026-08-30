#!/usr/bin/env bash
# SessionStart hook (matchers: startup, resume, compact). stdout on exit 0 is
# added to Claude's context, which is how continuity survives a restart, a
# supervisor respawn, or a compaction.

set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../bin/_common.sh"

cat > /dev/null

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
CHK="$ROOT/.agent/CHECKPOINT.md"
[ -f "$CHK" ] || CHK="$AGENT_DIR/CHECKPOINT.md"
TASK="${RUNNING_DIR:-$AGENT_DIR/running}/$WORKER.task"

echo "=== Worker context (injected by session-start hook) ==="
echo "worker: $WORKER"
echo "worktree: $ROOT"
echo "branch: $(git branch --show-current 2>/dev/null || echo unknown)"
echo "HEAD: $(git rev-parse --short HEAD 2>/dev/null || echo none)"
echo

if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  echo "--- UNCOMMITTED CHANGES PRESENT ---"
  git status --short 2>/dev/null | head -30
  echo "Decide whether these are yours to finish or to discard before starting new work."
  echo
fi

if [ -f "$TASK" ]; then
  echo "--- Current task ($TASK) ---"
  cat "$TASK"
  echo
else
  echo "--- No task leased. Do not claim one; wait for the supervisor to dispatch. ---"
  echo
fi

if [ -f "$CHK" ]; then
  echo "--- Checkpoint ($CHK) ---"
  cat "$CHK"
else
  echo "--- No checkpoint on file. This is a cold start. ---"
fi
echo
echo "Recent commits:"
git log --oneline -5 2>/dev/null || true
echo "=== end injected context ==="

echo "idle" > "$STATE_DIR/$WORKER.status"
exit 0
