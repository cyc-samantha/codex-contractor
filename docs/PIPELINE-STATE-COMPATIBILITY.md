# Pipeline State Compatibility Matrix

Status: fixture contract for the standalone transition

This document records the versioned compatibility surface pinned by the
synthetic fixtures in `tests/fixtures/pipeline-state/`. It describes data that
future standalone state readers and writers must support. It does not claim
that those readers or writers are implemented.

## Compatibility policy

- Canonical task state lives at
  `${HARNESS_DATA}/pipeline-state/<task-id>/pipeline.md`.
- Canonical version 1 state is readable and is the only task-state format
  written by new standalone code.
- The legacy flat `pipeline.md` shape is a read-only migration input. New
  state must not be written in that shape.
- Every JSON evidence artifact in this matrix uses `schema_version: 1`.
- An unknown schema version, missing required identity, or otherwise
  unevaluable required state fails closed.
- Readers may retain fields they do not interpret. They must not silently
  reinterpret an unknown field as a required identity or verdict.

The terms in the tables have these meanings:

| Requirement | Meaning |
|---|---|
| Required | Version 1 readers reject the artifact when the field is absent or empty. |
| Optional | Readers accept the artifact without the field and preserve it when rewriting a containing record. |
| Legacy-only | Readers may translate the field from a supported legacy input; canonical writers never emit it. |

## Canonical `pipeline.md` version 1

Fixtures:
`canonical-active/pipeline.md` and `canonical-completed/pipeline.md`.

| Field | Requirement | Compatibility meaning |
|---|---|---|
| `schema_version` | Required | Must equal `1`; any other value fails closed. |
| `task_id` | Required | Stable task identity; must agree with the containing task directory. |
| `repository` | Required | Canonical repository identity used for task discovery and matching. |
| `phase` | Required | Current workflow phase. |
| `status` | Required | Lifecycle classification, including active versus completed state. |
| `verdict` | Required | Current gate or terminal result. |
| `branch` | Required | Task branch identity. |
| `worktree` | Required | Registered task worktree identity. |
| `updated_at` | Required | ISO-8601 timestamp of the latest state transition. |
| `updated_by` | Required | Harness that performed the latest transition: `claude` or `codex`. |
| `next_action` | Optional | Human-readable next-phase context; it is not an ownership claim. |

The active fixture pins `phase: build`, `status: in_progress`, and
`verdict: pending`. The completed fixture pins `phase: ship`,
`status: completed`, and `verdict: merged`. Readers must retain completed
state rather than treating it as disposable runtime scratch data.

## Supported legacy flat state

Fixture: `legacy-pipeline.md`.

The legacy fixture has no `schema_version`. Its recognition depends on its
legacy field names and path, not on assuming that an absent version means
canonical version 1.

| Legacy field | Requirement | Canonical interpretation |
|---|---|---|
| `task_id` | Required | `task_id` |
| `project_path` | Required | `repository` |
| `current_phase` | Required | `phase` |
| `status` | Required | `status`; legacy values require explicit translation by the future reader. |
| `branch` | Required | `branch` |
| `tier` | Legacy-only | Prior task-size metadata; retain as migration context without treating it as the standalone gear contract. |
| `created` | Legacy-only | Original creation timestamp; it does not substitute for canonical `updated_at`. |

The fixture does not provide canonical `verdict`, `worktree`, `updated_at`,
or `updated_by`. A future reader must represent those facts as unavailable
and must fail closed when a transition requires one of them. It must not
invent values. A future writer upgrades state only into the canonical
per-task path and never overwrites the legacy input in place.

## Build result version 1

Fixture: `build-result.json`.

| Field | Requirement | Compatibility meaning |
|---|---|---|
| `schema_version` | Required | Must equal `1`. |
| `agent_role` | Required | Identity of the producing role. |
| `base_sha` | Required | Git base used by the build. |
| `branch` | Required | Branch built by the producing role. |
| `generated_at` | Required | Artifact creation time. |
| `green` | Required | Whether the required build checks passed. |
| `head_sha` | Required | Immutable Git target produced by the build. |
| `tests_executed` | Required | Commands or test identities used as build evidence. |
| `unresolved` | Required | Outstanding build issues, including an empty list. |
| `verdict` | Required | Build-phase result. |

## Verification evidence version 1

Fixture: `verification-evidence.json`.

| Field | Requirement | Compatibility meaning |
|---|---|---|
| `schema_version` | Required | Must equal `1`. |
| `task_id` | Required | Task to which the evidence belongs. |
| `git_head` | Required | Exact reviewed Git HEAD that was verified. |
| `generated_at` | Required | Artifact creation time. |
| `verdict` | Required | Verification result. |
| `tier_results` | Required | Per-tier verification outcomes, including an empty list when valid for the task contract. |
| `sandbox_run` | Required | Whether verification ran in the required isolated environment. |

Verification evidence is fresh only when `git_head` equals the final reviewed
HEAD and the current task HEAD. A later change invalidates it.

## Observation version 1

Fixture: `observation.json`.

| Field | Requirement | Compatibility meaning |
|---|---|---|
| `schema_version` | Required | Must equal `1`. |
| `task_id` | Required | Task that produced the observation. |
| `timestamp` | Required | Observation creation time. |
| `source` | Required for Codex writes | `codex` for standalone Codex observations; older Claude records may omit it and are interpreted as Claude-authored. |
| `outcome` | Required | Result associated with the observation. |
| `observation` | Required | Privacy-safe learning statement. |
| `commit` | Optional | Git commit associated with the observation when one exists. |

Observation compatibility never permits copying private runtime task content
into repository fixtures.

## Unknown and malformed state

Fixture: `malformed-unknown-version/pipeline.md`.

`schema_version: 999` is intentionally unsupported. Its
`expected_verdict: FAIL_CLOSED` value is fixture metadata, not a canonical
pipeline field. Readers must reject this artifact without attempting to
interpret `unrecognized-phase` or `unevaluable` as supported values.

The same fail-closed rule applies when any required identity is absent,
empty, contradictory, or cannot be evaluated. The fixture audit currently
pins required identities for canonical state, Build results, verification
evidence, and observations. Later implementation tasks may strengthen
validation, but they must not weaken this baseline.

## Rollout rules

Any schema change requires:

1. an explicit new version;
2. synthetic fixtures containing no private task content;
3. a backward-compatible reader or a coordinated migration;
4. canonical-only writes at the per-task path;
5. tests proving unknown or malformed required state fails closed.

The implementation sequence is intentionally split: T01 documents this
matrix; T05-T07 add reading, validation, and atomic canonical writing.
