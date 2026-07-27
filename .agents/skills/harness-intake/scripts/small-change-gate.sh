#!/usr/bin/env bash
set -euo pipefail

fail_closed() {
  echo "small-change-gate: invalid or incomplete input" >&2
  exit 2
}

[[ "$#" -ge 8 ]] || fail_closed
command -v jq >/dev/null 2>&1 || fail_closed
command -v realpath >/dev/null 2>&1 || fail_closed

spec="$1"
repository="$2"
already_requested="$3"
ambiguous="$4"
dependencies="$5"
architecture_change="$6"
scope_expansion="$7"
shift 7

[[ -f "$spec" ]] || fail_closed
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
    (.tdd_exception.type == "docs_only"
      and (.tdd_exception.rationale | type == "string" and length > 0))
  )
' "$spec" >/dev/null 2>&1 || fail_closed

for touched_file in "$@"; do
  [[ "$touched_file" != "." && "$touched_file" != /* \
    && "$touched_file" != ./* && "$touched_file" != ../* \
    && "$touched_file" != *"/../"* && "$touched_file" != *"/.." ]] \
    || fail_closed
  canonical_file="$(realpath -m -- "$repository/$touched_file")" \
    || fail_closed
  [[ "$canonical_file" == "$repository/"* ]] || fail_closed
  jq -e --arg file "$touched_file" \
    '.expected_files | index($file) != null' "$spec" >/dev/null || {
      echo "CONFIRM"
      exit 3
    }
done

if [[ "$already_requested" == "false" || "$ambiguous" == "true" \
  || "$dependencies" == "true" || "$architecture_change" == "true" \
  || "$scope_expansion" == "true" ]]; then
  echo "CONFIRM"
  exit 3
fi

echo "PROCEED"
