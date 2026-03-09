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
- 2026-03-09: Refreshed the backlog and prompt pack after confirming S01 and S02 were completed in code.
- 2026-03-09: Refreshed the backlog and prompt pack again after confirming S03 was already implemented.
- 2026-03-09: Implemented S03 plan triage stages with explicit `observe`, `reflect`, and `organize` commands backed by `plan.json`.
- 2026-03-09: Extended persisted plan state to carry per-stage notes and optional strategy text without changing the append-only findings history contract.
- 2026-03-09: Added CLI and state tests covering triage transitions, validation failures, and scan-time preservation of plan-stage metadata.
- 2026-03-09: Implemented S04 queue operations with explicit `plan focus`, `plan resolve`, and `plan reopen` commands.
- 2026-03-09: Kept manual queue actions split cleanly between `plan.json` focus changes and append-only finding status events in `findings.jsonl`.
- 2026-03-09: Added tests covering direct-id focus, cluster focus, append-only resolution events, attestation enforcement, and reopen behavior.

## Discoveries

- The spec naturally decomposes into infrastructure, queue model, detector
  breadth, review flow, and automation tracks.
- The backlog is clearer when already-shipped slices stay visible as baseline
  instead of disappearing from the sequence.
- Review prompts are easier to keep honest when they are slice-scoped rather
  than asking for a generic “does this match the spec?” pass.
- The branch advanced faster than the docs, so the durable slice backlog needs
  occasional re-sync against the actual implementation state.
- The same re-sync issue happened again with S03, so the prompt pack should be
  treated as a living operational artifact rather than a one-time handoff.
- Keeping plan-state mutations out of `findings.jsonl` makes the workflow stage
  machine much easier to reason about: scans still own observation history,
  while triage only reshapes operator intent in `plan.json`.
- Scan-time plan rebuilding needs to preserve stored stage notes and strategy
  text so triage work survives ordinary rescans.
- Explicit manual queue actions still need a shared ordering helper; otherwise
  focus changes, `next`, and post-resolution refocusing drift apart.
- `reopen` is low-risk when it is scoped to previously resolved statuses and
  simply appends a new `open` event plus a plan focus update.

## Decision Log

- 2026-03-09: Save implementation slices as a durable design-doc reference so
  implementers can use it outside a single active task.
- 2026-03-09: Keep the decomposition generic to `docgarden` infrastructure and
  explicitly defer RMN-specific detectors until the core loop is more mature.
- 2026-03-09: Model S03 as a validated lifecycle stage machine in `plan.json`
  instead of adding synthetic finding events for triage progress.
- 2026-03-09: Preserve `strategy_text` in the plan schema during S03 so the
  later `--complete --strategy` slice can land without another state-format
  migration.
- 2026-03-09: Implement S04 by adding plan-focused helpers that synchronize
  `current_focus` after manual status changes rather than teaching the CLI to
  mutate plan state ad hoc.
- 2026-03-09: Include `reopen` in S04 because it reuses the existing status
  event model cleanly and closes the loop on mistaken manual resolutions.

## Outcomes / Retrospective

Pending verification and future use by implementation work.
