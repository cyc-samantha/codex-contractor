#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  HARNESS_DATA="$BATS_TEST_TMPDIR/harness"
  WORKTREE="$BATS_TEST_TMPDIR/worktree"
  mkdir -p "$WORKTREE"
  git -C "$WORKTREE" init -q -b build/claim
  git -C "$WORKTREE" config user.email test@example.com
  git -C "$WORKTREE" config user.name Test
  touch "$WORKTREE/README"
  git -C "$WORKTREE" add README
  git -C "$WORKTREE" commit -qm initial
  HEAD="$(git -C "$WORKTREE" rev-parse HEAD)"
  CLI=(python3 "$REPO_ROOT/scripts/lib/writer_claim_cli.py" "$HARNESS_DATA")
  IDENTITY=(--owner codex --session-id session-a --repository "$WORKTREE" --branch build/claim --worktree "$WORKTREE")
}

@test "takeover records authorization and installs reconciled successor" {
  run "${CLI[@]}" acquire task-one "${IDENTITY[@]}"
  [ "$status" -eq 0 ]

  run "${CLI[@]}" takeover task-one \
    --owner codex --session-id session-b --repository "$WORKTREE" \
    --branch build/claim --worktree "$WORKTREE" --head "$HEAD" \
    --confirmed-stopped --authorizer-identity human@example.com \
    --authorization-reference incident-42 --rationale "prior process stopped"
  [ "$status" -eq 0 ]
  [[ "$output" == *'"session_id": "session-b"'* ]]
  grep -q '"authorization_reference": "incident-42"' "$HARNESS_DATA/pipeline-state/task-one/trajectory.jsonl"
}

@test "acquire inspect heartbeat and release expose claim lifecycle" {
  run "${CLI[@]}" acquire task-one "${IDENTITY[@]}"
  [ "$status" -eq 0 ]
  [[ "$output" == *'"session_id": "session-a"'* ]]

  run "${CLI[@]}" inspect task-one
  [ "$status" -eq 0 ]

  run "${CLI[@]}" heartbeat task-one "${IDENTITY[@]}"
  [ "$status" -eq 0 ]

  run "${CLI[@]}" release task-one "${IDENTITY[@]}"
  [ "$status" -eq 0 ]
  [ ! -e "$HARNESS_DATA/pipeline-state/task-one/writer.lock" ]
}

@test "takeover fails without human confirmation" {
  run "${CLI[@]}" acquire task-one "${IDENTITY[@]}"
  [ "$status" -eq 0 ]

  run "${CLI[@]}" takeover task-one --owner codex --session-id session-b --repository /repo --branch build/claim --worktree "$WORKTREE"
  [ "$status" -ne 0 ]
  [[ "$output" == *"auditable human authorization"* ]]
}
