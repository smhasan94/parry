#!/usr/bin/env bash
# Central configuration. Sourced by the supervisor, every hook, and the CLI tools.
# Edit this file; do not edit the scripts.

# --- Repository -------------------------------------------------------------
# Absolute path to the main checkout. The supervisor creates worktrees under it.
REPO_ROOT="/Users/sharukhhasan/code/parry"

# Branch new worktrees are cut from.
BASE_BRANCH="main"

# --- Workers ----------------------------------------------------------------
# Space-separated worker ids. Each gets its own tmux session and git worktree.
# Every extra worker burns plan capacity proportionally. Start with one.
WORKERS="w1"

# Model for worker sessions. opusplan = Opus while planning, Sonnet while executing.
WORKER_MODEL="${WORKER_MODEL:-opusplan}"

# Permission mode for unattended workers.
#   acceptEdits  - auto-approves file edits, still prompts for shell commands
#   auto         - classifier-gated, fewest stalls, requires /auto-mode-setup first
# bypassPermissions is deliberately not the default. See README before changing.
WORKER_PERMISSION_MODE="${WORKER_PERMISSION_MODE:-acceptEdits}"

# --- Usage policy -----------------------------------------------------------
# Write a checkpoint and wind down when the 5-hour window passes this percentage.
USAGE_CHECKPOINT_PCT="95"

# Stop dispatching new tasks above this percentage (leaves headroom to finish
# work already in flight rather than starting something that cannot complete).
USAGE_DISPATCH_PCT="85"

# Same thresholds for the weekly window.
WEEKLY_CHECKPOINT_PCT="${WEEKLY_CHECKPOINT_PCT:-95}"
WEEKLY_DISPATCH_PCT="${WEEKLY_DISPATCH_PCT:-90}"

# --- Testing ----------------------------------------------------------------
# Run from the worktree root. Keep it fast; it runs at the end of every turn
# that produced a commit. If your command contains double quotes, use single
# quotes here: TEST_CMD='${TEST_CMD:-pytest -q -k "not slow"}'
TEST_CMD="pytest -q -x -m 'not slow'"

# Seconds before the test gate gives up.
TEST_TIMEOUT="${TEST_TIMEOUT:-300}"

# --- Supervisor -------------------------------------------------------------
SUPERVISOR_INTERVAL="${SUPERVISOR_INTERVAL:-30}"   # seconds between polls
STALE_LEASE_MINUTES="${STALE_LEASE_MINUTES:-90}"   # reclaim a task after this idle
TMUX_PREFIX="${TMUX_PREFIX:-cc}"                   # tmux session name prefix

# --- Paths (derived; usually leave alone) -----------------------------------
AGENT_DIR="${AGENT_DIR:-$REPO_ROOT/.agent}"
STATE_DIR="$AGENT_DIR/state"
QUEUE_DIR="$AGENT_DIR/queue"
RUNNING_DIR="$AGENT_DIR/running"
DONE_DIR="$AGENT_DIR/done"
EXPORT_DIR="$AGENT_DIR/export"
BLOCKER_LOG="$AGENT_DIR/blockers.jsonl"
SUPERVISOR_LOG="$STATE_DIR/supervisor.log"
