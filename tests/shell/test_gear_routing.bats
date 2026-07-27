#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SKILL="$REPO_ROOT/.agents/skills/harness-intake/SKILL.md"
}

@test "intake skill exposes the four approved gears" {
  [ -f "$SKILL" ]

  for gear in "Discuss" "Small Change" "Build" "High Risk"; do
    run grep -F -- "$gear" "$SKILL"
    [ "$status" -eq 0 ]
  done
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
  run grep -F \
    'If scope, dependencies, architecture impact, or classification is uncertain, choose Build.' \
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
