#!/usr/bin/env bats
# CX-50 — main-branch-guard PreToolUse hook.

load helper

setup() { GUARD="${HOOKS_DIR}/main-branch-guard.sh"; }

@test "blocks bare 'git checkout' at repo root" {
  make_repo
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "git checkout -b topic")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "allows 'git -C <worktree> checkout' delegation form" {
  make_repo_with_worktree
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "git -C $WORKTREE_DIR checkout -b topic")' | '$GUARD'"
  [ "$status" -eq 0 ]
}

@test "allows a non-HEAD-mutating command" {
  make_repo
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "git status")' | '$GUARD'"
  [ "$status" -eq 0 ]
}

@test "blocks bare 'gh pr create' at repo root" {
  make_repo
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "gh pr create --fill")' | '$GUARD'"
  [ "$status" -eq 2 ]
  [[ "$output" == *"literal absolute registered-worktree path"* ]]
  [[ "$output" != *'$WT'* ]]
}

@test "allows 'gh pr create' delegated to a registered worktree" {
  make_repo_with_worktree
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "cd $WORKTREE_DIR && gh pr create --fill")' | '$GUARD'"
  [ "$status" -eq 0 ]
}

@test "blocks 'gh pr create' delegated to an unregistered directory" {
  make_repo
  local unregistered; unregistered="$(cxh_mktemp_dir)"
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "cd $unregistered && gh pr create --fill")' | '$GUARD'"
  rm -rf "$unregistered"
  [ "$status" -eq 2 ]
}

@test "blocks 'gh pr create' delegated through HOME" {
  make_repo_with_worktree
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash 'cd $HOME && gh pr create --fill')' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "blocks 'gh pr create' delegated through an unset variable" {
  make_repo_with_worktree
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash 'cd $UNSET_WORKTREE && gh pr create --fill')' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "blocks assignment-controlled worktree delegation" {
  make_repo_with_worktree
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "TARGET=$WORKTREE_DIR; cd \\$TARGET && gh pr create --fill")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "blocks registered-worktree delegation followed by repo-root escape" {
  make_repo_with_worktree
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "cd $WORKTREE_DIR && cd $REPO_DIR && gh pr create --fill")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "blocks parenthesized repo-root escape after worktree delegation" {
  make_repo_with_worktree
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "cd $WORKTREE_DIR && (cd $REPO_DIR && gh pr create --fill)")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "blocks newline-separated repo-root escape after worktree delegation" {
  make_repo_with_worktree
  local command payload
  command="cd $WORKTREE_DIR && git status"$'\n'"cd $REPO_DIR"$'\n'"gh pr create --fill"
  payload="$(payload_bash "$command")"
  run bash -c "cd '$REPO_DIR' && printf '%s' '$payload' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "blocks carriage-return repo-root escape after worktree delegation" {
  make_repo_with_worktree
  local command payload
  command="cd $WORKTREE_DIR && git status"$'\r'"cd $REPO_DIR"$'\r'"gh pr create --fill"
  payload="$(payload_bash "$command")"
  run bash -c "cd '$REPO_DIR' && printf '%s' '$payload' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "blocks nested git -C repo-root escape after worktree delegation" {
  make_repo_with_worktree
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "cd $WORKTREE_DIR && git -C $REPO_DIR checkout main")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "blocks nested git-dir repo-root escape after worktree delegation" {
  make_repo_with_worktree
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "cd $WORKTREE_DIR && git --git-dir=$REPO_DIR/.git checkout main")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "ignores non-Bash tool payloads" {
  run bash -c "printf '%s' '$(payload_write /tmp/x.py)' | '$GUARD'"
  [ "$status" -eq 0 ]
}

# --- wrapper-bypass hardening (security-review MEDIUM finding) ---

@test "blocks 'command git checkout' wrapper bypass at repo root" {
  make_repo
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "command git checkout -b topic")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "blocks 'env git checkout' wrapper bypass at repo root" {
  make_repo
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "env git checkout -b topic")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "blocks 'nice -n 10 git checkout' wrapper bypass (separate-arg flag)" {
  make_repo
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "nice -n 10 git checkout -b topic")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "blocks 'stdbuf -o 0 git checkout' wrapper bypass (separate-arg flag)" {
  make_repo
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "stdbuf -o 0 git checkout -b topic")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "blocks 'timeout 5 git checkout' wrapper bypass (mandatory positional arg)" {
  make_repo
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "timeout 5 git checkout -b topic")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "allows 'git -C <worktree> checkout' delegation form under a wrapper" {
  make_repo_with_worktree
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "nice -n 10 git -C $WORKTREE_DIR checkout -b topic")' | '$GUARD'"
  [ "$status" -eq 0 ]
}

# --- wrapper + git -C composition (security-review round 3 CRITICAL) ---
# A wrapper prefix must not skip git -C worktree validation: the wrapper
# must be stripped BEFORE git -C detection, not after.

@test "blocks 'nice git -C <REPO_ROOT> checkout' (wrapper hides REPO_ROOT target)" {
  make_repo
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "nice git -C $REPO_DIR checkout main")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "blocks 'command git -C <unregistered-path> checkout' (wrapper hides unregistered target)" {
  make_repo
  local unregistered; unregistered="$(cxh_mktemp_dir)"
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "command git -C $unregistered checkout -b evil main")' | '$GUARD'"
  rm -rf "$unregistered"
  [ "$status" -eq 2 ]
}

@test "blocks 'env -i VAR=x git checkout' (KEY=VALUE + -i wrapper form)" {
  make_repo
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "env -i VAR=x git checkout -b topic")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "blocks 'env VAR=x git checkout' (bare KEY=VALUE wrapper form)" {
  make_repo
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "env VAR=x git checkout -b topic")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

# --- wrapper allow-list completeness (code-review round 3 CRITICAL) ---
# setsid/ionice/chrt/taskset/flock/sudo/doas are unprivileged (or
# privilege-adjacent) exec-passthrough wrappers in the same class as
# nice/timeout/stdbuf and must be stripped identically.

@test "blocks 'setsid git checkout main' wrapper bypass" {
  make_repo
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "setsid git checkout main")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "blocks 'sudo git checkout main' wrapper bypass" {
  make_repo
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "sudo git checkout main")' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "allows 'setsid git status' under new wrapper (no over-reach)" {
  make_repo
  run bash -c "cd '$REPO_DIR' && printf '%s' '$(payload_bash "setsid git status")' | '$GUARD'"
  [ "$status" -eq 0 ]
}

# --- Iron Law 8: fail-closed on unevaluable input ---

@test "fail-closed: blocks an empty payload" {
  run bash -c "printf '' | '$GUARD'"
  [ "$status" -eq 2 ]
}

@test "fail-closed: blocks a non-JSON payload" {
  run bash -c "printf 'not json at all' | '$GUARD'"
  [ "$status" -eq 2 ]
}

teardown() { cxh_cleanup; }
