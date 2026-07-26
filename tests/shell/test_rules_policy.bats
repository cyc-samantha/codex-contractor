#!/usr/bin/env bats

setup() {
  RULES_FILE="${BATS_TEST_DIRNAME}/../../.codex/rules/harness-destructive.rules"
}

@test "PR creation is delegated to the context-aware guard" {
  run grep -F 'prefix_rule(pattern=["gh", "pr", "create"], decision="forbidden")' \
    "$RULES_FILE"
  [ "$status" -eq 1 ]
}
