---
doc_id: docgarden-slice-loop-automation-exec-plan
doc_type: exec-plan
domain: exec-plans
owner: kirby
status: draft
last_reviewed: 2026-03-09
review_cycle_days: 14
applies_to:
  - repo
source_of_truth:
  - docs/design-docs/docgarden-implementation-slices.md
  - docs/design-docs/docgarden-spec.md
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - exec-plan
  - automation
  - slices
---

# Docgarden Slice Loop Automation Exec Plan

## Purpose

Automate the manual implementation-slice loop so `docgarden` can generate the
next slice prompt, run a Codex worker, run a Codex reviewer, feed revision
findings back into the worker, and advance to the next slice only when review
recommends doing so.

## Context

The repo already has a durable implementation backlog and a manually maintained
prompt pack. The current human loop works, but it is repetitive and vulnerable
to prompt drift. The next step is to make the loop itself a first-class command
inside `docgarden`.

## Assumptions

- The implementation-slice backlog stays the durable source of truth for slice
  order, status, dependencies, and acceptance criteria.
- `codex exec` is available locally when operators choose to run the automated
  loop.
- Structured JSON outputs are a better automation boundary than trying to parse
  free-form prose from worker and reviewer agents.

## Steps / Milestones

1. Parse slice metadata directly from the implementation backlog doc.
2. Generate implementation and review prompts from that metadata.
3. Add a CLI command that can run Codex worker and reviewer passes in a loop.
4. Persist prompts, schemas, outputs, and logs under `.docgarden/`.
5. Update the README and docs routing so the new automation is discoverable.
6. Verify the command surface and loop behavior with tests.

## Validation

- `uv run pytest`
- `uv run docgarden scan`

## Progress

- 2026-03-09: Added a slice-automation module that parses the implementation backlog and derives implementation/review prompts from it.
- 2026-03-09: Added `docgarden slices next`, `kickoff-prompt`, `review-prompt`, and `run` command surfaces.
- 2026-03-09: Wired `docgarden slices run` to call `codex exec` with structured worker and reviewer output schemas and to persist run artifacts under `.docgarden/slice-loops/`.
- 2026-03-09: Added tests covering backlog parsing, prompt rendering, and a multi-round worker/reviewer loop that revises once and then advances to the next slice.
- 2026-03-09: Updated the README and plan routing so the new loop is discoverable from the normal repo entry points.
- 2026-03-09: Repackaged the automation into a reusable `docgarden.slices` module and kept `docgarden.slice_automation` as a compatibility re-export.
- 2026-03-09: Added configurable path resolution for the slice backlog, spec, exec plan, and artifact directory so other project repos can use the loop without copying this repo’s exact docs layout.

## Discoveries

- The slice backlog is a stronger automation source than the manual prompt pack because it already contains the goal, planned changes, dependencies, and acceptance criteria in a stable structure.
- Structured reviewer output is the critical control point for the loop; once the recommendation is machine-readable, retry vs advance decisions become deterministic.
- The loop still benefits from durable human-readable artifacts, so prompt text, JSON schemas, structured outputs, and stdout/stderr logs should all be kept under `.docgarden/slice-loops/`.
- Advancing to the next slice should not depend on docs being updated in the middle of the same run; the command can progress through the ordered slice catalog it parsed at startup.
- Reuse depends more on configurable document paths than on the prompt text itself; the hardcoded repo-doc locations were the main thing preventing clean adoption in other repos.

## Decision Log

- 2026-03-09: Generate prompts from `docs/design-docs/docgarden-implementation-slices.md` instead of scraping the manual prompt pack.
- 2026-03-09: Use `codex exec` with `--output-schema` and `--output-last-message` so the loop consumes structured JSON instead of brittle prose parsing.
- 2026-03-09: Keep the default run bounded to one slice at a time with `--max-slices 1`, while allowing `--max-slices 0` for continuous advancement.
- 2026-03-09: Persist run artifacts inside `.docgarden/` because the automation loop is an operational stateful workflow, not just a transient convenience wrapper.
- 2026-03-09: Keep the reusable Python API under `docgarden.slices` and reserve the top-level `docgarden.slice_automation` import as a backwards-compatible shim.

## Outcomes / Retrospective

Pending real-world use of the automated loop across future slices.
