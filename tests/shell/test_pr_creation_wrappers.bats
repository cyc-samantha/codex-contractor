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

@test "PR gate wrappers fail closed when shared helpers are unavailable" {
  wrappers=("$APPROVAL_GATE" "$HOOK_PYTEST_GATE" "$QUALITY_GATE")

  for wrapper in "${wrappers[@]}"; do
    run env HARNESS_ROOT="$BATS_TEST_TMPDIR/missing-harness" bash "$wrapper"
    [ "$status" -eq 2 ]
    [[ "$output" == *"PR_BLOCKED"* ]]
  done
}

@test "PR gate wrappers honor every documented harness-root fallback" {
  harness_root="$BATS_TEST_TMPDIR/harness"
  helper_dir="$harness_root/hooks/_lib"
  mkdir -p "$helper_dir"
  ln -s "$harness_root" "$BATS_TEST_TMPDIR/.claude"
  printf '%s\n' '_at_resolve_task_id() { :; }' > "$helper_dir/approval-token.sh"
  printf '%s\n' 'check_bypass_gate() { return 1; }' '_hpg_hook_body_changed() { return 1; }' > "$helper_dir/hook-pytest-gate.sh"
  printf '%s\n' 'check_bypass_gate() { return 1; }' > "$helper_dir/check-bypass-gate.sh"
  printf '%s\n' '_qg_detect_runtime() { echo unknown; }' '_qg_check_tests() { :; }' '_qg_check_lint() { :; }' '_qg_check_audit() { :; }' '_qg_check_shape() { :; }' '_qg_check_contract() { :; }' '_qg_check_freshness() { :; }' > "$helper_dir/quality-gate-checks.sh"

  for wrapper in "$APPROVAL_GATE" "$HOOK_PYTEST_GATE" "$QUALITY_GATE"; do
    run env HARNESS_ROOT="$harness_root" bash "$wrapper"; [ "$status" -eq 0 ]
    run env -u HARNESS_ROOT CLAUDE_PLUGIN_ROOT="$harness_root" bash "$wrapper"; [ "$status" -eq 0 ]
    run env -u HARNESS_ROOT -u CLAUDE_PLUGIN_ROOT CLAUDE_CONFIG_DIR="$harness_root" bash "$wrapper"; [ "$status" -eq 0 ]
    run env -u HARNESS_ROOT -u CLAUDE_PLUGIN_ROOT -u CLAUDE_CONFIG_DIR HOME="$BATS_TEST_TMPDIR" bash "$wrapper"; [ "$status" -eq 0 ]
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
