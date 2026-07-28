# codex-harness

## Purpose

A thin contractor fallback kit that ports the Claude Code harness's
engineering discipline onto OpenAI Codex CLI. It shares one
`HARNESS_DATA` root with the Claude harness (memory, learning, and eval
state live there, not in a local copy) — this is **not** a full port.
Codex is normally a single-thread contractor. Guarded delivery uses an opt-in
coordinator that launches one isolated Builder and a separate fresh-context,
read-only Guardian before deterministic verification. The rest of the kit is
the enforcement hooks, skill catalog, and pipeline-state contract. See
`PLAN.md` for the full capability mapping and `AGENTS.md` for the
standalone playbook (13 Iron Laws, code shape rules, phase order,
worktree/commit protocol).

## Install

Run `scripts/install-skills.sh` to install the ported skill catalog.
The script is idempotent — running it again on an already-installed
checkout is safe and makes no further changes.

## Trust the hooks

Codex CLI requires a one-time review-and-trust step before it will run
the enforcement hooks shipped inside this repo (`.codex/hooks/`).
Unlike the Claude harness, whose hooks live under `~/.claude/hooks/` and
are implicitly trusted, a fresh `codex-harness` checkout ships hooks
*inside the repo*, so Codex treats them as untrusted until you approve
them. Follow the flow in `.codex/hooks/TRUST.md` (run `/hooks` in the
CLI, read each script, then trust it) before doing any pipeline work —
until you do, the enforcement layer is silently inert.

## Testing

Run `bats tests/shell/` to execute the enforcement-hook test suite.
Requires `bats` and `jq` on `PATH`. CI runs the same command via
`.github/workflows/harness-gate.yml`.

### Python mutation testing

Create an isolated local environment; do not commit `.venv/`:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
mutmut run
mutmut results --all true | python3 scripts/check-mutation-score.py
```

The checked-in mutmut configuration limits mutation testing to
`scripts/lib/pipeline_state.py` and its unit tests. The score check enforces
the required 70% killed-mutant threshold; use `mutmut results` to inspect any
surviving mutants.

## Layout

- `AGENTS.md` — merged CLAUDE.md + rules/core.md, Codex-native autoload
- `.agents/skills/` — ported skill catalog
- `.codex/` — `config.toml`, `hooks/`, `rules/`
- `scripts/` — skill installation and the guarded-delivery coordinator
- `scripts/codex-harness` — opt-in Builder–Guardian workflow coordinator;
  see `docs/BUILDER-GUARDIAN.md`
- `pipeline-state/` — portable per-task state contract, including the
  `HANDOFF-CONTRACT.md` baton protocol
- `tests/shell/` — the enforcement-hook (bats) test suite

## Gotchas

- `.codex/config.toml` ships with `[mcp_servers.memory]` commented out
  by design: it points at the shared `${HARNESS_DATA:-$HOME/.claude}/
  mcp_memory/server.py`, the live Claude-side server (there is no local
  `memory/` port). Uncommenting it before that path is reachable fails
  every `codex exec`, because `required = true` is intentionally
  fail-closed.
- LF line endings are enforced via `.gitattributes`
  (`* text=auto eol=lf`) — a CRLF-touched `AGENTS.md` once produced an
  872-line phantom diff.
- Runtime state (memory, eval, learning, pipeline-state content) is
  never committed — only code and curated seed content live in this
  repo.

## License

No `LICENSE` file is included. This is an intentional, advisory
decision for the current pre-publication state of this repo, not an
oversight — if this repo is ever published, add a license file
separately at that time.
