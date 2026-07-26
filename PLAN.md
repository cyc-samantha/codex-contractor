# Codex-Harness Port Plan

> **Historical document — superseded as an executable roadmap.**
>
> This file records the original full-port design, the later contractor
> pivot, and completed CX work. It contains mutually historical architecture
> states and must not be used to decide the next implementation task.
>
> The approved target and current executable roadmap are:
>
> - `docs/STANDALONE-CODEX-HARNESS-SPEC.md`
> - `docs/STANDALONE-CODEX-HARNESS-IMPLEMENTATION-PLAN.md`
>
> The next planned implementation task is T00. Standalone capability must not
> be claimed until its required tasks and the T32 activation gate are merged.


Porting the Claude Code harness at `/home/samanthachen/git/.claude` (skills, agent
team, enforcement hooks, memory/recall, continuous learning, internal eval) onto
OpenAI Codex CLI.


**Verified against Codex CLI documentation as of 2026-07-09** (`developers.openai.com/codex/*`,
mirrored from `github.com/openai/codex/docs/*`). Every capability claim below is
either (a) cited to a specific doc page fetched during this planning pass, or
(b) explicitly marked `<unverified>` where the doc set did not confirm behavior.
Do not treat `<unverified>` items as blocking — they are flagged for a follow-up
manual probe (CX-90, Phase 6) before the harness depends on them.


**Headline finding that revises the brief's assumed shape**: Codex CLI in
mid-2026 ships native equivalents for three primitives the origin brief assumed
would need heavy substitution — **Skills** (`.agents/skills/SKILL.md`,
progressive disclosure, near byte-identical contract to Claude's Skill tool),
**Subagents** (`agents.<name>` TOML config + `/agent` CLI switching + parallel
dispatch), and **Hooks** (`hooks.json` with `PreToolUse`/`PostToolUse`/
`SessionStart`/`SubagentStart`/`SubagentStop`/`Stop`/`PreCompact`/`PostCompact`/
`UserPromptSubmit`/`PermissionRequest` events, `command`-type handlers). This
plan ports against that reality rather than the heavier substitution ladder
(prompts-as-skills, `codex exec`-as-orchestration, git-hooks-as-enforcement)
that would be needed on an older Codex CLI. Where Codex's native primitive is
narrower than Claude's, the gap is called out per-row in the capability table.


---


## 1. Executive Summary


**Goal**: reproduce, on Codex CLI, as much of the Claude harness's engineering
discipline as the platform supports — Iron Laws, pipeline phase gating,
skills/agents, worktree isolation, memory/recall, continuous learning, internal
eval — while being honest about what cannot port at all.


**What ports at (near-)FULL fidelity**:
- Skills — Codex's `.agents/skills/SKILL.md` format is structurally the same
  contract as Claude's Skill tool (name + description frontmatter, progressive
  disclosure, optional `scripts/`, `references/`, `assets/`). The ~75-skill
  catalog ports as a skill directory tree with no format rewrite needed.
- AGENTS.md / CLAUDE.md autoload — Codex's own native mechanism (global →
  project-root → nested, `AGENTS.override.md` precedence). This is *more*
  capable than Claude's single-file `CLAUDE.md` + `rules/core.md` combo, so
  the merged `AGENTS.md` in this repo is a straight port, not a substitute.
- Memory/recall/learning/eval — `memory.sqlite`, `observations.jsonl`,
  `reindex-memory`, `recall`, `mcp_memory` (stdio JSON-RPC server) are Python
  stdlib scripts with zero dependency on which coding agent invokes them. They
  port byte-for-byte; only the *caller* (Codex hook / prompt) changes.
- Pipeline state (`pipeline-state/{task-id}/*.md`) — plain markdown with YAML
  frontmatter. Portable verbatim; a task begun under Claude can resume under
  Codex and vice versa if both harnesses point at the same `HARNESS_DATA` dir.


**What needs re-architecture**:
- Agent Team / parallel dispatch — Codex's `agents.<name>` TOML files are a
  weaker primitive than Claude's per-role `agents/*.md` (no per-agent
  `tools:` allowlist enforcement, no `isolation: "worktree"` frontmatter field,
  `agents.max_depth` defaults to 1 vs Claude's configurable depth-3). The
  orchestration script layer (Phase 2, CX-20 through CX-27) closes this gap by
  wrapping `codex exec --profile <role>` invocations with the worktree-creation
  and tool-scoping logic Codex doesn't do natively.
- Verdict gating / phase advancement — Codex has no concept of a "pipeline
  phase verdict gate." This is pure orchestration-script logic (bash/Python
  driving `codex exec` in sequence, parsing `--output-schema` JSON for the
  verdict field) — there is no native primitive to lean on at all.
- Mutation-semantic hook injection (Claude's `instinct-injector.sh` splicing a
  `## Learned Patterns` block into a spawn prompt) — Codex hooks today only
  run `type: "command"` handlers; `prompt` and `agent` handler types are
  *parsed but skipped* (verified, `codex/hooks` doc). There is no confirmed
  `modified_tool_input`-equivalent on any Codex hook event. The orchestration
  script must inject instincts/session-memory/scratchpad by literally
  concatenating them into the prompt string it hands to `codex exec`, mirroring
  what the Claude harness's orchestrator already does at the application layer
  (per `protocols/autonomous-intelligence.md` — the orchestrator splice, not
  the hook, does the injection there too). Net effect: this actually ports at
  **FULL** fidelity, because the source harness's real mechanism was always
  orchestrator-side string concatenation, not a hook mutation.


**What is impossible (or not worth attempting) on Codex today**:
- Per-agent enforced tool allowlists (Claude's `pre-agent-allowlist.sh`,
  ENFORCING since 2026-05-14) — Codex's `agents.<name>` config has no
  `tools:` allowlist / deny-list field in the verified doc set. `<unverified>`
  whether `mcp_servers` scoping per agent role can approximate this; flagged
  for CX-90 probe. Until then: DROPPED, replaced by an AGENTS.md-level
  admonition (advisory only).
- True mid-session `PreToolUse` *blocking* on non-command hook types (the
  Claude harness's `exit 2` semantics) is confirmed to work for `command`
  hooks on Codex (`hooks.json`), so this is NOT impossible — see the
  Hooks Substitution Ladder in §3. What IS impossible: Claude's
  `modified_tool_input` patch-in-place semantics used by advisory Path-B
  hooks (`instinct-injector.sh`, `pre-agent-thinking.sh`) — Codex has no
  documented equivalent. These stay orchestration-script-side (see above).
- `Computer` tool parity for `vlm-critic` / `design-qc` screenshot-diff
  work — `<unverified>`; Codex's tool surface for vision/computer-use was not
  confirmed in the fetched doc set. Marked DROPPED pending a dedicated probe;
  not a Phase 0-5 blocker.


---


## 2. Capability Mapping Table


| Claude Code primitive | Codex CLI equivalent | Port strategy | Fidelity |
|---|---|---|---|
| `CLAUDE.md` + `rules/core.md` autoload | `AGENTS.md` discovery chain (global `~/.codex/AGENTS.md` → project-root → neste
| Skill tool (`skills/*/SKILL.md`, ~75 dirs) | Native Codex Skills (`.agents/skills/<name>/SKILL.md`), verified `codex/ski
| Agent tool + ~20-role agent team | `agents.<name>` TOML config (`~/.codex/agents/*.toml` or `<repo>/.codex/agents/*.toml
| Hooks: `PreToolUse` / `PostToolUse` / `SessionStart` (deterministic, blocking, `exit 2`) | Native `hooks.json` with the 
| Agent tool worktree isolation (`isolation: "worktree"`) | No native per-agent worktree field. Automatic "Worktree" featu
| MCP servers (`mcpServers` in `settings.json`) | `mcp_servers.<id>.*` in `config.toml` (`command`, `args`, `env`, `enable
| Plugin data dirs (`$CLAUDE_PLUGIN_DATA`) | `$CODEX_HOME` (defaults `~/.codex`, overridable) | Runtime state (`pipeline-s
| Verdict gating (`BUILD_COMPLETE`, `APPROVE`, …) | No native primitive. | Pure orchestration-script logic: drive `codex e
| Pipeline state files (`pipeline-state/{task-id}/*.md`) | No native primitive — plain files. | Keep the identical markdow
| Non-interactive mode (used for Ship/Deploy/CI-gated phases) | `codex exec` (JSONL streaming via `--json`, `--output-last
| Reversibility escapes (`CLAUDE_DISABLE_*` env vars) | Equivalent env-var short-circuits in the orchestration script (har
| Rules/permission scoping (`settings.json` allowlists) | `.rules` files + `prefix_rule(...)` (experimental, verified `cod
| Prompt Tracing (`CLAUDE_ENABLE_TRACE`) | `--json` streaming on `codex exec` gives per-turn/per-item events (`thread.star
| Instinct injection / session memory / scratchpad splice into spawn prompt | No native mutation hook; must be orchestrato
| Codebase-map auto-generation (`~/.claude/db/codebase-map/`) | No native primitive | Port the tree-sitter + PageRank gene
| Reversibility / depth caps (`CLAUDE_SUBAGENT_MAX_DEPTH`) | `agents.max_depth` (default 1), `agents.max_threads` (default
| Per-Agent Tool Allowlists (`tools:` frontmatter, ENFORCING) | No confirmed equivalent | AGENTS.md-level advisory instruc
| Computer tool / VLM screenshot-diff (`vlm-critic`, `design-qc`) | `<unverified>` | Not attempted in Phase 0-5. Revisit a


---


## 3. Architecture of the Codex Harness


### Repo layout (this repo, `codex-harness`)


```
codex-harness/
  AGENTS.md                         # merged CLAUDE.md + rules/core.md, Codex-native autoload
  PLAN.md                           # this file
  .agents/skills/                   # ported skill catalog (one dir per harness skill)
    harness-intake/SKILL.md
    harness-pipeline/SKILL.md
    harness-build-implementation/SKILL.md
    harness-learn/SKILL.md
    harness-recall/SKILL.md
    ... (~75 total, see §6 Skill Port Catalog)
  .codex/
    agents/                         # per-role subagent TOML configs
      software-engineer.toml
      code-reviewer.toml
      security-engineer.toml
      architect.toml
      ... (~20 total, mirrors agents/*.md)
    hooks/
      hooks.json                    # command-type hook registrations
      code-shape-check.sh           # ported 1:1 from hooks/code-shape-check.sh
      main-branch-guard.sh          # ported 1:1
      ...
    rules/
      harness-destructive.rules     # ported destructive-verb prefix_rules
    config.toml                     # mcp_servers.memory, agents.max_depth, sandbox_mode, approval_policy
  scripts/
    codex-harness                   # orchestration entrypoint (bash), replaces "the orchestrator"
    lib/
      dispatch-agent.sh             # wraps: worktree create -> codex exec --profile <role> -> parse verdict -> worktree m
      verdict-parse.py              # reads --output-schema JSON, returns verdict enum
      instinct-inject.py            # ports hooks/_lib/instinct_loader.py verbatim
      session-memory.sh             # ports hooks/_lib/session-store.sh verbatim
  memory/                           # ports learning/, db/, session-memory/ verbatim (Python stdlib)
    reindex-memory/
    recall/
    capture/
    mcp_memory/
  eval/
    baselines/
    cases/
    suites/
  learning/
    instincts/
  pipeline-state/                   # same per-task-subdirectory contract as the Claude harness
```


### Runtime model


1. **Human or CI invokes `scripts/codex-harness <command>`** (e.g. `pipeline start <task-id>`, `pipeline resume <task-id>`
2. **The orchestration script is the orchestrator.** It never writes source code
   itself (Iron Law 3 substitute — see §4). It only:
   - creates/removes git worktrees,
   - assembles prompts (skill body + agent role file + instincts + session
     memory + scratchpad + prior phase's `## Next Phase Input`),
   - invokes `codex exec --profile <role> --cd <worktree> --sandbox
     workspace-write --output-schema <phase-verdict-schema.json> "<assembled prompt>"`,
   - parses the verdict JSON, writes `pipeline-state/{task-id}/{phase}.md`,
   - decides the next phase per the same phase order as the Claude harness.
3. **Skills are read by Codex itself**, not re-implemented by the script — once
   a `codex exec` invocation is scoped to a worktree with `.agents/skills/`
   visible (repo-root scope), Codex's own skill-selection logic (implicit
   description-match, or explicit `$skill-name` mention in the assembled
   prompt) picks up the ported `SKILL.md` files exactly as it would any other
   skill. The orchestration script's job is to *mention* the right skill by
   name in the prompt it assembles (mirroring how the Claude orchestrator's
   spawn prompt says "Read `~/.claude/skills/{name}/SKILL.md`").
4. **Subagent parallelism**: Best-of-N and multi-slice Build dispatch become N
   parallel `codex exec` invocations, one per worktree, backgrounded by the
   orchestration script (`&` + `wait`), exactly mirroring the Claude harness's
   "parallel subagent calls in a single message" default dispatch mode (no
   `TeamCreate`/tmux-pane equivalent is needed — Codex has no visible-team
   concept; every dispatch is the parallel-subagent default, never the
   opt-in visible-team mode).
5. **Hooks fire natively inside each `codex exec` invocation** — the code-shape
   checker, main-branch guard, and observation-capture hooks are registered
   once in `.codex/hooks.json` and apply to every spawned agent without the
   orchestration script re-wiring them per call.


### Key design moves (detail)


#### Skills → Codex native Skills (not a prompt substitute)


Because Codex Skills already implement progressive disclosure
(`codex/skills`: *"Codex starts with each skill's name, description, and file
path. Codex loads the full SKILL.md instructions only when it decides to use a
skill."*), the ~75 harness `skills/*/SKILL.md` files port with **no format
change** — copy the directory, keep frontmatter, done. The install step is a
placement decision only: which of the five discovery scopes (REPO `$CWD/.agents/skills`,
REPO parent, REPO root, USER `$HOME/.agents/skills`, ADMIN `/etc/codex/skills`)
each skill belongs in. Harness-wide skills (pipeline, intake, build-implementation,
learn) go in REPO ROOT scope so every subfolder of a checked-out project inherits
them; project-specific overrides would go in nested REPO scopes (not needed for
Phase 0-5).


One real constraint: Codex's skill-selection budget caps the *initial* skill
list at "2% of the model's context window, or 8,000 characters when the
context window is unknown" (verified `codex/skills`) — with ~75 skills, harness
skill *descriptions* must stay terse (front-load the trigger words) or Codex
will shorten them further / omit some from the initial list. Phase 1 (CX-10)
includes a description-length audit pass for this reason.


#### Subagent team → `agents.<name>` TOML + orchestration wrapper


Each Claude `agents/<role>.md` becomes a `.codex/agents/<role>.toml` with the
three REQUIRED fields (`name`, `description`, `developer_instructions`) plus
optional `model`, `model_reasoning_effort`, `sandbox_mode`. The
`developer_instructions` field is where the ported agent role-definition body
(TDD protocol, decision ladder, self-review checklist) lives verbatim.
`skills.config` in the TOML can pre-enable/disable specific skills per role,
approximating (loosely) Claude's per-agent `tools:` allowlist for the *skill*
surface — it does NOT approximate the `tools:` allowlist for raw tool access
(Bash/Write/Edit/etc.), which has no confirmed per-role gate on Codex today
(see §2 DROPPED row).


Parallel dispatch = parallel `codex exec` processes, each with its own
`--cd <worktree>`; worktree isolation = the orchestration script's
`dispatch-agent.sh` running plain `git worktree add` before each invocation
(the CLI has no first-class isolation flag for this — the automatic
"Worktree" UI feature is scoped to the ChatGPT desktop app only, confirmed
above). This is intentionally identical in shape to how the Claude harness's
`hooks/worktree-create.sh` already works — Codex just doesn't do it for you.


#### Hooks → substitution ladder (revised: native hooks cover more than expected)


1. **Native `command`-type `hooks.json` entries** — for every Claude hook that
   is a deterministic exit-2-on-violation check (shape rules, protected-path
   checks, destructive-verb detection), port the shell script body unchanged
   and register it under the matching Codex event name. Confirmed available
   events: `PreToolUse`, `PostToolUse`, `SessionStart`, `SubagentStart`,
   `SubagentStop`, `PreCompact`, `PostCompact`, `UserPromptSubmit`,
   `PermissionRequest`, `Stop` (verified `codex/hooks`).
2. **`.rules` / `prefix_rule` for command-level allow/forbid** — the
   Non-LLM Gate on destructive verbs (Iron Law 4 companion) ports as
   `prefix_rule(pattern=[...], decision="forbidden")` entries. Marked
   experimental by OpenAI — do not treat as load-bearing until it stabilizes
   past the "may change" warning on the doc page.
3. **CI checks** — anything that needs a second, independent verification pass
   (mutation-score gating, EVAL_PASSED gate) runs as a GitHub Action step
   invoking `codex exec` non-interactively, mirroring the Claude harness's
   Internal Eval Gate.
4. **`sandbox_mode` / `approval_policy`** as the permission layer — `codex exec`
   defaults to `read-only`; the orchestration script explicitly requests
   `workspace-write` per Build-phase invocation and never `danger-full-access`
   outside a documented isolated runner (per the doc's own warning, mirrored
   verbatim into AGENTS.md).
5. **What does NOT port**: mutation-semantic hooks that patch the spawn prompt
   in place (`instinct-injector.sh`, `pre-agent-thinking.sh`,
   `cache-breakpoint-injector.sh`). Codex hooks parse but skip `prompt`/`agent`
   handler types (verified) and there is no confirmed `modified_tool_input`
   equivalent. These become orchestration-script string concatenation instead
   — which, as noted in §1, is actually what the Claude harness does today too
   (the hook there is advisory/log-only; the real splice is orchestrator-side).


Iron-Law enforcement-status downgrade table is in §4.


#### Memory/recall port (FULL fidelity)


`memory.sqlite` + `observations.jsonl` + `reindex-memory` + `recall` (3-tier
progressive disclosure: search / timeline / hydrate) + `mcp_memory` (stdio
JSON-RPC server) are pure Python stdlib. Register the server verbatim:


```toml
[mcp_servers.memory]
command = "python3"
args = ["$CODEX_HOME/harness-data/mcp_memory/server.py"]
required = true
```


`required = true` means `codex exec` exits with an error if the memory server
fails to start — the codex-harness equivalent of Claude's fail-closed posture
for a broken memory index (Iron Law 8 spirit).


#### Learning loop port


`observations.jsonl` → `/harness-learn` (ported skill, same 10-step procedure:
pattern detection, anti-pattern mining, sandbox-fragility mining, instinct
creation/pruning/promotion, memory-promotion drafts) → instinct files under
`learning/{project-hash}/instincts/*.md`, unchanged schema. Instinct injection
substitute: the orchestration script's `instinct-inject.py` (a straight port of
`hooks/_lib/instinct_loader.py` + the resolver's role/confidence/dedup/sort
logic) runs BEFORE each `codex exec` call and concatenates the rendered
`## Learned Patterns` block into the assembled prompt — same position in the
prompt-assembly order as the Claude harness's Agent Spawn protocol (skill →
agent def → instincts → agent memory → session memory → scratchpad →
scratchpad-write-instruction).


#### Eval port


`internal-eval`'s baseline/suite/regression-diff machinery is scripts driving
an agent pipeline against fixed cases — swap the `codex exec` invocation in for
whatever ran the Claude-side pipeline per case, **keep the identical
`eval/baselines/{date}-{model}.md` file format**. This means a single
`eval/cases/` corpus can score BOTH harnesses and the reports are directly
diffable — a genuine bonus capability the origin harness doesn't have (no
cross-agent-vendor eval today).


#### Pipeline state


`pipeline-state/{task-id}/{phase}.md` kept byte-for-byte identical (YAML
frontmatter + Summary/Test Results/Key Findings/Next Phase Input sections). A
task started under the Claude harness can be resumed under codex-harness (or
vice versa) provided both point `HARNESS_DATA`/`$CODEX_HOME/harness-data` at
the same directory — genuinely portable state, no format translation needed.


---


## 4. Iron Laws — Full Transcription (1-13) with Codex Enforcement Status


Source: `rules/core.md` § Iron Laws (1-8) + `protocols/data-science-invariants.md`
§ DS Iron Laws (9-13), read verbatim from the source harness on 2026-07-09.


| # | Law (verbatim intent) | Claude status | Codex status | Substitution mechanism |
|---|---|---|---|---|
| 1 | No AC ships without a failing-then-passing test AND mutation score ≥70% on changed lines. | ASPIRATIONAL | **ADVISOR
| 2 | No completion claims without fresh verification evidence — stale test output is not evidence. | ASPIRATIONAL (log-on
| 3 | The orchestrator never writes source code. | **ENFORCED** (`hooks/_lib/is-protected-path.sh`) | **ADVISORY → partial
| 4 | REPO_ROOT HEAD stays on `main` for the entire pipeline run. | **ENFORCED** (`hooks/main-branch-guard.sh`, PreToolUse
| 5 | No phase skipped, no gate bypassed, no skill omitted. | ASPIRATIONAL | **ADVISORY** | Pure orchestration-script sequ
| 6 | Findings surfaced during review are fixed in this pipeline, never deferred. | ASPIRATIONAL | **ADVISORY** | Orchestr
| 7 | Every pipeline produces an observation. | ASPIRATIONAL | **ADVISORY, script-enforced** | The orchestration script's 
| 8 | A security/correctness gate that cannot evaluate its condition fails closed. | ASPIRATIONAL | **PARTIAL — hook-enfor
| 9 (DS) | No model/analysis conclusion ships without a pre-registered experiment card + holdout eval vs baseline. | ASPIR
| 10 (DS) | A negative/null result is a valid pipeline outcome; no silent re-run to flip a verdict. | ASPIRATIONAL | **ADV
| 11 (DS) | Every dataset reference resolves to an immutable version; every run reproducible from (code-ref, data-ref, env
| 12 (DS) | Raw data never enters agent context/transcripts/logs/commits beyond capped, PII-masked samples. | **ENFORCED a
| 13 (DS) | A data-contract violation halts the pipeline; no silent coercion/null-dropping/row-filtering. | ASPIRATIONAL |


**Summary of what actually strengthens vs weakens under Codex**: Law 4
(main-branch invariant) is the strongest native-hook parity point because
Codex's `PreToolUse` `command` hooks genuinely block, same as Claude's. Laws 1,
2, 5, 6, 7 downgrade to script-enforced-only because Codex has no pipeline-phase
or verdict-gate primitive at all — this is an intrinsic architecture gap, not
a hook-maturity gap, and will not close as Codex hooks mature further; it needs
the orchestration script to keep doing this work indefinitely. Law 3 downgrades
because Codex has no "orchestrator process" concept to gate — the invariant
becomes "the wrapper script's source is small and reviewed," a code-review-time
guarantee rather than a runtime one.


---


## 5. Work Breakdown


Phased tasks. `Size`: S = <1 day, M = 1-3 days, L = 3-7 days.


### Phase 0 — Bootstrap


| ID | Description | Deliverable(s) | Acceptance Criteria | Deps | Size | Owner |
|---|---|---|---|---|---|---|
| CX-01 | Scaffold repo layout | Directory tree per §3 | `codex-harness` repo has all top-level dirs from §3 layout, each 
| CX-02 | Author merged `AGENTS.md` | `AGENTS.md` at repo root | Contains all 13 Iron Laws + code shape rules + pipeline p
| CX-03 | Port `.codex/config.toml` skeleton | `config.toml` with `agents.max_depth=3`\*, `sandbox_mode`, `approval_policy
| CX-04 | Probe hook trust flow | Notes doc `.codex/hooks/TRUST.md` | Documents the `/hooks` review-and-trust step a fresh


\* Codex's documented default is `1`; the harness sets `3` to match the Claude
side's `CLAUDE_SUBAGENT_MAX_DEPTH` default — flagged for a real-world load test
in CX-91 (Phase 6) since the doc does not confirm behavior above the default.


### Phase 1 — Core Instructions + Skills


| ID | Description | Deliverable(s) | Acceptance Criteria | Deps | Size | Owner |
|---|---|---|---|---|---|---|
| CX-10 | Skill catalog port + description-length audit | `.agents/skills/harness-*/SKILL.md` (~75 dirs, see §6) | Every p
| CX-11 | Port `intake`, `pipeline`, `build-implementation` skills | 3 `SKILL.md` files, unchanged procedure bodies | Diff
| CX-12 | Port remaining Plan/Build/Review/Final-Gate/Ship/Deploy/Reflect skills | Remaining skill dirs from §6 PROMPT/SCR
| CX-13 | Install script | `scripts/install-skills.sh` | Idempotent; symlinks (not copies) from `codex-harness/.agents/ski


### Phase 2 — Orchestration / Agent Team


| ID | Description | Deliverable(s) | Acceptance Criteria | Deps | Size | Owner |
|---|---|---|---|---|---|---|
| CX-20 | **DEFERRED — see §5 Phase 7.** Author `.codex/agents/*.toml` for all ~20 roles | 20 TOML files | Each has required `name`/`description`/`develo
| CX-21 | **DEFERRED — see §5 Phase 7.** `scripts/codex-harness` entrypoint | Bash dispatcher (`pipeline start`, `pipeline resume`, `pipeline status`) | 
| CX-22 | **DEFERRED — see §5 Phase 7.** `scripts/lib/dispatch-agent.sh` | Worktree-create → `codex exec` → worktree-merge wrapper | Given a role + task-
| CX-23 | **DEFERRED — see §5 Phase 7.** `scripts/lib/verdict-parse.py` | Parses `--output-schema` JSON output into a verdict enum | Unit tests cover: we
| CX-24 | **DEFERRED — see §5 Phase 7.** Parallel Best-of-N dispatch | `scripts/lib/dispatch-bestofn.sh` | Spawns N `codex exec` invocations backgrounded
| CX-25 | **DEFERRED — see §5 Phase 7.** Phase-order state machine | `scripts/lib/phase-order.sh` | Encodes Plan → Plan Validation → Build (incl. code-re
| CX-26 | **DEFERRED — see §5 Phase 7.** Fix-engineer in-cycle rework loop | `scripts/lib/dispatch-fix.sh` | On non-passing verdict, re-dispatches the fi
| CX-27 | **DEFERRED — see §5 Phase 7.** Reversibility escape hatches | `CODEX_HARNESS_DISABLE_*` env-var checks in each `scripts/lib/*.sh` | Each escape


### Phase 3 — Memory + Learning

> **RE-SCOPED by the Phase 7 pivot (CX-70).** The shared
> `${HARNESS_DATA:-$HOME/.claude}` root IS the Claude harness's live
> runtime dir, which already contains the real `mcp_memory/server.py`,
> `recall`, `capture`, instincts, and session-memory. Porting copies into
> this repo would create exactly the "second synced copy" the handoff
> contract forbids. The `memory/` and `learning/instincts/` placeholder
> trees are removed in Phase 8 (CX-83).

| ID | Description | Deliverable(s) | Acceptance Criteria | Deps | Size | Owner |
|---|---|---|---|---|---|---|
| CX-30 | **SUPERSEDED by CX-70 (shared root) — the live subsystem is used in place, no port.** Port `reindex-memory`, `recall`, `capture`, `mcp_memory` | `memory/` subtree, unchanged Python | `python3 memory
| CX-31 | **RE-SCOPED by CX-70 — `config.toml` registers the Claude-side server at `${HARNESS_DATA}/mcp_memory/server.py`; no local `memory/mcp_memory/` is created.** Register `mcp_memory` in `config.toml` | `[mcp_servers.memory]` entry | `required = true`; smoke test per `codex
| CX-32 | **SUPERSEDED by CX-73 — the contractor only appends `source: codex` observations; Claude, as primary, runs learn.** Port `learn` skill (10-step procedure) | `.agents/skills/harness-learn/SKILL.md` | All 10 steps present (bootstr
| CX-33 | **DEFERRED — see §5 Phase 7 (only served the dispatch layer's prompt assembly).** `scripts/lib/instinct-inject.py` | Port of `hooks/_lib/instinct_loader.py` resolver logic | Given a role + proje
| CX-34 | **DEFERRED — see §5 Phase 7 (shared root already carries the live session-memory).** Session-memory sub-file port | `scripts/lib/session-memory.sh` + `memory/session-memory/config/templates/*.md` |


### Phase 4 — Eval

> **SUPERSEDED by the Phase 7 pivot (CX-70).** Eval corpus, baselines, and
> the run/score/capture machinery stay Claude-side in the shared root; the
> contractor neither runs the internal eval nor keeps a second copy of its
> data. The `eval/` placeholder tree is removed in Phase 8 (CX-83).
> Cross-harness comparison (old CX-61) is dropped with the orchestrator.

| ID | Description | Deliverable(s) | Acceptance Criteria | Deps | Size | Owner |
|---|---|---|---|---|---|---|
| CX-40 | **SUPERSEDED by CX-70 (shared root).** Port `internal-eval` orchestration shell | `.agents/skills/harness-internal-eval/SKILL.md` + `eval/` dirs | `run
| CX-41 | **SUPERSEDED by CX-70 (shared root).** Swap per-case runner to `codex exec` | `eval/cases/*/run.sh` invokes `codex exec` instead of the Claude Agent to
| CX-42 | **SUPERSEDED by CX-70 (shared root) — there is only ONE baselines dir now, so format identity is trivially true.** Keep baseline file format identical | `eval/baselines/{date}-{model}.md` | Byte-for-byte same YAML frontmatter (


### Phase 5 — Enforcement Substitutes


| ID | Description | Deliverable(s) | Acceptance Criteria | Deps | Size | Owner |
|---|---|---|---|---|---|---|
| CX-50 | Port `main-branch-guard.sh` as native Codex `PreToolUse` hook | `.codex/hooks/hooks.json` entry + script | A tes
| CX-51 | Port `code-shape-check.sh` / `function-body-check.sh` / `comment-smell-check.sh` | `PostToolUse` hook entries | 
| CX-52 | Port destructive-verb list as `.rules` `prefix_rule` entries | `.codex/rules/harness-destructive.rules` | `codex
| CX-53 | SessionStart hooks (codebase-map rebuild, learning GC, worktree reaper) | `SessionStart` hook entries, ported sc
| CX-54 | CI-Green / Internal-Eval merge gate | GitHub Action step | PR touching `.codex/hooks/`, `.agents/skills/`, `.cod


### Phase 6 — Validation


| ID | Description | Deliverable(s) | Acceptance Criteria | Deps | Size | Owner |
|---|---|---|---|---|---|---|
| CX-60 | **SUPERSEDED — presupposed the deferred orchestrator; replaced by CX-74 (handoff round-trip dry run).** End-to-end dry run: T5-equivalent feature pipeline | Recorded transcript / trace | A trivial feature request run
| CX-61 | **SUPERSEDED — presupposed the deferred orchestrator; contractor-model validation is CX-74 instead.** Cross-harness eval comparison | `eval/runs/{run-id}/report.md` for both harnesses on the same case set | Report 
| CX-90 | Probe: per-agent tool-scoping equivalent | Written probe result (RED/GREEN) | Confirms or refutes whether `mcp_s
| CX-91 | Probe: per-call wall-clock cap equivalent | Written probe result | Confirms or refutes any Codex-native per-agen


### Phase 7 — Contractor Handoff (strategy pivot, 2026-07-11)

The maintainer decided codex-harness will NOT be a full port of the
Claude harness's orchestration layer. Codex is a fallback **contractor**
used only when the Claude harness's 5-hour usage window runs out; Claude
remains primary and does the vast majority of pipeline work. The core
deliverable of this pivot is **shared runtime state**: both harnesses
point at ONE data root (`${HARNESS_DATA:-$HOME/.claude}`, the Claude
harness's live runtime dir — see AGENTS.md § Runtime Model) so
`pipeline-state/`, learning observations, and eval baselines are visible
to whichever side is on shift, with no sync step. A `HANDOFF.md` contract
plus an `ACTIVE_HARNESS` baton file (`pipeline-state/HANDOFF-CONTRACT.md`)
coordinate the shift change. The Claude side gains a matching `/handoff`
skill in a separate repo, added in parallel. Because Codex is now a
single-thread contractor rather than an independent orchestrator, the
full `scripts/codex-harness` dispatch layer (worktree-create →
parallel-`codex exec` → verdict-parse → phase-order state machine) is
no longer required to hit the goal — the Phase 2 rows that built that
layer (CX-20 through CX-27 — CX-22, CX-23, and CX-27 only ever served
that layer too) are downgraded to deferred/optional and superseded by
this phase's thinner kit. Net narrative: **Codex is the contractor,
Claude is the general contractor** — the contractor needs the handoff
kit, the engineering discipline, and the enforcement hooks, not the
dispatch layer.

| ID | Description | Deliverable(s) | Acceptance Criteria | Deps | Size | Owner |
|---|---|---|---|---|---|---|
| CX-70 | Shared `HARNESS_DATA` root | `AGENTS.md` § Runtime Model updated; `.codex/config.toml` memory-server comment updated | Default runtime-state root is `${HARNESS_DATA:-$HOME/.claude}`, matching the Claude harness's `$CLAUDE_PLUGIN_DATA` default; seed-vs-runtime split language preserved; no remaining `$CODEX_HOME/harness-data` state-path reference in AGENTS.md | none | S | — |
| CX-71 | `HANDOFF.md` contract + `ACTIVE_HARNESS` baton | `pipeline-state/HANDOFF-CONTRACT.md` | Documents the full `HANDOFF.md` v1 frontmatter + section schema, the `ACTIVE_HARNESS` single-line baton format, and the reconcile-against-git rule; cross-references the Claude-side `/handoff` counterpart | CX-70 | S | — |
| CX-72 | `harness-resume-handoff` skill | `.agents/skills/harness-resume-handoff/SKILL.md` | Checks the baton before reading any `HANDOFF.md`; finds newest `baton: codex` handoff; reconciles against git/tests before trusting prose; continues `Next Actions` vertically (no subagent dispatch); wraps with a return `HANDOFF.md` (`baton: claude`) + baton flip; verdict block covers RESUMED/NO_BATON/NOTHING_TO_RESUME/STATE_DIVERGED | CX-71 | S | — |
| CX-73 | `source: codex` observation tagging | Documented in `pipeline-state/HANDOFF-CONTRACT.md` § Observation tagging; enforced by `harness-resume-handoff` Step 5 | Every observation the Codex side appends carries `"source": "codex"`; Claude-authored records may omit the field (defaults to `claude`) | CX-71, CX-72 | S | — |
| CX-74 | Handoff round-trip dry run (replaces CX-60/CX-61 as the port's validation gate) | Recorded transcript + the `HANDOFF.md` pair (claude→codex→claude) | A real task started under the Claude harness hands off with `baton: codex`; Codex resumes via `harness-resume-handoff`, reconciles against git/tests before trusting prose, completes ≥1 `Next Actions` item vertically (single-thread, no subagent dispatch), appends a `source: codex` observation, and hands back with a return `HANDOFF.md` + baton flip to `claude`; the Claude side then resumes cleanly | CX-71, CX-72, CX-73 | S | — |


### Phase 8 — Contractor Cull + Doc Reconciliation (2026-07-11)

The Phase 7 pivot changed the goal; this phase makes the repo match it.
Roughly 40 of the ~60 ported skills, the `.codex/agents/` role-team
concept, the `memory/`/`learning/`/`eval/` port scaffolds, and large
sections of `AGENTS.md` still describe the orchestrator-and-subagent
architecture Phase 7 deferred. A contractor needs the handoff kit, the
on-shift working discipline, and the enforcement hooks — not the dispatch
layer. Forcing function: `.agents/skills/README.md` records an aggregate
skill-description budget of 8,516 chars against Codex's 8,000-char
fallback cap — the catalog is over budget today, so the cull is
correctness, not just hygiene.

**Keep (the contractor core)**: the handoff kit
(`pipeline-state/HANDOFF-CONTRACT.md`, `pipeline-state/README.md`,
`.agents/skills/harness-resume-handoff/` — this is now the product);
~20 on-shift working-discipline skills (`build-implementation`,
`bug-fix`, `refactor`, `debug`, `verify`, `polish`, `smell-scan`,
`debt-ledger`, `tool-synthesis`, `pr-creation`, `changelog`, `deploy`,
`deployment-verification`, `db-migration`, `web-frontend-patterns`,
`react-native-patterns`, `accessibility-check`, `module-extraction`,
`security-alert-fix`, `health-scan`, `tech-spike`); enforcement + config
(`.codex/config.toml`, `.codex/hooks/TRUST.md`, `.codex/rules/`,
`scripts/install-skills.sh` — the Iron Laws apply to whoever is on
shift, so Phase 5 stays live); `AGENTS.md`, `PLAN.md`, `.gitattributes`,
`.gitignore`, this repo's `.claude/CLAUDE.md`.

| ID | Description | Deliverable(s) | Acceptance Criteria | Deps | Size | Owner |
|---|---|---|---|---|---|---|
| CX-80 | Remove dispatch/orchestrator skills (~15) | Delete `.agents/skills/`: `harness-pipeline`, `harness-intake`, `harness-batch-pipeline`, `harness-pipeline-resume` (superseded by `harness-resume-handoff`), `harness-workstream`, `harness-continuous-planning`, `harness-property-based-test`, `harness-sandbox-verify`, `harness-spec-blind-validate`, `harness-patch-critique`, `harness-product-acceptance`, `harness-plan-cache-lookup`, `harness-plan-self-validation`, `harness-spec-grounding` | No remaining skill body spawns an agent or drives phase order; the contractor entry point is `harness-resume-handoff` only | CX-72 | S | — |
| CX-81 | Remove Claude-telemetry/maintenance skills | Delete `.agents/skills/`: `harness-eval-model-effectiveness` (20 Python files — the single biggest removal), `harness-cache-audit`, `harness-mutation-score-report`, `harness-forensics`, `harness-harness-audit`, `harness-harness-config`, `harness-internal-eval`, `harness-learn`; edit `pipeline-state/HANDOFF-CONTRACT.md` §124-129 to drop the "this repo's harness-learn port" reference (Codex only appends tagged observations; Claude runs learn) | These skills audit/tune the Claude harness's metrics and agent team, which the contractor neither generates nor tunes; contract text no longer references a local learn port | CX-73 | S | — |
| CX-82 | Remove plan/greenfield-phase skills | Delete `.agents/skills/`: `harness-epic-breakdown`, `harness-story-writing`, `harness-estimation`, `harness-greenfield-scaffold`, `harness-creative-direction`, `harness-design-system-init`, `harness-project-setup` | Claude is primary and owns Plan; a contractor picking up mid-shift never starts an epic or a greenfield project, and works in repos Claude already set up | none | S | — |
| CX-83 | Remove subsystem port scaffolds; fix stale gotcha | Delete `memory/` (all `.gitkeep` placeholders), `learning/instincts/`, `eval/{baselines,cases,suites}` placeholder trees; update `.claude/CLAUDE.md` Gotchas ("until CX-31… memory/mcp_memory/ exists" is stale — the MCP block points at `${HARNESS_DATA}/mcp_memory/server.py`, the Claude-side copy) | No placeholder subsystem tree remains; no doc claims a local memory/eval port is coming; `.codex/config.toml` comment and CLAUDE.md agree on the shared-root path | CX-70 | S | — |
| CX-84 | Remove Phase-2 skeletons | Delete or stub `.codex/agents/` (README describes 20 role TOMLs from deferred CX-20 — replace with a one-line deferral note or delete the dir); remove `scripts/lib/.gitkeep` (CX-22/23 scripts and CX-27 escape hatches are deferred with the layer they served) | No empty scaffolding advertises the deferred dispatch layer | CX-80 | S | — |
| CX-85 | Rewrite review skills as inline self-review | Rewrite `harness-code-review` + `harness-security-review`: keep the review checklists (the value), drop "spawn code-reviewer/security-engineer" bodies; both become single-thread self-review procedures the contractor runs inline | Neither skill references subagent dispatch; checklists preserved | CX-80 | S | — |
| CX-86 | Rewrite `AGENTS.md` for the contractor model | Cut the Agent Team table (19 roles, all "TBD"), the T0-T6 Work-Class Routing section, and the orchestration-script-gated Pipeline Phase Order paragraph; rewrite § Runtime Model around the baton/`HANDOFF.md` flow (its opening still says `scripts/codex-harness` "ships in Phase 2, CX-21"); KEEP Iron Laws, code shape rules, worktree/commit protocol, and shared-root sections | A fresh Codex session reading only `AGENTS.md` gets the contractor model — no orphaned references to the orchestrator, the agent team, or T0-T6 routing | CX-80, CX-81, CX-82, CX-83, CX-84, CX-85 | M | — |
| CX-87 | Regenerate skill catalog + re-measure budget | Regenerate `.agents/skills/README.md` after the cull; re-measure the aggregate description budget | Catalog lists only surviving skills; aggregate description budget ≤ 8,000 chars (was 8,516) | CX-80, CX-81, CX-82, CX-85 | S | — |


---


## 6. Skill Port Catalog


Every directory under the source harness's `skills/` (77 entries, including
`README.md`, `_deferred`, `_template`). Decision legend: **PROMPT** = ports as
a Codex Skill (`.agents/skills/harness-<name>/SKILL.md`) largely unchanged;
**SCRIPT** = ports as a Python/bash script the orchestration layer calls
directly (not agent-invoked); **MERGED** = folded into another skill or into
`AGENTS.md`/`config.toml`/`hooks.json`; **DROPPED** = not ported.


| Skill dir | Decision | Rationale |
|---|---|---|
| `README.md` | N/A | Not a skill — catalog index, not ported as a directory. |
| `_deferred` | DROPPED | Explicitly not-yet-active in the source harness; no reason to port dormant content. |
| `_template` | SCRIPT | Scaffold template used by the scratch-tool promotion loop (§ learn Step 7b) — needed verbatim for
| `accessibility-check` | PROMPT | WCAG audit procedure — pure instructions, ports as-is. |
| `api-scaffold` | PROMPT | Ports as-is. |
| `batch-pipeline` | PROMPT | T3 mechanical-sweep dispatch target — ports as-is, references the phase-order state machine 
| `best-of-n` | DROPPED | Was MERGED into `dispatch-bestofn.sh` (CX-24); flipped to DROPPED by the Phase 7 pivot — the dispatch script is deferred and will not exist, and heavy Build variants stay Claude-side. |
| `bug-fix` | PROMPT | T4 dispatch target — ports as-is. |
| `build-implementation` | PROMPT | Core Build-phase skill — Phase 1 priority (CX-11). |
| `cache-audit` | PROMPT | Ports as-is. |
| `cache-flip-gate` | MERGED | Folds into CI-gate logic (CX-54) — it is a rollout-gate check, not agent-facing. |
| `capture` | SCRIPT | Privacy sanitizer — pure Python, called by the memory-write path (CX-30). |
| `changelog` | PROMPT | Ports as-is. |
| `code-review` | PROMPT | Inline Build-phase gate — Phase 1 priority. |
| `continuous-planning` | PROMPT | Ports as-is. |
| `cost-report` | SCRIPT | Reads `tool-timings.jsonl`-equivalent; Codex's `--json` turn-usage events (`turn.completed.usag
| `creative-direction` | PROMPT | Ports as-is. |
| `db-migration` | PROMPT | Ports as-is. |
| `debt-ledger` | PROMPT | Ports as-is. |
| `debug` | PROMPT | Environment-dependent debugging loop — ports as-is. |
| `debug-trace` | MERGED | Folds into the `--json` trace-tee wrapper (§3 Prompt Tracing row) — the toggle semantics are or
| `deploy` | PROMPT | Ports as-is. |
| `deployment-verification` | PROMPT | Ports as-is. |
| `design-qc` | DROPPED (for now) | Depends on VLM/Computer-tool screenshot-diff parity — `<unverified>` on Codex; revisit
| `design-system-init` | PROMPT | Ports as-is. |
| `embedder` | SCRIPT | Embedding-similarity search backing `recall`/`mcp_memory` — pure Python, ports with `memory/` (CX-
| `epic-breakdown` | PROMPT | Ports as-is. |
| `estimation` | PROMPT | Ports as-is. |
| `eval-model-effectiveness` | PROMPT | Ports as-is; reads the ported cost-quality correlation output from `learn` (CX-32)
| `forensics` | PROMPT | Ports as-is; reads ported `metrics/` JSONL files. |
| `greenfield-scaffold` | PROMPT | Ports as-is. |
| `harness-audit` | PROMPT | Ports as-is; verdict-consistency check re-targets `.agents/skills/` instead of `skills/`. |
| `harness-config` | PROMPT | T2 config-only dispatch target — ports as-is. |
| `health-scan` | PROMPT | Ports as-is. |
| `infra-scaffold` | PROMPT | Ports as-is. |
| `intake` | PROMPT | Fingerprint/tier-routing entry point — Phase 1 priority (CX-11). |
| `internal-eval` | PROMPT + SCRIPT | Orchestration shell ports as PROMPT; the run/score/capture sub-skills' heavy lifting
| `learn` | PROMPT | Phase 3 priority (CX-32). |
| `load-test` | PROMPT | Ports as-is. |
| `mcp_memory` | SCRIPT | Registers as a native `mcp_servers` entry (CX-31), not a Codex Skill — it's a server process, no
| `module-extraction` | PROMPT | Ports as-is. |
| `mutation-score-report` | PROMPT | Ports as-is; feeds the Law-1 CI backstop (§4). |
| `observability-setup` | PROMPT | Ports as-is. |
| `patch-critique` | PROMPT | Final-Gate skill — ports as-is. |
| `pdr-rtv` | DROPPED | Was MERGED into `dispatch-bestofn.sh`'s tournament-mode sibling; flipped to DROPPED by the Phase 7 pivot — same rationale as `best-of-n`. |
| `pipeline` | PROMPT | Core orchestrator-facing skill — Phase 1 priority (CX-11), paired with `phase-order.sh` (CX-25). |
| `pipeline-resume` | PROMPT | Ports as-is; reads the portable `pipeline-state/` contract directly. |
| `plan-cache-lookup` | PROMPT | Ports as-is. |
| `plan-cache-rollout-gate` | MERGED | Folds into CI-gate logic (CX-54), same class as `cache-flip-gate`. |
| `plan-self-validation` | PROMPT | Ports as-is. |
| `polish` | PROMPT | Ports as-is. |
| `pr-creation` | PROMPT | Ports as-is; approval-token gate check re-targets the portable `approval.token` file. |
| `product-acceptance` | PROMPT | Ports as-is. |
| `project-setup` | PROMPT | Ports as-is; becomes the `AGENTS.md`-missing bootstrap trigger (mirrors Claude's Project Read
| `property-based-test` | PROMPT | Ports as-is. |
| `qa-test-strategy` | PROMPT | Ports as-is. |
| `react-native-patterns` | PROMPT | Ports as-is. |
| `recall` | SCRIPT | Progressive-disclosure query API — pure Python, ports with `memory/` (CX-30). |
| `refactor` | PROMPT | Ports as-is. |
| `reindex-memory` | SCRIPT | Ports with `memory/` (CX-30). |
| `sandbox-verify` | PROMPT | Ports as-is; E2B sandbox dependency is agent-vendor-agnostic. |
| `security-alert-fix` | PROMPT | Ports as-is. |
| `security-review` | PROMPT | Separate-phase security gate — ports as-is. |
| `skill-builder` | PROMPT | Meta-skill for authoring new skills — Codex's own `$skill-creator` built-in (verified `codex/
| `skill-security-lint` | PROMPT | Ports as-is. |
| `smell-scan` | PROMPT | Ports as-is. |
| `spec-blind-validate` | PROMPT | Ports as-is. |
| `spec-grounding` | PROMPT | Ports as-is. |
| `spec_grounding` | DROPPED | Appears to be a duplicate/legacy-named sibling of `spec-grounding` in the source tree — fla
| `story-writing` | PROMPT | Ports as-is. |
| `swe-pruner-rollout-gate` | MERGED | Folds into CI-gate logic (CX-54), same class as `cache-flip-gate`. |
| `tech-spike` | PROMPT | T0 dispatch target — ports as-is. |
| `tool-synthesis` | PROMPT | Ports as-is; scratch tools land under `.claude-scratch-tools/`-equivalent `.codex-scratch-to
| `verify` | PROMPT | Final-Gate skill — ports as-is. |
| `vlm-critic` | DROPPED (for now) | Same VLM/Computer-tool dependency as `design-qc`. |
| `web-frontend-patterns` | PROMPT | Ports as-is. |
| `workstream` | PROMPT | Ports as-is; the `pipeline-state/workstreams/{ws}/` layout carries over unchanged. |


**Totals** (pre-pivot port decisions): 77 source entries → 2 non-skill
(README, `_deferred` dropped) → 2 DROPPED (`design-qc`, `vlm-critic`, both
VLM-dependent) + 1 DROPPED duplicate (`spec_grounding`) + 2 DROPPED by the
Phase 7 pivot (`best-of-n`, `pdr-rtv`) → **4 MERGED** into
orchestration-script/CI-gate logic (`cache-flip-gate`, `debug-trace`,
`plan-cache-rollout-gate`, `swe-pruner-rollout-gate`) → **6 SCRIPT**
(`_template`, `capture`, `cost-report`, `embedder`, `mcp_memory`,
`recall`/`reindex-memory` counted together as the memory subsystem) → the
remainder (**~62**) were ported as native Codex Skills.

**Post-pivot note**: this catalog records the original port decisions and
is kept as history. The surviving set after the Phase 8 cull (CX-80..87)
is roughly **20 contractor-core skills** — the keep-list in §5 Phase 8 is
the SSOT for what remains; a PROMPT row here does NOT mean the skill
survives the cull.


---


## 7. Risks & Known Losses


- **No mid-session `PreToolUse` prompt-mutation interception.** Confirmed:
  Codex hooks parse but skip `prompt`/`agent` handler types. Any enforcement
  that depends on rewriting a tool call's *input* in place (not just
  allow/deny it) has no home on Codex today. The workaround (orchestration
  script pre-assembles the full prompt before the `codex exec` call ever
  happens) closes most of the gap for instinct/memory injection, but there is
  no way to intercept and modify a tool call the AGENT decides to make
  mid-turn (e.g., Claude's `cache-breakpoint-injector.sh` rewriting an Agent
  spawn's cache-control blocks after the orchestrator has already handed off).
- **Single-agent context contamination between phases.** The Claude harness's
  subagent-per-phase model keeps each phase's context clean by construction
  (a fresh subagent spawn per phase, no shared conversation history). Codex's
  `codex exec` model is closer to this than a long-lived session, so this risk
  is actually LOWER on Codex than initially assumed — flag as a positive
  finding, not a loss.
- **Cost profile differences.** Codex's model lineup (`gpt-5.6`,
  `gpt-5.6-terra`, `gpt-5.4`, `gpt-5.3-codex-spark`) and reasoning-effort
  levels (`minimal`/`low`/`medium`/`high`/`xhigh`/`max`/`ultra`, model-dependent)
  do not map 1:1 onto the Claude harness's opus/sonnet/haiku tiering — the
  Agent Team table's per-role model defaults (§ CLAUDE.md source) need a fresh
  cost-quality calibration pass on Codex rather than a naive rename. Not
  attempted in this plan; flagged as a Phase 6+ follow-up.
- **Prompt-injection surface of `AGENTS.md`.** Same class of risk as Claude's
  `CLAUDE.md` — a nested `AGENTS.override.md` deeper in a checked-out repo can
  silently override the harness's own Iron Laws for that subtree. Codex's own
  docs acknowledge this precedence chain is intentional (nearer files win) —
  the harness AGENTS.md should say so explicitly and recommend reviewing any
  `AGENTS.override.md` encountered in an unfamiliar repo before trusting it,
  mirroring the general supply-chain caution the source harness already
  applies to `.codex/hooks/` trust review.
- **Hook-trust friction on every fresh clone.** Because Codex requires
  reviewing and trusting non-managed command hooks before they run
  (`/hooks` in the CLI), every fresh `codex-harness` checkout has a one-time
  manual trust step the Claude harness does not have (Claude's hooks are
  trusted by virtue of being inside `~/.claude/hooks/`, which the user already
  controls). This is a genuine UX regression versus Claude, not a bug in the
  port — document it prominently in the onboarding section of `AGENTS.md`.
- **Drift between harnesses.** Because both harnesses can share
  `pipeline-state/` and `learning/` (per §3's portability claims), a bug fixed
  in one harness's skill/hook logic but not the other's creates silent
  behavioral drift on shared state. Recommend a `scripts/lib/verify-parity.sh`
  smoke check (not scoped as a numbered task above — flag for a follow-up
  pipeline once both harnesses have run in production for a few weeks) that
  diffs the two `AGENTS.md`/`rules/core.md` Iron-Law transcriptions and fails
  CI on drift.
- **`.rules` is explicitly experimental.** OpenAI's own doc says "Rules are
  experimental and may change." Treat the Iron-Law-4-companion destructive-verb
  port (§4, CX-52) as defense-in-depth alongside the `main-branch-guard.sh`
  hook port, never as the sole enforcement layer.


---


## 8. Definition of Done (for the port itself)


Revised 2026-07-11 for the Phase 7 contractor model: Codex is the
contractor, Claude is the general contractor. "Done" no longer means the
full-port phases complete — it means the contractor kit is complete and
proven by a real shift change.


The codex-harness port is DONE when ALL of the following hold:


- Phase 0 (CX-01..04), Phase 1's surviving surface, Phase 5 (CX-50..54),
  Phase 7 (CX-70..74), and Phase 8 (CX-80..87) are complete with passing
  acceptance criteria as stated in §5. Phases 2-4 and CX-60/CX-61 are
  deferred or superseded per their per-phase notes and are NOT
  DoD-blocking.
- CX-74 (handoff round-trip dry run) completes claude → codex → claude on
  a real task: baton honoured before any `HANDOFF.md` is trusted, state
  reconciled against git/tests, ≥1 Next Action worked vertically
  single-thread, a `source: codex` observation appended, and a clean
  return handoff the Claude side resumes from.
- Every §2 table row has a fidelity rating and, for anything below FULL, an
  explicit substitution mechanism or DROPPED rationale — no silent gaps.
- Every §4 Iron Law has a stated Codex enforcement status — no law silently
  omitted from the transcription. (The Iron Laws apply to whoever is on
  shift — the hooks port stays live under the contractor model.)
- `AGENTS.md` stands alone: a fresh Codex session reading only `AGENTS.md`
  (no chased file references) can state the Iron Laws, the code shape
  rules, the worktree/commit protocol, and the baton/`HANDOFF.md` runtime
  model — with no orphaned references to the agent team, T0-T6 routing, or
  the deferred orchestration script (CX-86).
- `.agents/skills/README.md` lists only surviving skills and its aggregate
  description budget is ≤ 8,000 chars (CX-87).
- CX-90 and CX-91 probes are deferred alongside the dispatch layer they
  would inform; if that layer is ever revived, they run and record RED or
  GREEN before anything depends on them — not silently skipped.
- The Risks & Known Losses section (§7) is reviewed by a human before the
  first production shift on codex-harness — this is a plan-review gate,
  not a mechanically-checkable one.
