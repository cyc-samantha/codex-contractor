#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  GATE="$REPO_ROOT/.agents/skills/harness-intake/scripts/small-change-gate.sh"
  SPEC="$REPO_ROOT/tests/fixtures/small-change/compact-spec.json"
}

make_repository() {
  TEST_REPO="$BATS_TEST_TMPDIR/repository-$BATS_TEST_NUMBER"
  mkdir -p "$TEST_REPO"
  git -C "$TEST_REPO" init -q
  git -C "$TEST_REPO" config user.email test@example.invalid
  git -C "$TEST_REPO" config user.name Test
  printf 'initial\n' > "$TEST_REPO/README.md"
  git -C "$TEST_REPO" add README.md
  git -C "$TEST_REPO" commit -qm initial
}

@test "complete compact specification may proceed without second approval" {
  run "$GATE" "$SPEC" "$REPO_ROOT" preflight \
    true false false false false

  [ "$status" -eq 0 ]
  [ "$output" = "PROCEED" ]
}

@test "post-change derives an allowed touched file from Git" {
  make_repository
  printf 'changed\n' > "$TEST_REPO/README.md"

  run "$GATE" "$SPEC" "$TEST_REPO" post-change \
    true false false false false

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
    run "$GATE" "$mutant" "$REPO_ROOT" preflight \
      true false false false false
    [ "$status" -eq 2 ]
  done
}

@test "typed TDD exceptions accept the approved enum" {
  exception_types=(
    docs_only
    generated_artifact
    non_executable_metadata
    test_infrastructure_only
    exploratory_spike
  )

  for exception_type in "${exception_types[@]}"; do
    mutant="$BATS_TEST_TMPDIR/exception-$exception_type.json"
    jq --arg type "$exception_type" \
      '.tdd_exception = {type: $type, rationale: "Recorded exception"}' \
      "$SPEC" > "$mutant"
    run "$GATE" "$mutant" "$REPO_ROOT" preflight \
      true false false false false
    [ "$status" -eq 0 ]
  done
}

@test "typed TDD exception rejects unknown type and missing rationale" {
  unknown="$BATS_TEST_TMPDIR/unknown-exception.json"
  missing_rationale="$BATS_TEST_TMPDIR/missing-rationale.json"
  jq '.tdd_exception.type = "skip_tests"' "$SPEC" > "$unknown"
  jq '.tdd_exception.rationale = ""' "$SPEC" > "$missing_rationale"

  run "$GATE" "$unknown" "$REPO_ROOT" preflight \
    true false false false false
  [ "$status" -eq 2 ]
  run "$GATE" "$missing_rationale" "$REPO_ROOT" preflight \
    true false false false false
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
    run "$GATE" "$SPEC" "$REPO_ROOT" preflight $flags
    [ "$status" -eq 3 ]
    [ "$output" = "CONFIRM" ]
  done
}

@test "file outside expected scope requires confirmation" {
  make_repository
  printf 'outside\n' > "$TEST_REPO/AGENTS.md"

  run "$GATE" "$SPEC" "$TEST_REPO" post-change \
    true false false false false

  [ "$status" -eq 3 ]
  [ "$output" = "CONFIRM" ]
}

@test "malformed gate inputs fail closed" {
  run "$GATE" "$SPEC" "$REPO_ROOT" preflight \
    TRUE false false false false
  [ "$status" -eq 2 ]
  run "$GATE" "$SPEC" "$REPO_ROOT" unknown \
    true false false false false
  [ "$status" -eq 2 ]
  run "$GATE" "$BATS_TEST_TMPDIR/absent.json" "$REPO_ROOT" preflight \
    true false false false false
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
    run "$GATE" "$mutant" "$REPO_ROOT" preflight \
      true false false false false
    [ "$status" -eq 2 ]
  done
}

@test "post-change fails closed without Git change evidence" {
  make_repository
  run "$GATE" "$SPEC" "$TEST_REPO" post-change \
    true false false false false

  [ "$status" -eq 2 ]
}

@test "post-change fails closed when tracked evidence is unevaluable" {
  unborn="$BATS_TEST_TMPDIR/unborn"
  mkdir -p "$unborn"
  git -C "$unborn" init -q
  printf 'untracked\n' > "$unborn/README.md"

  run "$GATE" "$SPEC" "$unborn" post-change \
    true false false false false

  [ "$status" -eq 2 ]
}

@test "rename validates both source and destination scope" {
  make_repository
  printf 'outside\n' > "$TEST_REPO/OUTSIDE.md"
  git -C "$TEST_REPO" add OUTSIDE.md
  git -C "$TEST_REPO" commit -qm outside
  git -C "$TEST_REPO" mv OUTSIDE.md allowed.md
  mutant="$BATS_TEST_TMPDIR/rename-spec.json"
  jq '.expected_files = ["allowed.md"]' "$SPEC" > "$mutant"

  run "$GATE" "$mutant" "$TEST_REPO" post-change \
    true false false false false

  [ "$status" -eq 3 ]
  [ "$output" = "CONFIRM" ]
}

@test "canonical scope rejects an in-repository symlink escape" {
  make_repository
  outside="$BATS_TEST_TMPDIR/outside"
  mkdir -p "$outside"
  ln -s "$outside" "$TEST_REPO/escape"
  mutant="$BATS_TEST_TMPDIR/symlink-spec.json"
  jq '.expected_files = ["escape"]' "$SPEC" > "$mutant"

  run "$GATE" "$mutant" "$TEST_REPO" post-change \
    true false false false false

  [ "$status" -eq 2 ]
}
