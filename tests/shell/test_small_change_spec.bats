#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  GATE="$REPO_ROOT/.agents/skills/harness-intake/scripts/small-change-gate.sh"
  SPEC="$REPO_ROOT/tests/fixtures/small-change/compact-spec.json"
}

@test "complete compact specification may proceed without second approval" {
  run "$GATE" "$SPEC" true false false false false README.md

  [ "$status" -eq 0 ]
  [ "$output" = "PROCEED" ]
}

@test "compact specification requires every contract field" {
  fields=(
    intended_behavior
    allowed_scope
    prohibited_changes
    expected_files
    verification
    tdd_exception
  )

  for field in "${fields[@]}"; do
    mutant="$BATS_TEST_TMPDIR/missing-$field.json"
    jq "del(.$field)" "$SPEC" > "$mutant"
    run "$GATE" "$mutant" true false false false false README.md
    [ "$status" -eq 2 ]
  done
}

@test "typed TDD exception rejects unknown type and missing rationale" {
  unknown="$BATS_TEST_TMPDIR/unknown-exception.json"
  missing_rationale="$BATS_TEST_TMPDIR/missing-rationale.json"
  jq '.tdd_exception.type = "skip_tests"' "$SPEC" > "$unknown"
  jq '.tdd_exception.rationale = ""' "$SPEC" > "$missing_rationale"

  run "$GATE" "$unknown" true false false false false README.md
  [ "$status" -eq 2 ]
  run "$GATE" "$missing_rationale" true false false false false README.md
  [ "$status" -eq 2 ]
}

@test "clear conversation plan is the only no-second-approval path" {
  confirmation_cases=(
    "false false false false false"
    "true true false false false"
    "true false true false false"
    "true false false true false"
    "true false false false true"
  )

  for flags in "${confirmation_cases[@]}"; do
    run "$GATE" "$SPEC" $flags README.md
    [ "$status" -eq 3 ]
    [ "$output" = "CONFIRM" ]
  done
}

@test "file outside expected scope requires confirmation" {
  run "$GATE" "$SPEC" true false false false false README.md AGENTS.md

  [ "$status" -eq 3 ]
  [ "$output" = "CONFIRM" ]
}

@test "malformed gate inputs fail closed" {
  run "$GATE" "$SPEC" TRUE false false false false README.md
  [ "$status" -eq 2 ]
  run "$GATE" "$SPEC" true false false false
  [ "$status" -eq 2 ]
  run "$GATE" "$BATS_TEST_TMPDIR/absent.json" true false false false false README.md
  [ "$status" -eq 2 ]
}

@test "expected files reject absolute and traversal paths" {
  unsafe_paths=(
    "/tmp/outside.md"
    "../outside.md"
    "./README.md"
  )

  for unsafe_path in "${unsafe_paths[@]}"; do
    mutant="$BATS_TEST_TMPDIR/unsafe-${unsafe_path//\//_}.json"
    jq --arg path "$unsafe_path" '.expected_files = [$path]' "$SPEC" > "$mutant"
    run "$GATE" "$mutant" true false false false false "$unsafe_path"
    [ "$status" -eq 2 ]
  done
}
