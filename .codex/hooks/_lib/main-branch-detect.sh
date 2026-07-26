#!/usr/bin/env bash
# Main-branch invariant detection. Bash 3.2 SAFE; ERE only. Per-clause check is
# the unit; `cd <path> &&` whole-command early-exit validates cd target against
# registered worktrees. `git -C`/`--git-dir=` are self-contained per clause.
# Regexes live in main-branch-detect-regex.sh.
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/main-branch-detect-regex.sh"

# Pure output-filter commands that, when appearing as a pipe RHS, can be
# safely stripped before clause splitting — they consume stdout but cannot
# mutate HEAD. Iterative stripping handles chained filters
# (`cmd | grep foo | head`). The forbidden leading clause is preserved, so
# `git checkout foo | tail` still blocks at the `git checkout foo` clause.
# Redirect tokens (2>&1, &>, >file, etc.) are also stripped — they confuse
# the safe-pull / safe-fetch carve-outs that iterate whitespace-split tokens.
_mbd_strip_filter_tails() {
  local cmd="$1" prev
  local filter_re='[[:space:]]*\|[[:space:]]*(tail|head|grep|jq|awk|sed|cat|tr|wc|sort)([[:space:]][^|;&]*)?$'
  local redirect_re='([[:space:]]+[0-9]*(>>|<<|<|>)(&[0-9]+|[[:space:]]*[^[:space:]|;&]+)|[[:space:]]+&>[[:space:]]*[^[:space:]|;&]+)'
  while :; do
    prev="$cmd"
    cmd=$(printf '%s' "$cmd" | sed -E "s#${filter_re}##")
    cmd=$(printf '%s' "$cmd" | sed -E "s#${redirect_re}##g")
    [[ "$cmd" == "$prev" ]] && break
  done
  printf '%s' "$cmd"
}

split_clauses() {
  printf '%s' "$1" | awk 'BEGIN{RS=""} { gsub(/\|\||&&|;|\|/, "\n"); print }'
}
_mbd_fetch_dst_remote_only() {
  printf '%s' "$1" | awk '
    { for(i=1;i<=NF;i++) if($i ~ /:/) { split($i,a,":"); d=a[2];
        if (d == "main" || d == "refs/heads/main") { bad=1; exit }
        if (d !~ /^refs\/remotes\//) { bad=1; exit } } }
    END { exit bad+0 }'
}
_mbd_is_safe_fetch() {
  [[ "$1" =~ git[[:space:]]+fetch[[:space:]] ]] && _mbd_fetch_dst_remote_only "$1"
}
# Safe when last non-flag token after `pull` is empty/origin/upstream/main.
_mbd_is_safe_pull() {
  [[ "$1" =~ git[[:space:]]+pull([[:space:]]|$) ]] || return 1
  local seen=0 b="" t
  for t in $1; do
    [[ "$seen" = 1 && ! "$t" =~ ^- ]] && b="$t"; [[ "$t" = "pull" ]] && seen=1
  done
  [[ -z "$b" || "$b" = "origin" || "$b" = "upstream" || "$b" = "main" ]]
}
# Safe when --ff-only and last non-flag target matches main/origin/upstream equivalents or is empty.
_mbd_is_safe_merge() {
  [[ "$1" =~ git[[:space:]]+merge[[:space:]]+--ff-only([[:space:]]|$) ]] || return 1
  local seen=0 b="" t
  for t in $1; do
    [[ "$t" = "--ff-only" ]] && seen=1 && continue
    [[ "$seen" = 1 && ! "$t" =~ ^- ]] && b="$t"
  done
  [[ -z "$b" ]] && return 1
  [[ "$b" =~ ^(origin/main|main|upstream/main|origin|upstream)$ ]]
}
# Safe when git checkout uses the pathspec form (-- separator): restores files
# without moving HEAD. Both bare and ref-prefixed forms are allowed:
#   git checkout -- <pathspec>
#   git checkout <ref> -- <pathspec>
# Branch-switching and branch-creating forms are NOT safe and fall through:
#   -b / -B / --branch create or move HEAD → blocked regardless of -- separator.
#   --orphan creates a new orphan branch and moves HEAD → blocked.
#   Trailing -- with NO pathspec (e.g. "git checkout main --") is ambiguous
#   and some git versions treat it as a branch switch → blocked; only
#   "-- <non-empty>" (space after -- followed by a non-space token) is safe.
# Bash 3.2 SAFE: ERE only, no PCRE.
_mbd_is_safe_checkout_pathspec() {
  [[ "$1" =~ git[[:space:]]+(checkout)[[:space:]] ]] || return 1
  # Block branch-create / orphan flags even when a -- separator is present;
  # -b/-B create a branch and move HEAD, --orphan does too.
  [[ "$1" =~ (^|[[:space:]])-[bB]([[:space:]]|$) ]] && return 1
  [[ "$1" =~ --orphan([[:space:]]|$) ]] && return 1
  # Require a ' -- <non-empty>' token: space-dash-dash-space followed by at
  # least one non-space character. Trailing ' --' with no pathspec is NOT safe.
  [[ "$1" =~ [[:space:]]--[[:space:]][^[:space:]] ]] || return 1
  return 0
}

# Safe when deleting a branch that is not the currently checked-out branch and
# is not a protected name (main/master). All non-flag tokens after -d/-D are
# collected; if ANY is a protected name or the current branch → not safe.
# Precedence: (1) git -C $CLAUDE_WORKTREE_PATH if set; (2) bare git rev-parse
# from hook cwd; (3) both empty → fail-closed. Detached HEAD yields literal
# "HEAD" which no real branch name equals → allowed (correct: no branch here).
_mbd_is_safe_branch_delete() {
  [[ "$1" =~ git[[:space:]]+branch[[:space:]]+-[dD]([[:space:]]|$) ]] || return 1
  local seen=0 t
  local -a targets=()
  for t in $1; do
    if [[ "$seen" = 1 && ! "$t" =~ ^- ]]; then targets+=("$t"); fi
    [[ "$t" =~ ^-[dD]$ ]] && seen=1
  done
  [[ ${#targets[@]} -eq 0 ]] && return 1
  # Block protected names regardless of current branch.
  for t in "${targets[@]}"; do
    [[ "$t" = "main" || "$t" = "master" ]] && return 1
  done
  local current=""
  if [[ -n "${CLAUDE_WORKTREE_PATH:-}" ]]; then
    current=$(git -C "${CLAUDE_WORKTREE_PATH}" rev-parse --abbrev-ref HEAD 2>/dev/null)
  fi
  if [[ -z "$current" ]]; then
    current=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
  fi
  [[ -z "$current" ]] && return 1
  # Block if ANY target matches the currently checked-out branch.
  for t in "${targets[@]}"; do
    [[ "$t" = "$current" ]] && return 1
  done
  return 0
}
# Extract the path token after `cd ` in a cd-prefix command.
# Two-pass: quoted form first (`cd "..."` or `cd '...'`), then unquoted fallback.
_mbd_extract_cd_target() {
  local result
  result=$(printf '%s' "$1" | sed -E "s#^[[:space:]]*\(?[[:space:]]*cd[[:space:]]+['\"]([^'\"]+)['\"].*#\1#")
  if [[ "$result" != "$1" ]]; then printf '%s' "$result"; return; fi
  printf '%s' "$1" | sed -E 's#^[[:space:]]*\(?[[:space:]]*cd[[:space:]]+([^[:space:]]+)[[:space:]].*#\1#'
}

# Extract the path token after `git -C ` from the start of a clause.
_mbd_extract_git_c_target() {
  printf '%s' "$1" | sed -E 's#^[[:space:]]*\(?[[:space:]]*git[[:space:]]+-C[[:space:]]+([^[:space:]]+).*#\1#'
}

# Strip the `-C <path>` from a git -C clause so the verb becomes visible.
_mbd_strip_git_c_prefix() {
  printf '%s' "$1" | sed -E 's#[[:space:]]+-C[[:space:]]+[^[:space:]]+##'
}

# Validate that a raw path token (possibly quoted) resolves to a registered
# worktree — NOT REPO_ROOT. Fail-closed on empty, unresolvable, or unregistered.
# If python3 is absent, deny (return 1 = blocked) — fail-CLOSED; allowing
# would re-enable the REPO_ROOT delegation bypass.
# Breadcrumb: if ALL delegation is blocked, verify hook cwd is within a git repo
# and that python3 is in PATH.
_mbd_target_is_valid_worktree() {
  local raw="$1"
  # Dequote surrounding double-quotes then single-quotes (BSD sed safe; $ protected).
  local target
  target=$(printf '%s' "${raw:-}" | sed -E 's#^"(.*)"$#\1#')
  target=$(printf '%s' "${target:-}" | sed -E "s/^'(.*)'$/\\1/")
  # Empty after dequote → deny.
  [[ -z "${target:-}" ]] && return 1
  # Variable targets are unevaluable from the command string and therefore
  # cannot prove registered-worktree identity.
  [[ "${target:0:1}" = '$' ]] && return 1
  # Backtick command substitution anywhere in target → deny.
  [[ "$target" == *'`'* ]] && return 1
  # Require python3 for canonical path resolution; fail-CLOSED if absent
  # (returning 0 = allow would re-enable REPO_ROOT delegation bypass).
  command -v python3 > /dev/null 2>&1 || return 1
  local resolved; resolved=$(python3 -c 'import os.path,sys; print(os.path.realpath(sys.argv[1]))' "$target" 2>/dev/null)
  [[ -z "${resolved:-}" ]] && return 1
  # Get REPO_ROOT: CLAUDE_WORKTREE_PATH leg first for fast-path, then bare git.
  local repo_real=""
  if [[ -n "${CLAUDE_WORKTREE_PATH:-}" ]]; then
    local cwp_real; cwp_real=$(python3 -c 'import os.path,sys; print(os.path.realpath(sys.argv[1]))' "${CLAUDE_WORKTREE_PATH}" 2>/dev/null)
    if [[ -n "${cwp_real:-}" && "$cwp_real" = "$resolved" ]]; then
      # Fast-path: matches CLAUDE_WORKTREE_PATH exactly → valid registered worktree.
      return 0
    fi
  fi
  # Resolve REPO_ROOT CWD-independently: first entry of porcelain worktree list = main worktree.
  # Replaces `git rev-parse --show-toplevel` which is CWD-dependent — when hook CWD is a
  # registered worktree, rev-parse returns the worktree root, making it appear equal to
  # REPO_ROOT and causing self-denial of legitimate `cd <worktree> && gh pr create` commands.
  # Amendment 2: `head -1` is correct here (first entry = main worktree unconditionally).
  local repo_root
  repo_root=$(git worktree list --porcelain 2>/dev/null \
    | awk '/^worktree /{print $2}' | head -1)
  # Fallback: CLAUDE_PROJECT_DIR if set and porcelain list empty.
  # Canonicalize and require the dir to exist; fail-closed on garbage path.
  if [[ -z "${repo_root:-}" && -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    repo_root=$(python3 -c 'import os.path,sys; print(os.path.realpath(sys.argv[1]))' \
      "${CLAUDE_PROJECT_DIR}" 2>/dev/null)
    [[ -d "${repo_root:-}" ]] || return 1
  fi
  [[ -z "${repo_root:-}" ]] && return 1
  repo_real=$(python3 -c 'import os.path,sys; print(os.path.realpath(sys.argv[1]))' "${repo_root}" 2>/dev/null)
  [[ -z "${repo_real:-}" ]] && return 1
  # REPO_ROOT itself → deny.
  [[ "$resolved" = "$repo_real" ]] && return 1
  # Check registered worktrees (skip first entry = main worktree = REPO_ROOT).
  local wt_path wt_real
  while IFS= read -r wt_path; do
    [[ -z "${wt_path:-}" ]] && continue
    wt_real=$(python3 -c 'import os.path,sys; print(os.path.realpath(sys.argv[1]))' "${wt_path}" 2>/dev/null)
    [[ -n "${wt_real:-}" && "$wt_real" = "$resolved" ]] && return 0
  done < <(git worktree list --porcelain 2>/dev/null \
    | awk '/^worktree /{print $2}' | tail -n +2)
  # Not found in registry → deny, fail-closed.
  return 1
}

is_forbidden_clause() {
  local clause="$1" norm git_c_target=""
  # Strip leading wrapper tokens (command/env/nice/.../timeout) FIRST — every
  # downstream check (wrapper_re, git -C detection/validation, forbidden_re,
  # the safe-form carve-outs) is anchored or target-extracting and must see
  # the unwrapped clause. A wrapper token left in place pushes `git` off the
  # `^` anchor these checks rely on, silently skipping git -C worktree
  # validation (security-review round 3 CRITICAL).
  clause=$(_mbd_strip_leading_wrappers "$clause")
  [[ "$clause" =~ $(_mbd_wrapper_re) ]] && return 0
  # Detect git -C <path> prefix; extract target and strip before normalization.
  # Cache regex once — _mbd_git_c_prefix_re uses [[:space:]] which matches tabs,
  # so this correctly catches both space- and tab-separated -C forms.
  local git_c_re; git_c_re=$(_mbd_git_c_prefix_re)
  if [[ "$clause" =~ $git_c_re ]]; then
    git_c_target=$(_mbd_extract_git_c_target "$clause")
    clause=$(_mbd_strip_git_c_prefix "$clause")
    # Multiple -C flags: if stripping one -C still leaves another, deny outright.
    # (git applies -C cumulatively; last wins — agents never legitimately need 2+.)
    if [[ "$clause" =~ $git_c_re ]]; then
      return 0
    fi
  fi
  norm=$(_mbd_normalize "$clause")
  [[ "$norm" =~ $(_mbd_forbidden_re) ]] || return 1
  _mbd_is_safe_fetch "$norm" && return 1
  _mbd_is_safe_pull "$norm" && return 1
  _mbd_is_safe_merge "$norm" && return 1
  _mbd_is_safe_branch_delete "$norm" && return 1
  _mbd_is_safe_checkout_pathspec "$norm" && return 1
  # If this clause had a git -C target, validate it; allow only registered worktrees.
  if [[ -n "${git_c_target:-}" ]]; then
    _mbd_target_is_valid_worktree "$git_c_target" && return 1
    return 0
  fi
  return 0
}
_mbd_any_clause_forbidden() {
  local clause
  while IFS= read -r clause; do
    [[ -n "$clause" ]] && is_forbidden_clause "$clause" && return 0
  done < <(split_clauses "$1")
  return 1
}
_mbd_is_safe_cd_delegation() {
  local remainder
  remainder=$(printf '%s' "$1" | sed -E 's#^[[:space:]]*\(?[[:space:]]*cd[[:space:]]+[^[:space:]]+[[:space:]]*&&[[:space:]]*##')
  LC_ALL=C printf '%s' "$remainder" | grep -q '[[:cntrl:]]' && return 1
  [[ "$remainder" =~ ^gh[[:space:]]+pr[[:space:]]+create([[:space:]]|$) ]] || return 1
  [[ "$remainder" == *'&'* || "$remainder" == *';'* || "$remainder" == *'|'* ]] && return 1
  [[ "$remainder" == *'('* || "$remainder" == *')'* || "$remainder" == *'`'* ]] && return 1
  return 0
}
is_forbidden_command() {
  if [[ "$1" =~ $(_mbd_cd_prefix_re) ]]; then
    _mbd_target_is_valid_worktree "$(_mbd_extract_cd_target "$1")" || return 0
    _mbd_is_safe_cd_delegation "$1" && return 1
    return 0
  fi
  local stripped; stripped=$(_mbd_strip_filter_tails "$1")
  _mbd_any_clause_forbidden "$stripped"
}
# Test-fixture helpers (is_in_main_tree/is_in_worktree) live in main-branch-detect-fixtures.sh.
