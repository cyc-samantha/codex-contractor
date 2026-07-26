# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com).

## [Unreleased]

### Added

- Add a commit-bound Builder/Guardian delivery gate with automatic Guardian dispatch, independently sourced patch review, isolated review, independent verification, and fail-closed handoff validation

### Fixed

- Honor the explicitly authorized PR quality-gate bypass before loading migration-era gate helpers
