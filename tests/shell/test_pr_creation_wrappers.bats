#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  APPROVAL_GATE="$REPO_ROOT/.agents/skills/harness-pr-creation/lib/check-approval-token.sh"
  HOOK_PYTEST_GATE="$REPO_ROOT/.agents/skills/harness-pr-creation/lib/check-hook-pytest-gate.sh"
  QUALITY_GATE="$REPO_ROOT/.agents/skills/harness-pr-creation/lib/check-quality-gate.sh"
}

@test "PR gate wrappers load shared helpers from HARNESS_ROOT" {
  wrappers=("$APPROVAL_GATE" "$HOOK_PYTEST_GATE" "$QUALITY_GATE")

  for wrapper in "${wrappers[@]}"; do
    run grep -F -- '"${HARNESS_ROOT}/hooks/_lib/' "$wrapper"
    [ "$status" -eq 0 ]
  done
}

@test "quality-gate wrapper honors its documented bypass before loading checks" {
  run env CLAUDE_DISABLE_QUALITY_GATE=1 bash "$QUALITY_GATE"

  [ "$status" -eq 0 ]
  [[ "$output" == *"gate skipped"* ]]
  [[ "$output" != *"No such file or directory"* ]]
  [[ "$output" != *"command not found"* ]]
}

@test "quality-gate wrapper does not bypass without the exact authorization" {
  run env CLAUDE_DISABLE_QUALITY_GATE=0 bash "$QUALITY_GATE"

  [ "$status" -eq 2 ]
  [[ "$output" == *"PR_BLOCKED"* ]]
  [[ "$output" != *"gate skipped"* ]]
}
