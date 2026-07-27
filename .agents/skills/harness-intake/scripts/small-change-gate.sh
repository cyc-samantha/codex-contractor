#!/usr/bin/env bash
set -euo pipefail

fail_closed() {
  echo "small-change-gate: invalid or incomplete input" >&2
  exit 2
}

[[ "$#" -eq 8 ]] || fail_closed
command -v jq >/dev/null 2>&1 || fail_closed
command -v python3 >/dev/null 2>&1 || fail_closed

spec="$1"
repository="$2"
mode="$3"
already_requested="$4"
ambiguous="$5"
dependencies="$6"
architecture_change="$7"
scope_expansion="$8"

[[ -f "$spec" ]] || fail_closed
[[ "$mode" =~ ^(preflight|post-change)$ ]] || fail_closed
repository="$(cd "$repository" 2>/dev/null && pwd -P)" || fail_closed
git_root="$(git -C "$repository" rev-parse --show-toplevel 2>/dev/null)" \
  || fail_closed
git_root="$(cd "$git_root" 2>/dev/null && pwd -P)" || fail_closed
[[ "$repository" == "$git_root" ]] || fail_closed

for value in "$already_requested" "$ambiguous" "$dependencies" \
  "$architecture_change" "$scope_expansion"; do
  [[ "$value" =~ ^(true|false)$ ]] || fail_closed
done

jq -e '
  def repository_relative:
    length > 0
    and (startswith("/") | not)
    and (startswith("./") | not)
    and (startswith("../") | not)
    and (contains("/../") | not)
    and (endswith("/..") | not);

  type == "object"
  and (.intended_behavior | type == "string" and length > 0)
  and (.allowed_scope | type == "array" and length > 0
    and all(.[]; type == "string" and length > 0))
  and (.prohibited_changes | type == "array" and length > 0
    and all(.[]; type == "string" and length > 0))
  and (.expected_files | type == "array" and length > 0
    and all(.[]; type == "string" and repository_relative))
  and (.verification | type == "array" and length > 0
    and all(.[]; type == "string" and length > 0))
  and (.tdd_exception | type == "object")
  and (
    (.tdd_exception.type == "none"
      and .tdd_exception.rationale == null)
    or
    ((.tdd_exception.type | IN(
      "docs_only",
      "generated_artifact",
      "non_executable_metadata",
      "test_infrastructure_only",
      "exploratory_spike"
    ))
      and (.tdd_exception.rationale | type == "string" and length > 0))
  )
' "$spec" >/dev/null 2>&1 || fail_closed

if [[ "$already_requested" == "false" || "$ambiguous" == "true" \
  || "$dependencies" == "true" || "$architecture_change" == "true" \
  || "$scope_expansion" == "true" ]]; then
  echo "CONFIRM"
  exit 3
fi

[[ "$mode" == "post-change" ]] || {
  echo "PROCEED"
  exit 0
}

change_list="$(mktemp "${TMPDIR:-/tmp}/small-change-files.XXXXXX")" \
  || fail_closed
trap 'rm -f "$change_list"' EXIT
{
  git -C "$repository" diff --name-only -z HEAD
  git -C "$repository" ls-files --others --exclude-standard -z
} > "$change_list" || fail_closed

[[ -s "$change_list" ]] || fail_closed

while IFS= read -r -d '' touched_file; do
  [[ "$touched_file" != "." && "$touched_file" != /* \
    && "$touched_file" != ./* && "$touched_file" != ../* \
    && "$touched_file" != *"/../"* && "$touched_file" != *"/.." ]] \
    || fail_closed
  canonical_file="$(python3 -c \
    'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve(strict=False))' \
    "$repository/$touched_file")" || fail_closed
  [[ "$canonical_file" == "$repository/"* ]] || fail_closed
  jq -e --arg file "$touched_file" \
    '.expected_files | index($file) != null' "$spec" >/dev/null || {
      echo "CONFIRM"
      exit 3
    }
done < "$change_list"

echo "PROCEED"
