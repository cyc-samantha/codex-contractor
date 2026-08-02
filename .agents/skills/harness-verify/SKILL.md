---
name: "verify"
description: "Use when user wants to Structured verification workflow: contract tests, smoke tests, mutation testing."
context: fork
verdict: VERIFIED|VERIFIED_WITH_SKIP|UNVERIFIED|E2E_SKIP_NO_ENV
---

# Verification Workflow

## Current Context
- Branch: !`git branch --show-current`
- Changed files: !`git diff main...HEAD --name-only 2>/dev/null || echo 'N/A'`
- Diff stats: !`git diff main...HEAD --stat 2>/dev/null || echo 'N/A'`

## What This Skill Does

Proves a feature works correctly beyond just passing tests. Runs three verification tiers and produces a verdict.

## Inputs

| Input | Source |
|-------|--------|
| Candidate diff | `git diff main...HEAD` over the build worktree (full unified diff). |
| Build state | `$state_dir/{task-id}/build.md` § Sandbox Verify section produced by Build phase Step 5b. |
| Worktree HEAD | `git -C "$CLAUDE_WORKTREE_PATH" rev-parse HEAD` — written into the new `verification-evidence.json` so downstream gates can compare. |

The verify skill writes `$state_dir/{task-id}/verification-evidence.json` (see Step 6 below) for the downstream freshness guard.

## Verification Tiers

| Feature Type | Tier 1 (Contract) | Tier 2 (Smoke) | Tier 3 (Rule-Based Mutation) | Tier 3.5 (LLM-Mutant) | Tier 4 (E2E) | Tier 5 (External Oracle) |
|-------------|-------------------|----------------|------------------------------|------------------------|--------------|--------------------------|
| Backend API | Hit real endpoint, verify response shape | curl + DB state check + log check | Mutate handler logic | ≥60% kill rate | N/A | Reference impl / spec server diff (if available) |
| Frontend | Props match API response shape | Playwright/browser screenshot | Mutate component logic | ≥60% kill rate | N/A | N/A (typically no oracle) |
| Mobile/WebView | Hook/service contract tests | Component render + prop verification | Mutation testing on lib/ business logic | ≥60% kill rate | Maestro (mobile) AND/OR Playwright/Cypress (web) — multi-target dispatch per `protocols/e2e-protocol.md` | N/A |
| Web (browser) | API contract tests against real endpoint | Curl + DOM snapshot + log check | Mutate handler/component logic | ≥60% kill rate | Playwright/Cypress against a **local** `docker-compose.e2e.yml` stack spun up by `/harness:verify` and torn down after (conditional per `protocols/e2e-protocol.md` — local-only, no cloud) | N/A |
| Database | Schema constraint tests | Migrate up+down, verify integrity | N/A | N/A | N/A | Compare SQL execution result against upstream engine (e.g. PostgreSQL `psql`) on identical inputs |
| Infrastructure | Health endpoint responds | Readiness probe passes | N/A | N/A | N/A | N/A |
| Parser / Compiler / Codegen | AST shape matches grammar | Round-trip parse → emit → parse | Mutate production/precedence logic | ≥60% kill rate | N/A | Differential test vs reference (e.g. GCC, official parser, ANTLR-generated parser) |
| JSON / Schema-bound payload | Field-presence tests | Real consumer parses output | Mutate validator logic | ≥60% kill rate | N/A | `ajv` / `jsonschema` / language-native validator diff |

## Process

### Parallel Tier Execution

Where tiers are independent, run them in parallel:
- Tier 1 (Contract) and Tier 2 (Smoke) can often run simultaneously
- Tier 3 (Mutation) depends on test results from Tier 1/2, so runs after
- Tier 4 (E2E) is independent of Tier 3 and can run in parallel with it
- Use parallel Bash calls for independent tiers where the tool surface allows it; otherwise run tiers sequentially in this same session — there is no separate agent to spawn per tier

### 1. Identify Feature Type

Detect from changed files: API routes → Backend API, components → Frontend, hooks/lib → Mobile/WebView, migrations → Database, Dockerfile/CI → Infrastructure.

Read the project's tech stack pattern file if one exists at `.agents/skills/harness-[stack]-patterns/SKILL.md` for tech-specific verification strategies.

### 2. Run Tier 1: Contract Tests

- Test real boundaries (API responses, database constraints, service contracts)
- Verify response shapes match expected contracts
- For APIs: actual HTTP requests, not mocked responses

### 3. Run Tier 2: Smoke Tests

- Exercise the feature end-to-end in the real environment
- Verify side effects: database state changes, log entries, events emitted
- For UI: capture screenshots of key states

**Regression run — full-suite requirement (MANDATORY):**

Run the full test suite without early-exit flags. The following flags are **FORBIDDEN** on the Tier-2 regression run:

| Runner | Forbidden flag(s) |
|--------|-------------------|
| pytest | `-x`, `--exitfirst` |
| jest | `--bail` (any value) |
| rspec | `--fail-fast` |
| mocha | `--bail` |
| go test | *(no equivalent, but do not pipe through `head` or similar)* |

**Why**: stopping at the first failure masks contamination elsewhere in the suite. On 2026-06-03, a verifier ran `pytest tests/ -x` at repo root; it halted at the first alphabetical test failure, so the "main is clean" claim covered ~5% of the suite and an uncommitted mutant went undetected for ~2 hours. A single failure does not tell you the suite is otherwise clean.

**Required instead**: run the full suite, collect the complete set of failing test IDs, and compare that set against the baseline passing set. Report:
- `failing_now` — set of test IDs that fail on the candidate
- `failing_baseline` — set of test IDs that fail on `main` (or the pinned baseline commit)
- `regressions` = `failing_now − failing_baseline` — these are the Tier-2 signal; any non-empty set → Tier 2 FAIL
- `fixed` = `failing_baseline − failing_now` — informational only; never masks a regression

Do NOT report only an exit code or only the first failure. The full diff of failing-ID sets is the authoritative signal.

### 4. Run Tier 3: Mutation Testing (HARD GATE — >= 70% kill rate)

> **Read-only note.** Tier 3 at verify is **read-only measuring** only. The active, time-boxed Mutation Kill Loop ran at Build (atdd-procedure.md step 4 Mutation Kill Loop); because the loop runs at Build before the Final Gate fans out, no mid-gate commits occur and the `verification-evidence.json` git_head freshness contract is intact. Verify MUST NOT write tests or commit. If kill rate is below 70% here, the slice returns to Build (UNVERIFIED) — the fix loop runs there, not here.

> **Tier 3 is a HARD GATE.** Kill rate >= 70% on changed lines is required for VERIFIED. Below threshold means UNVERIFIED — the slice returns to Build with the surviving-mutation list as targeted test gaps. Patch-critic also reads this report; a failing mutation gate is a deal-breaker for PATCH_APPROVED.

**Check tool availability first:**
- JavaScript/TypeScript: `which npx && npx stryker --version` (Stryker)
- Ruby: `bundle show mutant` (Mutant)
- Python: `which mutmut` (mutmut)

**If mutation testing tool is available:** run it on changed lines only (not the full file). Compute kill rate = killed / (killed + survived). Report the surviving-mutation list verbatim. Score < 70% → Tier 3 FAIL → UNVERIFIED.

**If mutation testing tool is NOT installed (manual fallback, still gated):**
1. For every conditional in the changed lines, mentally swap the condition (`>` → `<=`, `&&` → `||`, boundary off-by-one).
2. For each mutation, identify the test that catches it. If none, the mutation survives.
3. Compute kill rate = caught / total mutations checked. Score < 70% → Tier 3 FAIL → UNVERIFIED.
4. Report manual-fallback methodology, total mutations checked, and surviving-mutation list.

The manual fallback is approved as a gate-passing methodology — but the >= 70% threshold still applies. "Tooling unavailable" is not an exemption from the gate.

### 4.25. Run Tier 3.5: LLM-Mutant Pass (HARD GATE — ≥60% kill rate)

> **Tier 3.5 is ADDITIVE to Tier 3, NOT a replacement.** Tier 3 retains its ≥70% rule-based mutation gate. Tier 3.5 layers a Codex-driven semantic-mutant pass on top: rule-based catches operator-shape bugs (5x cheaper); LLM-based catches intent-shape bugs (Wang et al.'s 46.3 pp lift on fault detection). Both gates must pass for VERIFIED. Iron Law 1's 70% mutation requirement on changed lines refers to Tier 3 — Tier 3.5 ships its own per-tier gate at 60%.

**Prerequisite**: Tier 3 has produced a mutation report. Read the **latest Kill-Loop round's** survivor list to dedup (the `### Kill-Loop Round N` section with the highest N, if any Kill-Loop rounds exist; fall back to the Tier-3 baseline only when no Kill-Loop rounds are present) — Tier 3.5 does not re-propose mutations the latest Kill-Loop round already covered. Deduping against the stale Tier-3 baseline when Kill-Loop rounds exist would (a) miss mutants the loop did not kill, and (b) re-propose mutants the loop already killed.

**Operator categories (5 fixed, no others):**
- `off-by-one` — boundary mutations (`<` ↔ `<=`, `i + 1` ↔ `i`, range/slice endpoints).
- `wrong-comparator` — comparator swaps (`==` ↔ `!=`, `>` ↔ `<`, `&&` ↔ `||`).
- `swapped-args` — same-typed arguments transposed at call sites.
- `null-vs-empty` — `null`/`undefined`/`None` ↔ empty collection (`[]`, `""`, `{}`).
- `async-without-await` — dropped `await` on a Promise/Future, dropped `.catch`/error path on async work.

**Mutant generation (ONE read-only Codex adapter call per slice — NO retry):**

1. Invoke `scripts/lib/llm_mutant_adapter.py` through one fresh, tool-free, network-free Codex runtime with the changed-line diff, the 5 operator categories above, and the **latest Kill-Loop round's** survivor list (for dedup — or the Tier-3 baseline if no Kill-Loop rounds exist). Request 5–10 mutants — fewer is acceptable; the strict schema rejects more than 10. The adapter reconstructs and digests the canonical diff from the bound repository identity and reviewed HEAD; caller-supplied diff text is untrusted and must match the reconstructed digest.
2. Each mutant in the response carries the schema:
   ```
   {
     file:        <relative path>,
     line_range:  <"start-end" or "line">,
     original:    <verbatim source snippet>,
     mutated:     <verbatim mutated snippet>,
     category:    <one of the 5 above>,
     rationale:   <why this is a plausible bug>,
     equivalent:  <yes | no | unsure>
   }
   ```
3. **Equivalence filter**: drop any mutant with `equivalent: yes` from the kill-rate denominator. `unsure` defaults to inclusion (conservative — counts against kill rate unless killed). `equivalent: yes` requires a one-line rationale; code-reviewer + patch-critic spot-check.
4. **Cost guardrail**: ONE call per slice, max 10 mutants per response. NO retry. If the call times out, returns malformed output (parse failure), or returns zero non-equivalent mutants → Tier 3.5 = **SKIP** with documented reason → composite verdict becomes **VERIFIED_WITH_SKIP**. Product-reviewer must acknowledge the skip in the Accept phase.

**Per-mutant apply-test-revert loop:**

1. Apply the mutant in a scratch worktree (`git stash` snapshot or temporary branch — NEVER in-place edits to the active worktree).
2. Run the test suite.
3. **Killed**: a test fails on the mutated code (the mutation was caught).
4. **Survived**: the suite stays green on the mutated code (the mutation slipped past tests).
5. **Timed-out**: treat as **killed** (Stryker semantics — runaway tests indicate the mutation broke a tight loop).
6. Revert the mutant before applying the next one.

**Per-tier gate:**
```
kill_rate = killed / (killed + survived)
```
where the denominator excludes `equivalent: yes` mutants. **kill_rate ≥ 0.60 required.** Below threshold → Tier 3.5 = **FAIL** → composite verdict becomes **UNVERIFIED**, slice returns to Build with the surviving-mutant list as targeted test gaps.

**Audit-trail invariant**: Tier 3.5 results **APPEND to the existing mutation report**, placed **below any Kill-Loop rounds** (i.e., after the last `### Kill-Loop Round N` section written by the Build-phase Mutation Kill Loop, as defined in `atdd-procedure.md` step 4). They do NOT generate a new report file. The audit-trail count locked by `protocols/atdd-procedure.md` (3 artifacts: batched RED, GREEN, mutation-report) is preserved. Do NOT append between the Tier-3 baseline and the Kill-Loop rounds — that would interleave Build-phase and Final-Gate content in the same artifact.

**Call-shape discipline**: ONE call, NO retry, max-N items per response, JSON schema, parse-failure → silent skip. This is the same discipline applied anywhere else in this harness that renders a bounded LLM-judged batch (e.g. the SAST triage loop in `$harness-security-review` § 0.3) — keep it consistent if you extend this section.

**Citations:**
- arXiv 2406.09843 (Wang et al., 2024) — LLM-generated mutants achieve 87.98% fault detection vs 41.64% rule-based (46.3 pp lift) on a comprehensive benchmark; motivates Tier 3.5 as additive to Tier 3.
- arXiv 2404.09952 (LLMorpheus, 2024) — measured ~18.2% structurally equivalent / near-equivalent mutant rate (8.5% equivalent + 9.7% near-equivalent), capping achievable kill rate at ~80–82% for LLM-mutant suites; motivates the 60% per-tier gate (headroom for tooling variance below the structural ceiling).

### 4.5. Run Tier 4: E2E Tests (Conditional, multi-target)

Tier 4 can run in parallel with Tier 3 (they are independent). Multi-target: mobile (Maestro) and web (Playwright / Cypress) dispatch independently per `protocols/e2e-protocol.md`. Both can fire on the same change.

1. **Detect targets** via `hooks/_lib/e2e_target_resolver.py`:

   ```python
   from e2e_target_resolver import detect_targets, select_web_driver, \
       coerce_web_status_for_flake, compose_verdict
   firing = detect_targets(changed_files, project_root)
   # → {"mobile": "FIRED"|"N/A", "web": "FIRED"|"N/A"}
   ```

   - Mobile fires when: changed file matches a mobile glob AND `maestro/` directory exists.
   - Web fires when: changed file matches a web glob AND (`playwright.config.{ts,js}` OR `cypress.config.{ts,js}` is present).
   - Both matchers run independently — no short-circuit.

2. **For each fired target, execute its suite** per the protocol's per-target Execution section.

   - **Mobile** (Maestro): Check prerequisites (CLI, simulator, dev build, credentials). If unmet → mobile status = SKIP. Else select flows via the flow-to-file mapping (always include `app-launch.yaml`), execute, retry once on failure.
   - **Web** (Playwright/Cypress): Resolve driver via `select_web_driver(project_root)` — when both configs are present, prefer Playwright and emit the warning verbatim into the report. Check prerequisites (driver installed). Then run the **Local E2E Stack Lifecycle** below to bring up the project's `docker-compose.e2e.yml`. If the compose file is missing OR `docker info` fails → web status = SKIP. Else execute the suite against the resolved `baseURL`, then tear the stack down (in a trap so teardown runs on failure too).

   **Local E2E Stack Lifecycle (web target only — local-only, no cloud fallback per `protocols/e2e-protocol.md`):**

   1. **Discovery** — at `$PROJECT_ROOT`, look for (in order): `docker-compose.e2e.yml` → `docker-compose.e2e.yaml` → `docker-compose.yml` (only if it declares an `e2e` profile). First hit wins. None found → web status = SKIP, reason `no-e2e-compose-file`. This repo has no infra-scaffold skill to generate the compose file — hand back to Claude (or the user) to add one; never reach for a cloud preview.
   2. **Runtime check** — `docker info >/dev/null 2>&1`. Non-zero → web status = SKIP, reason `docker-runtime-unavailable`. Surface "Docker Desktop / OrbStack / colima not running" in the verify report so the user has an unambiguous fix path.
   3. **Bring up** — `docker compose -f "$COMPOSE_FILE" -p "e2e-${CLAUDE_PIPELINE_TASK_ID}" up -d --wait` (project-name namespaced so parallel slices don't collide; `--wait` blocks until all healthchecks pass).
   4. **Resolve baseURL** — read the app service's mapped host port via `docker compose -p "e2e-${CLAUDE_PIPELINE_TASK_ID}" port <app-service> <container-port>` (use dynamic port mapping in the compose file to avoid host-port conflicts across pipelines). Export as `PLAYWRIGHT_BASE_URL` / `CYPRESS_BASE_URL` for the driver.
   5. **Run suite** — `npx playwright test` (or `npx cypress run`). Capture intra-run flake_rate from the driver's retry counter as today.
   6. **Teardown (mandatory, trapped)** — register a trap that runs `docker compose -f "$COMPOSE_FILE" -p "e2e-${CLAUDE_PIPELINE_TASK_ID}" down -v --remove-orphans` on EXIT, ERR, INT, and TERM. Teardown failure is non-fatal to the verdict but MUST be logged in the verify report.

   Out of scope (do NOT implement a fallback): polling a Vercel/Netlify preview URL, spawning a Fly machine, hitting a Supabase/Neon branch endpoint, any other remote host. If the local stack cannot come up, the verdict is SKIP with an actionable reason — the harness never reaches for a third party.

3. **Web flake handling (strict, no small-suite carve-out)**: capture intra-run flake_rate from the driver's retry counter, then coerce BEFORE composing.

   ```python
   coerced = coerce_web_status_for_flake(target_results, flake_rate)
   # web → FAIL when flake_rate > 0.05 (strict `>`).
   ```

   Document `flake_rate: <decimal>` in the verify report.

4. **Screenshots**: web E2E screenshots-on-assertion land at `$state_dir/{task_id}/scratchpad/qa-engineer-verify-screenshots/` (mirrored as `SCREENSHOT_PATH_TEMPLATE` in the resolver — verbatim invariant).

5. **Composite verdict (COERCE FIRST, COMPOSE SECOND)**:

   ```python
   verdict = compose_verdict(coerced)
   ```

   - Any target = FAIL → UNVERIFIED
   - Any target = SKIP and no FAILs → VERIFIED_WITH_SKIP
   - All fired targets = PASS → VERIFIED
   - All N/A → VERIFIED
   - **Side-channel emit (independent of composite)**: when Tier 4 web target status = `SKIP`, additionally emit `E2E_SKIP_NO_ENV` (info-level, per `protocols/verdict-catalog.md`). This does NOT change the composite verdict — it travels alongside the report so the loud yellow line is visible in the PR/HANDOFF.md, not silently swallowed.

6. **First-fire release note**: on first web-target fire for a project (no prior `$state_dir/{task_id}/scratchpad/qa-engineer-verify-screenshots/` history), emit one line in the verify report: "Web E2E gating now active because <reason>".

### 4.75. Run Tier 5: External Oracle (Conditional, HARD GATE when oracle exists)

> **Tier 5 is conditional**: it only fires when a known-good external comparator exists for the change. When it fires, oracle-match is required for `VERIFIED`. When no oracle applies, Tier 5 = N/A and the composite verdict is unaffected.

**Motivation**: Anthropic's C-compiler post documented the "GCC-as-oracle" differential-testing pattern — comparing a candidate implementation's output against a battle-tested reference is the cheapest, sharpest correctness signal available. Where an oracle exists, *not using it* is leaving free verification on the table. Tier 5 institutionalises the pattern.

**Detection — does an oracle apply?**

An oracle applies when ALL of the following hold:
1. The change has a *deterministic, comparable output* — a parse tree, a SQL row set, a validation pass/fail, an emitted artifact, a numeric result — not a UX flow or a side-effecting workflow.
2. A *known-good external comparator* is available locally or via a trusted dependency: a reference parser, a reference SQL engine, a schema validator binary, a published reference implementation, a prior frozen version of the same library.
3. The oracle is *independent* of the code under test — not the same library wrapped differently, not a fork of the candidate.

If any clause fails → Tier 5 = **N/A** (not SKIP).

**Examples (non-exhaustive):**
- Hand-written parser → diff AST against ANTLR-generated parser or upstream grammar.
- SQL builder / query DSL → execute generated SQL via `psql` against the same fixture data; diff result sets.
- JSON schema validation logic → run identical payloads through `ajv` (or language-native equivalent); diff verdict + error path.
- Codegen / template emitter → emit and compile/parse with the target toolchain (e.g. `tsc --noEmit`, `gcc -fsyntax-only`); diff diagnostics.
- Reimplementation of a published algorithm → diff against the reference implementation on a corpus of inputs.

**Procedure:**

1. **Identify the oracle.** Name it explicitly in the report (binary/version, library/version, or source URL). If selection is non-obvious, prefer the most widely-deployed reference.
2. **Define the input corpus.** Reuse existing fixtures where possible. Minimum 1 input; ≥10 inputs preferred for non-trivial changes. Inputs should cover changed-line behaviour, not the full surface.
3. **Run candidate and oracle on identical inputs**, in isolated workspaces.
4. **Diff outputs** with a stable serializer (canonical JSON, sorted result set, normalised whitespace). Record every divergence verbatim.
5. **Classify divergences:**
   - **Match** — candidate output equals oracle output (after canonical normalisation).
   - **Documented divergence** — candidate intentionally differs from oracle (e.g. extending grammar, fixing a known oracle bug); MUST be accompanied by a one-line justification AND a passing test that locks in the new behaviour.
   - **Bug** — undocumented divergence.
6. **Gate:** ZERO undocumented divergences (no "bug" entries) → Tier 5 = **PASS**. Any bug entry → Tier 5 = **FAIL** → composite `UNVERIFIED`, slice returns to Build with the divergence list as targeted gaps.

**Cost guardrail:** Tier 5 input corpus is bounded to changed-line behaviour. Do not run the oracle on the entire test fixture set — that is Tier 1's job. If the oracle setup takes >5 minutes to install/configure and no pre-existing harness fixture is available, Tier 5 = **N/A** with the reason "oracle-setup-prohibitive" documented in the report; do not SKIP — N/A means the gate does not apply.

**SKIP vs N/A:** Tier 5 emits **SKIP** only when an oracle *applies* (clauses 1–3 above all hold) but execution failed (oracle binary crashed, version mismatch unresolvable, environment unavailable). SKIP → composite verdict becomes `VERIFIED_WITH_SKIP`. N/A means no oracle applies — composite verdict unaffected.

**Citation:**
- Anthropic engineering blog — GCC-as-oracle differential testing applied to a from-scratch C compiler. The pattern generalises: where a reference implementation exists, differential testing dominates ad-hoc unit assertions on correctness-shape questions.

### 5. Produce Verification Report

### 6. Write Verification Evidence State File

The verifier MUST write `$state_dir/{task-id}/verification-evidence.json` at the end of every tier-completion using `os.replace` (atomic rename — write to `verification-evidence.json.tmp` first, then `os.replace` to the canonical path). Resolve the write target via `_psp_verification_evidence_path "${CLAUDE_PIPELINE_TASK_ID}" "${CLAUDE_WORKSTREAM:-}"` relative to `$CLAUDE_REPO_ROOT` (NEVER relative to cwd — `/harness:verify` runs inside the build worktree but the state-file path must resolve against the repo root). Schema: `{schema_version: 1, task_id, git_head, generated_at, verdict, tier_results, sandbox_run}` — see `protocols/_proposals/2026-05-14-iron-law-2-freshness-hook.md` for the field definitions. The Path-B advisory hook `hooks/verification-freshness-guard.sh` reads this file on every gated spawn (patch-critic, product-reviewer, pr-creation) and compares the recorded `git_head` to the current worktree HEAD.

## Output Format

```markdown
## Verification Report: [Feature]

### Feature Type: [Backend API / Frontend / Database / Infrastructure]

### Tier 1: Contract Tests
- **Status**: PASS / FAIL
- **Evidence**: [actual responses, constraint results]

### Tier 2: Smoke Tests
- **Status**: PASS / FAIL
- **Evidence**: [curl output, DB queries, screenshots]
- **Regression run**: full suite (no `-x`/`--bail`/`--fail-fast`); report failing-ID set diff: `regressions` = `failing_now − failing_baseline`; empty set = PASS signal

### Tier 3: Mutation Testing
- **Status**: PASS / FAIL / N/A
- **Score**: [X/Y mutations caught]
- **Uncaught**: [list of surviving mutations]

### Tier 3.5: LLM-Mutant Pass
- **Status**: PASS / FAIL / SKIP / N/A
- **Score**: [X/Y mutants killed (excluding equivalent)]
- **Equivalent excluded**: [N]
- **Uncaught**: [list of surviving non-equivalent mutants with category + rationale]
- **Skip reason** (if SKIP): [reason — call timeout, parse failure, zero non-equivalent mutants returned]

### Tier 4: E2E (multi-target — mobile + web)
- **Per-target status**:
  - Mobile (Maestro): PASS / FAIL / SKIP / N/A
  - Web (Playwright/Cypress): PASS / FAIL / SKIP / N/A
- **Loud-skip line** (rendered when web target = SKIP): `E2E: SKIPPED (no execution environment) — UI/API changes shipped without browser verification`
- **Composite (after coerce-then-compose)**: VERIFIED / VERIFIED_WITH_SKIP / UNVERIFIED
- **Mobile flows run**: [list of executed Maestro flow files]
- **Web driver**: Playwright | Cypress | (none — N/A)
- **Web flake_rate**: [decimal; FAIL if > 0.05 — strict `>`]
- **Driver-collision warning** (M4): [present iff both playwright + cypress configs detected]
- **Screenshots**: `$state_dir/{task_id}/scratchpad/qa-engineer-verify-screenshots/` (web only)
- **Evidence**: [pass/fail per flow + per-spec, retry attempts, skip reason if applicable]

### Tier 5: External Oracle
- **Status**: PASS / FAIL / SKIP / N/A
- **Oracle**: [binary/library name + version OR source URL; "no oracle applies" if N/A]
- **Input corpus**: [N inputs, source/path]
- **Divergences**: [count of match / documented / bug entries]
- **Bugs**: [verbatim divergence list — empty when PASS]
- **N/A reason** (if N/A): [non-comparable output | no oracle available | oracle-not-independent | oracle-setup-prohibitive]
- **Skip reason** (if SKIP): [oracle binary crash | version unresolvable | env unavailable]

### Verdict: VERIFIED / VERIFIED_WITH_SKIP / UNVERIFIED

**Verdict semantics**:
- **VERIFIED** — Tier 3 (≥70% rule-based) AND Tier 3.5 (≥60% LLM-mutant) both PASS (or both N/A per the tier matrix). Tier 4 fired and PASSED (or all N/A). **AND Tier 5 PASSED where an oracle applies (or N/A when none applies).** Oracle-match is required for VERIFIED whenever a known-good external comparator exists for the change.
- **VERIFIED_WITH_SKIP** — at least one tier was SKIP (Tier 3.5 SKIP on Codex-adapter failure; Tier 4 SKIP per E2E protocol prerequisites unmet; Tier 5 SKIP when an oracle applies but execution failed) AND no tier FAILED. Tier 5 = N/A (no oracle applies) does NOT cause VERIFIED_WITH_SKIP — it leaves the composite verdict unaffected. Call out any SKIP explicitly (PR body / HANDOFF.md) so it isn't silently swallowed.
- **UNVERIFIED** — any tier FAILED. Slice returns to Build with the failing tier's evidence (surviving-mutant list, failing E2E flows, **oracle divergence list**) as targeted gaps.

[If VERIFIED_WITH_SKIP: name which tier was SKIP and why -- call this out explicitly in the PR/HANDOFF.md]
[If UNVERIFIED: which tier failed and why]
```

## Prerequisite

- Review phase complete: BOTH `/harness:code-review` and `/harness:security-review` returned APPROVE

## Phase Output

```
Verdict: VERIFIED / VERIFIED_WITH_SKIP / UNVERIFIED
Next: If VERIFIED or VERIFIED_WITH_SKIP → proceed to ship/handoff yourself (this repo has no separate QA-strategy or product-acceptance skill — note any SKIP explicitly in the PR/HANDOFF.md so a human or Claude sees it before merge)
      If UNVERIFIED → return to Build to fix failing tiers, then re-run your own review pass
Tier results: Tier 1: [PASS/FAIL] | Tier 2: [PASS/FAIL] | Tier 3: [PASS/FAIL/N/A] | Tier 3.5: [PASS/FAIL/SKIP/N/A] | Tier 4: [PASS/FAIL/SKIP/N/A] | Tier 5: [PASS/FAIL/SKIP/N/A]
Side-channel verdict: E2E_SKIP_NO_ENV emitted when Tier 4 web = SKIP (acknowledge required at Accept).
Agent summaries: [verification summary]
```
