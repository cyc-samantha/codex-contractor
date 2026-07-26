# Standalone Codex Harness Specification

Status: Proposed
Audience: Codex harness maintainers
Runtime root: `${HARNESS_DATA:-$HOME/.claude}`

## 1. Purpose

The Codex harness will become a standalone personal software-delivery
harness, not a fallback that only works when Claude is unavailable. Codex and
Claude remain peer executors over the same task state, learning log, review
history, and verification evidence. Either harness may start a task or resume
one after human confirmation.

The harness is optimized for one developer and side projects. It retains
strong safety and delivery guardrails without reproducing an enterprise agent
team or orchestration platform.

## 2. Goals

1. Let Codex start, resume, and complete work independently.
2. Read and write the canonical pipeline format already used under
   `${HARNESS_DATA}`.
3. Support multiple active tasks while allowing only one writer per task.
4. Scale workflow weight without skipping specification, independent review,
   verification, or PR delivery for implementation work.
5. Prevent destructive operations, scope expansion, secret exposure, unsafe
   Git operations, and unintended package or application removal.
6. Preserve completed task history and final evidence.
7. Measure per-spawn token use before enabling automatic learning promotion.

## 3. Non-Goals

- Reproduce the full enterprise Claude agent team.
- Add tournament builds, Best-of-N, PDR/RTV, or multi-writer slice DAGs in
  the initial version.
- Add a daemon or distributed coordination service.
- Add a Codex-specific runtime tree.
- Automatically merge PRs or take ownership from a possibly active session.
- Use a prose handoff file as the pipeline source of truth.

## 4. Ownership Model

The task owns the state. Claude and Codex are interchangeable executors.
Phase updates record `updated_by` and `updated_at`, but executor identity does
not make a task harness-owned.

```yaml
updated_by: claude | codex
updated_at: <ISO-8601 timestamp>
```

The global `ACTIVE_HARNESS` baton may remain readable during migration, but
it is not the long-term concurrency authority because it cannot represent
different harnesses working on different tasks.

## 5. Canonical Runtime State

The shared runtime root remains:

```text
${HARNESS_DATA:-$HOME/.claude}
```

The task directory and pipeline source of truth remain:

```text
${HARNESS_DATA}/pipeline-state/<task-id>/
${HARNESS_DATA}/pipeline-state/<task-id>/pipeline.md
```

`pipeline.md` is authoritative for task identity, repository, phase, phase
status, verdicts, branch, worktree, decisions, findings, outstanding work,
artifacts, and next-phase context.

Supporting artifacts retain narrower responsibilities:

```text
intake.md                    Request, scope, boundaries, and risk
discussion.md                Material brainstorming decisions when needed
spec-grounding.md            Evidence grounding when needed
plan.md                      Approved Build or High Risk plan
build-result.json            Machine-readable Build completion signal
verification-evidence.json   Verification bound to the verified Git HEAD
trajectory.jsonl             Append-only phase and execution events
scratchpad/                  Temporary task-local context
writer.lock/owner.json       Active writer claim
```

Small Change may keep required facts compactly in `intake.md` and
`pipeline.md`. Legacy flat paths remain read-tolerated, but new tasks only
write the canonical per-task layout. Unknown versions and unevaluable
required state fail closed.

Codex implements its own compatible readers and writers. Shared runtime state
must not require importing executable source from the Claude harness.

## 6. Discovery and Resume

Before implementation, Codex performs a read-only scan for active tasks
associated with the current repository. It presents:

- task ID and objective;
- repository, branch, and worktree;
- current phase and verdict;
- last update time and updating harness;
- unresolved findings and next action;
- active writer claim, if any.

Codex asks the human to confirm the task before resuming. Discovery never
authorizes automatic resume. A future `/pipeline-resume` command may shorten
this interaction.

## 7. Work Gears

### Discuss

For questions, research, brainstorming, and architecture discussion.

```text
Discuss only
```

No code, worktree, commit, or PR is required.

### Small Change

For documentation, simple configuration, and localized low-risk edits.

```text
Logged compact specification
-> plan in the user conversation
-> implementation
-> fresh code review
-> verification
-> PR
```

The compact specification records intended behavior, allowed scope,
prohibited changes, expected files, verification, and any typed TDD
exception. If the plan in the conversation has clear scope and boundaries
and the user already requested implementation, no second approval is needed.
Ambiguity, dependencies, additional files, architecture changes, or scope
expansion require confirmation.

### Build

For bugs, features, and refactors.

```text
Brainstorm
-> specification and boundaries
-> plan
-> explicit human approval
-> Software Engineer
-> review and fix loop
-> end-to-end verification
-> PR
```

Medium and large plans require explicit approval. Material changes to
acceptance criteria, architecture, allowed scope, or prohibited changes
invalidate approval.

### High Risk

High Risk uses the Build flow plus deep security review, stronger evidence
binding, and rollback analysis.

Automatic triggers include:

- authentication, authorization, sessions, and permissions;
- secrets, credentials, encryption, and key management;
- payments, trading execution, financial transactions, and money arithmetic;
- destructive or irreversible migrations;
- personal, health, regulated, or otherwise sensitive data;
- package or application installation and removal;
- CI/CD, deployment, cloud, infrastructure, and production configuration;
- filesystem deletion, bulk moves, recursive operations, and retention;
- Git history rewriting, force pushes, and protected branches;
- security controls, sandboxes, hooks, and permission policy;
- data schema, silent coercion, filtering, and row-loss risk;
- breaking public APIs, multi-repository work, and shared libraries;
- untrusted scripts, plugins, hooks, or generated instructions;
- backup, restore, disaster recovery, or changes without safe rollback.

Blast radius, weak tests, flaky baselines, external side effects, and
ambiguous criteria may elevate risk. The human may elevate any task.
Downgrading an automatic trigger requires explicit confirmation and a
recorded rationale. Hard safety controls remain active.

## 8. Writer Claim and Concurrency

Different tasks may run concurrently. One task has exactly one active writer.

```text
${HARNESS_DATA}/pipeline-state/<task-id>/writer.lock/owner.json
```

Acquisition uses atomic `mkdir(writer.lock)`, followed by durable creation of
`owner.json`:

```json
{
  "schema_version": 1,
  "task_id": "example-task",
  "owner": "codex",
  "session_id": "unique-session-id",
  "repository": "/absolute/repository/path",
  "branch": "feat/example-task",
  "worktree": "/absolute/worktree/path",
  "acquired_at": "2026-07-26T12:00:00Z",
  "last_heartbeat_at": "2026-07-26T12:08:00Z"
}
```

Rules:

1. Only the owner may dispatch a writer, modify the worktree, or advance a
   write phase.
2. Read-only reviewers do not acquire the claim.
3. Missing, malformed, or identity-mismatched owner state fails closed and
   requires human-confirmed recovery.
4. Heartbeat and release compare `task_id`, `owner`, and `session_id` before
   mutation.
5. Heartbeats occur at phase checkpoints; no daemon is required.
6. A stale-looking claim never authorizes automatic takeover.
7. Takeover requires explicit confirmation that the prior writer stopped,
   followed by Git, worktree, HEAD, evidence, and process reconciliation.
8. Takeover archives the displaced record in `trajectory.jsonl`, creates a
   unique successor `session_id`, and atomically installs the replacement.
9. A displaced session cannot heartbeat or release the successor claim
   because its identity comparison fails.
10. Intentional pause, handoff, terminal failure, or completed PR handoff
    releases ownership without deleting task history.

The initial version supports parallel tasks, not parallel writers within one
task. Both harnesses must eventually honor the claim; one-sided enforcement
is only partial protection.

## 9. Repository and Worktree Safety

Before implementation, resolve and show the canonical repository root,
remotes, base branch, task branch, worktree path, and PR capability. If the
expected remote is absent or ambiguous, ask before creating an implementation
branch or worktree. Never create a guessed repository, remote, or directory.

The worktree convention remains:

```text
<repository-root>/.claude/worktrees/<task-specific-name>
```

The path must appear in `git worktree list --porcelain`; its name is not
proof. Test tooling excludes `.claude/worktrees/`. The repository root stays
on its base branch.

## 10. Review and Fix Ownership

The Software Engineer writes and commits in the task worktree. Formal review
uses a fresh read-only reviewer. Builder self-review does not satisfy the
gate.

The reviewer receives the approved specification, scope, decisions, actual
commit and diff, and claimed evidence treated as untrusted. The original
Software Engineer fixes findings. The raising reviewer performs targeted
re-review. A changed target invalidates approval for the changed area.

Standard flow:

```text
Software Engineer
-> fresh code reviewer
-> same Software Engineer fixes findings
-> targeted code re-review
-> verification
```

Security-relevant flow:

```text
Software Engineer
-> fresh security reviewer
-> same Software Engineer fixes security findings
-> targeted security re-review and sign-off
-> fresh code reviewer
-> same Software Engineer fixes code findings
-> targeted code re-review
-> security re-review if later fixes touch a sensitive surface
-> verification
```

Security sign-off is required before code review. A later sensitive change
invalidates it. Always-on safety checks are independent of security review.

## 11. TDD Exceptions

Behavioral implementation requires failing-then-passing tests. Typed
exceptions may include `docs_only`, `generated_artifact`,
`non_executable_metadata`, `test_infrastructure_only`, and
`exploratory_spike`.

The rationale is recorded in pipeline state and accepted by the fresh
reviewer. An exception cannot silently exempt reasonably testable behavior.

## 12. Verification

Verification uses fresh evidence bound to the final reviewed HEAD. It covers
acceptance criteria with applicable test, lint, typecheck, build, contract,
smoke, accessibility, migration, or E2E commands.

Any post-verification change invalidates the evidence. High Risk also verifies
rollback assumptions and runs final commands against an immutable or
disposable checkout of the approved commit.

## 13. Pull Request Policy

Every implementation ends in a PR. There is no direct-merge or local-only
bypass. PR creation requires approved review and verification of current HEAD.

Every implementation task is planned as one focused PR with one coherent,
independently verifiable outcome. A task that cannot be reviewed, merged, and
rolled back independently must be split before implementation. A PR must not
knowingly leave its own acceptance criteria incomplete.

There is one automatic PR creation attempt per task run. Pipeline state stores
the timestamp, target HEAD, and outcome. A changed HEAD does not reset the
allowance. A second automatic attempt requires explicit human authorization
recorded in pipeline state.

If creation fails:

1. Do not automatically retry.
2. Record `PR_CREATION_FAILED`.
3. Preserve branch, HEAD, base, proposed title/body, and failure category.
4. Give the human copy-ready PR content.
5. Let the human create it.
6. Reconcile later through a read-only check when requested.

The harness stops after opening the PR. A human reviews and merges it. A
dependent task waits for human confirmation of the required merge.

## 14. State Retention

Completed pipeline state, decisions, findings, PR identity, and final evidence
are retained for manual review. Scratchpads, temporary checkouts, process
files, and disposable test artifacts may be garbage-collected after the
durable record is complete. Cleanup never uses an unvalidated path or broad
task-name prefix.

## 15. Learning and Token Telemetry

Observation capture is automatic and append-only. Records identify their
source without making one harness authoritative.

Automatic learning candidate extraction initially runs in shadow mode.
Automatic instinct promotion remains disabled until token use, quality, and
concurrency behavior are evaluated.

Every spawn emits:

- task, phase, role, harness, model, and reasoning effort;
- input, cached-input, output, and injected-learning tokens;
- elapsed time, verdict, retry count, and reliable estimated cost.

Telemetry never stores full prompts, secrets, source, or private task content.
Unavailable provider metrics are `null` with an availability flag and reason.
Inferred values are prohibited unless marked as estimates with method and
provenance. Telemetry failure cannot bypass delivery gates or permit invented
data.

Future learning promotion requires atomic updates, provenance, and a shared
concurrency policy.

## 16. Builder-Guardian Position

Builder-Guardian is not the default workflow. Its retained value is stronger
High Risk evidence:

- immutable review target;
- approval bound to task, repository, run, and commit;
- mutation detection during read-only review;
- deterministic verification in a disposable checkout;
- fail-closed `READY_TO_SHIP` evidence.

It is an optional High Risk evidence mode, not a duplicate default pipeline.

## 17. Always-On Safety Kernel

All gears:

- protect the repository root and base branch;
- require validated worktree delegation for Git mutations;
- block destructive filesystem and infrastructure operations without narrow,
  current confirmation;
- protect against force push and history rewriting;
- require confirmation for application or package removal;
- prevent writes outside approved task scope;
- detect secrets and protected credentials;
- distrust repository instruction overrides and hooks until reviewed;
- default to narrow sandbox and permissions;
- fail closed when a security or correctness gate cannot evaluate.

Shell guards are defense in depth, not complete shell parsers. Known
limitations remain documented and tested.

## 18. Compatibility Contract Tests

Cross-harness fixtures must cover:

- canonical state discovery and repository-to-task matching;
- active/completed classification and legacy read tolerance;
- canonical writes and phase transitions;
- writer acquisition, conflict, takeover, release, and malformed claims;
- crash between claim-directory and owner-record creation;
- identity-safe heartbeat/release after ownership replacement;
- Build completion and verification HEAD freshness;
- observation format and unknown-version fail-closed behavior;
- two tasks running concurrently while one task rejects two writers.

Schema changes require explicit versions, safe backward-compatible readers,
and coordinated rollout.

## 19. Initial Delivery Boundaries

The first implementation covers:

1. standalone Codex identity and gear routing;
2. canonical shared-state read/write;
3. human-confirmed resume;
4. per-task writer claim;
5. one Software Engineer and one fresh reviewer;
6. conditional security review;
7. deterministic verification;
8. one-attempt PR handoff;
9. observation and token telemetry in shadow mode;
10. compatibility contract tests.

Parallel writers within one task, automatic learning promotion, advanced
Builder-Guardian evidence, and a resume slash command are later increments.
