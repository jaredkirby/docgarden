---
doc_id: design-docs-index
doc_type: canonical
domain: design-docs
owner: kirby
status: verified
last_reviewed: 2026-03-10
review_cycle_days: 30
applies_to:
  - repo
source_of_truth:
  - SPEC-FULL.md
  - docs/design-docs/docgarden-spec.md
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - design
  - specs
  - routing
---

# Design Docs Index

## Purpose

Route agents and contributors to durable design intent for `docgarden`.

## Scope

This index covers product-shape documents that explain where `docgarden` should
grow beyond the current MVP implementation.

## Source of Truth

- [Full spec working draft](../../SPEC-FULL.md)
- [Docgarden spec](docgarden-spec.md)

## Rules / Definitions

- `docs/design-docs/` holds durable design intent rather than transient task
  notes.
- The spec can get ahead of implementation, but active exec plans should record
  which parts are currently being built.
- When the tool behavior changes in a durable way, the relevant design doc
  should be updated alongside code and plans.

## Exceptions / Caveats

- Draft design targets are allowed to describe behavior that is not implemented
  yet.
- When implementation and design docs disagree, current code and active exec
  plans win until the design doc is reviewed.

## Validation / How to verify

- Run `docgarden scan`.
- Confirm this index links to the current spec and active implementation plans.

## Related docs

- [Docs index](../index.md)
- [Docgarden spec](docgarden-spec.md)
- [Domain intelligence prioritization exec plan](../exec-plans/active/2026-03-10-domain-intelligence-prioritization.md)
