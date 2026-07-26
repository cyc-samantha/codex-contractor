# Claude Harness Alignment Check

Purpose: Verify that the Claude harness can interoperate safely with the
standalone Codex harness defined by:

- `docs/STANDALONE-CODEX-HARNESS-SPEC.md`
- `docs/STANDALONE-CODEX-HARNESS-IMPLEMENTATION-PLAN.md`

This is an evidence-gathering and compatibility review task for the Claude
harness. Do not modify either harness during the check.

## 1. Required Outcome

Return:

```text
ALIGNED
```

only when every required contract is already compatible and supported by
evidence.

Otherwise return:

```text
CHANGES_REQUIRED

- Finding ID
- Severity
- Contract area
- Current Claude behavior
- Required change
- Evidence path
- Suggested owner
- Rollout order
```

Unknown or unevaluable behavior is `CHANGES_REQUIRED`, not assumed compatible.

## 2. Runtime SSOT

Verify:

1. `${HARNESS_DATA:-$HOME/.claude}` is the effective shared runtime root.
2. `${HARNESS_DATA}/pipeline-state/<task-id>/pipeline.md` is the overall
   pipeline SSOT.
3. New Claude tasks write the canonical per-task directory layout.
4. Legacy flat paths are read-only compatibility inputs.
5. `build-result.json` is the Build completion signal.
6. `verification-evidence.json` binds verification to Git HEAD.
7. Completed pipeline state and final evidence are retained.
8. Unknown versions and malformed required state fail closed.

Provide evidence paths for all readers, writers, schemas, and cleanup jobs.

## 3. Pipeline Writer Inventory

Inventory every Claude path that creates or mutates:

- `pipeline.md`;
- phase documents;
- `build-result.json`;
- `verification-evidence.json`;
- `trajectory.jsonl`;
- observations;
- scratchpads;
- completed-state cleanup.

For each writer report:

```text
Producer:
Entry point:
Canonical path helper used:
Atomic write:
Schema/version validation:
Failure behavior:
Evidence:
```

Flag direct path construction, dual writes, broad prefix deletion, and writes
that bypass canonical helpers.

## 4. Writer Claim Compatibility

Check whether Claude can implement and honor:

```text
${HARNESS_DATA}/pipeline-state/<task-id>/writer.lock/owner.json
```

Required behavior:

- atomic `mkdir(writer.lock)` acquisition;
- durable `owner.json`;
- one active writer per task;
- different tasks may have different writers concurrently;
- reviewers remain read-only and do not claim writer ownership;
- identity-safe heartbeat and release using task, owner, and session ID;
- malformed or incomplete claims fail closed;
- no automatic stale takeover;
- human-confirmed takeover;
- Git/worktree/HEAD/evidence/process reconciliation;
- displaced record archived in trajectory;
- successor installed with a new session ID;
- displaced owner cannot mutate successor ownership;
- intentional pause, handoff, terminal failure, or completed PR handoff
  releases ownership.

Identify every current use of `ACTIVE_HARNESS` and classify it as:

```text
advisory display
global write lock
handoff signal
other
```

Explain the migration needed to prevent the global baton from blocking
independent tasks or permitting same-task collisions.

## 5. Gear and Approval Alignment

Map current Claude routing to:

| Gear | Required behavior |
|---|---|
| Discuss | No code or PR |
| Small Change | Compact logged spec, plan-in-message, review, verify, PR |
| Build | Brainstorm, spec, approved plan, SE, review loop, E2E verify, PR |
| High Risk | Build plus security, rollback, and stronger evidence |

Verify:

- clear Small Change plans do not require duplicate approval;
- medium/large plans require explicit approval;
- material plan changes invalidate approval;
- risk elevation is recorded;
- automatic High Risk triggers cannot be silently downgraded;
- downgrade requires recorded human confirmation.

Provide the classifier, approval, and downgrade evidence paths.

## 6. Review Alignment

Verify formal code review is:

- performed by a fresh context;
- read-only;
- bound to actual task, repository, branch, and HEAD;
- independent from the builder;
- followed by fixes from the original engineer;
- followed by targeted re-review from the raising reviewer;
- invalidated when the reviewed target changes.

List any current self-review procedure that is treated as formal approval.
That behavior is incompatible even if a later optional reviewer sometimes
runs.

## 7. Security Ordering

Verify security-relevant tasks follow:

```text
build
-> security review
-> security fixes
-> targeted security re-review and sign-off
-> code review
-> code fixes and targeted re-review
-> renewed security review if sensitive surfaces changed
-> verification
```

Provide:

- security trigger source;
- sign-off representation;
- reviewed HEAD binding;
- invalidation behavior;
- downgrade behavior;
- tests for ordering and re-review.

Always-on destructive, secret, scope, branch, and sandbox controls are
separate from the conditional security-review phase.

## 8. Worktree and Repository Alignment

Verify Claude uses:

```text
<repository-root>/.claude/worktrees/<task-specific-name>
```

Check:

- repository root resolution;
- remote and base-branch resolution;
- missing/ambiguous remote behavior;
- `git worktree list --porcelain` validation;
- root checkout base-branch invariant;
- test-runner exclusion of `.claude/worktrees/`;
- no guessed repository or local directory creation.

## 9. Verification and PR Alignment

Verify:

- fresh verification is bound to the final reviewed HEAD;
- later changes invalidate review and verification;
- every implementation ends in a PR;
- the harness never merges automatically;
- one automatic PR creation attempt is allowed per task run;
- a changed HEAD does not reset the attempt allowance;
- another attempt requires recorded human authorization;
- a failed attempt stores branch, HEAD, base, title, body, and failure;
- failure returns copy-ready PR content and does not automatically retry;
- dependent work waits for human merge confirmation.

Identify the PR-attempt state producer and all PR creation entry points.

## 10. Retention and Garbage Collection

Verify completed pipeline state, decisions, findings, PR identity, and final
evidence are retained.

Inventory all cleanup hooks and scripts. For each, show:

- enumerated targets;
- path validation;
- prefix-neighbor protection;
- treatment of completed state;
- failure behavior.

Broad wildcard or prefix cleanup is incompatible.

## 11. Observation, Learning, and Token Telemetry

Verify Claude can emit comparable per-spawn events containing:

- task, phase, role, harness, model, and reasoning effort;
- input, cached-input, output, and learning-injection tokens;
- elapsed time, verdict, retry count, and reliable estimated cost;
- explicit `null` plus reason for unavailable provider metrics;
- method and provenance for estimates.

Confirm:

- full prompts, secrets, source, and private task content are excluded;
- observations are automatic and append-only;
- Codex observations are consumed symmetrically;
- candidate extraction can run in shadow mode;
- instinct promotion can remain disabled pending evaluation;
- telemetry failure cannot invent values or bypass delivery gates.

List every observation, learning, and telemetry producer.

## 12. Builder-Guardian Alignment

Determine whether Claude has an equivalent of the retained High Risk evidence
mode:

- immutable review target;
- approval bound to task, repository, run, and commit;
- read-only mutation detection;
- deterministic disposable-checkout verification;
- fail-closed final evidence.

Do not require role or implementation identity. Report behavioral overlap and
gaps. Confirm that this heavier evidence mode is not forced on normal Small
Change or Build tasks.

## 13. Required Compatibility Tests

Report existing tests or missing tests for:

- canonical and legacy state discovery;
- canonical writes and phase transitions;
- malformed/unknown state;
- two tasks with concurrent writers;
- same-task acquisition collision;
- crash between lock directory and owner record;
- identity-safe heartbeat and release;
- human-confirmed takeover;
- Build result and verification HEAD freshness;
- security-before-code-review ordering;
- review invalidation after fixes;
- one-attempt PR behavior;
- completed-state retention;
- observation and telemetry schemas.

Tests must use synthetic data and must not copy private runtime task content.

## 14. Final Compatibility Matrix

Return this table with evidence:

| Contract | Status | Evidence | Required change |
|---|---|---|---|
| Runtime SSOT | aligned/gap/unknown | path | action |
| Pipeline writers | aligned/gap/unknown | path | action |
| Writer claim | aligned/gap/unknown | path | action |
| Gear routing | aligned/gap/unknown | path | action |
| Human approvals | aligned/gap/unknown | path | action |
| Fresh review | aligned/gap/unknown | path | action |
| Security ordering | aligned/gap/unknown | path | action |
| Worktree safety | aligned/gap/unknown | path | action |
| Verification freshness | aligned/gap/unknown | path | action |
| PR policy | aligned/gap/unknown | path | action |
| State retention | aligned/gap/unknown | path | action |
| Learning/telemetry | aligned/gap/unknown | path | action |
| High Risk evidence | aligned/gap/unknown | path | action |

Plain `ALIGNED` is not valid if any row is `gap` or `unknown`. Unresolved work
must be versioned, assigned an owner, and ordered so neither harness writes an
incompatible state during migration.
