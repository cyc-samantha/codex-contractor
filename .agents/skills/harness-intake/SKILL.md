---
name: "intake"
description: "Classify a request as Discuss, Small Change, Build, or human-elevated High Risk before implementation work begins."
---

# Harness Intake

Classify each new request before creating implementation state. This skill
records the route; it does not implement the request or encode the automatic
High Risk trigger catalog.

Translate the request into these ordered inputs, then run:

```bash
.agents/skills/harness-intake/scripts/route.sh \
  <kind> <scope-clear> <dependency-change> <architecture-change> \
  <human-elevated>
```

Boolean inputs use `true` or `false`. Supported `kind` values are `question`,
`research`, `brainstorm`, `architecture-discussion`, `documentation`,
`configuration`, `bug`, `feature`, and `refactor`. An unknown value routes to
Build. Any other kind, missing argument, or non-canonical boolean fails closed
with exit 2. Dependency or architecture changes route to Build even when the
request would otherwise be Discuss.

## Routing order

Apply these rules in order:

1. If the human elevates the task to High Risk, choose High Risk.
2. If the request is only a question, research, brainstorming, or architecture
   discussion, choose Discuss.
3. If the request is a documentation, simple configuration, or localized
   low-risk edit with clear scope and no architecture or dependency change,
   choose Small Change.
4. If the request is a bug, feature, or refactor, choose Build.
5. If scope, dependencies, architecture impact, or classification is uncertain, choose Build.

A human High Risk elevation always wins. Never downgrade it.

| Gear | Request shape | Implementation state |
|---|---|---|
| Discuss | Question, research, brainstorming, or architecture discussion | No |
| Small Change | Clear, localized, low-risk documentation or configuration edit | Yes |
| Build | Bug, feature, or refactor | Yes |
| High Risk | Human explicitly elevates the request | Yes |

## Required output

Emit this compact record before continuing:

```yaml
gear: <Discuss | Small Change | Build | High Risk>
reason: <one sentence>
human_elevated: <true | false>
implementation_state: <create | none>
```

For Discuss, set `implementation_state: none` and do not create a worktree, task state, commit, or PR.

For Build and High Risk, record a plan before implementation.
A medium or large plan requires explicit human approval; do not enter Build until that approval is recorded.
Small Change specification and approval behavior are
defined by T04. Automatic High Risk triggers and downgrade enforcement are
defined by T16; until T16 merges, only explicit human elevation selects High
Risk through this skill.
