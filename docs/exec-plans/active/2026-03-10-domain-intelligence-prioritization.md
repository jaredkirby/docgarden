---
doc_id: domain-intelligence-prioritization-exec-plan
doc_type: exec-plan
domain: exec-plans
owner: kirby
status: draft
last_reviewed: 2026-03-10
review_cycle_days: 14
applies_to:
  - repo
source_of_truth:
  - docs/design-docs/docgarden-spec.md
  - README.md
  - docgarden/cli.py
  - docgarden/scan/alignment.py
verification:
  method: implementation-linked
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - exec-plan
  - prioritization
  - domain-intelligence
---

# Domain Intelligence Prioritization Exec Plan

## Purpose

Prioritize the highest-leverage implementation slices that preserve
`docgarden`'s broad domain-intelligence direction while focusing first on the
capabilities this repository will use and validate most often.

## Context

The product spec intentionally reaches further than the current code. The repo
already has mechanical checks, persistent findings, score rollups, review
packet prepare/import, safe autofix for low-risk edits, and CI or PR-draft
support. The missing pieces are not equally valuable.

If we chase every spec gap in parallel, we will spend effort on features that
this repo cannot exercise well yet, especially narrow business-domain packs.
The highest-value path is to first implement domain intelligence that can
self-host inside `docgarden`: command-surface truth, config truth, workflow
truth, and plan or review lifecycle truth. Those slices improve the current
project immediately and create the shared infrastructure needed for broader
domain packs later.

## Assumptions

- Broad domain intelligence should stay a product goal, but the first slices
  should be reusable and repo-agnostic where possible.
- `docgarden` gets the most leverage from detectors that can compare docs
  against live repo truth instead of hand-maintained allowlists.
- Shared registries and rule-pack infrastructure are more valuable than
  shipping one-off metrics, platforms, or account heuristics first.
- Higher-risk automation such as generated-doc regeneration or cleanup PR
  creation should follow only after the repo can prove detector accuracy on
  self-hosted rule packs.

## Steps / Milestones

1. Define and document the prioritization rubric used for spec-gap work.
   Rank candidate slices by repo-local leverage, detector trustworthiness,
   reuse across domains, and implementation dependency depth.
2. Implement S1: shared truth registries for live command, config, and workflow
   surfaces.
   Extract supported CLI command metadata from the argparse surface, centralize
   supported validation-command checks, and expose config or `block_on` schema
   data from one source of truth.
3. Implement S2: domain-policy infrastructure before new business packs.
   Add a rule-pack or detector-registry layer so broad domain intelligence can
   be enabled by domain without hard-coding the whole product around RMN repo
   assumptions.
4. Implement S3: operational workflow intelligence as the first high-value pack.
   Detect drift between docs and live repo truth for CI workflows, review
   flows, PR-draft publish behavior, validation commands, and plan lifecycle
   instructions.
5. Implement S4: operator-surface parity that closes the most visible spec or
   implementation gaps.
   Add `docgarden review run --runner ...` and `docgarden plan triage
   --complete --strategy ...` so the documented workflow can execute without
   manual glue.
6. Implement S5: broaden safe autofix only where the new registries make the
   edits deterministic.
   Candidate follow-ons are index maintenance, command-example rewrites, and
   other low-risk registry-backed doc updates.
7. Defer S6: business-domain packs until the framework is proven.
   Metrics, platforms, accounts, and other repo-specific intelligence should
   land only after S1-S4 stabilize and after at least one self-hosted pack
   demonstrates acceptable signal quality.

## Validation

- `uv run pytest`
- `uv run docgarden scan`
- Targeted regression coverage for new detector registries, review or plan CLI
  surfaces, and any new safe-fix paths

## Progress

- 2026-03-10: Compared the current implementation against the design spec and
  identified the main missing slices.
- 2026-03-10: Ranked self-hosted command, config, and workflow intelligence as
  the highest-leverage next investment.
- 2026-03-10: Wrote this prioritization plan to guide the next implementation
  pass.

## Discoveries

- The current validation-command checker already shows why shared truth
  registries matter: it can drift behind real CLI capabilities even inside the
  same repo.
- Many of the most visible spec gaps are not missing detectors; they are
  missing integration surfaces that would let higher-level intelligence stay
  honest.
- Broad domain intelligence without a pack or registry model would push the
  project toward brittle, repo-specific conditionals instead of a reusable
  framework.
- This repo can validate workflow and operator-intelligence slices every day,
  while business-domain packs would remain mostly speculative until adopted by a
  richer target repo.

## Decision Log

- 2026-03-10: Prioritize self-hosted operational intelligence over speculative
  RMN-specific packs because it yields immediate product value and produces
  better feedback loops.
- 2026-03-10: Treat shared command, config, and workflow truth registries as
  prerequisites for most of the remaining spec gaps.
- 2026-03-10: Keep broad domain intelligence in scope by introducing rule-pack
  infrastructure before adding new domain-specific detectors.
- 2026-03-10: Defer cleanup PR automation and generated-doc regeneration until
  the repo has stronger deterministic edit primitives backed by live truth
  registries.

## Outcomes / Retrospective

Pending implementation of the first prioritized slice.
