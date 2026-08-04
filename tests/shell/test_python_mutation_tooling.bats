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

@test "limits mutmut to protected Python modules and their tests" {
  run python3 -c '
import tomllib
from pathlib import Path

config = tomllib.loads(Path("pyproject.toml").read_text())["tool"]["mutmut"]
assert config["source_paths"] == ["scripts/lib"]
assert config["only_mutate"] == ["scripts/lib/code_review_dispatch.py", "scripts/lib/dispatch_contract.py", "scripts/lib/execution_policy.py", "scripts/lib/final_verification.py", "scripts/lib/orchestrator_write_boundary.py", "scripts/lib/pipeline_state.py", "scripts/lib/pr_handoff.py", "scripts/lib/pr_handoff_state.py", "scripts/lib/pr_handoff_validation.py", "scripts/lib/review_evidence.py", "scripts/lib/review_workflow.py", "scripts/lib/software_engineer_dispatch.py", "scripts/lib/spawn_telemetry.py", "scripts/lib/task_discovery.py", "scripts/lib/task_selection.py", "scripts/lib/writer_claim.py", "scripts/lib/writer_claim_io.py", "scripts/lib/writer_claim_reconciliation.py"]
assert config["pytest_add_cli_args_test_selection"] == ["tests/test_code_review_dispatch.py", "tests/test_dispatch_contract.py", "tests/test_execution_policy.py", "tests/test_final_verification.py", "tests/test_orchestrator_write_boundary.py", "tests/test_pipeline_state.py", "tests/test_pr_handoff.py", "tests/test_review_evidence.py", "tests/test_review_workflow.py", "tests/test_software_engineer_dispatch.py", "tests/test_spawn_telemetry.py", "tests/test_task_discovery.py", "tests/test_task_selection.py", "tests/test_writer_claim.py"]
'

  [ "$status" -eq 0 ]
}

@test "mutation config covers T13B-T13D protected modules and tests" {
  run python3 -c '
import tomllib
from pathlib import Path

config = tomllib.loads(Path("pyproject.toml").read_text())["tool"]["mutmut"]
assert "scripts/lib/execution_policy.py" in config["only_mutate"]
assert "scripts/lib/software_engineer_dispatch.py" in config["only_mutate"]
assert "scripts/lib/spawn_telemetry.py" in config["only_mutate"]
assert "tests/test_execution_policy.py" in config["pytest_add_cli_args_test_selection"]
assert "tests/test_software_engineer_dispatch.py" in config["pytest_add_cli_args_test_selection"]
assert "tests/test_spawn_telemetry.py" in config["pytest_add_cli_args_test_selection"]
'

  [ "$status" -eq 0 ]
}

@test "mutation config covers the T13A protected-write boundary" {
  run python3 -c '
import tomllib
from pathlib import Path

config = tomllib.loads(Path("pyproject.toml").read_text())["tool"]["mutmut"]
assert "scripts/lib/orchestrator_write_boundary.py" in config["only_mutate"]
assert "tests/test_orchestrator_write_boundary.py" in config["pytest_add_cli_args_test_selection"]
'

  [ "$status" -eq 0 ]
}

@test "mutation config covers the T14-T15 review loop" {
  run python3 -c '
import tomllib
from pathlib import Path

config = tomllib.loads(Path("pyproject.toml").read_text())["tool"]["mutmut"]
for path in ("scripts/lib/code_review_dispatch.py", "scripts/lib/review_evidence.py", "scripts/lib/review_workflow.py"):
    assert path in config["only_mutate"]
for path in ("tests/test_code_review_dispatch.py", "tests/test_review_evidence.py", "tests/test_review_workflow.py"):
    assert path in config["pytest_add_cli_args_test_selection"]
'

  [ "$status" -eq 0 ]
}

@test "mutation config covers the T20-T21 PR handoff" {
  run python3 -c '
import tomllib
from pathlib import Path

config = tomllib.loads(Path("pyproject.toml").read_text())["tool"]["mutmut"]
assert "scripts/lib/pr_handoff.py" in config["only_mutate"]
assert "scripts/lib/pr_handoff_state.py" in config["only_mutate"]
assert "scripts/lib/pr_handoff_validation.py" in config["only_mutate"]
assert "tests/test_pr_handoff.py" in config["pytest_add_cli_args_test_selection"]
'

  [ "$status" -eq 0 ]
}

@test "CI validates TOML and runs pytest through uv without mutmut" {
  run grep -F "astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b" "$REPO_ROOT/.github/workflows/harness-gate.yml"
  [ "$status" -eq 0 ]

  run grep -F 'version: "0.12.0"' "$REPO_ROOT/.github/workflows/harness-gate.yml"
  [ "$status" -eq 0 ]

  run grep -F "uv pip install -r requirements-dev.txt" "$REPO_ROOT/.github/workflows/harness-gate.yml"
  [ "$status" -eq 0 ]

  run grep -F "tomllib.load" "$REPO_ROOT/.github/workflows/harness-gate.yml"
  [ "$status" -eq 0 ]

  run grep -F ".venv/bin/python -m pytest tests" "$REPO_ROOT/.github/workflows/harness-gate.yml"
  [ "$status" -eq 0 ]

  run grep -F "bats tests/shell/" "$REPO_ROOT/.github/workflows/harness-gate.yml"
  [ "$status" -eq 0 ]

  run grep -F "mutmut run" "$REPO_ROOT/.github/workflows/harness-gate.yml"
  [ "$status" -ne 0 ]

  run grep -F "mutmut results" "$REPO_ROOT/.github/workflows/harness-gate.yml"
  [ "$status" -ne 0 ]

  run grep -F "scripts/check-mutation-score.py" "$REPO_ROOT/.github/workflows/harness-gate.yml"
  [ "$status" -ne 0 ]
}

@test "PR filtering protects mutation tooling and its Python test suite" {
paths=(pyproject.toml requirements-dev.txt "scripts/**" tests/test_code_review_dispatch.py tests/test_dispatch_contract.py tests/test_execution_policy.py tests/test_final_verification.py tests/test_orchestrator_write_boundary.py tests/test_pipeline_state.py tests/test_pr_handoff.py tests/test_review_evidence.py tests/test_review_workflow.py tests/test_software_engineer_dispatch.py tests/test_spawn_telemetry.py tests/test_task_discovery.py tests/test_task_selection.py tests/test_writer_claim.py)
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
