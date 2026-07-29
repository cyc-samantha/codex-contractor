#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
}

@test "justfile defines the repeatable CI task graph" {
  run grep -Fx "setup:" "$REPO_ROOT/justfile"
  [ "$status" -eq 0 ]

  run grep -Fx "toml-check:" "$REPO_ROOT/justfile"
  [ "$status" -eq 0 ]

  run grep -Fx "python-test:" "$REPO_ROOT/justfile"
  [ "$status" -eq 0 ]

  run grep -Fx "shell-test:" "$REPO_ROOT/justfile"
  [ "$status" -eq 0 ]

  run grep -Fx "hooks-json:" "$REPO_ROOT/justfile"
  [ "$status" -eq 0 ]

  run grep -Fx "shell-lint:" "$REPO_ROOT/justfile"
  [ "$status" -eq 0 ]

  run grep -Fx "ci: setup toml-check python-test hooks-json shell-lint shell-test" "$REPO_ROOT/justfile"
  [ "$status" -eq 0 ]

  run grep -F "uv venv --python 3.14 --allow-existing" "$REPO_ROOT/justfile"
  [ "$status" -eq 0 ]

  run grep -F "jq -e . .codex/hooks/hooks.json" "$REPO_ROOT/justfile"
  [ "$status" -eq 0 ]

  run grep -F "shellcheck --severity=error" "$REPO_ROOT/justfile"
  [ "$status" -eq 0 ]
}

@test "pull requests run CI when the justfile changes" {
  run grep -F -- '- "justfile"' "$REPO_ROOT/.github/workflows/harness-gate.yml"

  [ "$status" -eq 0 ]
}

@test "README documents the repeated CI commands" {
  run grep -F "just setup" "$REPO_ROOT/README.md"
  [ "$status" -eq 0 ]

  run grep -F "just ci" "$REPO_ROOT/README.md"
  [ "$status" -eq 0 ]
}
