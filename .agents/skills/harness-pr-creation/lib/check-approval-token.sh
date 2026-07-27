#!/usr/bin/env bash
# Approval token gate for /pr-creation. Exits 0 to proceed, 2 to block.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS_ROOT="${HARNESS_ROOT:-${CLAUDE_PLUGIN_ROOT:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}}}"
# shellcheck source=/dev/null
source "${HARNESS_ROOT}/hooks/_lib/approval-token.sh" || {
  echo "PR_BLOCKED: cannot load approval-token helper." >&2; exit 2;
}

BRANCH="$(git branch --show-current 2>/dev/null || echo "")"
TASK_ID="$(_at_resolve_task_id "$BRANCH")"

if [ -z "$TASK_ID" ] || ! _at_pipeline_active "$TASK_ID"; then
  echo "manual PR path — no active pipeline"
  exit 0
fi

if ! _at_token_exists "$TASK_ID"; then
  echo "PR_BLOCKED: approval token missing for task '$TASK_ID' (path=$(_at_token_path "$TASK_ID")). Remediation: Run /product-acceptance for this pipeline before /pr-creation."
  exit 2
fi

VERDICT="$(_at_token_verdict "$TASK_ID")"
case "$VERDICT" in
  APPROVED|APPROVED_WITH_CONDITIONS) exit 0 ;;
  REJECTED) echo "PR_BLOCKED: approval token verdict is REJECTED for task '$TASK_ID'. Remediation: Re-run /product-acceptance after fixes are applied." ;;
  *) echo "PR_BLOCKED: approval token malformed for task '$TASK_ID' (verdict='$VERDICT'). Remediation: Re-run /product-acceptance to write a fresh token." ;;
esac
exit 2
