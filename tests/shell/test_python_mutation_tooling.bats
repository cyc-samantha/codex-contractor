#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
}

@test "pins the Python mutation-test dependencies" {
  run grep -Fx "mutmut==3.6.0" "$REPO_ROOT/requirements-dev.txt"
  [ "$status" -eq 0 ]

  run grep -Fx "pytest==8.4.2" "$REPO_ROOT/requirements-dev.txt"
  [ "$status" -eq 0 ]
}

@test "limits mutmut to the pipeline-state module and its tests" {
  run python3 -c '
import tomllib
from pathlib import Path

config = tomllib.loads(Path("pyproject.toml").read_text())["tool"]["mutmut"]
assert config["source_paths"] == ["scripts/lib"]
assert config["only_mutate"] == ["scripts/lib/pipeline_state.py"]
assert config["pytest_add_cli_args_test_selection"] == ["tests/test_pipeline_state.py"]
'

  [ "$status" -eq 0 ]
}

@test "CI installs the shared dev requirements before running mutmut" {
  run grep -F "pip install -r requirements-dev.txt" "$REPO_ROOT/.github/workflows/harness-gate.yml"
  [ "$status" -eq 0 ]

  run grep -F "mutmut run" "$REPO_ROOT/.github/workflows/harness-gate.yml"
  [ "$status" -eq 0 ]
}

@test "PR filtering protects mutation tooling and its Python test suite" {
  paths=(pyproject.toml requirements-dev.txt "scripts/**" tests/test_pipeline_state.py)
  for path in "${paths[@]}"; do
    run grep -F -- "- \"$path\"" "$REPO_ROOT/.github/workflows/harness-gate.yml"
    [ "$status" -eq 0 ]
  done
}

@test "README documents isolated Python setup and the mutation command" {
  run grep -F "python3 -m venv .venv" "$REPO_ROOT/README.md"
  [ "$status" -eq 0 ]

  run grep -F "python3 -m pip install -r requirements-dev.txt" "$REPO_ROOT/README.md"
  [ "$status" -eq 0 ]

  run grep -F "mutmut run" "$REPO_ROOT/README.md"
  [ "$status" -eq 0 ]
}

@test "mutation score gate rejects a score below seventy percent" {
  run bash -c "printf 'first: killed\\nsecond: survived\\n' | python3 '$REPO_ROOT/scripts/check-mutation-score.py'"

  [ "$status" -ne 0 ]
}

@test "mutation score gate accepts seventy percent and fails closed otherwise" {
  run bash -c "printf 'one: killed\\ntwo: killed\\nthree: killed\\nfour: killed\\nfive: killed\\nsix: killed\\nseven: killed\\neight: survived\\nnine: survived\\nten: survived\\n' | python3 '$REPO_ROOT/scripts/check-mutation-score.py'"
  [ "$status" -eq 0 ]

  run bash -c "printf 'one: timeout\\n' | python3 '$REPO_ROOT/scripts/check-mutation-score.py'"
  [ "$status" -eq 2 ]
}

@test "ignores local environments and mutmut artifacts" {
  run git -C "$REPO_ROOT" check-ignore .venv/ mutants/mutmut-stats.json

  [ "$status" -eq 0 ]
}
