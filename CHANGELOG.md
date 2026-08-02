# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com).

## [Unreleased]

### Added

- Add deterministic High Risk trigger routing with auditable human-authorized downgrade decisions
- Add security-first review sign-off ordering, telemetry binding, and sensitive-change invalidation
- Add atomic verification evidence bound to reviewed and current Git HEAD
- Add read-only deterministic verifier dispatch gated by durable spawn telemetry
- Add a fail-closed, identity-bound native Codex adapter for Tier 3.5 semantic mutants
- Add an identity- and model-bound read-only Code Reviewer dispatch and targeted re-review loop with fresh telemetry evidence
- Add an orchestrator protected-write boundary whose Software Engineer dispatch capability is issued only after a correlated telemetry canary and activation record are durably read back
- Add an inactive telemetry-gated Software Engineer dispatch facade with deterministic execution profiles and durable spawn accounting, pending the T13A activation prerequisite
- Add strict versioned dispatch contracts and least-privilege Codex Agent profiles for the five standalone workflow roles
- Add explicit human decisions for resuming or starting pipeline tasks
- Add read-only discovery of repository-matching active pipeline tasks
- Add symlink-safe atomic writes for canonical pipeline state
- Add managed Python mutation tooling with a 70% score gate for pipeline state
- Add fail-closed validation for canonical and legacy pipeline state documents
- Add canonical-first, read-only pipeline state discovery with supported legacy flat-path compatibility
- Add fail-closed Small Change compact specifications and approval gating
- Add deterministic standalone intake routing for Discuss, Small Change, Build, and human-elevated High Risk workflows
- Add a commit-bound Builder/Guardian delivery gate with automatic Guardian dispatch, independently sourced patch review, isolated review, independent verification, and fail-closed handoff validation

### Fixed

- Honor the explicitly authorized PR quality-gate bypass before loading migration-era gate helpers
