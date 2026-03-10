---
doc_id: remove-slice-module-exec-plan
doc_type: exec-plan
domain: exec-plans
owner: kirby
status: archived
last_reviewed: 2026-03-10
review_cycle_days: 14
applies_to:
  - repo
source_of_truth:
  - README.md
  - pyproject.toml
verification:
  method: implementation-linked
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - exec-plan
  - deprecation
  - cleanup
---

# Remove Slice Module Exec Plan

## Purpose

Remove the extracted slice automation surface from `docgarden` so this
repository only ships the documentation-quality tooling that still belongs
here.

## Context

The slice worker/reviewer loop was moved out of this project, but this repo
still exposes the `docgarden slices` CLI family, ships the `docgarden.slices`
package, and routes contributors into slice-specific docs and skills.

## Assumptions

- Slice automation is now owned elsewhere and should no longer be presented as
  first-class `docgarden` behavior.
- Historical planning notes can remain in the repo if they are no longer routed
  as current truth.
- Removing the feature should also remove repo-local skills and reference docs
  that only exist to operate that feature.

## Steps / Milestones

1. Remove the `docgarden slices` CLI registration and implementation modules.
2. Delete slice-specific tests, local skills, and design-doc references.
3. Update README and canonical indexes so they describe the current project
   scope.
4. Run tests and `docgarden scan` to catch stale references.

## Validation

- `uv run pytest`
- `uv run docgarden scan`

## Progress

- 2026-03-10: Started removing the in-repo slice module, its operator skill,
  and its routed documentation surfaces.
- 2026-03-10: Removed the `docgarden slices` CLI surface, deleted the in-repo
  slice runtime and tests, updated the README and routed docs, and verified the
  repo with `uv run pytest` plus `uv run docgarden scan`.

## Discoveries

- Slice-specific transient artifact paths were still treated as ignorable in PR
  draft changed-file collection, so the cleanup needs to trim that policy too.
- The public README had grown a large slice-automation section that would have
  left the feature looking supported even after the code deletion.

## Decision Log

- 2026-03-10: Delete slice-only design docs instead of keeping stale routed
  references to commands that no longer ship.
- 2026-03-10: Keep historical exec-plan files in the repo for provenance, but
  stop routing current users to the old slice implementation plan as active
  product behavior.

## Outcomes / Retrospective

Archived on 2026-03-10 after the slice-removal change landed and verification
passed. `docgarden` now treats the slice loop as extracted historical scope
rather than active repo functionality.
