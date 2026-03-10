---
doc_id: docs-index
doc_type: canonical
domain: docs
owner: kirby
status: verified
last_reviewed: 2026-03-10
review_cycle_days: 30
applies_to:
  - repo
source_of_truth:
  - AGENTS.md
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - routing
  - docs
---

# Docs Index

## Purpose

Route agents and contributors to the canonical documentation for this repository.

## Scope

This index covers the durable documentation that defines how `docgarden` works
and how multi-step work should be tracked.

## Source of Truth

- [AGENTS.md](../AGENTS.md)
- [Tool plans](PLANS.md)

## Rules / Definitions

- `docs/index.md` is the primary documentation entry point.
- Active implementation work belongs in `docs/exec-plans/active/`.
- Design intent and future-shape specs live in `docs/design-docs/`.
- Generated quality output is published in `docs/QUALITY_SCORE.md`.
- Repo automation under `.github/workflows/docgarden-*.yml` enforces scans,
  publishes score artifacts, and keeps scheduled review or autofix runs
  auditable.

## Exceptions / Caveats

- Historical notes can live outside this index if they are archived and not
  routed as current truth.

## Validation / How to verify

- Run `docgarden scan`.
- Confirm routed files exist and remain current.

## Related docs

- [QUALITY_SCORE.md](QUALITY_SCORE.md)
- [PLANS.md](PLANS.md)
- [Design docs index](design-docs/index.md)
- [Docgarden spec](design-docs/docgarden-spec.md)
- [Domain intelligence prioritization exec plan](exec-plans/active/2026-03-10-domain-intelligence-prioritization.md)
