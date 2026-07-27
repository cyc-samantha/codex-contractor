#!/usr/bin/env bash
set -euo pipefail

kind="${1:-unknown}"
scope_clear="${2:-false}"
dependency_change="${3:-false}"
architecture_change="${4:-false}"
human_elevated="${5:-false}"

if [[ "$human_elevated" == "true" ]]; then
  echo "High Risk"
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
