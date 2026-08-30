#!/usr/bin/env bash
# PreCompact hook. Compaction is the other way a long unattended session loses
# its place. Snapshot the mechanical facts to disk so session-start.sh can
# re-inject them afterwards, even if the summary drops them.

set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../bin/_common.sh"

cat > /dev/null

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
CHK="$ROOT/.agent/CHECKPOINT.md"

log "pre-compact: snapshotting state before compaction"

{
  echo ""
  echo "<!-- auto-appended by pre-compact hook $(date -Iseconds) -->"
  echo "- HEAD at compaction: $(git rev-parse --short HEAD 2>/dev/null || echo none)"
  echo "- branch: $(git branch --show-current 2>/dev/null || echo unknown)"
  echo "- uncommitted at compaction:"
  git status --short 2>/dev/null | sed 's/^/    /' | head -20
} >> "$CHK" 2>/dev/null || true

exit 0
