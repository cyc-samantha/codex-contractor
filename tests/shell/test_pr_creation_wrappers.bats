#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  QUALITY_GATE="$REPO_ROOT/.agents/skills/harness-pr-creation/lib/check-quality-gate.sh"
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
