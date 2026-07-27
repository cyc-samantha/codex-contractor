#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SKILL="$REPO_ROOT/.agents/skills/harness-intake/SKILL.md"
  ROUTER="$REPO_ROOT/.agents/skills/harness-intake/scripts/route.sh"
}

@test "structured intake routes the approved decision table" {
  [ -x "$ROUTER" ]

  cases=(
    "question false false false false|Discuss"
    "documentation true false false false|Small Change"
    "configuration false false false false|Build"
    "bug true false false false|Build"
    "feature true false false false|Build"
    "refactor true false false false|Build"
    "question true false false true|High Risk"
  )

  for case in "${cases[@]}"; do
    inputs="${case%%|*}"
    expected="${case#*|}"
    run "$ROUTER" $inputs
    [ "$status" -eq 0 ]
    [ "$output" = "$expected" ]
  done
}

@test "skill catalog describes the standalone transition consistently" {
  CATALOG="$REPO_ROOT/.agents/skills/README.md"

  run grep -F 'The catalog now contains **25 available' "$CATALOG"
  [ "$status" -eq 0 ]
  run grep -F 'contractor handoff model' "$CATALOG"
  [ "$status" -eq 1 ]
  run grep -F 'keep-list below is **24 skills**' "$CATALOG"
  [ "$status" -eq 1 ]
}

@test "routing table keeps implementation out of Discuss" {
  run grep -F \
    '| Discuss | Question, research, brainstorming, or architecture discussion | No |' \
    "$SKILL"

  [ "$status" -eq 0 ]
}

@test "routing table sends bugs features and refactors to Build" {
  run grep -F \
    '| Build | Bug, feature, or refactor | Yes |' \
    "$SKILL"

  [ "$status" -eq 0 ]
}

@test "manual High Risk elevation wins and cannot be downgraded" {
  run grep -F \
    'A human High Risk elevation always wins. Never downgrade it.' \
    "$SKILL"

  [ "$status" -eq 0 ]
}

@test "uncertain or expanded scope fails upward to Build" {
  cases=(
    "documentation false false false"
    "documentation true true false"
    "documentation true false true"
    "question true true false"
    "question true false true"
    "unknown true false false"
  )

  for inputs in "${cases[@]}"; do
    run "$ROUTER" $inputs false
    [ "$status" -eq 0 ]
    [ "$output" = "Build" ]
  done
}

@test "malformed routing input fails closed" {
  cases=(
    "question true false false"
    "question true false false TRUE"
    "other true false false false"
  )

  for inputs in "${cases[@]}"; do
    run "$ROUTER" $inputs
    [ "$status" -eq 2 ]
  done
}

@test "Build approval gate blocks unapproved medium and large plans" {
  run grep -F \
    'A medium or large plan requires explicit human approval; do not enter Build until that approval is recorded.' \
    "$SKILL"

  [ "$status" -eq 0 ]
}

@test "intake output records routing evidence without creating Discuss state" {
  required=(
    'gear: <Discuss | Small Change | Build | High Risk>'
    'reason: <one sentence>'
    'human_elevated: <true | false>'
    'implementation_state: <create | none>'
  )

  for field in "${required[@]}"; do
    run grep -F -- "$field" "$SKILL"
    [ "$status" -eq 0 ]
  done

  run grep -F \
    'For Discuss, set `implementation_state: none` and do not create a worktree, task state, commit, or PR.' \
    "$SKILL"
  [ "$status" -eq 0 ]
}
