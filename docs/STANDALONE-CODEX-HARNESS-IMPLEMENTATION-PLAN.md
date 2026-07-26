# Standalone Codex Harness Implementation Plan

Status: Proposed
Depends on: `docs/STANDALONE-CODEX-HARNESS-SPEC.md`

## 1. Delivery Strategy

Implement the standalone harness as small, reviewable slices. Preserve the
existing safety hooks and Builder-Guardian workflow while replacing the
fallback-contractor assumptions incrementally.

The harness remains skills-driven. Python or shell code is used only where a
deterministic state transition, atomic writer claim, evidence check, or safety
gate is required. Do not build a general orchestration service.

Every slice follows:

```text
approved slice contract
-> isolated worktree
-> failing contract/regression tests
-> implementation
-> fresh reviewer
-> original engineer fixes findings
-> targeted re-review
-> fresh verification
-> PR
```

Documentation-only slices use the recorded `docs_only` TDD exception.

### PR-sized task invariant

Every implementation task must be small enough to produce one focused PR.
This is a hard planning constraint, not a preference.

A task is PR-sized only when:

- it has one coherent observable outcome;
- its acceptance criteria can be verified independently;
- its diff can be reviewed without reading a future task;
- it can be merged and rolled back independently;
- it does not combine schema, orchestration, review, telemetry, and migration
  concerns;
- it leaves the repository green and the shared runtime format compatible.

If a planned task cannot satisfy all six conditions, split it before
implementation. Do not open a partial PR that knowingly leaves its own
acceptance criteria incomplete.

## 2. Global Acceptance Criteria

### AC-01: Standalone identity

Codex can start a new task without a Claude handoff and no user-facing
instruction describes Codex as a fallback contractor.

### AC-02: Shared pipeline compatibility

Codex reads existing canonical Claude pipeline state and writes new state at:

```text
${HARNESS_DATA}/pipeline-state/<task-id>/pipeline.md
```

New writes never use a legacy flat path. Unknown or malformed required state
fails closed.

### AC-03: Human-confirmed resume

Codex discovers repository-matching active tasks read-only and asks the human
to choose before acquiring ownership or changing a worktree.

### AC-04: Single writer

Two different tasks can acquire writer claims concurrently. Two sessions
cannot acquire the same task. Stale or malformed claims require explicit
human-confirmed recovery.

### AC-05: Gear workflow

Discuss, Small Change, Build, and High Risk routes enforce the workflow
defined in the specification. Medium and large plans cannot enter Build
without recorded human approval.

### AC-06: Independent review

A write-capable engineer cannot approve its own implementation. Formal review
uses a fresh read-only context. Findings return to the original engineer and
then to the raising reviewer.

### AC-07: Security ordering

Security-relevant work receives security review and sign-off before code
review. A later sensitive change invalidates security sign-off.

### AC-08: Fresh verification

Verification evidence is bound to the final reviewed Git HEAD. Any later
change invalidates it.

### AC-09: PR handoff

Every implementation reaches a PR attempt. Only one automatic attempt is
allowed per task run unless a human records authorization for another.
Failure preserves copy-ready PR content and does not retry automatically.

### AC-10: Retention

Completed pipeline state, decisions, findings, PR identity, and final evidence
remain available. Cleanup only removes explicitly disposable artifacts.

### AC-11: Observation and token telemetry

Every spawn emits privacy-safe telemetry. Observation capture is automatic.
Learning promotion remains in shadow mode until token and quality results are
reviewed.

### AC-12: Safety kernel

Existing main-branch, destructive-command, code-shape, and worktree safety
tests remain green. New orchestration paths cannot bypass them.

## 3. Slice 0: Baseline and Compatibility Fixtures

### Objective

Establish a falsifiable baseline before changing runtime behavior.

### Work

1. Inventory current canonical and legacy pipeline layouts under the local
   shared runtime without copying private task contents into the repository.
2. Derive synthetic, PII-free fixtures for:
   - canonical active task;
   - canonical completed task;
   - legacy flat state;
   - malformed and unknown-version state;
   - Build result;
   - verification evidence;
   - observation record.
3. Add a compatibility matrix documenting which fields are required,
   optional, or legacy-only.
4. Pin the existing hook and Builder-Guardian baseline.

### Candidate files

```text
tests/fixtures/pipeline-state/
tests/shell/test_pipeline_state_compatibility.bats
docs/PIPELINE-STATE-COMPATIBILITY.md
```

### Verification

- Existing shell suite passes before and after fixture addition.
- Fixtures contain no paths, identifiers, source, or prose copied from
  private runtime tasks.
- A schema/fixture audit fails on missing required identities.

## 4. Slice 1: Standalone Identity and Gear Routing

### Objective

Remove fallback-only behavior and provide the four lightweight routes.

### Work

1. Document the proposed transition without claiming standalone behavior is
   active before its delivery gates exist.
2. Add a minimal intake/gear skill that classifies:
   - Discuss;
   - Small Change;
   - Build;
   - human-elevated High Risk.
3. Record manual High Risk elevation. Automatic triggers and downgrade
   enforcement land later in the dedicated risk-routing task.
4. Define the Small Change compact specification and typed TDD exceptions.
5. Remove stale documentation describing the script or skill catalog.

### Candidate files

```text
AGENTS.md
README.md
PLAN.md
.agents/skills/harness-intake/SKILL.md
.agents/skills/harness-pipeline/SKILL.md
.agents/skills/README.md
scripts/README.md
tests/shell/test_gear_routing.bats
```

### Verification

- Table-driven routing tests cover Discuss, Small Change, Build, and explicit
  human elevation to High Risk.
- Discuss never creates implementation state.
- Small Change cannot expand declared scope silently.
- Build/High Risk requires plan approval at the specified thresholds.

## 5. Slice 2: Canonical Pipeline State Library

### Objective

Give Codex an independent, compatible state reader/writer.

### Work

1. Implement canonical path resolution using `HARNESS_DATA`.
2. Read canonical and supported legacy layouts.
3. Write only canonical per-task paths.
4. Parse and validate pipeline identity, repository, phase, verdict, branch,
   worktree, timestamps, approval state, and outstanding work.
5. Use atomic file replacement for state transitions.
6. Add `updated_by` and `updated_at` without breaking compatible readers.
7. Preserve completed state.

### Candidate files

```text
scripts/lib/pipeline_state.py
scripts/lib/pipeline_state_paths.py
scripts/lib/pipeline_state_cli.py
tests/test_pipeline_state.py
tests/fixtures/pipeline-state/
```

Use Python unit tests if this slice introduces Python modules; keep Bats for
shell entry-point behavior.

### Verification

- Canonical/legacy discovery matches fixtures.
- Canonical writes round-trip.
- Unknown versions and identity mismatches fail closed.
- Atomic-write interruption leaves either the old valid state or the new
  valid state, never a partial file.

## 6. Slice 3: Writer Claim

### Objective

Enforce one active writer per task while allowing parallel tasks.

### Work

1. Implement atomic claim acquisition with `mkdir(writer.lock)`.
2. Durably write and validate `owner.json`.
3. Implement identity-safe heartbeat and release.
4. Implement inspection and human-authorized takeover preparation.
5. Archive displaced ownership in `trajectory.jsonl`.
6. Install successor ownership atomically.
7. Reconcile repository, worktree registry, HEAD, dirty state, evidence, and
   detectable active processes before takeover.
8. Keep `ACTIVE_HARNESS` read compatibility during migration without treating
   it as the per-task lock.

### Candidate files

```text
scripts/lib/writer_claim.py
scripts/lib/writer_claim_cli.py
tests/test_writer_claim.py
tests/shell/test_writer_claim.bats
```

### Required tests

- Different tasks acquire concurrently.
- Same task has one winner under concurrent acquisition.
- Crash after lock-directory creation fails closed.
- Missing/malformed/mismatched `owner.json` fails closed.
- Old owner cannot heartbeat or release a successor claim.
- Takeover requires a recorded human authorization input.
- Release preserves completed task state.

## 7. Slice 4: Task Discovery and Human-Confirmed Resume

### Objective

Make new and in-progress task entry reliable without adding the future slash
command yet.

### Work

1. Match tasks to the canonical repository identity.
2. Present active task summaries without mutating state.
3. Require human selection.
4. Acquire writer claim only after selection.
5. Reconcile branch, worktree, HEAD, dirty state, test claim, and next action.
6. Create a new canonical task only when the user confirms the request is new.

### Candidate files

```text
.agents/skills/harness-intake/SKILL.md
.agents/skills/harness-pipeline/SKILL.md
scripts/lib/task_discovery.py
tests/test_task_discovery.py
```

### Verification

- Multiple matching tasks are presented deterministically.
- No selection means no state or Git mutation.
- Stale prose never overrides Git or test reality.
- New tasks use the same canonical format as compatible existing tasks.

## 8. Slice 5: Minimal Agent Workflow

### Objective

Implement the required Software Engineer and fresh reviewer loop without a
large role team.

### Work

1. Define minimal role contracts for:
   - Software Engineer;
   - code reviewer;
   - security reviewer.
2. Dispatch the Software Engineer into the claimed task worktree.
3. Dispatch reviewers with read-only permission and fresh context.
4. Bind review input to actual task, branch, and HEAD.
5. Return findings to the same engineer role and worktree.
6. Route targeted re-review to the raising reviewer.
7. Invalidate approvals when the reviewed HEAD changes.
8. Capture per-spawn result and identity in trajectory state.

### Candidate files

```text
.codex/agents/software-engineer.toml
.codex/agents/code-reviewer.toml
.codex/agents/security-reviewer.toml
.agents/skills/harness-pipeline/SKILL.md
scripts/lib/review_evidence.py
tests/test_review_evidence.py
```

Confirm the current Codex role-configuration surface before committing to the
TOML paths. Prefer native subagents plus small role instructions over a custom
process orchestrator.

### Verification

- Builder identity cannot produce an accepted formal review.
- Reviewer execution cannot modify the repository.
- Findings bind to task and reviewed HEAD.
- A fix invalidates prior approval and triggers targeted re-review.

## 9. Slice 6: Security Routing and Sign-Off

### Objective

Run deep security review only when justified while keeping the safety kernel
always active.

### Work

1. Encode the High Risk trigger catalog.
2. Persist `security_review.required`, triggers, verdict, reviewer, and
   reviewed HEAD.
3. Enforce security sign-off before code review.
4. Detect later changes to sensitive surfaces and invalidate sign-off.
5. Require recorded human rationale for downgrade.

### Candidate files

```text
scripts/lib/risk_routing.py
scripts/lib/review_evidence.py
.agents/skills/harness-security-review/SKILL.md
tests/test_risk_routing.py
tests/test_security_ordering.py
```

### Verification

- Security and non-security table cases route correctly.
- Builder cannot downgrade risk.
- Code review cannot start before required security approval.
- Sensitive fixes after code review require renewed security sign-off.

## 10. Slice 7: Verification and PR Handoff

### Objective

Bind fresh verification to reviewed HEAD and enforce the one-attempt PR rule.

### Work

1. Produce canonical `verification-evidence.json` atomically.
2. Compare verification HEAD with review approval and current worktree HEAD.
3. Derive required commands from acceptance criteria and project commands.
4. Persist PR attempt allowance and result in pipeline state.
5. Make PR creation idempotent by checking for an existing PR first.
6. Attempt creation once.
7. On failure, save copy-ready title/body and stop.
8. Stop after PR creation; never merge automatically.

### Candidate files

```text
scripts/lib/verification_evidence.py
scripts/lib/pr_handoff.py
.agents/skills/harness-verify/SKILL.md
.agents/skills/harness-pr-creation/SKILL.md
tests/test_verification_evidence.py
tests/test_pr_handoff.py
```

### Verification

- Changed HEAD invalidates review and verification.
- Missing evidence fails closed.
- Existing PR is reconciled read-only rather than duplicated.
- Failure does not retry and preserves complete manual PR content.
- A second attempt requires recorded human authorization.

## 11. Slice 8: Observation and Spawn Telemetry

### Objective

Capture the data and establish the evaluation framework without enabling
automatic promotion.

### Work

1. Define a versioned privacy-safe spawn event.
2. Capture token fields exposed by the provider.
3. Record unavailable metrics as `null` with reason.
4. Mark estimates with method and provenance.
5. Record learning/memory injection token size.
6. Append task observations automatically.
7. Run learning candidate extraction in shadow mode.
8. Add the versioned evaluation method and report template.

### Candidate files

```text
scripts/lib/spawn_telemetry.py
scripts/lib/observation_capture.py
.codex/hooks/spawn-telemetry.sh
tests/test_spawn_telemetry.py
tests/test_observation_capture.py
docs/LEARNING-TELEMETRY-EVALUATION.md
```

Confirm which Codex lifecycle event reliably exposes usage before selecting a
hook registration. Do not fabricate metrics to satisfy the schema.

### Later evaluation questions

- Token overhead per role and phase.
- Learning-injection tokens as a percentage of input.
- Review findings prevented by injected learning.
- Retry and failure rates with and without learning candidates.
- Differences between Claude and Codex metric availability.

## 12. Slice 9: High Risk Evidence Mode

### Objective

Retain Builder-Guardian only for stronger High Risk evidence.

### Work

1. Remove duplication between standard reviewer orchestration and Guardian
   role behavior.
2. Reuse shared task, review, and verification evidence types.
3. Route High Risk tasks to immutable review and disposable verification.
4. Keep `READY_TO_SHIP` exclusive to the evidence-bound gate.
5. Repair stale documentation and executable-mode verification.

### Candidate files

```text
scripts/lib/builder_guardian*.py
scripts/codex-harness
docs/BUILDER-GUARDIAN.md
scripts/README.md
tests/shell/test_builder_guardian.bats
```

### Verification

- Standard tasks do not pay Builder-Guardian overhead.
- High Risk approval is commit-bound.
- Mutation or dirty state blocks shipping.
- Full Builder-Guardian suite passes from the documented executable command.

## 13. Slice 10: Retention, Migration, and Documentation

### Objective

Finish migration without deleting historical runtime state.

### Work

1. Update installation, hook trust, runtime, recovery, and troubleshooting
   documentation.
2. Keep completed durable artifacts.
3. Limit garbage collection to enumerated disposable paths.
4. Add migration warnings for fallback-era baton and handoff behavior.
5. Verify a task can move Codex -> Claude -> Codex using fixtures and a
   non-sensitive dry run.

### Verification

- Cleanup cannot delete prefix-neighbor tasks.
- Completed evidence remains readable.
- Root checkout remains on the base branch.
- Full unit, shell, compatibility, safety, and workflow suites pass freshly.

## 14. PR-Sized Task Sequence

The slices above are capability groups, not implementation task boundaries.
Implement them through the following focused PRs.

| Task | One-PR outcome | Depends on |
|---|---|---|
| T00 | Add synthetic state fixtures and pin the existing test baseline | none |
| T01 | Document the versioned pipeline compatibility matrix | T00 |
| T02 | Document the proposed standalone transition without claiming it is active | T01 |
| T03 | Add Discuss/Small Change/Build routing plus manual High Risk elevation | T01 |
| T04 | Add Small Change compact-spec and approval behavior | T03 |
| T05 | Read canonical pipeline paths and supported legacy paths | T01 |
| T06 | Validate pipeline identity, versions, and required fields | T05 |
| T07 | Write canonical pipeline state atomically | T06 |
| T08 | Discover repository-matching tasks read-only | T07 |
| T09 | Add human-confirmed new-task and resume selection | T08 |
| T10 | Acquire one atomic writer claim per task | T07 |
| T11 | Add identity-safe claim heartbeat and release | T10 |
| T12 | Add human-confirmed claim takeover and trajectory archive | T11 |
| T13 | Define and dispatch the Software Engineer into the claimed worktree | T09, T11 |
| T14 | Add fresh read-only code review bound to task and HEAD | T13 |
| T15 | Return findings to the same engineer and run targeted re-review | T14 |
| T16 | Add automatic High Risk triggers and human-authorized downgrade enforcement | T04 |
| T17 | Add security-first review, sign-off, and invalidation | T15, T16 |
| T18 | Write verification evidence bound to reviewed HEAD | T15 |
| T19 | Derive and run task-appropriate final verification commands | T18 |
| T20 | Add one-attempt PR state and existing-PR reconciliation | T19 |
| T21 | Attempt PR creation once and preserve manual handoff on failure | T20 |
| T22 | Emit privacy-safe per-spawn token telemetry in shadow mode | T13 |
| T23 | Append observations automatically without promoting instincts | T22 |
| T24 | Add the token/learning evaluation framework and report template | T23 |
| T25 | Reuse shared evidence types in Builder-Guardian | T17, T19 |
| T26 | Route High Risk tasks to optional immutable evidence mode | T25 |
| T27 | Constrain garbage collection to disposable task artifacts | T07 |
| T28 | Add migration warnings and legacy-baton compatibility behavior | T21, T26 |
| T29 | Document installation, runtime operation, and recovery | T28 |
| T30 | Remove stale fallback-era references after a repository-wide audit | T29 |
| T31 | Add an automated synthetic cross-harness round-trip test and privacy-safe result | T30, Claude alignment complete |
| T32 | Remove final fallback identity and declare standalone behavior active | T12, T21, T23, T24, T27, T30, T31 |
| T33 | Publish the first evidence-based token/learning evaluation | T24, evaluation sample met |

Each task gets its own:

- task ID and canonical `pipeline.md`;
- compact or full approved plan;
- branch and registered worktree;
- single writer claim;
- fresh review;
- fresh verification;
- PR attempt and retained evidence.

Tasks may proceed in parallel only when their plans identify non-overlapping
files and contracts. A task that changes a shared schema, central skill, or
common fixture blocks dependent tasks until its PR is human-confirmed merged.

The T31 external prerequisite is satisfied only when the separate Claude
alignment check returns `ALIGNED`. If an earlier check returns
`CHANGES_REQUIRED`, deploy the versioned compatibility changes and rerun the
complete alignment check. Deployment without a subsequent `ALIGNED` result
does not satisfy the prerequisite. T31's PR artifact is the automated
synthetic round-trip test plus a privacy-safe result record; private runtime
task content is never copied.

T33 begins only after at least 20 representative spawns across at least three
completed tasks have been captured. Include both harnesses when comparable
Claude metrics are available; otherwise record the unavailable Claude sample
as a limitation rather than delaying Codex-only measurement indefinitely.

After every PR, wait for human merge confirmation before starting a dependent
task.

## 15. Definition of Done

The standalone transition is complete when:

- all global acceptance criteria pass;
- Claude-compatible state fixtures pass in Codex;
- writer-claim collision and recovery tests pass;
- formal reviewers are fresh and read-only;
- security ordering is enforced;
- verification and PR evidence are HEAD-bound;
- every automatic PR attempt obeys the task-run allowance;
- observations and telemetry are emitted without private prompt capture;
- automatic learning promotion remains gated by the evaluation decision;
- existing safety hooks and High Risk evidence tests pass;
- documentation no longer describes Codex as a fallback contractor.
