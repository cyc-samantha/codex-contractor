#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 5 ]]; then
  echo "route: expected exactly 5 arguments" >&2
  exit 2
fi

kind="$1"
scope_clear="$2"
dependency_change="$3"
architecture_change="$4"
human_elevated="$5"

if [[ ! "$kind" =~ ^(question|research|brainstorm|architecture-discussion|documentation|configuration|bug|feature|refactor|unknown)$ ]]; then
  echo "route: invalid kind" >&2
  exit 2
fi

for value in "$scope_clear" "$dependency_change" "$architecture_change" "$human_elevated"; do
  if [[ ! "$value" =~ ^(true|false)$ ]]; then
    echo "route: booleans must be true or false" >&2
    exit 2
  fi
done

if [[ "$human_elevated" == "true" ]]; then
  echo "High Risk"
elif [[ "$dependency_change" == "true" || "$architecture_change" == "true" ]]; then
  echo "Build"
elif [[ "$kind" =~ ^(question|research|brainstorm|architecture-discussion)$ ]]; then
  echo "Discuss"
elif [[ "$kind" =~ ^(documentation|configuration)$ ]] \
  && [[ "$scope_clear" == "true" ]] \
  && [[ "$dependency_change" == "false" ]] \
  && [[ "$architecture_change" == "false" ]]; then
  echo "Small Change"
else
  echo "Build"
fi
