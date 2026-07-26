#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  FIXTURES="$REPO_ROOT/tests/fixtures/pipeline-state"
}

fixture_audit() {
  local root="$1"
  local required
  required="task_id repository phase status branch worktree"

  for state in canonical-active canonical-completed; do
    for field in $required; do
      grep -Eq "^${field}: [^[:space:]].*" "$root/$state/pipeline.md" || return 1
    done
  done

  jq -e '
    .schema_version == 1
    and (.agent_role | type == "string" and length > 0)
    and (.head_sha | type == "string" and length > 0)
    and (.verdict | type == "string" and length > 0)
  ' "$root/build-result.json" >/dev/null || return 1

  jq -e '
    .schema_version == 1
    and (.task_id | type == "string" and length > 0)
    and (.git_head | type == "string" and length > 0)
    and (.verdict | type == "string" and length > 0)
  ' "$root/verification-evidence.json" >/dev/null || return 1

  jq -e '
    .schema_version == 1
    and (.task_id | type == "string" and length > 0)
    and (.source | type == "string" and length > 0)
    and (.outcome | type == "string" and length > 0)
  ' "$root/observation.json" >/dev/null
}

@test "ships the complete synthetic compatibility fixture set" {
  expected=(
    baseline.json
    build-result.json
    canonical-active/pipeline.md
    canonical-completed/pipeline.md
    legacy-pipeline.md
    malformed-unknown-version/pipeline.md
    observation.json
    verification-evidence.json
  )

  for fixture in "${expected[@]}"; do
    [ -f "$FIXTURES/$fixture" ]
  done
}

@test "canonical and evidence fixtures pass the identity audit" {
  run fixture_audit "$FIXTURES"

  [ "$status" -eq 0 ]
}

@test "identity audit kills every required-field deletion" {
  markdown_fields=(task_id repository phase status branch worktree)
  json_mutants=(
    build-result.json:agent_role
    build-result.json:head_sha
    build-result.json:verdict
    verification-evidence.json:task_id
    verification-evidence.json:git_head
    verification-evidence.json:verdict
    observation.json:task_id
    observation.json:source
    observation.json:outcome
  )

  for state in canonical-active canonical-completed; do
    for field in "${markdown_fields[@]}"; do
      copy="$BATS_TEST_TMPDIR/$state-$field"
      cp -R "$FIXTURES" "$copy"
      sed -i "/^${field}:/d" "$copy/$state/pipeline.md"

      run fixture_audit "$copy"
      [ "$status" -ne 0 ]
    done
  done

  for mutant in "${json_mutants[@]}"; do
    file="${mutant%%:*}"
    field="${mutant#*:}"
    copy="$BATS_TEST_TMPDIR/${file%.json}-$field"
    cp -R "$FIXTURES" "$copy"
    jq "del(.$field)" "$copy/$file" > "$copy/mutant.json"
    mv "$copy/mutant.json" "$copy/$file"

    run fixture_audit "$copy"
    [ "$status" -ne 0 ]
  done
}

@test "identity audit rejects empty JSON identity values" {
  copy="$BATS_TEST_TMPDIR/empty-identity"
  cp -R "$FIXTURES" "$copy"
  jq '.task_id = ""' "$copy/observation.json" > "$copy/mutant.json"
  mv "$copy/mutant.json" "$copy/observation.json"

  run fixture_audit "$copy"

  [ "$status" -ne 0 ]
}

@test "unknown-version fixture is explicitly malformed and unevaluable" {
  run grep -E '^schema_version: 999$' \
    "$FIXTURES/malformed-unknown-version/pipeline.md"
  [ "$status" -eq 0 ]

  run grep -E '^expected_verdict: FAIL_CLOSED$' \
    "$FIXTURES/malformed-unknown-version/pipeline.md"
  [ "$status" -eq 0 ]
}

@test "fixtures contain synthetic identities and no private runtime paths" {
  run grep -R -n -E -- \
    '(/home/|samanthachen|build-cfd-advisor|s1-ohlcv|cfd-advisor|edinplane)' \
    "$FIXTURES"

  [ "$status" -eq 1 ]
  run grep -R -n -E -- \
    'fixture-task|/synthetic/repository|fixture-worktree' "$FIXTURES"
  [ "$status" -eq 0 ]
}

@test "baseline pins every current harness-gate verification command" {
  run jq -e '
    .schema_version == 1
    and .suite == "harness-gate"
    and (.commands | index("jq -e . .codex/hooks/hooks.json"))
    and (.commands | index("shellcheck --severity=error .codex/hooks/*.sh .codex/hooks/_lib/*.sh scripts/*.sh"))
    and (.commands | index("bats tests/shell/"))
  ' "$FIXTURES/baseline.json"

  [ "$status" -eq 0 ]
}
