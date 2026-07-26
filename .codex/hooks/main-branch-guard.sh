#!/usr/bin/env bash
# Main-branch invariant guard — Codex PreToolUse Bash hook (CX-50).
# Port of the Claude harness hooks/main-branch-guard.sh, stripped of the
# Claude-only logging/hook-profile scaffolding that Codex does not provide.
#
# Refuses HEAD-mutating commands at REPO_ROOT that lack an explicit worktree
# `git -C <literal-wt>` or `cd <literal-wt> && gh pr create` delegation, and blocks
# destructive verbs without a live confirmation token. Reads the tool payload
# on stdin ({"tool_name","tool_input":{"command"}}); exit 2 blocks the call.
#
# enforces: AGENTS.md § Iron Laws (Main-Branch Invariant)

set -uo pipefail
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${HOOK_DIR}/_lib/harness-paths.sh"
# shellcheck source=/dev/null
source "${HOOK_DIR}/_lib/main-branch-detect.sh"
# shellcheck source=/dev/null
source "${HOOK_DIR}/_lib/destructive-verb-detect.sh"

INPUT=$(cat)

# Fail-closed (Iron Law 8): an unevaluable payload — empty, or not JSON — cannot
# be checked for a forbidden command, so it must not be allowed through.
if [[ -z "$INPUT" ]] || ! printf '%s' "$INPUT" | jq -e . >/dev/null 2>&1; then
  printf 'BLOCKED: main-branch-guard received an unevaluable payload; failing closed.\n' >&2
  exit 2
fi

TOOL_NAME=$(printf '%s' "$INPUT" | jq -r '.tool_name // empty')
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')

[[ "$TOOL_NAME" != "Bash" ]] && exit 0
[[ -z "$COMMAND" ]] && exit 0

_mbg_redact() {
  printf '%s' "$1" | sed -E 's#(://)[^/@[:space:]]+:[^/@[:space:]]+@#\1REDACTED@#g'
}

_mbg_destructive_block() {
  printf 'BLOCKED: destructive verb detected without a live confirmation token.\n' >&2
  destructive_block_message "$(_mbg_redact "$COMMAND")"
  exit 2
}

_mbg_forbidden_block() {
  printf 'BLOCKED: REPO_ROOT HEAD must stay on `main`. The command:\n  %s\n' "$(_mbg_redact "$COMMAND")" >&2
  printf 'contains a HEAD-mutating clause without a delegation prefix.\n' >&2
  printf 'Use a literal absolute registered-worktree path: `cd /absolute/registered-worktree && gh pr create ...` or `git -C /absolute/registered-worktree ...`.\n' >&2
  printf 'See AGENTS.md § Iron Laws (Main-Branch Invariant).\n' >&2
  exit 2
}

if is_destructive_command "$COMMAND" && ! destructive_confirm_active; then
  _mbg_destructive_block
fi

is_forbidden_command "$COMMAND" || exit 0
_mbg_forbidden_block
