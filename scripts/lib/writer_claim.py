"""Fail-closed per-task writer claim lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from contextlib import contextmanager
import fcntl

if __package__:
    from .pipeline_state_paths import validate_task_id
    from . import writer_claim_io as claim_io
    from .writer_claim_reconciliation import ReconciliationError, active_processes, canonical_directory, registered_worktree_head
else:
    from pipeline_state_paths import validate_task_id
    import writer_claim_io as claim_io
    from writer_claim_reconciliation import ReconciliationError, active_processes, canonical_directory, registered_worktree_head


class ClaimError(ValueError):
    """Base writer-claim failure."""


class ClaimConflictError(ClaimError):
    """Raised when another valid writer owns a task."""


class ClaimIdentityError(ClaimError):
    """Raised when an owner attempts to mutate another claim."""


class ClaimRecoveryRequiredError(ClaimError):
    """Raised when claim state needs explicit human recovery."""


@dataclass(frozen=True)
class WriterClaim:
    task_id: str
    owner: str
    session_id: str
    repository: str
    branch: str
    worktree: str
    acquired_at: str
    last_heartbeat_at: str


class WriterClaimManager:
    """Owns atomic claim mutations beneath one harness-data root."""

    def __init__(self, harness_data: Path) -> None:
        self._harness_data = harness_data

    def acquire(self, task_id: str, identity: dict[str, str]) -> WriterClaim:
        claim = self._new_claim(task_id, identity)
        with self._task_directory(task_id, create=True) as task:
            try:
                os.mkdir("writer.lock", mode=0o700, dir_fd=task)
                os.fsync(task)
            except FileExistsError:
                existing = self.inspect(task_id)
                raise ClaimConflictError(f"task already claimed by {existing.session_id}")
            try:
                with claim_io.claim_directory(task) as lock:
                    self._write_claim(lock, claim)
            except Exception as error:
                raise ClaimRecoveryRequiredError("claim creation interrupted; human recovery required") from error
        return claim

    def inspect(self, task_id: str) -> WriterClaim:
        try:
            with self._task_directory(task_id) as task:
                self._ensure_no_transaction(task)
                with claim_io.claim_directory(task) as lock:
                    return self._parse_claim(lock, task_id)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ClaimRecoveryRequiredError("writer claim cannot be trusted") from error

    def heartbeat(self, task_id: str, identity: dict[str, str]) -> WriterClaim:
        with self._operation_lock(task_id):
            current = self._require_owner(task_id, identity)
            updated = WriterClaim(**{**current.__dict__, "last_heartbeat_at": self._timestamp()})
            with self._task_directory(task_id) as task, claim_io.claim_directory(task) as lock:
                self._write_claim(lock, updated)
            return updated

    def release(self, task_id: str, identity: dict[str, str]) -> None:
        with self._operation_lock(task_id):
            self._require_owner(task_id, identity)
            with self._task_directory(task_id) as task, claim_io.claim_directory(task) as lock:
                os.unlink("owner.json", dir_fd=lock)
                os.fsync(lock)
                os.rmdir("writer.lock", dir_fd=task)
                os.fsync(task)

    def takeover(self, task_id: str, identity: dict[str, str], *, authorization: dict[str, object]) -> WriterClaim:
        self._validate_authorization(authorization)
        with self._operation_lock(task_id):
            previous = self.inspect(task_id)
            if identity.get("session_id") == previous.session_id:
                raise ClaimRecoveryRequiredError("takeover requires a unique successor session")
            reconciliation = self._reconcile_takeover(task_id, previous, identity)
            successor = self._new_claim(task_id, identity)
            try:
                self._commit_takeover(task_id, previous, successor, authorization, reconciliation)
            except (OSError, ValueError) as error:
                raise ClaimRecoveryRequiredError("takeover transaction requires human recovery") from error
            return successor

    @contextmanager
    def _task_directory(self, task_id: str, *, create: bool = False):
        validate_task_id(task_id)
        try:
            root = claim_io.open_harness_data(self._harness_data, create)
        except (OSError, ValueError) as error:
            raise ClaimRecoveryRequiredError("unsafe harness data path") from error
        try:
            try:
                state = claim_io.open_directory(root, "pipeline-state", create)
            except OSError as error:
                raise ClaimRecoveryRequiredError("unsafe pipeline-state path") from error
            try:
                try:
                    task = claim_io.open_directory(state, task_id, create)
                except OSError as error:
                    raise ClaimRecoveryRequiredError("unsafe task claim path") from error
                try:
                    yield task
                finally:
                    os.close(task)
            finally:
                os.close(state)
        finally:
            os.close(root)

    @contextmanager
    def _operation_lock(self, task_id: str):
        with self._task_directory(task_id) as task:
            try:
                descriptor = os.open(
                    "writer.operation.lock",
                    os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=task,
                )
            except OSError as error:
                raise ClaimRecoveryRequiredError("claim operation lock cannot be trusted") from error
            os.fsync(task)
            try:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise ClaimRecoveryRequiredError("claim mutation is already in progress") from error
                yield
            finally:
                os.close(descriptor)

    def _new_claim(self, task_id: str, identity: dict[str, str]) -> WriterClaim:
        required = ("owner", "session_id", "repository", "branch", "worktree")
        if any(not identity.get(field) for field in required):
            raise ClaimRecoveryRequiredError("claim identity is incomplete")
        try:
            repository = canonical_directory(identity["repository"])
            worktree = canonical_directory(identity["worktree"])
        except ReconciliationError as error:
            raise ClaimRecoveryRequiredError(str(error)) from error
        timestamp = self._timestamp()
        values = (identity["owner"], identity["session_id"], repository, identity["branch"], worktree)
        return WriterClaim(task_id, *values, timestamp, timestamp)

    def _require_owner(self, task_id: str, identity: dict[str, str]) -> WriterClaim:
        claim = self.inspect(task_id)
        if any(getattr(claim, field) != identity.get(field) for field in ("owner", "session_id")):
            raise ClaimIdentityError("claim owner identity does not match")
        return claim

    def _write_claim(self, lock: int, claim: WriterClaim) -> None:
        claim_io.write_json(lock, "owner.json", {"schema_version": 1, **claim.__dict__})

    def _parse_claim(self, lock: int, task_id: str) -> WriterClaim:
        data = claim_io.read_json(lock, "owner.json")
        fields = ("task_id", "owner", "session_id", "repository", "branch", "worktree", "acquired_at", "last_heartbeat_at")
        if data.get("schema_version") != 1 or any(not isinstance(data.get(field), str) or not data[field] for field in fields):
            raise ValueError("invalid claim")
        if data["task_id"] != task_id:
            raise ValueError("claim task mismatch")
        return WriterClaim(**{field: data[field] for field in fields})

    def _commit_takeover(
        self,
        task_id: str,
        previous: WriterClaim,
        successor: WriterClaim,
        authorization: dict[str, object],
        reconciliation: dict[str, object],
    ) -> None:
        event = {
            "event": "writer_claim_displaced",
            "authorization": authorization,
            "reconciliation": reconciliation,
            "previous": previous.__dict__,
            "successor": successor.__dict__,
        }
        with self._task_directory(task_id) as task:
            try:
                trajectory = claim_io.open_optional_regular(task, "trajectory.jsonl")
                if trajectory is not None:
                    os.close(trajectory)
            except OSError as error:
                raise ClaimRecoveryRequiredError("trajectory path cannot be trusted") from error
            try:
                claim_io.write_json(task, "takeover.transaction.json", event)
                with claim_io.claim_directory(task) as lock:
                    self._write_claim(lock, successor)
                claim_io.append_json_line(task, "trajectory.jsonl", event)
                os.unlink("takeover.transaction.json", dir_fd=task)
                os.fsync(task)
            except OSError as error:
                raise ClaimRecoveryRequiredError("takeover trajectory requires human recovery") from error

    def _reconcile_takeover(
        self,
        task_id: str,
        previous: WriterClaim,
        identity: dict[str, str],
    ) -> dict[str, object]:
        immutable = ("repository", "branch", "worktree")
        if any(identity.get(field) != getattr(previous, field) for field in immutable):
            raise ClaimRecoveryRequiredError("successor task Git identity mismatches prior claim")
        try:
            prior_head = registered_worktree_head(previous.__dict__)
            head = registered_worktree_head(identity)
        except ReconciliationError as error:
            raise ClaimRecoveryRequiredError(str(error)) from error
        if identity.get("head") != head or prior_head != head:
            raise ClaimRecoveryRequiredError("successor HEAD mismatches claim")
        try:
            active = self._active_processes(Path(previous.worktree))
        except ReconciliationError as error:
            raise ClaimRecoveryRequiredError(str(error)) from error
        if active:
            raise ClaimRecoveryRequiredError("prior writer worktree still has active processes")
        evidence = self._reconcile_evidence(task_id, head)
        return {"git_head": head, "evidence": evidence, "active_processes": []}

    def _reconcile_evidence(self, task_id: str, head: str) -> str:
        try:
            with self._task_directory(task_id) as task:
                evidence = claim_io.read_json(task, "verification-evidence.json")
        except FileNotFoundError:
            return "absent"
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise ClaimRecoveryRequiredError("verification evidence cannot be trusted") from error
        if evidence.get("task_id") != task_id or evidence.get("git_head") != head or not evidence.get("verdict"):
            raise ClaimRecoveryRequiredError("verification evidence is stale or identity-mismatched")
        return "valid"

    @staticmethod
    def _active_processes(worktree: Path) -> list[int]:
        return active_processes(worktree)

    @staticmethod
    def _validate_authorization(authorization: dict[str, object]) -> None:
        fields = ("authorizer_identity", "authorization_reference", "rationale")
        valid_fields = all(isinstance(authorization.get(field), str) and authorization[field] for field in fields)
        if authorization.get("confirmed_stopped") is not True or not valid_fields:
            raise ClaimRecoveryRequiredError("auditable human authorization is required for takeover")

    @staticmethod
    def _ensure_no_transaction(task: int) -> None:
        if not claim_io.exists_no_follow(task, "takeover.transaction.json"):
            return
        raise ClaimRecoveryRequiredError("incomplete takeover transaction requires human recovery")

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat()
