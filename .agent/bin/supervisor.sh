#!/usr/bin/env bash
# Supervisor. Never calls the model. It owns:
#   - one git worktree + one detached tmux session per worker
#   - dispatching queued tasks into idle workers
#   - holding dispatch when plan usage is high
#   - pressing Enter when a quota resume goes stale after a sleep
#   - re-dispatching after the reset when automatic continue gave up
#
# Workers run INTERACTIVE claude inside tmux on purpose. Automatic continue at a
# usage limit is available in interactive sessions only, not in background
# sessions or -p runs, and a detached tmux pane is still a real interactive
# session with a PTY. That is the whole trick.
#
#   supervisor.sh start | stop | status | loop | dispatch <worker> | logs

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/_common.sh"

: "${REPO_ROOT:?set REPO_ROOT in .agent/config.sh}"

# Validate BEFORE creating anything. A malformed REPO_ROOT (a stray brace or
# quote left over from editing config.sh is the usual cause) would otherwise get
# mkdir -p'd into existence and the whole run would proceed against a directory
# with no repository in it.
case "$REPO_ROOT" in
  *'}'*|*'{'*|*'$'*|*'"'*)
    echo "supervisor: REPO_ROOT contains a shell metacharacter: $REPO_ROOT" >&2
    echo "            Check .agent/config.sh. It should read, with no braces:" >&2
    echo '              REPO_ROOT="/Users/you/code/yourrepo"' >&2
    exit 1 ;;
esac
if [ ! -d "$REPO_ROOT" ]; then
  echo "supervisor: REPO_ROOT does not exist: $REPO_ROOT" >&2
  echo "            Fix the path in .agent/config.sh." >&2
  exit 1
fi
if ! git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  echo "supervisor: REPO_ROOT is not a git repository: $REPO_ROOT" >&2
  echo "            Fix the path in .agent/config.sh." >&2
  exit 1
fi

WORKTREE_BASE="$REPO_ROOT/.claude/worktrees"
mkdir -p "$WORKTREE_BASE" "$STATE_DIR"

need() { command -v "$1" >/dev/null || { echo "supervisor: missing $1" >&2; exit 69; }; }
need tmux; need jq; need git; need claude

sess() { echo "${TMUX_PREFIX:-cc}-$1"; }
wt()   { echo "$WORKTREE_BASE/$1"; }
slog() { printf '%s [supervisor] %s\n' "$(date -Iseconds)" "$*" | tee -a "$SUPERVISOR_LOG"; }

# --- usage ------------------------------------------------------------------

max_usage() {   # prints "5h 7d" as integers across all workers
  local f five=0 week=0 a b
  for f in "$STATE_DIR"/usage-*.json; do
    [ -e "$f" ] || continue
    a=$(jq -r '.five_h // 0' "$f" 2>/dev/null | cut -d. -f1); a=${a:-0}
    b=$(jq -r '.week // 0'   "$f" 2>/dev/null | cut -d. -f1); b=${b:-0}
    [ "$a" -gt "$five" ] 2>/dev/null && five=$a
    [ "$b" -gt "$week" ] 2>/dev/null && week=$b
  done
  echo "$five $week"
}

dispatch_allowed() {
  read -r five week <<<"$(max_usage)"
  if [ "$five" -ge "${USAGE_DISPATCH_PCT:-85}" ]; then
    echo "5-hour window at ${five}% (hold at ${USAGE_DISPATCH_PCT:-85}%)"; return 1
  fi
  if [ "$week" -ge "${WEEKLY_DISPATCH_PCT:-90}" ]; then
    echo "weekly window at ${week}% (hold at ${WEEKLY_DISPATCH_PCT:-90}%)"; return 1
  fi
  return 0
}

# --- worker lifecycle -------------------------------------------------------

ensure_worktree() {
  local w="$1" dir branch
  dir="$(wt "$w")"; branch="agent/$w"
  [ -d "$dir" ] && return 0
  slog "creating worktree $dir on $branch"
  git -C "$REPO_ROOT" fetch --quiet origin "${BASE_BRANCH}" 2>/dev/null || true
  if git -C "$REPO_ROOT" show-ref --verify --quiet "refs/heads/$branch"; then
    git -C "$REPO_ROOT" worktree add "$dir" "$branch" >/dev/null || {
      slog "FAILED to add worktree $dir on existing branch $branch"; return 1; }
  else
    git -C "$REPO_ROOT" worktree add -b "$branch" "$dir" "$BASE_BRANCH" >/dev/null || {
      slog "FAILED to add worktree $dir on new branch $branch from $BASE_BRANCH"; return 1; }
  fi
  [ -d "$dir/.git" ] || [ -f "$dir/.git" ] || {
    slog "FAILED: $dir exists but is not a worktree"; return 1; }
}

ensure_session() {
  local w="$1" s dir
  s="$(sess "$w")"; dir="$(wt "$w")"
  tmux has-session -t "$s" 2>/dev/null && return 0
  ensure_worktree "$w" || { slog "not starting $w: worktree unavailable"; return 1; }
  slog "starting tmux session $s in $dir"
  tmux new-session -d -s "$s" -c "$dir" \
    "CC_WORKER=$w AGENT_DIR='$AGENT_DIR' exec claude --model '${WORKER_MODEL:-opusplan}' --permission-mode '${WORKER_PERMISSION_MODE:-acceptEdits}'"
  sleep 4
  echo "idle" > "$STATE_DIR/$w.status"
}

worker_status() {
  local w="$1"
  tmux has-session -t "$(sess "$w")" 2>/dev/null || { echo "down"; return; }
  cat "$STATE_DIR/$w.status" 2>/dev/null || echo "idle"
}

send() {   # send a single-line prompt into a worker
  local w="$1"; shift
  local s; s="$(sess "$w")"
  tmux send-keys -t "$s" "$*" 2>/dev/null || return 1
  sleep 0.4
  tmux send-keys -t "$s" Enter 2>/dev/null
  echo "busy" > "$STATE_DIR/$w.status"
}

# --- dispatch ---------------------------------------------------------------

cmd_dispatch() {
  local w="${1:?usage: dispatch <worker>}"
  ensure_session "$w" || return 1
  if [ ! -f "$RUNNING_DIR/$w.task" ]; then
    "$HERE/queue" claim "$w" >/dev/null 2>&1 || { slog "queue empty, nothing for $w"; return 1; }
    slog "$w claimed $(sed -n 's/^id:[[:space:]]*//p' "$RUNNING_DIR/$w.task" | head -1)"
  fi
  send "$w" "Read .agent/CHECKPOINT.md and .agent/running/$w.task, then work the task loop in CLAUDE.md. Plan before you edit."
  slog "dispatched to $w"
}

resume_after_checkpoint() {
  local w="$1"
  send "$w" "Continue from .agent/CHECKPOINT.md. Pick up at the next step recorded there. Do not restart the task from the beginning."
  slog "resumed $w from checkpoint"
}

# --- the loop ---------------------------------------------------------------

tick() {
  local w st now reset hold
  now=$(date +%s)

  "$HERE/queue" reap "${STALE_LEASE_MINUTES:-90}" >/dev/null 2>&1 || true

  for w in ${WORKERS:-w1}; do
    ensure_session "$w" || continue

    # 1. A stale quota resume is waiting on a literal keypress.
    if [ -f "$STATE_DIR/$w.needs-enter" ]; then
      slog "$w: pressing Enter to clear stale quota resume"
      tmux send-keys -t "$(sess "$w")" Enter 2>/dev/null
      rm -f "$STATE_DIR/$w.needs-enter"
      continue
    fi

    # 2. Automatic continue gave up, or the turn died on a rate limit.
    if [ -f "$STATE_DIR/$w.needs-redispatch" ]; then
      reset=$(cat "$STATE_DIR/$w.needs-redispatch" 2>/dev/null || echo 0)
      if [ "${reset:-0}" -gt 0 ] && [ "$now" -lt "$reset" ]; then
        continue   # still inside the limit window; wait it out
      fi
      slog "$w: reset window passed, resuming"
      rm -f "$STATE_DIR/$w.needs-redispatch" "$STATE_DIR/$w.quota-parked"
      resume_after_checkpoint "$w"
      continue
    fi

    st="$(worker_status "$w")"
    [ "$st" = "busy" ] && continue
    [ "$st" = "quota_wait" ] && continue

    # 3. Idle. Parked on usage? Resume once headroom returns.
    if [ -f "$STATE_DIR/$w.quota-parked" ]; then
      if hold="$(dispatch_allowed)"; then :; else continue; fi
      rm -f "$STATE_DIR/$w.quota-parked"
      resume_after_checkpoint "$w"
      continue
    fi

    # 4. Idle with a task still leased: nudge it onward.
    if [ -f "$RUNNING_DIR/$w.task" ]; then
      if ! hold="$(dispatch_allowed)"; then
        slog "holding $w: $hold"; continue
      fi
      resume_after_checkpoint "$w"
      continue
    fi

    # 5. Idle and free: take new work, if there is headroom.
    if ! hold="$(dispatch_allowed)"; then
      slog "holding dispatch: $hold"; continue
    fi
    cmd_dispatch "$w" >/dev/null 2>&1 || true
  done
}

cmd_loop() {
  slog "supervisor up: workers=[${WORKERS}] repo=$REPO_ROOT interval=${SUPERVISOR_INTERVAL:-30}s"
  trap 'slog "supervisor stopping"; exit 0' TERM INT
  while true; do
    tick
    sleep "${SUPERVISOR_INTERVAL:-30}"
  done
}

cmd_start() {
  # Keep the machine awake. Without this a closed lid sleeps the Mac, and a
  # quota reset that lands during a >30 minute sleep needs a keypress to clear.
  if command -v caffeinate >/dev/null && ! pgrep -f 'caffeinate -dimsu' >/dev/null; then
    nohup caffeinate -dimsu >/dev/null 2>&1 &
    slog "started caffeinate"
  fi
  if tmux has-session -t "$(sess supervisor)" 2>/dev/null; then
    echo "supervisor already running"; return 0
  fi
  tmux new-session -d -s "$(sess supervisor)" -c "$REPO_ROOT" \
    "AGENT_DIR='$AGENT_DIR' exec '$HERE/supervisor.sh' loop"
  echo "supervisor started in tmux session $(sess supervisor)"
}

cmd_stop() {
  local w
  tmux kill-session -t "$(sess supervisor)" 2>/dev/null && echo "supervisor stopped"
  for w in ${WORKERS:-w1}; do
    tmux kill-session -t "$(sess "$w")" 2>/dev/null && echo "stopped worker $w"
  done
  pkill -f 'caffeinate -dimsu' 2>/dev/null && echo "released caffeinate"
  true
}

cmd_status() {
  read -r five week <<<"$(max_usage)"
  printf 'usage      5h %s%%   7d %s%%\n' "$five" "$week"
  if hold="$(dispatch_allowed)"; then printf 'dispatch   open\n'
  else printf 'dispatch   HELD (%s)\n' "$hold"; fi
  printf 'supervisor %s\n' "$(tmux has-session -t "$(sess supervisor)" 2>/dev/null && echo running || echo down)"
  echo
  local w
  for w in ${WORKERS:-w1}; do
    printf '  %-5s %-10s %-28s %s\n' "$w" "$(worker_status "$w")" \
      "$(sed -n 's/^id:[[:space:]]*//p' "$RUNNING_DIR/$w.task" 2>/dev/null | head -1 || echo '-')" \
      "$(wt "$w")"
  done
  echo
  "$HERE/queue" status
}

case "${1:-status}" in
  start)    cmd_start ;;
  stop)     cmd_stop ;;
  loop)     cmd_loop ;;
  tick)     tick ;;
  status)   cmd_status ;;
  dispatch) shift; cmd_dispatch "$@" ;;
  logs)     tail -n "${2:-50}" -f "$SUPERVISOR_LOG" ;;
  attach)   tmux attach -t "$(sess "${2:-w1}")" ;;
  *) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 64 ;;
esac
