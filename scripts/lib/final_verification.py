"""Derive and execute a bounded, HEAD-bound verification command plan."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import selectors
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import resource
import re
from typing import Iterator, Sequence


class FinalVerificationError(ValueError):
    """Raised when a final verification precondition cannot be trusted."""


MAX_OUTPUT_BYTES = 64 * 1024
_HEAD_LENGTH = 40
_CONTROL_OPERATORS = frozenset(";&|<>$`(){}")
_SHELL_EXECUTABLES = frozenset(
    {"sh", "bash", "dash", "zsh", "fish", "csh", "ksh", "pwsh", "powershell", "cmd"}
)
_EVAL_EXECUTABLES = frozenset({"python", "python3", "node", "ruby", "perl"})
_EVAL_FLAGS = frozenset({"-c", "--command", "--eval", "-e"})
_EVAL_SHORT_FLAGS = {
    "python": frozenset({"c"}),
    "python3": frozenset({"c"}),
    "node": frozenset({"e", "p"}),
    "ruby": frozenset({"e"}),
    "perl": frozenset({"e", "E", "p", "n"}),
}
_EVAL_LONG_FLAGS = {
    "node": frozenset({"--eval", "--print"}),
    "ruby": frozenset({"--eval"}),
    "perl": frozenset(),
}
_WRAPPER_EXECUTABLES = frozenset(
    {"busybox", "command", "env", "exec", "find", "nice", "nohup", "setsid", "sudo", "stdbuf", "timeout", "xargs"}
)
_TRUSTED_SHELL_RUNNERS = frozenset({"bats"})
_COMMAND_TIMEOUT_SECONDS = 300
_INVOCATION_TIMEOUT_SECONDS = 900
_MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
_FILE_SIZE_LIMIT_BYTES = 64 * 1024 * 1024
_PROCESS_LIMIT = 64
_MAX_COMMANDS = 32
_MAX_ARGV_BYTES = 64 * 1024
_MAX_TOTAL_OUTPUT_BYTES = 1024 * 1024
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_MAX_MANIFEST_ENTRIES = 100_000
_MAX_MATERIALIZED_BYTES = 64 * 1024 * 1024
_TMPFS_BYTES = 64 * 1024 * 1024
_TRUSTED_COMMAND_ROOTS = (Path("/usr/local/bin"), Path("/usr/bin"), Path("/bin"))
_SYSTEM_MOUNTS = (Path("/usr"), Path("/bin"), Path("/sbin"), Path("/lib"), Path("/lib64"))
_SYSTEM_FILES = (
    Path("/etc/ld.so.cache"),
    Path("/etc/nsswitch.conf"),
    Path("/etc/passwd"),
    Path("/etc/group"),
    Path("/etc/localtime"),
)
_SYSTEM_BINARIES = {
    "bwrap": (Path("/usr/bin/bwrap"), Path("/bin/bwrap")),
    "git": (Path("/usr/bin/git"), Path("/bin/git")),
}
_BROAD_TOOL_ROOTS = frozenset(
    {Path("/"), Path("/home"), Path("/root"), Path("/tmp"), Path("/var"), Path("/mnt"), Path("/media"), Path("/etc"), Path("/usr"), Path("/usr/local")}
)


@dataclass(frozen=True)
class VerificationCommand:
    argv: tuple[str, ...]


@dataclass(frozen=True)
class CommandExecutionRequest:
    argv: tuple[str, ...]
    cwd: Path
    network_disabled: bool
    write_protected: bool
    deadline: float | None = None
    output_limit_bytes: int = MAX_OUTPUT_BYTES
    trusted_tool_roots: tuple[Path, ...] | None = None
    trusted_support_roots: tuple[Path, ...] = ()


@dataclass(frozen=True)
class CommandExecutionResult:
    exit_code: int | None
    stdout: str
    stderr: str


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str


@dataclass(frozen=True)
class FinalVerificationResult:
    verdict: str
    git_head: str
    command_results: tuple[CommandResult, ...]


def derive_verification_commands(
    acceptance_criteria: Sequence[str], required_tests: Sequence[str]
) -> tuple[VerificationCommand, ...]:
    _require_texts(acceptance_criteria, "acceptance criteria")
    _require_texts(required_tests, "required tests")
    commands: list[VerificationCommand] = []
    seen: set[tuple[str, ...]] = set()
    for value in required_tests:
        command = VerificationCommand(_parse_command(value))
        if command.argv not in seen:
            commands.append(command)
            seen.add(command.argv)
    return _validate_plan(commands)


def run_final_verification(
    commands: Sequence[VerificationCommand],
    *,
    worktree: Path,
    review_head: str,
    trusted_tool_roots: Sequence[Path] | None = None,
    trusted_support_roots: Sequence[Path] | None = None,
) -> FinalVerificationResult:
    plan = _validate_plan(commands)
    _require_head(review_head, "review HEAD")
    try:
        worktree = worktree.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise FinalVerificationError("verification worktree must be an existing directory") from error
    if not worktree.is_absolute() or not worktree.is_dir():
        raise FinalVerificationError("verification worktree must be an existing directory")
    tool_roots = _trusted_tool_roots(trusted_tool_roots, worktree)
    support_roots = _trusted_support_roots(trusted_support_roots, tool_roots, worktree)
    deadline = time.monotonic() + _INVOCATION_TIMEOUT_SECONDS
    _require_target(review_head, _probe_target(worktree, deadline))
    results: list[CommandResult] = []
    output_budget = _MAX_TOTAL_OUTPUT_BYTES
    with _materialized_review_tree(worktree, review_head, deadline) as target:
        for command in plan:
            if time.monotonic() >= deadline:
                results.extend(
                    _not_run_results(
                        plan[len(results):], "invocation deadline exceeded", output_budget
                    )
                )
                return FinalVerificationResult("UNVERIFIED", review_head, tuple(results))
            if output_budget <= 0:
                results.extend(
                    _not_run_results(
                        plan[len(results):], "invocation output budget exhausted", output_budget
                    )
                )
                return FinalVerificationResult("UNVERIFIED", review_head, tuple(results))
            result = _execute_command(
                command, target, deadline, output_budget, tool_roots, support_roots
            )
            results.append(result)
            output_budget -= _result_output_bytes(result)
            if result.exit_code != 0:
                results.extend(
                    _not_run_results(
                        plan[len(results):],
                        "not executed after a prior command failed",
                        output_budget,
                    )
                )
                return FinalVerificationResult("UNVERIFIED", review_head, tuple(results))
            _require_target(review_head, _probe_target(worktree, deadline))
        if time.monotonic() >= deadline:
            return FinalVerificationResult("UNVERIFIED", review_head, tuple(results))
    return FinalVerificationResult("VERIFIED", review_head, tuple(results))


def run_subprocess_command(request: CommandExecutionRequest) -> CommandExecutionResult:
    _require_execution_flags(request)
    tool_roots = _trusted_tool_roots(request.trusted_tool_roots)
    support_roots = _trusted_support_roots(
        request.trusted_support_roots, tool_roots, request.cwd
    )
    argv = _validate_argv(request.argv, request.cwd, tool_roots)
    request = CommandExecutionRequest(
        argv,
        request.cwd,
        request.network_disabled,
        request.write_protected,
        request.deadline,
        request.output_limit_bytes,
        tool_roots,
        support_roots,
    )
    environment = _safe_environment(request.cwd, request.trusted_tool_roots)
    sandbox = _trusted_system_binary("bwrap")
    if sandbox is None:
        return CommandExecutionResult(None, "", "read-only sandbox is unavailable")
    try:
        process = subprocess.Popen(
            _sandbox_command(sandbox, request, environment),
            cwd=request.cwd,
            env=environment,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            preexec_fn=_set_resource_limits,
        )
        return _collect_process(process, request.deadline, request.output_limit_bytes)
    except OSError as error:
        return CommandExecutionResult(None, "", str(error))


def _collect_process(
    process: subprocess.Popen[bytes], deadline: float | None, output_limit_bytes: int
) -> CommandExecutionResult:
    streams = {stream: bytearray() for stream in (process.stdout, process.stderr) if stream}
    selector = selectors.DefaultSelector()
    for stream in streams:
        selector.register(stream, selectors.EVENT_READ)
    timed_out = False
    command_deadline = min(
        time.monotonic() + _COMMAND_TIMEOUT_SECONDS,
        deadline if deadline is not None else float("inf"),
    )
    try:
        while selector.get_map():
            remaining = command_deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _kill_process(process)
                break
            for key, _ in selector.select(remaining):
                chunk = os.read(key.fileobj.fileno(), 4096)
                if chunk:
                    _append_bounded(streams, key.fileobj, chunk, output_limit_bytes)
                else:
                    selector.unregister(key.fileobj)
    finally:
        selector.close()
    _wait_for_process(process)
    for stream in streams:
        stream.close()
    stdout = streams.get(process.stdout, bytearray()).decode("utf-8", errors="replace")
    stderr = streams.get(process.stderr, bytearray()).decode("utf-8", errors="replace")
    if timed_out:
        stderr = f"{stderr}\ncommand timed out".strip()
    return CommandExecutionResult(None if timed_out else process.returncode, stdout, stderr)


def _append_bounded(
    streams: dict[object, bytearray], stream: object, chunk: bytes, output_limit_bytes: int
) -> None:
    remaining = output_limit_bytes - sum(len(buffer) for buffer in streams.values())
    if remaining > 0:
        streams[stream].extend(chunk[:remaining])


def _kill_process(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def _wait_for_process(process: subprocess.Popen[bytes]) -> None:
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _set_resource_limits() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (_MEMORY_LIMIT_BYTES, _MEMORY_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (_COMMAND_TIMEOUT_SECONDS, _COMMAND_TIMEOUT_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (_FILE_SIZE_LIMIT_BYTES, _FILE_SIZE_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_NPROC, (_PROCESS_LIMIT, _PROCESS_LIMIT))


def _sandbox_command(
    sandbox: str, request: CommandExecutionRequest, environment: dict[str, str]
) -> list[str]:
    command = [
        sandbox,
        "--die-with-parent",
        "--unshare-net",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-user",
        "--disable-userns",
        "--assert-userns-disabled",
        "--clearenv",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--size",
        str(_TMPFS_BYTES),
        "--tmpfs",
        "/tmp",
        "--dir",
        "/tmp/home",
    ]
    for parent in _sandbox_parents(request):
        command.extend(("--dir", str(parent)))
    for path in _sandbox_mounts(request):
        command.extend(("--ro-bind", str(path), str(path)))
    command.extend(("--chdir", str(request.cwd), "--setenv", "HOME", "/tmp/home", "--setenv", "PATH", environment["PATH"]))
    command.extend(("--setenv", "TMPDIR", "/tmp", "--setenv", "PYTHONDONTWRITEBYTECODE", "1"))
    command.extend(("--setenv", "PYTEST_ADDOPTS", "-p no:cacheprovider", "--"))
    return command + list(request.argv)


def _sandbox_mounts(request: CommandExecutionRequest) -> tuple[Path, ...]:
    mounts = [*_SYSTEM_MOUNTS, *_SYSTEM_FILES, request.cwd, *request.trusted_support_roots]
    for entry in _command_path(request.cwd, request.trusted_tool_roots).split(os.pathsep):
        path = Path(entry)
        if path.is_dir() and path not in mounts:
            mounts.append(path)
    return tuple(path for path in mounts if path.exists())


def _sandbox_parents(request: CommandExecutionRequest) -> tuple[Path, ...]:
    parents: set[Path] = set()
    for path in _sandbox_mounts(request):
        current = path.parent
        while current != Path("/"):
            parents.add(current)
            current = current.parent
    return tuple(sorted(parents, key=lambda path: len(path.parts)))


def _require_texts(values: Sequence[str], name: str) -> None:
    if not isinstance(values, (list, tuple)) or not values:
        raise FinalVerificationError(f"{name} must be a non-empty list")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise FinalVerificationError(f"{name} must contain non-empty text")


def _parse_command(value: str) -> tuple[str, ...]:
    if any(char in _CONTROL_OPERATORS or ord(char) < 32 for char in value):
        raise FinalVerificationError("verification command contains shell control syntax")
    try:
        argv = tuple(shlex.split(value, comments=False, posix=True))
    except ValueError as error:
        raise FinalVerificationError("verification command is malformed") from error
    if not argv or any(not token for token in argv):
        raise FinalVerificationError("verification command is empty")
    _validate_argv(argv)
    return argv


def _validate_argv(
    argv: tuple[str, ...],
    worktree: Path | None = None,
    trusted_tool_roots: Sequence[Path] | None = None,
) -> tuple[str, ...]:
    if type(argv) is not tuple or not argv or any(not isinstance(token, str) or not token for token in argv):
        raise FinalVerificationError("verification command argv is malformed")
    if any(any(char in _CONTROL_OPERATORS or ord(char) < 32 for char in token) for token in argv):
        raise FinalVerificationError("verification command contains shell control syntax")
    resolved = _reject_interpreters(argv, worktree, trusted_tool_roots)
    if worktree is not None:
        if resolved is None:
            raise FinalVerificationError("verification executable cannot be resolved")
        return (str(resolved), *argv[1:])
    return argv


def _reject_interpreters(
    argv: tuple[str, ...],
    worktree: Path | None = None,
    trusted_tool_roots: Sequence[Path] | None = None,
) -> Path | None:
    executable = Path(argv[0]).name.lower()
    if executable in _SHELL_EXECUTABLES or executable in _WRAPPER_EXECUTABLES:
        raise FinalVerificationError("verification command cannot launch a shell")
    roots = _trusted_tool_roots(trusted_tool_roots)
    resolved = _resolve_executable(argv[0], worktree, roots)
    family = _interpreter_family(executable) or _interpreter_family(
        Path(resolved).name if resolved is not None else ""
    )
    if family and any(_is_eval_flag(family, token) for token in argv[1:]):
        raise FinalVerificationError("verification command cannot use interpreter evaluation")
    if worktree is not None and "/" in argv[0] and not Path(argv[0]).is_absolute():
        _require_inside_worktree(resolved, worktree)
    if worktree is not None:
        _require_allowed_executable(resolved, worktree, roots)
    if resolved is not None and Path(resolved).name.lower() in _SHELL_EXECUTABLES | _WRAPPER_EXECUTABLES:
        raise FinalVerificationError("verification executable resolves to a shell or wrapper")
    if executable not in _TRUSTED_SHELL_RUNNERS and resolved is not None:
        _reject_shell_shebang(resolved, worktree, roots)
    return resolved


def _interpreter_family(name: str) -> str | None:
    patterns = {
        "python3": r"^python3(?:[0-9.]|t|[-_][A-Za-z0-9._-]*)*(?:[.]exe)?$",
        "python": r"^python(?:[0-9.]|[-_].*)*$",
        "node": r"^(?:node|nodejs)(?:[v0-9.]|[-_].*)*$",
        "ruby": r"^ruby(?:[v0-9.]|[-_].*)*$",
        "perl": r"^perl(?:[v0-9.]|[-_].*)*$",
    }
    normalized = name.lower()
    if normalized.endswith(".exe"):
        normalized = normalized[:-4]
    return next(
        (family for family, pattern in patterns.items() if re.match(pattern, normalized)),
        None,
    )


def _is_eval_flag(executable: str, token: str) -> bool:
    if token in _EVAL_FLAGS or any(token.startswith(f"{flag}=") for flag in _EVAL_FLAGS):
        return True
    if token.startswith("--"):
        return token.split("=", 1)[0] in _EVAL_LONG_FLAGS.get(executable, frozenset())
    return token.startswith("-") and any(
        flag in token[1:] for flag in _EVAL_SHORT_FLAGS.get(executable, frozenset())
    )


def _resolve_executable(
    executable: str,
    worktree: Path | None,
    trusted_tool_roots: Sequence[Path] | None = None,
) -> Path | None:
    path = Path(executable)
    if path.is_absolute():
        return path.resolve()
    if "/" in executable:
        return (worktree / path).resolve() if worktree is not None else None
    found = shutil.which(executable, path=_command_path(worktree, trusted_tool_roots))
    return Path(found).resolve() if found else None


def _command_path(
    worktree: Path | None, trusted_tool_roots: Sequence[Path] | None = None
) -> str:
    del worktree
    roots = _trusted_tool_roots(trusted_tool_roots)
    return os.pathsep.join(str(path) for path in roots if path.is_dir())


def _trusted_tool_roots(
    values: Sequence[Path] | None, forbidden_worktree: Path | None = None
) -> tuple[Path, ...]:
    roots = _default_trusted_tool_roots() if values is None else tuple(values)
    normalized: list[Path] = []
    for root in roots:
        path = Path(root).resolve()
        if not path.is_absolute() or not path.is_dir():
            raise FinalVerificationError("trusted tool root must be an existing directory")
        if path in _BROAD_TOOL_ROOTS or path.name != "bin":
            raise FinalVerificationError("trusted tool root is too broad")
        if forbidden_worktree is not None and (
            _is_inside(forbidden_worktree, path) or _is_inside(path, forbidden_worktree)
        ):
            raise FinalVerificationError("trusted tool root overlaps the verification worktree")
        if path not in normalized:
            normalized.append(path)
    if not normalized:
        raise FinalVerificationError("trusted tool roots must be non-empty")
    return tuple(normalized)


def _default_trusted_tool_roots() -> tuple[Path, ...]:
    runtime_bin = Path(sys.executable).resolve().parent
    if runtime_bin.name != "bin" or not runtime_bin.is_dir():
        return _TRUSTED_COMMAND_ROOTS
    remaining_roots = tuple(
        root for root in _TRUSTED_COMMAND_ROOTS if root != runtime_bin
    )
    return (runtime_bin, *remaining_roots)


def _trusted_support_roots(
    values: Sequence[Path] | None,
    tool_roots: Sequence[Path],
    forbidden_worktree: Path,
) -> tuple[Path, ...]:
    if values is None:
        return ()
    allowed = {root.parent / name for root in tool_roots for name in ("lib", "libexec", "share")}
    normalized: list[Path] = []
    for root in values:
        raw = Path(root)
        path = raw.resolve(strict=True)
        if not raw.is_absolute() or path != raw or not path.is_dir():
            raise FinalVerificationError("trusted support root must be a canonical directory")
        if path not in allowed or _is_inside(path, forbidden_worktree) or _is_inside(forbidden_worktree, path):
            raise FinalVerificationError("trusted support root is outside the tool policy")
        if path not in normalized:
            normalized.append(path)
    return tuple(normalized)


def _require_inside_worktree(resolved: Path | None, worktree: Path) -> None:
    if resolved is None:
        raise FinalVerificationError("verification executable cannot be resolved")
    try:
        resolved.relative_to(worktree.resolve())
    except ValueError as error:
        raise FinalVerificationError("verification executable escapes worktree") from error


def _require_allowed_executable(
    resolved: Path | None, worktree: Path, trusted_tool_roots: Sequence[Path]
) -> None:
    if resolved is None:
        raise FinalVerificationError("verification executable cannot be resolved")
    if _is_inside(resolved, worktree):
        return
    if any(_is_inside(resolved, root) for root in trusted_tool_roots):
        return
    raise FinalVerificationError("verification executable is outside the trusted roots")


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _reject_shell_shebang(
    resolved: Path,
    worktree: Path | None,
    trusted_tool_roots: Sequence[Path] | None = None,
) -> None:
    if not resolved.is_file():
        return
    try:
        first_line = resolved.read_bytes()[:256].decode("utf-8", errors="replace").splitlines()[0]
    except (OSError, IndexError) as error:
        raise FinalVerificationError("verification executable cannot be inspected") from error
    if not first_line.startswith("#!"):
        return
    parts = shlex.split(first_line[2:], comments=False, posix=True)
    if any(
        _shebang_part_is_forbidden(part, worktree, trusted_tool_roots) for part in parts
    ):
        raise FinalVerificationError("verification executable uses a shell shebang")


def _shebang_part_is_forbidden(
    part: str,
    worktree: Path | None,
    trusted_tool_roots: Sequence[Path] | None = None,
) -> bool:
    name = Path(part).name.lower()
    if name in _SHELL_EXECUTABLES | _WRAPPER_EXECUTABLES:
        return True
    candidate = Path(part)
    if not candidate.is_absolute() and "/" in part and worktree is not None:
        candidate = (worktree / candidate).resolve()
    elif not candidate.is_absolute():
        found = shutil.which(part, path=_command_path(worktree, trusted_tool_roots))
        if found:
            candidate = Path(found)
    try:
        return candidate.resolve().name.lower() in _SHELL_EXECUTABLES | _WRAPPER_EXECUTABLES
    except OSError:
        return True


def _validate_plan(commands: Sequence[VerificationCommand]) -> tuple[VerificationCommand, ...]:
    if not isinstance(commands, (list, tuple)) or not commands:
        raise FinalVerificationError("verification command plan is empty")
    plan = tuple(commands)
    if any(not isinstance(command, VerificationCommand) for command in plan):
        raise FinalVerificationError("verification command plan is malformed")
    if len(plan) > _MAX_COMMANDS:
        raise FinalVerificationError("verification command plan has too many commands")
    if sum(_argv_bytes(command.argv) for command in plan) > _MAX_ARGV_BYTES:
        raise FinalVerificationError("verification command plan is too large")
    return plan


def _argv_bytes(argv: tuple[str, ...]) -> int:
    return sum(len(token.encode("utf-8")) + 1 for token in argv)


def _require_head(value: str, name: str) -> None:
    if not isinstance(value, str) or len(value) != _HEAD_LENGTH:
        raise FinalVerificationError(f"{name} must be a full Git HEAD")
    if any(char not in "0123456789abcdef" for char in value):
        raise FinalVerificationError(f"{name} must be a full Git HEAD")


def _require_target(review_head: str, target: tuple[str, bool]) -> None:
    current_head, clean = target
    _require_head(current_head, "current HEAD")
    if current_head != review_head:
        raise FinalVerificationError("current HEAD does not match review HEAD")
    if type(clean) is not bool or not clean:
        raise FinalVerificationError("verification worktree must be clean")


def _probe_target(worktree: Path, deadline: float | None = None) -> tuple[str, bool]:
    head = _git_probe(worktree, ("rev-parse", "--verify", "HEAD"), deadline)
    status = _git_probe(
        worktree,
        ("status", "--porcelain", "--untracked-files=all", "--ignore-submodules=all"),
        deadline,
    )
    index_flags = _git_probe(worktree, ("ls-files", "-v", "--full-name"), deadline)
    normal_index = all(line.startswith("H ") for line in index_flags.splitlines())
    return head, not status and normal_index


@contextmanager
def _materialized_review_tree(
    worktree: Path, review_head: str, deadline: float | None = None
) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="t19-final-verification-") as directory:
        root = Path(directory) / "tree"
        root.mkdir()
        manifest = _read_manifest(worktree, review_head, deadline)
        _materialize_manifest(worktree, manifest, root, deadline)
        _materialize_git_context(worktree, review_head, manifest, root, deadline)
        yield root


def _read_manifest(
    worktree: Path, review_head: str, deadline: float | None
) -> tuple[tuple[Path, str, str], ...]:
    output = _run_git_output(worktree, ("ls-tree", "-r", "-z", "--full-tree", review_head), deadline)
    records: list[tuple[Path, str, str]] = []
    seen: set[Path] = set()
    for record in output.split(b"\0"):
        if not record:
            continue
        header, separator, raw_path = record.partition(b"\t")
        fields = header.decode("ascii", errors="strict").split()
        if separator != b"\t" or len(fields) != 3 or fields[1] != "blob":
            raise FinalVerificationError("review HEAD contains unsupported tree entry")
        mode, object_type, object_id = fields
        if object_type != "blob" or mode not in {"100644", "100755"} or len(object_id) != _HEAD_LENGTH:
            raise FinalVerificationError("review HEAD contains unsupported blob entry")
        path = _manifest_target(Path("/"), raw_path.decode("utf-8", errors="strict"))
        if path in seen:
            raise FinalVerificationError("review HEAD manifest contains duplicate paths")
        seen.add(path)
        records.append((path, mode, object_id))
        if len(records) > _MAX_MANIFEST_ENTRIES:
            raise FinalVerificationError("review HEAD manifest has too many entries")
    return tuple(records)


def _manifest_target(root: Path, name: str) -> Path:
    parts = name.split("/")
    if (
        not name
        or name.startswith("/")
        or any(part in ("", ".", "..") for part in parts)
        or ".git" in parts
        or any(ord(char) < 32 for char in name)
    ):
        raise FinalVerificationError("review HEAD contains an unsafe path")
    target = (root / Path(*parts)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as error:
        raise FinalVerificationError("review HEAD contains an unsafe path") from error
    return target


def _materialize_manifest(
    worktree: Path,
    manifest: Sequence[tuple[Path, str, str]],
    root: Path,
    deadline: float | None,
) -> None:
    total = 0
    for relative_path, mode, object_id in manifest:
        if deadline is not None and time.monotonic() >= deadline:
            raise FinalVerificationError("verification invocation deadline exceeded")
        target = root / relative_path.relative_to(Path("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        size = _blob_size(worktree, object_id, deadline)
        total += size
        if size > _FILE_SIZE_LIMIT_BYTES or total > _MAX_MATERIALIZED_BYTES:
            raise FinalVerificationError("review HEAD materialization is too large")
        _write_blob(worktree, object_id, target, deadline)
        target.chmod(int(mode, 8) & 0o7777)


def _materialize_git_context(
    worktree: Path,
    review_head: str,
    manifest: Sequence[tuple[Path, str, str]],
    root: Path,
    deadline: float | None,
) -> None:
    _run_git_output(root, ("init", "-q", "--initial-branch=main"), deadline)
    _run_git_output(root, ("config", "core.hooksPath", "/dev/null"), deadline)
    for path, _, object_id in manifest:
        relative = path.relative_to(Path("/")).as_posix()
        stored = _run_git_output(
            root, ("hash-object", "--no-filters", "-w", "--", relative), deadline
        )
        if stored.strip() != object_id.encode("ascii"):
            raise FinalVerificationError("materialized blob differs from the reviewed object")
    index = b"".join(
        f"{mode} {object_id}\t{path.relative_to(Path('/')).as_posix()}\n".encode("utf-8")
        for path, mode, object_id in manifest
    )
    _run_git_output(root, ("update-index", "--index-info"), deadline, index)
    tree = _run_git_output(root, ("write-tree",), deadline).strip()
    commit = _run_git_output(worktree, ("cat-file", "commit", review_head), deadline)
    stored = _run_git_output(root, ("hash-object", "-t", "commit", "-w", "--stdin"), deadline, commit)
    if stored.strip() != review_head.encode("ascii"):
        raise FinalVerificationError("sanitized Git context changed the reviewed commit")
    if not tree or b"tree " + tree not in commit.splitlines():
        raise FinalVerificationError("sanitized Git context changed the reviewed tree")
    _run_git_output(root, ("update-ref", "refs/heads/main", review_head), deadline)


def _blob_size(worktree: Path, object_id: str, deadline: float | None) -> int:
    output = _run_git_output(worktree, ("cat-file", "-s", object_id), deadline)
    try:
        return int(output.decode("ascii").strip())
    except (ValueError, UnicodeDecodeError) as error:
        raise FinalVerificationError("review HEAD blob size is invalid") from error


def _write_blob(worktree: Path, object_id: str, target: Path, deadline: float | None) -> None:
    git = _trusted_system_binary("git")
    if git is None:
        raise FinalVerificationError("trusted Git binary is unavailable")
    remaining = _remaining_seconds(deadline, 60)
    try:
        with target.open("xb") as output:
            result = subprocess.run(
                _git_command(worktree, ("cat-file", "blob", object_id)),
                shell=False,
                check=False,
                stdout=output,
                stderr=subprocess.DEVNULL,
                timeout=remaining,
                env=_git_environment(),
            )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise FinalVerificationError("review HEAD blob materialization failed") from error
    if result.returncode != 0:
        raise FinalVerificationError("review HEAD blob materialization failed")


def _run_git_output(
    worktree: Path,
    arguments: tuple[str, ...],
    deadline: float | None,
    input_data: bytes | None = None,
) -> bytes:
    process = subprocess.Popen(
        _git_command(worktree, arguments),
        shell=False,
        stdin=subprocess.PIPE if input_data is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_git_environment(),
        start_new_session=True,
    )
    output = bytearray()
    selector = selectors.DefaultSelector()
    if process.stdout is None:
        raise FinalVerificationError("Git manifest probe has no output stream")
    if input_data is not None and process.stdin is not None:
        try:
            process.stdin.write(input_data)
            process.stdin.close()
        except OSError as error:
            _kill_process(process)
            process.wait(timeout=1)
            raise FinalVerificationError("Git context input failed") from error
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while selector.get_map():
            remaining = _remaining_seconds(deadline, 10)
            if not selector.select(remaining):
                raise FinalVerificationError("Git manifest probe timed out")
            chunk = os.read(process.stdout.fileno(), 64 * 1024)
            if not chunk:
                selector.unregister(process.stdout)
                continue
            output.extend(chunk)
            if len(output) > _MAX_MANIFEST_BYTES:
                raise FinalVerificationError("Git manifest output is too large")
    except (OSError, ValueError, FinalVerificationError):
        _kill_process(process)
        process.wait(timeout=1)
        raise
    finally:
        selector.close()
        process.stdout.close()
    if process.wait(timeout=1) != 0:
        raise FinalVerificationError("Git manifest probe failed")
    return bytes(output)


def _git_command(worktree: Path, arguments: tuple[str, ...]) -> tuple[str, ...]:
    git = _trusted_system_binary("git")
    if git is None:
        raise FinalVerificationError("trusted Git binary is unavailable")
    return (
        git,
        "-C",
        str(worktree),
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "submodule.recurse=false",
        *arguments,
    )


def _remaining_seconds(deadline: float | None, default: float) -> float:
    if deadline is None:
        return default
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise FinalVerificationError("verification invocation deadline exceeded")
    return min(default, remaining)


def _git_probe(worktree: Path, arguments: tuple[str, ...], deadline: float | None = None) -> str:
    git = _trusted_system_binary("git")
    if git is None:
        raise FinalVerificationError("trusted Git binary is unavailable")
    try:
        result = subprocess.run(
            _git_command(worktree, arguments),
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            timeout=_remaining_seconds(deadline, 10),
            env=_git_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise FinalVerificationError("Git target probe failed") from error
    if result.returncode != 0:
        raise FinalVerificationError("Git target probe failed")
    return result.stdout.strip()


def _git_environment() -> dict[str, str]:
    return {
        "PATH": _command_path(None),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/false",
        "SSH_ASKPASS": "/bin/false",
    }


def _trusted_system_binary(name: str) -> str | None:
    for candidate in _SYSTEM_BINARIES.get(name, ()):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    return None


def _execute_command(
    command: VerificationCommand,
    worktree: Path,
    deadline: float,
    output_budget: int,
    trusted_tool_roots: Sequence[Path] | None = None,
    trusted_support_roots: Sequence[Path] | None = None,
) -> CommandResult:
    try:
        roots = _trusted_tool_roots(trusted_tool_roots)
        argv = _validate_argv(command.argv, worktree, roots)
        request = CommandExecutionRequest(
            argv,
            worktree,
            True,
            True,
            deadline,
            min(MAX_OUTPUT_BYTES, output_budget),
            roots,
            tuple(trusted_support_roots or ()),
        )
        execution = run_subprocess_command(request)
        if not isinstance(execution, CommandExecutionResult):
            raise FinalVerificationError("command runner returned malformed result")
        _validate_execution(execution)
    except Exception as error:
        return CommandResult(
            command.argv,
            None,
            "",
            _bounded_to(str(error), min(MAX_OUTPUT_BYTES, output_budget)),
        )
    stdout, stderr = _bounded_pair(execution.stdout, execution.stderr, min(MAX_OUTPUT_BYTES, output_budget))
    return CommandResult(command.argv, execution.exit_code, stdout, stderr)


def _not_run_results(
    commands: Sequence[VerificationCommand], reason: str, output_budget: int
) -> list[CommandResult]:
    results: list[CommandResult] = []
    remaining = max(0, output_budget)
    for command in commands:
        stderr = _bounded_to(reason, remaining)
        results.append(CommandResult(command.argv, None, "", stderr))
        remaining -= len(stderr.encode("utf-8"))
    return results


def _result_output_bytes(result: CommandResult) -> int:
    return len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8"))


def _validate_execution(execution: CommandExecutionResult) -> None:
    if type(execution.exit_code) is not int and execution.exit_code is not None:
        raise FinalVerificationError("command result exit code is malformed")
    if not isinstance(execution.stdout, str) or not isinstance(execution.stderr, str):
        raise FinalVerificationError("command result output is malformed")


def _require_execution_flags(request: CommandExecutionRequest) -> None:
    if not request.network_disabled or not request.write_protected:
        raise FinalVerificationError("verification runner must be read-only and offline")


def _safe_environment(
    worktree: Path, trusted_tool_roots: Sequence[Path] | None = None
) -> dict[str, str]:
    return {
        "PATH": _command_path(worktree, trusted_tool_roots),
        **{
            key: os.environ[key]
            for key in ("LANG", "LC_ALL")
            if key in os.environ
        },
    }


def _bounded_pair(stdout: str, stderr: str, limit: int) -> tuple[str, str]:
    bounded_stdout = _bounded_to(stdout, limit)
    remaining = max(0, limit - len(bounded_stdout.encode("utf-8")))
    return bounded_stdout, _bounded_to(stderr, remaining)


def _bounded_to(value: str, limit: int) -> str:
    encoded = value.encode("utf-8", errors="replace")
    candidate = encoded[: max(0, limit)]
    while candidate:
        try:
            return candidate.decode("utf-8")
        except UnicodeDecodeError as error:
            candidate = candidate[: error.start]
    return ""


def _bounded(value: str) -> str:
    encoded = value.encode("utf-8", errors="replace")
    return encoded[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
