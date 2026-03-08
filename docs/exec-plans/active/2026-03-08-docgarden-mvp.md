---
doc_id: docgarden-mvp-exec-plan
doc_type: exec-plan
domain: exec-plans
owner: kirby
status: draft
last_reviewed: 2026-03-08
review_cycle_days: 14
applies_to:
  - repo
source_of_truth:
  - pyproject.toml
verification:
  method: implementation-linked
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - exec-plan
  - mvp
---

# Docgarden MVP Exec Plan

## Purpose

Build a Phase 1 implementation of `docgarden` that can scan repo docs, persist
findings, compute quality scores, and publish a quality report.

## Context

The repository is starting from an empty workspace, so the MVP needs both tool
code and enough documentation structure to validate against.

## Assumptions

- Python 3.11+ is available.
- Initial scope favors deterministic mechanical checks over subjective review.
- The first version can focus on `docs/` plus `AGENTS.md`.

## Steps / Milestones

1. Create repo scaffolding, configuration, and initial docs.
2. Implement scanning, scoring, and persistent findings.
3. Add a narrow safe-fix path for headings and stale status.
4. Verify the CLI against this repository.

## Validation

- `python -m pytest`
- `python -m docgarden.cli scan --scope all`
- `python -m docgarden.cli quality write`

## Progress

- 2026-03-08: Created the initial specification-aligned repository scaffold.

## Discoveries

- The repo started empty, so self-hosting docs are part of the implementation.

## Decision Log

- 2026-03-08: Start with a Python CLI and standard-library-first design.
- 2026-03-08: Limit safe autofix to clearly mechanical documentation edits.

## Outcomes / Retrospective

Pending implementation and verification.
