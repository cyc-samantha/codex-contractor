---
name: "code-review"
description: "Run formal review through a fresh read-only collaboration reviewer Agent using a model distinct from the Builder."
context: fork
---

# Fresh Code Review

## What This Skill Does

Formal review runs in a fresh read-only collaboration reviewer Agent.
Builder self-review does not satisfy the formal review gate. The reviewer receives an
immutable Git target and may inspect it, but must not edit files, commit, push,
or mutate task state.

Use `collaboration.spawn_agent` from the Builder session. Default to
`gpt-5.6-sol` with `medium` reasoning when that is a different model from the
Builder. The reviewer must use a different model from the Builder. Otherwise select another available model. If no different model is
available, fail closed. Do not launch an additional `codex exec review` subprocess for this gate.

## Current Context

- Branch: !`git branch --show-current`
- Changed files: !`git diff main...HEAD --name-only 2>/dev/null || echo 'N/A'`
- Diff stats: !`git diff main...HEAD --stat 2>/dev/null || echo 'N/A'`

## Review Focus

The build step already passed: shape hooks (blocking), type/lint checks,
and the full test suite. Do not re-verify those — focus on what requires
judgment:

- Design decisions and abstractions
- Naming clarity and intent
- DRY/SOLID at the design level (not line counting)
- Edge cases and untested scenarios
- Integration with the broader codebase

If a shape violation still made it into the diff, that is a hook gap, not
a code finding — note it and move on; do not treat it as your own review
finding.

## When to Run

- After the build/fix work is functionally complete (tests green, shape
  constraints met), before writing `Done (verified)` into a `HANDOFF.md`
  or otherwise declaring the work finished.
- After every engineer fix that changes the reviewed Git target.
- Security review still runs first when the task touches a sensitive surface.

## Process

### 1. Bind the Review Target

```bash
REVIEW_TARGET="$(git rev-parse HEAD)"
test -z "$(git status --porcelain)"
git diff origin/main..."$REVIEW_TARGET" --stat
```

The worktree must be clean. A dirty or moving target fails closed.

### 2. Spawn the Reviewer

Call `collaboration.spawn_agent` with:

- `fork_turns: "none"` so the reviewer receives no Builder conversation
  context;
- `model: "gpt-5.6-sol"` and `reasoning_effort: "medium"` when Sol is
  different from the Builder;
- another available model when the Builder uses Sol;
- a task message that binds `REVIEW_TARGET`, names the repository and
  acceptance criteria, requires read-only behavior, and requests severity,
  file, and line for every finding.

Do not spawn until a distinct model is resolved. Do not treat a different
reasoning effort on the same model as model separation.

### 3. Enforce Read-Only Return

After the reviewer returns, confirm `HEAD` still equals `REVIEW_TARGET` and the
worktree is still clean. Any mutation or unevaluable state invalidates the
review and fails closed.

```bash
test "$(git rev-parse HEAD)" = "$REVIEW_TARGET"
test -z "$(git status --porcelain)"
```

### 4. Act on Findings

- **APPROVE with no CRITICAL/HIGH/MEDIUM findings**: proceed to fresh
  verification bound to `REVIEW_TARGET`.
- **Any CRITICAL/HIGH/MEDIUM findings**: Return findings to the original engineer.
  After the engineer commits the fix, run targeted re-review with the raising reviewer against the new immutable target.

## Review Checklist

Shape measurements are enforced by build hooks. Only flag a measurement
if it EXCEEDS limits despite the hooks — that indicates a hook gap, and
the finding severity is "process" (fix the hook, not just the code).

- [ ] Shape constraints met (AGENTS.md § Code Shape Rules)
- [ ] No DRY violations (duplicated logic)
- [ ] SRP: each class/module has one reason to change
- [ ] Tests are meaningful (not just coverage padding)
- [ ] No TODO/FIXME without linked ticket
- [ ] Error handling follows guard clause pattern
- [ ] No hardcoded values (extract to constants)

## Severity Grading

| Severity | Definition | Examples | Blocks? |
|----------|-----------|----------|---------|
| CRITICAL | Security vulnerability or data loss risk | SQL injection, exposed secrets, auth bypass | Yes |
| HIGH | Correctness bug or significant design flaw | Missing error handling, broken invariant, SOLID violation | Yes |
| MEDIUM | Code quality issue causing maintenance pain | DRY violation across files, unclear naming, missing edge case test, unnecessary coupling | Yes |
| LOW | Minor improvement or style preference | Variable rename suggestion, comment improvement | No |
| INFO | Observation, context, or positive feedback | "Nice pattern," "FYI this also handles X" | No |

**Verdict rule:** APPROVE if no CRITICAL, HIGH, or MEDIUM findings.
CHANGES_REQUESTED (fix-it-yourself) if any exist. LOW and INFO are noted
but do not block.

**In-cycle enforcement:** CHANGES_REQUESTED findings return to the original
engineer and are fixed in the same task, never deferred or shipped
known-broken. The raising reviewer performs targeted re-review.

## Preventability Classification (Backward Feedback)

For each finding, classify whether it could have been prevented at
write-time:

| Classification | Criteria | Example |
|---|---|---|
| **Preventable** | Standard pattern violation the build step should have caught | Missing input validation, SOLID violation, naming issue |
| **Review-level** | Requires cross-cutting perspective a fresh read surfaces | Architectural concern, subtle race condition, design inconsistency |

Tag each finding with `preventable: true/false`. The Claude side's
`/harness:learn` uses this to create instincts that prevent the same
findings earlier next time.

## Phase Output

```
Verdict: APPROVE / CHANGES_REQUESTED
Next: If APPROVE → proceed (verify/ship/handoff)
      If CHANGES_REQUESTED → original engineer fixes, raising reviewer re-reviews
Findings: [list of specific findings with severity and preventability]
Review target: [immutable Git SHA]
Reviewer model: [must differ from Builder model]
```

### Context for Next Step

Record a `## Context for Fix/Verify` note (in `HANDOFF.md` or the
pipeline-state file, whichever applies) so the next reader — you in a
later session, or Claude on the next shift — has this:

```markdown
## Context for Fix/Verify
- **Finding context**: [for each finding: not just "fix X" but "fix X because Y, consider approach Z"]
- **Areas of strength**: [what the diff did well — reinforces good patterns]
```
