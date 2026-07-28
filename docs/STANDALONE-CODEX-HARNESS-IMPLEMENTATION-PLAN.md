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

### Target runtime responsibilities

The standalone runtime uses a lightweight coordinator, not a general
orchestration service. These are target contracts and must not be described as
active until their focused implementation tasks merge.

| Role | Responsibility | Write authority |
|---|---|---|
| Orchestrator | Intake, scope and boundary checks, planning, dispatch, state transitions, gate decisions, PR coordination | Coordination state, dispatch contracts, PR artifacts, and observation artifacts only; never source, tests, or migrations |
| Software Engineer | TDD implementation in the claimed worktree and every fix raised by review | Files allowed by the approved task contract |
| Code Reviewer | Fresh-context review of the approved contract, immutable target, diff, and evidence | Read-only |
| Security Reviewer | Fresh threat-focused review and required security sign-off | Read-only |
| Verifier | Deterministic execution of the approved verification contract against the final reviewed HEAD | Read-only except explicitly enumerated disposable test output |

The orchestrator routes findings back to the same Software Engineer identity
and session; it never fixes implementation findings itself. Any engineer
change invalidates affected approval and verification evidence. Re-review
returns to the same reviewer identity and session that raised the finding.

Each dispatch contract binds task ID, repository identity, branch, registered
worktree, base and target HEAD, allowed and prohibited paths, acceptance
criteria, required tests, risk classification, role, model, reasoning effort,
write authority, and a stable role identity and session ID. Review evidence
binds `software_engineer_id` and `software_engineer_session_id`; each finding
also binds `raising_reviewer_id` and `raising_reviewer_session_id`. Missing or
contradictory required fields fail closed.

### Target model and reasoning-effort policy

Emergency model-balance policy routes model and effort deterministically by
work type. This intentional allocation reduces routine task token consumption
while reserving the higher-capability model for complex engineering and system
design. Roles not named below retain their existing documented effort until a
later, versioned policy explicitly changes them.

This replaces the initial single-model-family rollout assumption. The
telemetry gate remains required before introducing any additional model route
or changing this allocation.

| Work type or role group | Model and reasoning effort |
|---|---|
| Simple wording, configuration, and small bug fixes | `gpt-5.6-Luna` |
| General feature development and test authoring | `gpt-5.6-terra` |
| Complex debugging, multi-file refactoring, Code Reviewer, Security Reviewer, and Orchestrator | `gpt-5.6-sol` with `medium` reasoning |
| System design and Architect (brainstorm, specification, and planning) | `gpt-5.6-sol` with `high` reasoning |

Reasoning effort is selected deterministically from role and gear, not chosen
ad hoc by the spawned agent:

| Base role and gear | Default reasoning effort |
|---|---|
| Orchestrator intake, routing, and state transitions | `medium` |
| Brainstorm, specification, and planning | `high` |
| Small Change Software Engineer | `medium` |
| Build Software Engineer | `high` |
| Code Reviewer | `medium` |
| Security Reviewer | `medium` |
| Deterministic Verifier | `low` |
| PR and observation artifact generation | `low` |

High Risk retains its review and verification gates, but does not override the
work-type model-and-effort allocation above.

Resolution precedence is exact: select the matching work-type allocation.
High Risk does not alter that allocation. No agent or fallback may silently
lower the resolved effort.

Model or effort unavailability follows a versioned deterministic fallback
table. Every fallback records requested and actual model and effort, reason,
and policy version. A gating reviewer, security reviewer, or verifier fails
closed when no pre-authorized equivalent at the required minimum is
available. A non-gating mechanical role may use only an explicitly
pre-authorized fallback; otherwise it also stops for human direction. Agents
cannot invent a fallback or enable multi-model routing themselves.

### Multi-role telemetry rollout gate

No multi-role execution or Software Engineer dispatch becomes active until
every spawn emits a minimal privacy-safe telemetry envelope. The envelope
records task and PR attribution when known, role, requested and actual model
and reasoning effort, input, cached-input, and output tokens, duration, and
review/retry cycle identity. An unavailable provider metric is recorded as
`null` with an explicit availability reason; it is never omitted or inferred.
The minimal layer aggregates each task/run and exposes a user-visible known
token total plus the explicit set of unknown token fields; unknown is never
treated as zero. When PR identity becomes available after earlier spawns, late
reconciliation attaches the task/run totals to that PR without rewriting raw
spawn events. The gate requires actual values or explicit unavailability for
every required field, so rollout cannot create a blind-cost window.

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

### AC-13: Separated orchestration

The orchestrator cannot write source, tests, or migrations. It may write only
enumerated coordination, dispatch, PR, and observation artifacts. The
Software Engineer owns implementation and all reviewer fixes; formal
reviewers and the verifier remain fresh/read-only as specified.

### AC-14: Deterministic role execution policy

Role and gear resolve deterministically to model family, reasoning effort,
permissions, and fallback behavior. Gating roles fail closed when their
required execution profile is unavailable. Requested and actual execution
profiles are captured without enabling multi-model routing. Multi-role
execution remains disabled until every spawn satisfies the minimal telemetry
envelope.

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

## 8. Slice 5: Lightweight Orchestrator and Agent Workflow

### Objective

Separate coordination from engineering, then implement the required Software
Engineer and fresh reviewer loop without a large role team.

### Work

1. Define minimal role contracts for:
   - orchestrator;
   - Software Engineer;
   - code reviewer;
   - security reviewer;
   - verifier.
2. Define a versioned dispatch contract that binds scope, identity, Git
   target, risk, verification, role, execution profile, and permissions.
3. Enforce the orchestrator protected-write boundary while allowing only
   enumerated coordination, dispatch, PR, and observation artifacts.
4. Emit the minimal telemetry envelope for every spawn, aggregate task/run
   known totals and unknown fields, and support late PR-ID reconciliation
   before enabling multi-role execution.
5. Resolve model, reasoning effort, permissions, and fallback behavior from a
   deterministic role-and-gear policy.
6. Use the documented work-type model allocation; do not introduce further
   model routes until telemetry supports a later change.
7. Dispatch the Software Engineer into the claimed task worktree.
8. Dispatch reviewers with read-only permission and fresh context.
9. Bind review input to actual task, branch, and HEAD.
10. Bind review evidence and findings to stable engineer and reviewer identity
   and session IDs.
11. Return findings to the exact `software_engineer_id` and
    `software_engineer_session_id` in the same worktree.
12. Route targeted re-review to the exact `raising_reviewer_id` and
    `raising_reviewer_session_id`.
13. Invalidate approvals when the reviewed HEAD changes.
14. Dispatch deterministic verification read-only against the approved HEAD.
15. Capture requested and actual execution profile, result, and identity in
    trajectory state.

### Candidate files

```text
.codex/agents/orchestrator.toml
.codex/agents/software-engineer.toml
.codex/agents/code-reviewer.toml
.codex/agents/security-reviewer.toml
.codex/agents/verifier.toml
.agents/skills/harness-pipeline/SKILL.md
scripts/lib/dispatch_contract.py
scripts/lib/execution_policy.py
scripts/lib/review_evidence.py
tests/test_dispatch_contract.py
tests/test_execution_policy.py
tests/test_review_evidence.py
```

Confirm the current Codex role-configuration surface before committing to the
TOML paths. Prefer native subagents plus small role instructions over a custom
process orchestrator.

### Verification

- Orchestrator writes to source, tests, and migrations are blocked.
- Enumerated coordination artifacts remain writable by the orchestrator.
- Incomplete or contradictory dispatch contracts fail closed.
- Multi-role dispatch remains disabled when any spawn cannot emit actual or
  explicitly unavailable minimal telemetry.
- Task/run output shows a known token total and every unknown field; late PR
  reconciliation makes the same totals attributable to the PR.
- Role and gear produce the documented effort and permission profile.
- An unavailable gating execution profile fails closed rather than silently
  lowering effort or changing model family.
- Software Engineer identity cannot produce an accepted formal review.
- Reviewer execution cannot modify the repository.
- Findings bind to task, reviewed HEAD, exact Software Engineer identity and
  session, and exact raising reviewer identity and session.
- The bound Software Engineer instance fixes findings; a fix invalidates prior
  approval and triggers targeted re-review by the bound raising reviewer
  instance.
- Engineer, reviewer, and targeted re-review spawns cannot activate until
  their shared-envelope tests prove actual provider token values or
  `null` with an explicit reason.
- Verifier execution is deterministic and cannot modify tracked files.
- Verifier spawns cannot activate until their shared-envelope tests prove
  actual provider token values or `null` with an explicit reason.

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
6. Require the shared minimal telemetry envelope before activating security
   reviewer or security re-review spawns.

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
- Security review and re-review spawns prove actual provider token values or
  `null` with an explicit reason before the role activates.

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

Enrich the mandatory minimal spawn envelope with role/effort breakdowns and
quality analysis, and establish the evaluation framework without enabling
automatic promotion.

### Work

1. Extend the versioned minimal spawn event without weakening its required
   fields or null-with-reason behavior.
2. Add gear, policy version, fallback reason, verdict, review finding count,
   retry count, and injected-learning tokens.
3. Break down reconciled PR totals by role and reasoning effort.
4. Add learning attribution without storing prompt or task content.
5. Mark estimates with method and provenance.
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
- Quality and finding-rate differences by role and reasoning effort.
- Whether an approved effort fallback changes verdict, findings, or retries.
- Whether evidence supports introducing any multi-model route.
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

### T18B task card: native Codex LLM-mutant adapter

Replace the verification workflow's Claude-specific Tier 3.5 call with one
fresh, read-only Codex execution. The adapter accepts the immutable reviewed
HEAD diff, the latest rule-based mutation survivor list, and the five approved
semantic mutation categories. It returns at most ten schema-validated mutants
without editing the repository.

The implementation must:

- use a fresh context with a versioned dispatch contract and a non-engineer
  role, role identity, session ID, run ID, and telemetry event ID that cannot
  match the Software Engineer identity or session;
- run tool-free, network-free, and without repository or user-secret
  filesystem access; provide only the bounded diff and survivor payload, mark
  both as untrusted inert data, and prohibit following instructions found in
  source text, comments, filenames, or survivor descriptions;
- run read-only with one call, no automatic retry, and versioned fail-closed
  caps: at most 200 KiB of canonical diff input, 100 survivor records, 4 KiB
  per survivor record, 64 KiB for the complete survivor payload, 8,000 output
  tokens, 64 KiB of accepted output, and 120 seconds wall time;
- independently reconstruct the canonical diff from the bound repository
  identity, base HEAD, and reviewed target HEAD before dispatch; record and
  verify its digest instead of trusting a caller-supplied diff;
- bind every mutant to the task, reviewed Git HEAD, file, line range, original
  text, mutated text, category, rationale, equivalence verdict, producer role,
  producer identity and session, dispatch run, and telemetry event;
- reject malformed output, mismatched source text, paths outside the reviewed
  diff, unsupported mutation categories, oversized fields, control characters,
  instruction-like output outside the schema, and any identity, repository,
  base/target HEAD, digest, dispatch, or telemetry mismatch;
- preserve the existing `SKIP` result when the execution profile is
  unavailable or the single call returns no valid non-equivalent mutants;
- emit the shared minimal spawn telemetry envelope, including requested and
  actual model and reasoning effort, tokens or null-with-reason, duration, and
  retry-cycle identity;
- keep activation disabled until T13B and T13C have merged and the adapter's
  telemetry contract tests pass; activation additionally requires a runtime
  canary proving that the correlated telemetry event was durably persisted
  before the adapter result can be accepted.

Acceptance criteria:

1. No verification instruction requires a Claude runtime.
2. The write-capable Software Engineer cannot supply or approve Tier 3.5
   mutants; producer, dispatch, session, run, and telemetry identities prove a
   distinct non-engineer execution.
3. One invocation produces no more than ten schema-valid mutants and never
   retries automatically; every input, output, token, and duration cap has a
   passing boundary test.
4. Missing telemetry, contradictory identity or HEAD fields, repository
   writes, tool or network access, prompt-injection attempts, stale or
   substituted diffs, and malformed mutant output fail closed.
5. Unavailable execution records `SKIP` with an explicit reason rather than
   fabricating mutants or token values.
6. Activation remains mechanically disabled before the T13B/T13C rollout
   prerequisites and the correlated runtime telemetry canary are satisfied.

Candidate files:

```text
.agents/skills/harness-verify/SKILL.md
scripts/lib/llm_mutant_adapter.py
scripts/lib/spawn_telemetry.py
tests/test_llm_mutant_adapter.py
tests/test_spawn_telemetry.py
```

This plan-only governance change does not implement a runtime capability and
does not consume a capability task ID. T00 is complete. After this governance
PR is human-confirmed merged, T01 remains the next capability task.

### Logged delivery blocker: PR quality-gate helper resolution

The current `harness-pr-creation` gate wrappers resolve shared helpers beneath
the nonexistent repository-local `.agents/hooks/_lib/` path, rather than the
Claude-side `$HARNESS_ROOT/hooks/_lib/` install. The resulting missing helper
functions make the quality-gate wrapper fail closed before a PR can be created.

The next independent PR must correct the helper-resolution contract and add
regression coverage that executes the wrappers from their shipped
`.agents/skills/harness-pr-creation/lib/` location. It must not bypass the
quality gate or weaken its fail-closed behavior.

| Task | Status | One-PR outcome | Depends on |
|---|---|---|---|
| T00 | Complete | Add synthetic state fixtures and pin the existing test baseline | none |
| T01 | Complete | Document the versioned pipeline compatibility matrix | T00 |
| T02 | Complete | Document the proposed standalone transition without claiming it is active | T01 |
| T03 | Complete | Add Discuss/Small Change/Build routing plus manual High Risk elevation | T01 |
| T04 | Complete | Add Small Change compact-spec and approval behavior | T03 |
| T05 | Complete | Read canonical pipeline paths and supported legacy paths | T01 |
| T06 | Complete | Validate pipeline identity, versions, and required fields | T05 |
| T07 | Planned | Write canonical pipeline state atomically | T06 |
| T08 | Planned | Discover repository-matching tasks read-only | T07 |
| T09 | Planned | Add human-confirmed new-task and resume selection | T08 |
| T10 | Planned | Acquire one atomic writer claim per task | T07 |
| T11 | Planned | Add identity-safe claim heartbeat and release | T10 |
| T12 | Planned | Add human-confirmed claim takeover and trajectory archive | T11 |
| T13 | Planned | Define versioned role dispatch contracts with stable engineer and reviewer instance identities | T09, T11 |
| T13A | Planned | Enforce the orchestrator protected-write boundary and coordination-artifact allowlist | T13 |
| T13B | Planned | Emit the shared minimal envelope, aggregate task/run known totals plus unknown fields, and reconcile late PR identity | T13 |
| T13C | Planned | Add deterministic work-type model-effort allocation and fail-closed fallback handling | T13, T13B |
| T13D | Planned | Dispatch the Software Engineer only after its shared envelope proves actual provider tokens or null-with-reason | T13A, T13B, T13C |
| T14 | Planned | Add fresh read-only code review bound to task and HEAD with required shared-envelope coverage | T13D, T13B |
| T15 | Planned | Return findings to the bound engineer and targeted re-review to the bound raising reviewer, with shared-envelope coverage for each spawn | T14, T13B |
| T16 | Planned | Add automatic High Risk triggers and human-authorized downgrade enforcement | T04 |
| T17 | Planned | Add security-first review, re-review, sign-off, invalidation, and required shared-envelope coverage | T13B, T15, T16 |
| T18 | Planned | Write verification evidence bound to reviewed HEAD | T15 |
| T18A | Planned | Dispatch the deterministic verifier read-only only after its shared envelope proves actual provider tokens or null-with-reason | T13B, T13C, T18 |
| T18B | Planned | Replace the Claude-specific Tier 3.5 call with a fresh read-only Codex LLM-mutant adapter, activated only after telemetry gates pass | T13B, T13C, T18 |
| T19 | Planned | Derive and run task-appropriate final verification commands | T18A |
| T20 | Planned | Add one-attempt PR state and existing-PR reconciliation | T19 |
| T21 | Planned | Attempt PR creation once and preserve manual handoff on failure | T20 |
| T22 | Planned | Enrich reconciled telemetry with verdict, findings, retries, learning attribution, and quality breakdowns by role/effort | T13B, T13D |
| T23 | Planned | Append observations automatically without promoting instincts | T22 |
| T24 | Planned | Add the token/learning/model-effort evaluation framework and report template over enriched PR aggregates | T22, T23 |
| T25 | Planned | Reuse shared evidence types in Builder-Guardian | T17, T19 |
| T26 | Planned | Route High Risk tasks to optional immutable evidence mode | T25 |
| T27 | Planned | Constrain garbage collection to disposable task artifacts | T07 |
| T28 | Planned | Add migration warnings and legacy-baton compatibility behavior | T21, T26 |
| T29 | Planned | Document installation, runtime operation, and recovery | T28 |
| T30 | Planned | Remove stale fallback-era references after a repository-wide audit | T29 |
| T31 | Planned | Add an automated synthetic cross-harness round-trip test and privacy-safe result | T30, Claude alignment complete |
| T32 | Planned | Remove final fallback identity and declare standalone behavior active | T12, T21, T23, T24, T27, T30, T31 |
| T33 | Planned | Publish the first evidence-based token/learning/model-effort evaluation | T24, evaluation sample met |

Each task gets its own:

- task ID and canonical `pipeline.md`;
- compact or full approved plan;
- branch and registered worktree;
- single writer claim;
- fresh review;
- fresh verification;
- PR attempt and retained evidence.

### Emergency delivery bootstrap

The current PR-delivery blocker requires a minimal canonical task bootstrap in
the same PR as the gate repair: before implementation starts, intake must
create a new task directory atomically, write the version-1 `pipeline.md`, and
propagate `CLAUDE_PIPELINE_TASK_ID` to verification and PR commands. Existing
task state is never overwritten; a collision fails closed pending the planned
human-confirmed resume flow.

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
