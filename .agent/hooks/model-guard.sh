#!/usr/bin/env bash
# PreModelSwitch hook. Denies any switch to a model that can bill usage credits
# rather than plan capacity.
#
# This is the enforcement layer. CLAUDE.md asks nicely; a PreModelSwitch hook
# returning permissionDecision "deny" actually cancels the switch, and hooks fire
# before the permission-mode check, so no permission mode can bypass it.
#
# Register it with a broad matcher and decide here, so the allowlist lives in one
# readable place.

set -uo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../bin/_common.sh"

INPUT="$(cat)"
TARGET="$(jq -r '.model // .to // .new_model // empty' <<<"$INPUT" 2>/dev/null)"
[ -n "$TARGET" ] || exit 0

LOWER="$(printf '%s' "$TARGET" | tr '[:upper:]' '[:lower:]')"

deny() {
  log "model-guard: DENIED switch to $TARGET ($1)"
  jq -nc --arg m "$TARGET" --arg why "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreModelSwitch",
      permissionDecision: "deny",
      permissionDecisionReason: ("Blocked switch to \($m): \($why). This account runs on plan capacity only; models that can bill usage credits are not available. Stay on the current model. If the task genuinely requires more capability, log a blocker instead of switching.")
    }
  }'
  exit 0
}

case "$LOWER" in
  *fable*)  deny "Fable-class models can bill usage credits, and in non-interactive sessions they do so without a consent prompt" ;;
  *mythos*) deny "Mythos-class models are outside plan capacity" ;;
  *best*)   deny "the 'best' alias resolves to Fable where available" ;;
esac

case "$LOWER" in
  *"[1m]"*)
    deny "the 1M-context variant requires usage credits on this plan tier" ;;
esac

# Positive allowlist: anything not obviously an Opus/Sonnet/Haiku target is denied
# rather than allowed, so a new credit-billing family does not slip through.
case "$LOWER" in
  *opus*|*sonnet*|*haiku*|default|inherit|opusplan) exit 0 ;;
  *) deny "model is not on the plan-capacity allowlist (opus, sonnet, haiku, opusplan)" ;;
esac
