---
name: "intake"
description: "Classify a request as Discuss, Small Change, Build, or human-elevated High Risk before implementation work begins."
---

# Harness Intake

Classify each new request before creating implementation state. This skill
records the route; it does not implement the request or encode the automatic
High Risk trigger catalog.

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

For an implementation gear, report the classification and continue under the
workflow in `AGENTS.md`. Small Change specification and approval behavior are
defined by T04. Automatic High Risk triggers and downgrade enforcement are
defined by T16; until T16 merges, only explicit human elevation selects High
Risk through this skill.
