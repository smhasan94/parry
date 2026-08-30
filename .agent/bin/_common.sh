#!/usr/bin/env bash
# Shared helpers. Source this, do not run it.

# Locate the agent directory from wherever we were invoked. Hooks run with cwd
# set to the session's directory, which may be a worktree, so walk up to a
# checkout that has .agent/, then fall back to the main repo via config.
_find_agent_dir() {
  local d="${1:-$PWD}"
  while [ "$d" != "/" ]; do
    if [ -d "$d/.agent" ]; then printf '%s\n' "$d/.agent"; return 0; fi
    d="$(dirname "$d")"
  done
  return 1
}

AGENT_DIR="${AGENT_DIR:-$(_find_agent_dir || true)}"
if [ -z "$AGENT_DIR" ] || [ ! -d "$AGENT_DIR" ]; then
  echo "agent-runtime: cannot locate .agent directory from $PWD" >&2
  exit 0   # never break a session because the harness is misplaced
fi

# shellcheck source=/dev/null
[ -f "$AGENT_DIR/config.sh" ] && . "$AGENT_DIR/config.sh"

STATE_DIR="${STATE_DIR:-$AGENT_DIR/state}"
mkdir -p "$STATE_DIR"

WORKER="${CC_WORKER:-solo}"

log() {
  printf '%s [%s] %s\n' "$(date -Iseconds)" "$WORKER" "$*" \
    >> "${SUPERVISOR_LOG:-$STATE_DIR/supervisor.log}"
}

# Usage snapshot written by the status line. Prints "5h weekly resets" or nothing.
usage_snapshot() {
  local sid="$1" f
  f="$STATE_DIR/usage-$sid.json"
  [ -f "$f" ] || f="$(ls -t "$STATE_DIR"/usage-*.json 2>/dev/null | head -1)"
  [ -n "$f" ] && [ -f "$f" ] || return 1
  jq -r '"\(.five_h // 0) \(.week // 0) \(.resets // 0)"' "$f" 2>/dev/null
}

# Integer part of a possibly-float percentage, defaulting to 0.
pct() { printf '%.0f' "${1:-0}" 2>/dev/null || echo 0; }

have() { command -v "$1" >/dev/null 2>&1; }
