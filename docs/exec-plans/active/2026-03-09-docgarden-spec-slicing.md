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
- 2026-03-09: Tightened S04 after review so `plan resolve` only operates on currently actionable queue items, and added clearer CLI help for repetitive operator flows.
- 2026-03-09: Re-reviewed S04 against the slice backlog and prompt pack, then advanced the durable agent prompts so the next implementation kickoff targets S05 instead of already-shipped queue work.
- 2026-03-09: Implemented S05 changed-scope scans with `docgarden scan --scope changed`, including git-derived doc selection plus an explicit `--files` override for CI-style callers.
- 2026-03-09: Kept full scans as the only authoritative state refresh and made changed-scope output explicitly list the recomputed checks, skipped repo-wide views, and any last full-scan score baseline.
- 2026-03-09: Added tests covering git-derived changed scans, explicit file-list scans, subset-only detector execution, validation failures for non-doc paths, and read-only partial-scan behavior against persisted `.docgarden` state.
- 2026-03-09: Tightened S05 after review so changed-scope scans do not even create `.docgarden/` on first use, and explicit `--files` inputs now fail fast on missing doc-shaped paths instead of inferring deletions.
- 2026-03-09: Documented the git-derived changed-set rule in CLI help, scan output notes, and the README so operators can predict which files `--scope changed` will inspect.
- 2026-03-09: Re-synced the durable prompt pack after S05 landed, promoted the next implementation kickoff to S06, and refreshed the README so the public command overview matches the current queue and scan workflow.
- 2026-03-09: Implemented S06 generated-doc contract checks so `doc_type: generated` docs now require populated provenance details, not just the documented section headings.
- 2026-03-09: Added local upstream freshness comparison for generated docs, using the generated timestamp plus local file mtimes to flag stale generated references when the source file is newer.
- 2026-03-09: Added tests covering missing provenance metadata, stale local upstream files, fresh local upstream files, and graceful skips for remote or non-file upstream references.
- 2026-03-09: Tightened S06 after review so non-HTTP URI schemes such as `s3://` and `gs://` now degrade gracefully instead of being misclassified as missing local files.
- 2026-03-09: Tightened the generated-doc contract so regeneration commands must look runnable, and generated timestamps must be offset-aware ISO-8601 values before freshness comparisons run.
- 2026-03-09: Updated the durable slice backlog and README so they now reflect S06 as completed and point the next handoff at S07 workflow drift detection.
- 2026-03-09: Implemented S07 workflow drift detection by reusing shared markdown section/link helpers, scanning only workflow-like sections, and emitting actionable `missing-workflow-asset` findings for missing repo-owned local references.
- 2026-03-09: Added regression coverage for the S07 detector so missing local workflow assets are caught while external URLs, virtualenv command examples, Python module invocations, and design-doc planning references stay quiet.
- 2026-03-09: Implemented S08 routing quality detection so repo-wide scans now keep missing-target `broken-route` findings separate from `stale-route` findings when AGENTS or index docs still route readers to archived, deprecated, or superseded stale docs.
- 2026-03-09: Extended routing-quality evidence and recommended actions to surface canonical replacements from `superseded_by` when the replacement resolves to a current canonical doc.
- 2026-03-09: Added regression coverage for archived index routes, replacement suggestions, and the "stale only when a better canonical route exists" boundary.

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
- Queue commands need to stay queue-scoped; once a finding is already resolved,
  further status edits should go through a reopen step rather than another
  resolve action.
- Prompt packs drift behind implementation unless they are updated as part of
  slice review, so the review step should explicitly promote the next kickoff
  to the next queued slice.
- Partial scans cannot safely reuse the full-scan append-and-auto-resolve path:
  doing so would incorrectly mark unscanned findings as fixed.
- The safest S05 boundary is to treat changed-scope scans as fast, explicit
  previews that run document-local detectors only and leave durable score/plan
  state to full scans.
- CI-oriented changed-file inputs do not need a separate file-of-paths format
  yet; a direct `--files` list is enough for this slice and keeps the product
  surface small.
- Workflow drift needs narrower heuristics than generic broken-link detection:
  local asset references should be read from workflow-style sections and
  command/link snippets, not from planning prose such as "files likely
  touched" lists in design docs.
- Historical exec plans still contain useful shell examples like
  `.venv/bin/...` and `python -m docgarden.cli ...`, so the detector has to
  recognize virtualenv paths and Python module syntax as execution context, not
  missing repo-owned assets.
- "Read-only partial scan" needs to be interpreted literally: even creating the
  state-directory skeleton is a surprising side effect when no durable state is
  supposed to change.
- Explicit file lists are more predictable when they mean "existing files to
  scan now" only; deletions should stay a git-derived concern unless the CLI
  grows a separate explicit deleted-path input.
- The README is more useful when it explains both the full-scan source-of-truth
  loop and the narrower changed-scope preview loop; otherwise operators can
  infer the wrong authority from partial-scan commands.
- Generated-doc headings alone are not enough signal: the scanner needs
  content-aware provenance checks to catch empty sections and placeholder prose.
- Local directory paths show up naturally when generated docs describe a source
  folder rather than a single artifact, so freshness checks need to skip
  non-file paths instead of claiming the doc is stale.
- URI-style references need an explicit non-local escape hatch; otherwise
  generic path heuristics turn `s3://...`-style sources into false local-file
  failures.
- Freshness comparisons are only deterministic when generated timestamps carry
  an explicit offset, so the contract needs to reject naive timestamps instead
  of quietly interpreting them in host-local time.
- Index routing quality cannot rely on AGENTS-style raw path extraction alone;
  the scanner also has to inspect resolved markdown links because most index
  docs route readers with relative links rather than repo-root path literals.

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
- 2026-03-09: Treat `plan resolve` as a queue operation, not a general status
  editor, so it must reject non-actionable findings even though the event log
  itself remains append-only.
- 2026-03-09: Implement S05 changed-scope scans as non-persisting partial
  previews so full scans remain the source of truth for `findings.jsonl`,
  `plan.json`, `score.json`, and repo-wide quality claims.
- 2026-03-09: Skip duplicate-doc-id, broken-route, and orphan-doc recomputation
  during changed-scope scans instead of approximating them from stale global
  state, and report those omissions explicitly in the CLI output.
- 2026-03-09: Make changed-scope command setup avoid `ensure_state_dirs()` so a
  first-use partial scan leaves no `.docgarden/` footprint behind.
- 2026-03-09: Define explicit `--files` as an existing-doc list only; missing
  paths are validation errors, while deleted docs remain discoverable through
  git-derived changed scope.
- 2026-03-09: Model S06 provenance validation as one aggregated
  `generated-doc-contract` finding per doc so missing source, timestamp,
  upstream path, and regeneration command details stay actionable without
  spamming the queue.
- 2026-03-09: Only emit generated-doc freshness failures when the upstream
  reference resolves to an existing local file; remote URLs, descriptive text,
  directories, and missing local paths degrade to contract checks or skips
  rather than misleading stale findings.
- 2026-03-09: Treat any non-`file:` URI scheme as non-local for artifact
  resolution so storage or SSH references degrade gracefully instead of being
  reinterpreted as repo-relative paths.
- 2026-03-09: Require generated timestamps to be offset-aware ISO-8601 values
  before freshness checks run, and treat single-token path snippets like
  `scripts/generate_schema.py` as non-runnable regeneration placeholders unless
  they are invoked as an actual command.
- 2026-03-09: Model S08 as a separate `stale-route` detector scoped to AGENTS
  and `index.md` current-truth routers, leaving `broken-route` focused on
  missing targets so route existence and route quality stay distinguishable.

## Outcomes / Retrospective

Pending verification and future use by implementation work.
