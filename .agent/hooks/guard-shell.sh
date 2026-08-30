#!/usr/bin/env bash
# PreToolUse hook on Bash. Blocks the small set of commands that can destroy an
# unattended run: pushes to the default branch, force pushes, history rewrites,
# hard resets, and anything touching another worker's worktree.
#
# Exit 2 blocks and hands stderr back to Claude as feedback.

set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../bin/_common.sh"

INPUT="$(cat)"
CMD="$(jq -r '.tool_input.command // empty' <<<"$INPUT")"
[ -n "$CMD" ] || exit 0

block() { echo "BLOCKED by guard-shell: $1" >&2; log "guard-shell: blocked ($1): $CMD"; exit 2; }

# Normalise whitespace for matching.
N="$(printf '%s' "$CMD" | tr -s '[:space:]' ' ')"

case "$N" in
  *"git push"*"--force"*|*"git push"*" -f "*|*"git push --force"*)
    block "force push. Never rewrite a published branch in an unattended session." ;;
esac

case "$N" in
  *"git push"*" origin "*"main"*|*"git push"*" origin "*"master"*|*"git push origin HEAD:main"*|*"git push origin HEAD:master"*)
    block "push to the default branch. Push your own branch and open a PR instead." ;;
esac

case "$N" in
  *"git reset --hard"*)  block "git reset --hard. Use git revert, or commit first and branch." ;;
  *"git clean -"*)       block "git clean. It deletes untracked work the supervisor cannot recover." ;;
  *"git rebase"*)        block "git rebase. Merge or leave the branch as-is; the reviewer will handle history." ;;
  *"git filter-"*)       block "history rewrite." ;;
  *"git worktree remove"*|*"git worktree prune"*)
    block "worktree management. The supervisor owns worktrees." ;;
esac

# Cross-worktree access. Each worker may only touch its own directory.
if [ "$WORKER" != "solo" ]; then
  for other in ${WORKERS:-}; do
    [ "$other" = "$WORKER" ] && continue
    case "$N" in
      *".claude/worktrees/$other"*|*"/worktrees/$other"*|*"$other.task"*)
        block "access to worker $other's worktree or lease. Stay in your own." ;;
    esac
  done
fi

# The harness is not the worker's to edit.
case "$N" in
  *".agent/hooks/"*|*".agent/bin/"*|*".agent/config.sh"*)
    case "$N" in
      *".agent/bin/log-blocker"*|*".agent/bin/queue"*|*".agent/bin/render-blockers"*) ;;  # allowed CLIs
      *rm\ *|*mv\ *|*">"*|*sed\ -i*|*tee\ *)
        block "modification of the harness. Changing the harness is a blocker, not a fix." ;;
    esac ;;
esac

exit 0
