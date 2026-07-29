set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

default:
    @just --list

setup:
    uv venv --python 3.14 --allow-existing
    uv pip install -r requirements-dev.txt

toml-check:
    .venv/bin/python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb'))"

python-test:
    .venv/bin/python -m pytest tests

hooks-json:
    jq -e . .codex/hooks/hooks.json > /dev/null

shell-lint:
    shellcheck --severity=error .codex/hooks/*.sh .codex/hooks/_lib/*.sh scripts/*.sh

shell-test:
    bats tests/shell/

ci: setup toml-check python-test hooks-json shell-lint shell-test
