#!/usr/bin/env bash
# Path-independent Quality Gate for /pr-creation Ship step.
# Exits 0 to proceed, 2 to block (PR_BLOCKED).
#
# Runs the full _qg_check_* suite (tests/lint/audit/shape/contract + freshness)
# regardless of which tool creates the PR: gh pr create, gh api, or MCP.
# A Bash hook matcher (hooks/quality-gate.sh:23) is path-dependent — it fires
# ONLY for `gh pr create`. This skill step is path-agnostic by construction.
#
# WHY: check loop MUST stay identical to hooks/quality-gate.sh:38-45.
# If you add a check there, add it here too (MCP/skill path vs Bash/hook path).
# GP-C1, issue #33106 — permissionDecision:deny is not enforced for MCP tools.
#
# Does NOT call _qg_finalize (needs pairing.sh + jsonl-emit.sh; a skill step
# is not a hook — event emission is a hook concern). Does NOT call
# check_hook_profile (profile-gating is hook-only). Issues its OWN verdict.
# Mirrors skills/pr-creation/lib/check-hook-pytest-gate.sh (exit-2 gate shape).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The authorized escape hatch must not depend on the gate implementation it
# exists to bypass. This also keeps migration-era missing helpers fail-closed
# unless a human explicitly sets the documented per-run override.
if [[ "${CLAUDE_DISABLE_QUALITY_GATE:-0}" == "1" ]]; then
  echo "[quality-gate] CLAUDE_DISABLE_QUALITY_GATE=1 — gate skipped."
  exit 0
fi

# Resolve worktree path — must be the worktree, not a foreign cwd.
# Allow override via $WORKTREE env var for testing.
_cqg_resolve_worktree() {
  if [ -n "${WORKTREE:-}" ]; then
    printf '%s' "$WORKTREE"
  else
    git rev-parse --show-toplevel
  fi
}
WORKTREE="$(_cqg_resolve_worktree)"

# WHY: cd "" is a POSIX no-op (returns 0) so an empty WORKTREE must be
# rejected before the || guard below can help.
if [ -z "$WORKTREE" ]; then
  echo "PR_BLOCKED — could not resolve worktree."
  echo ""
  echo "To bypass (use only when failures are demonstrably pre-existing and unrelated):"
  echo "  CLAUDE_DISABLE_QUALITY_GATE=1 <re-run Ship>"
  exit 2
fi

# cd to the worktree so _qg_check_freshness "" resolves evidence via base="."
# || guard: fail CLOSED so a stale/missing path does not evaluate a decoy cwd.
cd "$WORKTREE" || { echo "PR_BLOCKED — cannot cd to worktree: $WORKTREE"; exit 2; }

# Source check libs (no pairing.sh, no jsonl-emit.sh — no _qg_finalize).
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../../../hooks/_lib/check-bypass-gate.sh"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/../../../hooks/_lib/quality-gate-checks.sh"

# Honour bypass: CLAUDE_DISABLE_QUALITY_GATE=1 skips the entire gate.
_cqg_check_bypass() {
  if check_bypass_gate "CLAUDE_DISABLE_QUALITY_GATE"; then
    echo "[quality-gate] CLAUDE_DISABLE_QUALITY_GATE=1 — gate skipped."
    exit 0
  fi
}
_cqg_check_bypass

# Run all checks; aggregate failures.
_cqg_run_checks() {
  local any_failed=0 rc rt
  rt=$(_qg_detect_runtime)
  # WHY: loop MUST stay identical to hooks/quality-gate.sh:38-45 (GP-C1, #33106).
  if [[ "${CLAUDE_QG_SKIP_CHECKS:-0}" != "1" ]]; then
    for check in tests lint audit shape contract; do
      _qg_check_${check} "$rt"; rc=$?
      [[ $rc -ne 0 ]] && any_failed=1
    done
  fi
  _qg_check_freshness ""; rc=$?
  [[ $rc -ne 0 ]] && any_failed=1
  printf '%s' "$any_failed"
}

ANY_FAILED="$(_cqg_run_checks)"

_cqg_emit_verdict() {
  local any_failed="$1"
  if [[ "$any_failed" -eq 0 ]]; then
    echo "[quality-gate] PASS — all checks passed."
    exit 0
  fi
  echo ""
  echo "PR_BLOCKED — quality gate failed."
  echo "Fix the failing checks above, then retry Ship."
  echo ""
  echo "To bypass (use only when failures are demonstrably pre-existing and unrelated):"
  echo "  CLAUDE_DISABLE_QUALITY_GATE=1 <re-run Ship>"
  exit 2
}

_cqg_emit_verdict "$ANY_FAILED"
