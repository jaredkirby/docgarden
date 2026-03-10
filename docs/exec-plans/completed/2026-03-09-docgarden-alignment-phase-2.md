---
doc_id: docgarden-alignment-phase-2-exec-plan
doc_type: exec-plan
domain: exec-plans
owner: kirby
status: archived
last_reviewed: 2026-03-10
review_cycle_days: 14
applies_to:
  - repo
source_of_truth:
  - SPEC-FULL.md
  - docs/design-docs/docgarden-spec.md
  - docgarden/scan/scanner.py
verification:
  method: implementation-linked
  confidence: medium
supersedes: []
superseded_by: docs/exec-plans/active/2026-03-10-domain-intelligence-prioritization.md
tags:
  - exec-plan
  - alignment
  - phase-2
---

# Docgarden Alignment Phase 2 Exec Plan

## Purpose

Implement the first alignment detector slice and promote the full product spec
into the scanned docs tree.

## Context

The MVP shipped mechanical checks, score generation, persistent findings, and a
narrow safe-fix path. The new design spec calls for alignment detectors, richer
planning, and stronger routing for durable design docs.

## Assumptions

- The first alignment pass should stay narrow enough to avoid false positives on
  draft design docs.
- Verified and non-draft docs are the best first place to enforce artifact
  alignment.
- We can extend the current scanner without changing the existing CLI surface.

## Steps / Milestones

1. Add `docs/design-docs/` with a routed spec mirror and index.
2. Create a follow-on exec plan for Phase 2 alignment work.
3. Add a first alignment detector for missing `source_of_truth` artifacts and
   unsupported `docgarden` validation commands.
4. Update tests and verify the new detector against this repo.
5. Use the next iteration to add resolution attestation and broader plan
   lifecycle commands.

## Validation

- `uv run pytest`
- `uv run docgarden scan`
- `uv run docgarden quality write`

## Progress

- 2026-03-09: Added durable design-docs routing for the full product spec.
- 2026-03-09: Started Phase 2 alignment detector implementation.
- 2026-03-09: Verified the S01 alignment slice with targeted tests and added the
  initial S02 finding lifecycle state model for richer statuses and
  attestation-ready metadata.
- 2026-03-09: Tightened S01 so alignment finding IDs are deterministic,
  Validation subheadings are scanned correctly, and repo-local artifact checks
  cover common non-URL file targets beyond the initial suffix allowlist.

## Discoveries

- A naive command drift detector would flag the future CLI examples inside the
  draft spec, so alignment checks need to respect doc status and trust level.
- The current `Alignment to artifacts` score weight exists already, but it needs
  real detector coverage to be meaningful.
- Scoring has to derive from the latest persisted finding state, not just the
  raw detector output, or statuses like `accepted_debt` never affect
  `overall_score`.
- The alignment slice needs deterministic finding suffixes because plan order,
  append-only history, and later resolution events all key off stable IDs.
- Validation blocks commonly use nested headings, so section parsing has to stop
  only at the next sibling-or-parent heading instead of the next heading of any
  depth.

## Decision Log

- 2026-03-09: Keep the full spec as a routed reference mirror under
  `docs/design-docs/` so it is discoverable without forcing canonical-section
  structure onto a proposal doc.
- 2026-03-09: Start alignment detection with trustworthy local artifacts and
  repo-local `docgarden` commands before attempting broader schema or workflow
  drift.
- 2026-03-09: Preserve append-only findings history by writing manual status
  changes as new JSONL events and carrying their resolution metadata forward on
  later observation events instead of mutating old lines.
- 2026-03-09: Generate alignment finding suffixes from deterministic slugs plus
  a stable digest instead of Python runtime hashes, and treat ordinary repo file
  paths like `scripts/check.sh` and `Makefile` as eligible local artifacts.

## Outcomes / Retrospective

Archived on 2026-03-10 after the first alignment slice shipped. Follow-on
domain-intelligence prioritization now lives in
`docs/exec-plans/active/2026-03-10-domain-intelligence-prioritization.md`.
