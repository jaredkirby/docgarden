---
doc_id: slice-loop-standalone-packaging-exec-plan
doc_type: exec-plan
domain: exec-plans
owner: kirby
status: archived
last_reviewed: 2026-03-10
review_cycle_days: 14
applies_to:
  - repo
source_of_truth:
  - docs/exec-plans/completed/2026-03-10-remove-slice-module.md
  - docs/exec-plans/completed/2026-03-10-slicegarden-rewrite-plan.md
  - README.md
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - exec-plan
  - packaging
  - slices
  - codex
---

# Slice Loop Standalone Packaging Exec Plan

## Purpose

Package the existing implementation-slice automation into a standalone Python
package that can be installed and used from other repositories without copying
`docgarden` wholesale.

## Context

The slice loop already exists and is not a thin prototype. Today it spans:

- catalog parsing in `docgarden/slices/catalog.py`
- prompt rendering and schemas in `docgarden/slices/prompts.py`
- run configuration in `docgarden/slices/config.py`
- worker/reviewer orchestration in `docgarden/slices/runner.py`,
  `docgarden/slices/run_execution.py`, and `docgarden/slices/run_agent.py`
- run-state, retry, watch, stop, prune, and recovery helpers in
  `docgarden/slices/run_status.py` and `docgarden/slices/run_recovery.py`
- CLI wiring in `docgarden/cli_slices.py`,
  `docgarden/cli_slices_commands.py`, and `docgarden/cli_slices_runtime.py`
- regression coverage in `tests/test_slice_automation.py`

The README already positions this as reusable from other repos via path
overrides, but the implementation still carries `docgarden`-specific defaults,
language, and verification behavior.

## Assumptions

- The standalone package will become the durable home for future slice-loop
  work.
- `docgarden` no longer needs to keep shipping the in-repo slice runtime while
  the extracted package design continues.
- Compatibility concerns matter, but they should not block removal of the old
  implementation from this repository.

## Current Findings

### What is already reusable

- The execution engine is already split into focused modules instead of hiding
  behind one large facade.
- Path resolution is configurable, so other repos can already point at custom
  slice backlogs, specs, exec plans, and artifact directories.
- The worker/reviewer loop is mostly driven by structured JSON contracts rather
  than brittle free-form parsing.
- The test suite already covers prompt generation, multi-round revise-then-pass
  behavior, timeout handling, retry/recover flows, and artifact management.

### What is still coupled to `docgarden`

- `build_slice_paths()` and the CLI help text were shaped around repo-local
  backlog, spec, exec-plan, and `.docgarden/slice-loops` defaults rather than
  a neutral host-profile model.
- worker prompts hard-code `uv run docgarden scan`, README/exec-plan update
  guidance, and the local `docgarden-slice-orchestrator` skill name.
- recovery hard-codes `uv run pytest` plus `uv run docgarden scan` as the
  verification contract.
- the subsystem imports `DocgardenError` and `atomic_write_text` from the
  surrounding package instead of owning its own tiny utilities.
- the markdown catalog parser assumes the current `docgarden` slice backlog
  shape and `S##` identifiers.
- the Codex runner hard-codes nested `codex exec` defaults and disabled MCP
  server names that may not be right for every downstream repo.
- the public entry point is the `docgarden slices ...` CLI family, which makes
  adoption feel like importing a repo-maintenance tool rather than a standalone
  slice runner.

## Goal State

Create a standalone package, tentatively named `slicegarden`, with:

- a repo-agnostic Python API for loading slice definitions, generating prompts,
  and running the worker/reviewer loop
- a first-class CLI such as `slicegarden ...`
- configuration that lets downstream repos define their own backlog paths,
  prompt wording, verifier commands, artifact root, and Codex launch settings
- a compatibility adapter so `docgarden slices ...` can delegate to the new
  package during migration
- docs and examples that show both greenfield use and `docgarden` compatibility

## Non-Goals

- redesign the slice backlog format in the first extraction pass
- support non-Codex agent backends in v1 unless that falls out naturally from
  a small runner interface
- move all of `docgarden` into a monorepo of packages
- build hosted orchestration or remote state sync

## Packaging Strategy

### Phase 1: Define the extraction boundary

1. Create a new package boundary around the existing slice subsystem rather
   than starting from scratch.
2. Treat these as the initial export candidates:
   - catalog parsing
   - prompt rendering and JSON schemas
   - run configuration models
   - worker/reviewer execution engine
   - run-status and recovery helpers
3. Leave `docgarden`-specific docs and operator skills in this repo, but make
   them consumers of the extracted package.

### Phase 2: Introduce repo-agnostic interfaces

1. Replace hard-coded defaults with a profile/config model.
   - `catalog_path`
   - `spec_path`
   - `plan_path`
   - `artifacts_dir`
   - verification commands
   - prompt policy text
   - Codex launch defaults
2. Split prompt generation into:
   - invariant loop instructions
   - repo/profile-specific guidance
3. Move generic error and file-write utilities into the extracted package so it
   no longer imports from `docgarden.errors` or `docgarden.files`.
4. Rename the docgarden-shaped config objects to neutral terms where needed.

### Phase 3: Create the standalone package

1. Stand up a new distributable package directory and `pyproject.toml`.
2. Publish a stable API surface, for example:
   - `slicegarden.catalog`
   - `slicegarden.config`
   - `slicegarden.prompts`
   - `slicegarden.runner`
   - `slicegarden.run_status`
3. Add a dedicated CLI:
   - `slicegarden next`
   - `slicegarden kickoff-prompt`
   - `slicegarden review-prompt`
   - `slicegarden run`
   - `slicegarden watch`
   - `slicegarden stop`
   - `slicegarden recover`
   - `slicegarden retry`
   - `slicegarden list`
   - `slicegarden prune`
4. Add package-owned docs explaining the required backlog format and minimal
   repo setup.

### Phase 4: Migrate `docgarden` to consume the package

1. Replace direct imports from `docgarden.slices.*` with imports from the new
   package or a thin compatibility shim.
2. Keep `docgarden slices ...` as a compatibility surface for at least one
   transition release.
3. Preserve the existing CLI contract where practical so current operators do
   not need a flag-day migration.
4. Update README, skill docs, and exec plans to point at the extracted package
   as the durable home for the loop.

### Phase 5: Prove reuse in another repo

1. Create a fixture repo or temp-repo integration test that is explicitly not
   laid out like `docgarden`.
2. Install the standalone package there and drive the loop using:
   - custom catalog/spec/plan paths
   - custom verification commands
   - custom artifact root
3. Do not call the extraction done until that cross-repo proof passes.

## Steps / Milestones

1. Define the extraction boundary and repo-neutral interfaces.
2. Build the standalone package and CLI surface.
3. Migrate `docgarden` to consume or reference the standalone package.
4. Prove the package in a non-docgarden repo before treating the move as done.

## Proposed Work Breakdown

1. Prep slice: inventory public imports, rename anything that would be awkward
   to support long-term, and document the proposed standalone package contract.
2. Config slice: introduce a neutral profile/config object and thread it
   through prompts, recovery, and CLI defaults.
3. Core extraction slice: move the reusable modules into the new package with
   their own tiny utility helpers and tests.
4. CLI slice: add the standalone CLI and keep `docgarden slices` as a wrapper.
5. Verification slice: replace hard-coded recovery commands with configurable
   command lists and document sane defaults.
6. Adoption slice: add end-to-end smoke coverage against a non-docgarden temp
   repo and update the docs.
7. Release slice: build/publish the package and document installation and
   upgrade guidance.

## Acceptance Criteria

- Another repository can install the new package and run the slice loop without
  importing the rest of `docgarden`.
- The extracted package owns its own errors, file utilities, packaging config,
  and CLI entry point.
- Verification commands and prompt add-ons are configurable instead of
  `docgarden`-hard-coded.
- `docgarden slices ...` still works during the migration window.
- Regression coverage exists for both the standalone CLI and the compatibility
  path inside this repo.

## Validation

- `uv run pytest`
- `uv run docgarden scan`
- a temp-repo smoke test using the standalone package and non-default paths

## Progress

- 2026-03-10: Captured the standalone-packaging direction after removing the
  in-repo slice module from `docgarden`.

## Discoveries

- The remaining extraction work is now mostly productization and package
  design, not preserving a compatibility wrapper around live repo code.
- Repo-shaped docs, verification commands, and operator language are part of
  the coupling just as much as Python imports are.

## Decision Log

- 2026-03-10: Switch this plan’s local verification to `uv run pytest` because
  the dedicated slice-automation test module no longer lives in this repo.
- 2026-03-10: Treat this plan as forward-looking packaging work, not as a
  requirement to keep the old `docgarden slices` surface alive here.

## Outcomes / Retrospective

Archived on 2026-03-10 because standalone slice-package work no longer belongs
in the active `docgarden` repo queue. Keep this plan as historical context for
the extraction direction.

## Risks

- Prompt quality may regress if repo-specific guidance is stripped out too
  aggressively. Keep a profile layer instead of forcing one generic prompt.
- The current markdown parser may be too opinionated for other teams. If that
  becomes a blocker, treat parser pluggability as the first extension point.
- Recovery behavior is more repo-specific than the run loop itself because
  verification commands and acceptable artifact roots differ by project.
- The Codex launch defaults that are correct for this environment may be too
  opinionated for downstream adopters, especially around MCP disabling and
  sandbox/network flags.

## Decisions To Make Before Coding

- Final package name: `slicegarden`, `codex-slices`, or another repo-neutral
  name.
- Whether the backlog parser remains markdown-only in v1 or ships with a small
  parser interface.
- Whether verification configuration lives in CLI flags, a YAML file, Python
  API config, or some combination.
- Whether the standalone package should preserve the existing `S##` slice id
  convention or relax it in the initial release.

## Recommended First Implementation Slice

Introduce a repo-neutral `SliceLoopProfile` and thread it through:

- `docgarden/slices/config.py`
- `docgarden/slices/prompts.py`
- `docgarden/slices/run_recovery.py`
- `docgarden/cli_slices.py`
- `docgarden/cli_slices_commands.py`
- `docgarden/cli_slices_runtime.py`

That slice buys the most extraction leverage with the lowest migration risk,
because it removes the biggest remaining source of repo-specific coupling
without forcing an immediate package move.
