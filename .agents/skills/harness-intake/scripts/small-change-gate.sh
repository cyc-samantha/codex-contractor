#!/usr/bin/env bash
set -euo pipefail

fail_closed() {
  echo "small-change-gate: invalid or incomplete input" >&2
  exit 2
}

[[ "$#" -ge 6 ]] || fail_closed
command -v jq >/dev/null 2>&1 || fail_closed

spec="$1"
already_requested="$2"
ambiguous="$3"
dependencies="$4"
architecture_change="$5"
scope_expansion="$6"
shift 6

[[ -f "$spec" ]] || fail_closed

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
