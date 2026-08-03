from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.lib.final_verification import (
    CommandExecutionRequest,
    CommandExecutionResult,
    FinalVerificationError,
    VerificationCommand,
    _command_path,
    _execute_command,
    _git_probe,
    _materialized_review_tree,
    _manifest_target,
    _not_run_results,
    _probe_target,
    _sandbox_mounts,
    _trusted_support_roots,
    _validate_argv,
    derive_verification_commands,
    run_final_verification,
    run_subprocess_command,
)


HEAD = "b" * 40


@pytest.fixture(autouse=True)
def healthy_git_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.lib.final_verification._probe_target",
        lambda _worktree, _deadline=None: (HEAD, True),
    )
    monkeypatch.setattr(
        "scripts.lib.final_verification.run_subprocess_command",
        lambda _request: CommandExecutionResult(0, "", ""),
    )
    monkeypatch.setattr(
        "scripts.lib.final_verification._materialized_review_tree",
        _passthrough_materialized_tree,
    )


@contextmanager
def _passthrough_materialized_tree(
    worktree: Path, _review_head: str, _deadline: float | None = None
):
    yield worktree


def install_runner(monkeypatch: pytest.MonkeyPatch, runner: object) -> None:
    monkeypatch.setattr("scripts.lib.final_verification.run_subprocess_command", runner)


def test_derives_unique_declared_commands() -> None:
    commands = derive_verification_commands(
        ["T19 is verified."], ["pytest -q", "bats tests/shell", "pytest -q"]
    )

    assert [command.argv for command in commands] == [
        ("pytest", "-q"),
        ("bats", "tests/shell"),
    ]


@pytest.mark.parametrize(
    "commands", [[], [""], ["''"], ["pytest ; rm -rf ."], ["pytest\n-q"]]
)
def test_rejects_unsafe_or_empty_commands(commands: list[str]) -> None:
    with pytest.raises(FinalVerificationError):
        derive_verification_commands(["T19 is verified."], commands)


def test_rejects_empty_acceptance_criteria() -> None:
    with pytest.raises(FinalVerificationError, match="acceptance criteria"):
        derive_verification_commands([], ["pytest -q"])


def test_rejects_malformed_quoted_command() -> None:
    with pytest.raises(FinalVerificationError, match="malformed"):
        derive_verification_commands(["T19 is verified."], ["pytest '"])


@pytest.mark.parametrize(
    "command",
    [
        "sh -c 'echo unsafe'",
        "python3 -c 'print(unsafe)'",
        "python3 -cpass",
        "node -e 'unsafe'",
        "node -p 1",
        "node --print=1",
        "node -pe 1",
        "node --eval=unsafe",
        "ruby -e0",
        "perl -E0",
        "perl -we0",
    ],
)
def test_rejects_shell_and_interpreter_evaluation(command: str) -> None:
    with pytest.raises(FinalVerificationError, match="shell|evaluation"):
        derive_verification_commands(["T19 is verified."], [command])


def test_execution_sink_revalidates_constructed_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[CommandExecutionRequest] = []

    def runner(request: CommandExecutionRequest) -> CommandExecutionResult:
        calls.append(request)
        return CommandExecutionResult(0, "unsafe", "")

    install_runner(monkeypatch, runner)
    result = run_final_verification(
        [VerificationCommand(("sh", "-c", "echo unsafe"))],
        worktree=tmp_path,
        review_head=HEAD,
    )

    assert result.verdict == "UNVERIFIED"
    assert calls == []


def test_refuses_stale_or_dirty_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = derive_verification_commands(["T19 is verified."], ["pytest -q"])
    calls: list[CommandExecutionRequest] = []

    def runner(request: CommandExecutionRequest) -> CommandExecutionResult:
        calls.append(request)
        return CommandExecutionResult(0, "", "")
    install_runner(monkeypatch, runner)

    monkeypatch.setattr(
        "scripts.lib.final_verification._probe_target",
        lambda _worktree, _deadline=None: ("c" * 40, True),
    )
    with pytest.raises(FinalVerificationError, match="current HEAD"):
        run_final_verification(
            commands,
            worktree=tmp_path,
            review_head=HEAD,
        )
    assert calls == []

    monkeypatch.setattr(
        "scripts.lib.final_verification._probe_target",
        lambda _worktree, _deadline=None: (HEAD, False),
    )
    with pytest.raises(FinalVerificationError, match="clean"):
        run_final_verification(
            commands,
            worktree=tmp_path,
            review_head=HEAD,
        )
    assert calls == []


def test_rejects_invalid_head_and_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = derive_verification_commands(["T19 is verified."], ["pytest -q"])

    with pytest.raises(FinalVerificationError, match="full Git HEAD"):
        run_final_verification(
            commands,
            worktree=tmp_path,
            review_head="not-a-head",
        )
    with pytest.raises(FinalVerificationError, match="existing directory"):
        run_final_verification(
            commands,
            worktree=tmp_path / "missing",
            review_head=HEAD,
        )
    monkeypatch.setattr(
        "scripts.lib.final_verification._probe_target",
        lambda _worktree, _deadline=None: ("not-a-head", True),
    )
    with pytest.raises(FinalVerificationError, match="current HEAD"):
        run_final_verification(
            commands,
            worktree=tmp_path,
            review_head=HEAD,
        )


def test_runs_commands_without_shell_and_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = derive_verification_commands(
        ["T19 is verified."], ["pytest -q", "true tests/shell"]
    )
    requests: list[CommandExecutionRequest] = []

    def runner(request: CommandExecutionRequest) -> CommandExecutionResult:
        requests.append(request)
        return CommandExecutionResult(0, "ok", "")
    install_runner(monkeypatch, runner)

    result = run_final_verification(
        commands,
        worktree=tmp_path,
        review_head=HEAD,
    )

    assert result.verdict == "VERIFIED"
    assert requests[0].argv[0].endswith("/pytest")
    assert requests[0].argv[1:] == ("-q",)
    assert Path(requests[1].argv[0]).name in {"true", "gnutrue"}
    assert requests[1].argv[1:] == ("tests/shell",)
    assert all(request.cwd == tmp_path for request in requests)
    assert all(request.network_disabled for request in requests)
    assert all(request.write_protected for request in requests)


def test_records_all_passed_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = derive_verification_commands(["T19 is verified."], ["pytest -q"])

    install_runner(monkeypatch, lambda _request: CommandExecutionResult(0, "passed", ""))
    result = run_final_verification(
        commands,
        worktree=tmp_path,
        review_head=HEAD,
    )

    assert result.verdict == "VERIFIED"
    assert result.command_results[0].exit_code == 0
    assert result.command_results[0].stdout == "passed"


def test_stops_and_fails_on_first_command_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = derive_verification_commands(
        ["T19 is verified."], ["pytest -q", "bats tests/shell"]
    )
    calls: list[tuple[str, ...]] = []

    def runner(request: CommandExecutionRequest) -> CommandExecutionResult:
        calls.append(request.argv)
        return CommandExecutionResult(1, "failed", "error")
    install_runner(monkeypatch, runner)

    result = run_final_verification(
        commands,
        worktree=tmp_path,
        review_head=HEAD,
    )

    assert result.verdict == "UNVERIFIED"
    assert len(result.command_results) == 2
    assert len(calls) == 1
    assert calls[0][0].endswith("/pytest")
    assert calls[0][1:] == ("-q",)
    assert result.command_results[1].exit_code is None
    assert "not executed" in result.command_results[1].stderr


def test_runner_error_is_recorded_as_unevaluable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = derive_verification_commands(["T19 is verified."], ["pytest -q"])

    def runner(_request: CommandExecutionRequest) -> CommandExecutionResult:
        raise RuntimeError("runner unavailable")
    install_runner(monkeypatch, runner)

    result = run_final_verification(
        commands,
        worktree=tmp_path,
        review_head=HEAD,
    )

    assert result.verdict == "UNVERIFIED"
    assert result.command_results[0].exit_code is None
    assert "runner unavailable" in result.command_results[0].stderr


def test_target_change_after_command_invalidates_verification(tmp_path: Path) -> None:
    commands = derive_verification_commands(["T19 is verified."], ["pytest -q"])
    states = iter(((HEAD, True), ("c" * 40, True)))

    with patch(
        "scripts.lib.final_verification._probe_target",
        side_effect=lambda _worktree, _deadline=None: next(states),
    ):
        with pytest.raises(FinalVerificationError, match="current HEAD"):
            run_final_verification(
                commands,
                worktree=tmp_path,
                review_head=HEAD,
            )


def test_rejects_empty_plan() -> None:
    with pytest.raises(FinalVerificationError, match="empty"):
        run_final_verification(
            [],
            worktree=Path("/tmp/worktree"),
            review_head=HEAD,
        )


def test_rejects_malformed_plan() -> None:
    with pytest.raises(FinalVerificationError, match="malformed"):
        run_final_verification(
            [object()],
            worktree=Path("/tmp/worktree"),
            review_head=HEAD,
        )


def test_rejects_command_count_and_argv_budget() -> None:
    too_many = [VerificationCommand(("pytest", str(index))) for index in range(33)]
    with pytest.raises(FinalVerificationError, match="too many"):
        run_final_verification(too_many, worktree=Path("/tmp/worktree"), review_head=HEAD)

    too_large = [VerificationCommand(("pytest", "x" * (64 * 1024)))]
    with pytest.raises(FinalVerificationError, match="too large"):
        run_final_verification(too_large, worktree=Path("/tmp/worktree"), review_head=HEAD)


@pytest.mark.parametrize(
    "execution",
    [CommandExecutionResult(True, "", ""), CommandExecutionResult(0, None, "")],
)
def test_malformed_runner_result_fails_closed(
    tmp_path: Path, execution: CommandExecutionResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = derive_verification_commands(["T19 is verified."], ["pytest -q"])
    install_runner(monkeypatch, lambda _request: execution)

    result = run_final_verification(
        commands,
        worktree=tmp_path,
        review_head=HEAD,
    )

    assert result.verdict == "UNVERIFIED"
    assert result.command_results[0].exit_code is None


def test_subprocess_runner_requires_read_only_offline_flags() -> None:
    request = CommandExecutionRequest(("pytest",), Path("/tmp"), False, True)

    with pytest.raises(FinalVerificationError, match="read-only"):
        run_subprocess_command(request)


def test_subprocess_runner_fails_closed_without_sandbox() -> None:
    request = CommandExecutionRequest(("/usr/bin/pytest",), Path("/tmp"), True, True)

    with patch("scripts.lib.final_verification._trusted_system_binary", return_value=None):
        result = run_subprocess_command(request)

    assert result.exit_code is None
    assert "sandbox" in result.stderr


def test_git_probe_uses_fixed_binary_and_sanitized_environment(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def run(arguments: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        calls.append({"arguments": arguments, **kwargs})
        return SimpleNamespace(returncode=0, stdout=HEAD + "\n")

    with patch("scripts.lib.final_verification.subprocess.run", side_effect=run):
        result = _git_probe(tmp_path, ("rev-parse", "--verify", "HEAD"))

    assert result == HEAD
    assert calls[0]["arguments"][0] in ("/usr/bin/git", "/bin/git")
    environment = calls[0]["env"]
    assert "GIT_DIR" not in environment
    assert environment["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert environment["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert environment["GIT_NO_LAZY_FETCH"] == "1"
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert environment["GIT_ASKPASS"] == "/bin/false"
    assert environment["SSH_ASKPASS"] == "/bin/false"
    arguments = calls[0]["arguments"]
    assert "core.fsmonitor=false" in arguments
    assert "core.hooksPath=/dev/null" in arguments
    assert "submodule.recurse=false" in arguments


def test_command_path_ignores_ambient_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/tmp/attacker")

    assert "/tmp/attacker" not in _command_path(None)


def test_default_tool_roots_include_python_runtime_bin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_bin = tmp_path / "venv" / "bin"
    runtime_bin.mkdir(parents=True)
    runtime = runtime_bin / "python"
    runtime.write_text("runtime")
    monkeypatch.setattr(sys, "executable", str(runtime))

    assert str(runtime_bin.resolve()) in _command_path(None).split(os.pathsep)


def test_command_path_accepts_only_explicit_tool_roots(tmp_path: Path) -> None:
    tool_root = tmp_path / "bin"
    tool_root.mkdir()

    assert _command_path(None, (tool_root,)) == str(tool_root)


def test_sandbox_mounts_policy_bound_launcher_support_roots(tmp_path: Path) -> None:
    version_root = tmp_path / "runtime"
    tool_root = version_root / "bin"
    tool_root.mkdir(parents=True)
    (version_root / "libexec").mkdir()
    request = CommandExecutionRequest(
        ("pytest",),
        tmp_path,
        True,
        True,
        trusted_tool_roots=(tool_root,),
        trusted_support_roots=(version_root / "libexec",),
    )

    mounts = _sandbox_mounts(request)

    assert version_root / "libexec" in mounts
    assert _command_path(tmp_path, (tool_root,)) == str(tool_root)


def test_support_root_symlink_escape_fails_closed(tmp_path: Path) -> None:
    version_root = tmp_path / "runtime"
    tool_root = version_root / "bin"
    tool_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    support = version_root / "share"
    support.symlink_to(outside, target_is_directory=True)

    with pytest.raises(FinalVerificationError, match="canonical"):
        _trusted_support_roots((support,), (tool_root,), tmp_path / "worktree")


def test_sandbox_runs_canonical_argv_with_matching_path(tmp_path: Path) -> None:
    fake_bwrap = tmp_path / "bwrap"
    fake_bwrap.write_text("sandbox")
    fake_bwrap.chmod(0o755)
    request = CommandExecutionRequest(("pytest", "-q"), tmp_path, True, True)

    with (
        patch.dict(
            "scripts.lib.final_verification._SYSTEM_BINARIES",
            {"bwrap": (fake_bwrap,)},
            clear=False,
        ),
        patch("scripts.lib.final_verification.subprocess.Popen") as popen,
        patch(
            "scripts.lib.final_verification._collect_process",
            return_value=CommandExecutionResult(0, "", ""),
        ),
    ):
        result = run_subprocess_command(request)

    command = popen.call_args.args[0]
    environment = popen.call_args.kwargs["env"]
    assert result.exit_code == 0
    assert command[0] == str(fake_bwrap.resolve())
    assert "--unshare-net" in command
    assert "--unshare-pid" in command
    assert "--unshare-ipc" in command
    assert "--unshare-uts" in command
    assert "--unshare-user" in command
    assert "--disable-userns" in command
    assert "--assert-userns-disabled" in command
    assert command[command.index("--size") + 1] == str(64 * 1024 * 1024)
    assert command[-3] == "--"
    assert command[-2].endswith("/pytest")
    assert command[-1] == "-q"
    assert environment["PATH"] == _command_path(tmp_path)


def test_relative_shebang_resolves_inside_worktree(tmp_path: Path) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "aliasbash").symlink_to("/bin/bash")
    script = tools_dir / "check"
    script.write_text("#!tools/aliasbash\n")
    script.chmod(0o755)

    with pytest.raises(FinalVerificationError, match="shell shebang"):
        _validate_argv(("./tools/check",), tmp_path)


def test_absolute_executable_must_be_in_target_or_trusted_root(tmp_path: Path) -> None:
    with pytest.raises(FinalVerificationError, match="trusted roots"):
        _validate_argv(("/tmp/attacker",), tmp_path)


def test_versioned_interpreter_eval_is_rejected(tmp_path: Path) -> None:
    cases = [
        ("/usr/bin/python3.14-x86_64-linux-gnu", "-c"),
        ("/usr/bin/python3.13t", "-c"),
        ("/usr/bin/python3.13t.exe", "-c"),
        ("/usr/bin/python.exe", "-c"),
        ("/usr/bin/node20", "-p"),
        ("/usr/bin/node.exe", "-p"),
        ("/usr/bin/ruby3.4", "-e"),
        ("/usr/bin/ruby.exe", "-e"),
        ("/usr/bin/perl5.40.1", "-E"),
        ("/usr/bin/perl.exe", "-e"),
    ]
    for executable, flag in cases:
        with pytest.raises(FinalVerificationError, match="evaluation"):
            _validate_argv((executable, flag, "pass"), tmp_path)


def test_versioned_interpreter_symlink_alias_is_rejected(tmp_path: Path) -> None:
    alias = tmp_path / "perl-alias"
    alias.symlink_to("/usr/bin/perl5.40.1")

    with pytest.raises(FinalVerificationError, match="evaluation"):
        _validate_argv((str(alias), "-e", "pass"))

    python_alias = tmp_path / "python-free-threaded"
    python_alias.symlink_to("/usr/bin/python3.13t")
    with pytest.raises(FinalVerificationError, match="evaluation"):
        _validate_argv((str(python_alias), "-c", "pass"))


def test_git_control_paths_are_not_materialized() -> None:
    with pytest.raises(FinalVerificationError, match="unsafe path"):
        _manifest_target(Path("/"), "nested/.git/config")


def test_bounds_command_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = derive_verification_commands(["T19 is verified."], ["pytest -q"])
    install_runner(
        monkeypatch,
        lambda _request: CommandExecutionResult(0, "x" * 100_000, ""),
    )

    result = run_final_verification(
        commands,
        worktree=tmp_path,
        review_head=HEAD,
    )

    assert len(result.command_results[0].stdout.encode()) <= 64 * 1024


def test_exception_output_obeys_remaining_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_runner(monkeypatch, lambda _request: (_ for _ in ()).throw(RuntimeError("x" * 100)))

    result = _execute_command(
        VerificationCommand(("pytest",)),
        tmp_path,
        deadline=10**12,
        output_budget=1,
    )

    assert len(result.stderr.encode()) <= 1


def test_placeholder_and_multibyte_output_respect_invocation_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("scripts.lib.final_verification._MAX_TOTAL_OUTPUT_BYTES", 1)
    install_runner(monkeypatch, lambda _request: CommandExecutionResult(1, "🙂", ""))
    commands = [VerificationCommand(("pytest",)), VerificationCommand(("true",))]

    result = run_final_verification(commands, worktree=tmp_path, review_head=HEAD)

    total = sum(
        len(item.stdout.encode("utf-8")) + len(item.stderr.encode("utf-8"))
        for item in result.command_results
    )
    assert total <= 1
    assert all(item.stderr.encode("utf-8").decode("utf-8") == item.stderr for item in result.command_results)


def test_not_run_results_share_the_remaining_budget() -> None:
    commands = [VerificationCommand(("pytest",)), VerificationCommand(("true",))]

    results = _not_run_results(commands, "érror", 1)

    assert sum(len(item.stderr.encode("utf-8")) for item in results) <= 1


def test_materializes_only_review_head_without_git_metadata_or_ignored_files(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git = "/usr/bin/git"

    def git_run(*arguments: str) -> None:
        subprocess.run(
            (git, "-C", str(repo), *arguments),
            check=True,
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
            },
        )

    git_run("init", "-q")
    (repo / ".gitignore").write_text("ignored.txt\n")
    (repo / "tracked.txt").write_text("reviewed\n")
    git_run("add", ".gitignore", "tracked.txt")
    git_run("-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-qm", "target")
    (repo / "ignored.txt").write_text("unreviewed\n")
    head = subprocess.run(
        (git, "-C", str(repo), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    with _materialized_review_tree(repo, head) as target:
        assert (target / "tracked.txt").read_text() == "reviewed\n"
        assert not (target / "ignored.txt").exists()
        assert (target / ".git").is_dir()
        assert subprocess.run(
            (git, "-C", str(target), "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip() == head


def test_probe_rejects_assume_unchanged_index_flags(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git = "/usr/bin/git"
    environment = {
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    for arguments in (("init", "-q"),):
        subprocess.run((git, "-C", str(repo), *arguments), check=True, env=environment)
    (repo / "tracked.txt").write_text("reviewed\n")
    subprocess.run((git, "-C", str(repo), "add", "tracked.txt"), check=True, env=environment)
    subprocess.run(
        (git, "-C", str(repo), "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-qm", "target"),
        check=True,
        env=environment,
    )
    head = subprocess.run(
        (git, "-C", str(repo), "rev-parse", "HEAD"), check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run((git, "-C", str(repo), "update-index", "--assume-unchanged", "tracked.txt"), check=True)

    assert _probe_target(repo) == (head, False)
