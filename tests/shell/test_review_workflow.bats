#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  PLAYBOOK="$REPO_ROOT/AGENTS.md"
  REVIEW_SKILL="$REPO_ROOT/.agents/skills/harness-code-review/SKILL.md"
}

@test "formal review spawns a distinct fresh read-only reviewer Agent" {
  required=(
    'fresh read-only collaboration reviewer Agent'
    '`collaboration.spawn_agent`'
    '`fork_turns: "none"`'
    '`gpt-5.6-sol`'
    '`medium` reasoning'
    'different model from the Builder'
    'fail closed'
  )

  for contract in "${required[@]}"; do
    run grep -F -- "$contract" "$REVIEW_SKILL"
    [ "$status" -eq 0 ]
  done

  run grep -F -- 'fresh read-only collaboration reviewer Agent' "$PLAYBOOK"
  [ "$status" -eq 0 ]
}

@test "formal review binds a clean immutable target before and after review" {
  run grep -F -- 'REVIEW_TARGET="$(git rev-parse HEAD)"' "$REVIEW_SKILL"
  [ "$status" -eq 0 ]

  run grep -F -- 'test "$(git rev-parse HEAD)" = "$REVIEW_TARGET"' "$REVIEW_SKILL"
  [ "$status" -eq 0 ]

  run grep -F -c -- 'test -z "$(git status --porcelain)"' "$REVIEW_SKILL"
  [ "$status" -eq 0 ]
  [ "$output" -eq 2 ]
}

@test "formal review forbids subprocess review and builder approval" {
  run grep -F -- 'Do not launch an additional `codex exec review` subprocess' \
    "$REVIEW_SKILL"
  [ "$status" -eq 0 ]

  run grep -F -- 'Builder self-review does not satisfy the formal review gate.' \
    "$REVIEW_SKILL"
  [ "$status" -eq 0 ]

  run grep -F -- 'there is no separate reviewer to spawn' "$REVIEW_SKILL"
  [ "$status" -eq 1 ]
}

@test "findings return to the engineer and raising reviewer" {
  run grep -F -- 'Return findings to the original engineer' "$REVIEW_SKILL"
  [ "$status" -eq 0 ]

  run grep -F -- 'targeted re-review with the raising reviewer' "$REVIEW_SKILL"
  [ "$status" -eq 0 ]
}
