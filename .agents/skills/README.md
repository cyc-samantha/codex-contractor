# Skill Catalog (`.agents/skills/`)

One directory per harness skill, in Codex CLI's native Skills format
(`<name>/SKILL.md` with `name` + `description` frontmatter, progressive
disclosure, optional `scripts/`, `references/`, `assets/`).

**Post-Phase-8-cull catalog (CX-80..87).** The Phase 7 pivot (contractor
handoff model) made roughly 40 of the original ~60 ported skills, the
`.codex/agents/` role-team concept, and the `memory/`/`learning/`/`eval/`
port scaffolds obsolete — a contractor needs the handoff kit, the on-shift
working discipline, and the enforcement hooks, not a dispatch layer. The
keep-list below is **24 skills**: the handoff kit
(`harness-resume-handoff`), ~20 on-shift working-discipline skills, and
the two review skills rewritten as inline self-review procedures
(`harness-code-review`, `harness-security-review` — CX-85). Full
port-history and delete rationale: `PLAN.md` §5 Phase 8 and §6 Skill Port
Catalog (kept as historical record — a `PROMPT` row there does NOT mean
the skill survives this cull).

Every ported directory is prefixed `harness-<name>` (Codex has no per-repo
namespace, so the prefix avoids collision with a target repo's own skills
once installed via `scripts/install-skills.sh`).

Constraint honored when porting (CX-10, re-verified at CX-87): Codex caps
the initial skill list at 2% of the model context window (or 8,000
characters when unknown), so skill `description:` fields are audited and
trimmed to front-load trigger words.

## Catalog

| Skill dir | Description |
|---|---|
| `harness-accessibility-check` | Run axe-core against changed routes and gate on WCAG 2.1 AA violations. Run this yourself after frontend build work. |
| `harness-bug-fix` | Root cause analysis workflow with incremental TDD for bug fixes. Covers reproduce, analyze, regression test, fix, verify, and prevent. |
| `harness-build-implementation` | Structured Build-phase TDD implementation: RED-GREEN-REFACTOR per slice, mutation kill loop. Use when implementing acceptance criteria after a plan is approved. |
| `harness-changelog` | Use to ship a PR with a human-readable narrative and changelog entry: derives a 'what changed and why' PR body plus a Keep-a-Changelog entry from the diff and ACs. |
| `harness-code-review` | Inline self-review pass over your own diff before handing work back: SOLID/DRY, cohesion, test quality, complexity, naming. Run this on yourself — there is no separate reviewer to spawn. |
| `harness-db-migration` | Structured database migration workflow. |
| `harness-debt-ledger` | Advisory grep-collector that harvests every `DEBT:` deliberate-simplification marker across the tree, renders a ledger grouped by file, and flags `no-trigger` entries. |
| `harness-debug` | Persistent debug state management for complex, multi-session bugs. Maintains structured debug state files under HARNESS_DATA that survive context compaction. |
| `harness-deploy` | Continuous deployment skill: environment-aware deploy with pre-flight checks, staging verification, production rollout, and rollback. |
| `harness-deployment-verification` | Post-deploy verification: health checks, smoke tests against live URL, error rate monitoring, automatic rollback trigger. |
| `harness-health-scan` | Scan a codebase for security vulnerabilities, dependency freshness, test coverage gaps, tech debt signals, and dead code. |
| `harness-intake` | Classify a request as Discuss, Small Change, Build, or human-elevated High Risk before implementation work begins. |
| `harness-module-extraction` | Extract a bounded context into an in-process module with an explicit public port (same repo, no new process or deploy unit). |
| `harness-polish` | Lightweight mechanical cleanup pass you run yourself after Build, before code-review/security-review. |
| `harness-pr-creation` | Ship a feature: GitHub pull request workflow with validation, feature branch management, and automated PR creation. |
| `harness-react-native-patterns` | Expo Router v4 patterns, NativeWind, Gluestack UI v3, TanStack Query + Zustand, platform handling, Maestro E2E. |
| `harness-refactor` | Safe refactoring workflow: identify smell, write characterization tests, refactor in small steps, verify green after each. |
| `harness-resume-handoff` | Resume work handed off by the Claude harness: reads ACTIVE_HARNESS baton + HANDOFF.md, reconciles against git ground truth, continues the task vertically, and wraps by writing a return HANDOFF.md with baton: claude. |
| `harness-security-alert-fix` | Investigate and fix open GitHub security alerts (CodeQL + secret-scanning). |
| `harness-security-review` | Inline security audit pass over your own diff: OWASP Top 10, secrets, auth/authz, dependency vulns. Run this on yourself before verify/ship — there is no separate security-engineer to spawn. |
| `harness-smell-scan` | Advisory Fowler-catalog smell sweep on changed files. Use to check for Feature Envy, Data Clumps, Shotgun Surgery, and other architectural smells before review. |
| `harness-tech-spike` | Time-boxed technical research workflow: question, explore, prototype, findings, recommendation. |
| `harness-tool-synthesis` | Use when standard tools can't do the job and a one-shot scratch tool would help (codebase-specific search, AST analyzer, repo-specific linter). |
| `harness-verify` | Structured verification workflow: contract tests, smoke tests, mutation testing. |
| `harness-web-frontend-patterns` | Web frontend tech-stack pattern reference (React/Next.js/Vite/Remix). Use for framework-specific build/debug/verify guidance. |

**Aggregate `description:` character count across all 25 available
skills: 3,487** (measured 2026-07-27 by summing each skill's SKILL.md
`description:` frontmatter value — well under the 8,000-char cap; was
8,516 pre-cull, CX-87 AC). Re-measure with:

```bash
python3 -c "
import re, pathlib
total = 0
for p in sorted(pathlib.Path('.agents/skills').glob('harness-*/SKILL.md')):
    m = re.search(r'^description:\s*\"(.*)\"\s*$', p.read_text(), re.M)
    if m:
        total += len(m.group(1))
print(total)
"
```

## Installation

`scripts/install-skills.sh [target-dir]` symlinks every `harness-*` skill
directory from this repo's `.agents/skills/` into
`<target-dir>/.agents/skills/`. Defaults to `.` (this repo's own root scope)
when no argument is given. Idempotent — safe to re-run; refreshes stale
symlinks and reports (without clobbering) any pre-existing non-symlink path.
