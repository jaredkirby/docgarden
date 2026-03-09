---
doc_id: docgarden-spec-slicing-exec-plan
doc_type: exec-plan
domain: exec-plans
owner: kirby
status: draft
last_reviewed: 2026-03-09
review_cycle_days: 14
applies_to:
  - repo
source_of_truth:
  - docs/design-docs/docgarden-spec.md
  - docs/design-docs/docgarden-implementation-slices.md
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - exec-plan
  - planning
  - slicing
---

# Docgarden Spec Slicing Exec Plan

## Purpose

Turn the full `docgarden` spec into an implementation backlog made of atomic,
mergeable slices.

## Context

The spec has grown large enough that it is easy to agree with conceptually while
still struggling to decide what to build next. The repo needs a durable map from
spec sections to PR-sized implementation units.

## Assumptions

- The current repo already covers the Phase 1 mechanical baseline.
- The right next planning artifact is a slice backlog, not a new high-level
  roadmap.
- Each slice should be independently verifiable with tests and `docgarden scan`.

## Steps / Milestones

1. Identify which parts of the full spec are already shipped.
2. Group the remaining work into small, dependency-aware slices.
3. Write a durable backlog doc under `docs/design-docs/`.
4. Route the new backlog from design-doc and plan indexes.
5. Verify the docs remain scan-clean.

## Validation

- `uv run docgarden scan`
- `uv run docgarden quality write`

## Progress

- 2026-03-09: Created the first atomic-slices backlog for the full spec.
- 2026-03-09: Routed the backlog from the design-doc and plan indexes.
- 2026-03-09: Added reusable implementation and PM-review prompts for S01 and S02 handoff.

## Discoveries

- The spec naturally decomposes into infrastructure, queue model, detector
  breadth, review flow, and automation tracks.
- The backlog is clearer when already-shipped slices stay visible as baseline
  instead of disappearing from the sequence.
- Review prompts are easier to keep honest when they are slice-scoped rather
  than asking for a generic “does this match the spec?” pass.

## Decision Log

- 2026-03-09: Save implementation slices as a durable design-doc reference so
  implementers can use it outside a single active task.
- 2026-03-09: Keep the decomposition generic to `docgarden` infrastructure and
  explicitly defer RMN-specific detectors until the core loop is more mature.

## Outcomes / Retrospective

Pending verification and future use by implementation work.
