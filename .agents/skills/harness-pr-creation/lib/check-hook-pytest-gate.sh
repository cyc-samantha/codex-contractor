#!/usr/bin/env bash
# Hook-Change Pytest Gate for /pr-creation Ship step.
# Exits 0 to proceed, 2 to block (PR_BLOCKED).
#
# Runs the targeted pytest subset from the worktree when the branch diff
# (main...HEAD) touches a hooks/*.sh or hooks/_lib/*.sh body line.
#
# if this regresses to a gh-keyed hook, gh api bypasses it — see GP-19.
#
# Modelled on skills/pr-creation/lib/check-approval-token.sh (exit-2 gate shape).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS_ROOT="${HARNESS_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}}}"

# Resolve worktree path — must be the worktree, not REPO_ROOT (GP-19 lesson).
# Allow override via $WORKTREE env var for testing.
if [ -z "${WORKTREE:-}" ]; then
  WORKTREE="$(cd "$(git rev-parse --show-toplevel)" && pwd -P)"
fi

# Source the reusable gate lib.
# shellcheck source=/dev/null
source "${HARNESS_ROOT}/hooks/_lib/hook-pytest-gate.sh"

# Guard: if WORKTREE HEAD is main/master the diff base is degenerate (empty),
# and the gate cannot see any hook changes — emit a loud WARN (GP-19 trap).
_hpg_check_degenerate_worktree() {
  local wt="$1"
  local head_branch
  head_branch=$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
  if [ "$head_branch" = "main" ] || [ "$head_branch" = "master" ]; then
    echo "HOOK-PYTEST GATE: WARN — \$WORKTREE HEAD is $head_branch; diff base main...HEAD is degenerate (empty), gate cannot see hook changes. Are you running from the worktree?"
  fi
}
_hpg_check_degenerate_worktree "$WORKTREE"

# Honour bypass gate — must come AFTER sourcing the lib (which sources check-bypass-gate.sh).
if check_bypass_gate "CLAUDE_DISABLE_HOOK_PYTEST_GATE"; then
  echo "[hook-pytest-gate] CLAUDE_DISABLE_HOOK_PYTEST_GATE=1 — gate skipped."
  exit 0
fi

# Check if any hook body changed.
if ! _hpg_hook_body_changed "$WORKTREE"; then
  echo "[hook-pytest-gate] No hook body changes detected — no-op, proceeding."
  exit 0
fi

echo "[hook-pytest-gate] Hook body change detected — running targeted pytest subset from worktree..." >&2

# Check for empty subset before running — surface the WARN/block to the operator.
_HPG_NODES=$(_hpg_targeted_nodes "$WORKTREE")
_HPG_NODES_RC=$?

if [ "$_HPG_NODES_RC" -eq 2 ]; then
  echo ""
  echo "PR_BLOCKED — hook body changed AND the targeted test(s) were deleted/renamed; cannot verify."
  echo "Restore the deleted/renamed test(s), or set CLAUDE_DISABLE_HOOK_PYTEST_GATE=1 to bypass."
  echo ""
  exit 2
fi

if [ -z "$_HPG_NODES" ]; then
  echo "HOOK-PYTEST GATE: WARN — hook body changed but NO targeted tests resolved; nothing ran"
  exit 0
fi

# Run the targeted subset.
if _hpg_run "$WORKTREE"; then
  echo "[hook-pytest-gate] Targeted subset GREEN — proceeding to PR creation."
  exit 0
fi

# Subset was RED — block the PR.
echo ""
echo "PR_BLOCKED — hook-change pytest gate failed."
echo "The targeted test subset (tests/test_*_invariants.py + hook-reading tests)"
echo "reported failures after this branch's hook changes."
echo "Fix the failing tests, then retry Ship."
echo ""
echo "To bypass (use only when failures are demonstrably pre-existing and unrelated):"
echo "  CLAUDE_DISABLE_HOOK_PYTEST_GATE=1 <re-run Ship>"
exit 2
