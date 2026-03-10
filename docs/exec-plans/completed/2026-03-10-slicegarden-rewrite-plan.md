---
doc_id: slicegarden-rewrite-exec-plan
doc_type: exec-plan
domain: exec-plans
owner: kirby
status: archived
last_reviewed: 2026-03-10
review_cycle_days: 14
applies_to:
  - repo
source_of_truth:
  - docs/exec-plans/completed/2026-03-10-slice-loop-standalone-packaging.md
  - docs/exec-plans/completed/2026-03-10-remove-slice-module.md
  - AGENTS.md
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - exec-plan
  - rewrite
  - slices
  - skills
  - standalone-package
---

# Slicegarden Rewrite Exec Plan

## Purpose

Design a fresh standalone package that turns an implementation plan into
machine-generated execution slices, then runs a skill-driven worker/reviewer
automation loop over those slices until the plan is complete or blocked.

The package should not inherit the current `docgarden` slice automation
architecture by default. Reuse ideas, not structure.

## Context

The current `docgarden` slice loop proved that:

- a worker/reviewer loop is operationally useful
- structured reviewer outputs are a strong control point
- durable artifact directories make retries and recovery workable
- repo-specific prompt text and defaults become the main barrier to reuse

The next version should promote a different boundary:

- input: an implementation plan document or prompt
- slicer: a Codex-powered slice compiler
- runtime: a general execution engine over those slices
- skills: first-class role instructions loaded intentionally per phase
- adapters: host-repo configuration for paths, verification, and policy

## Assumptions

- `docgarden` no longer needs to ship the slice runtime internally.
- The new package can break from the old architecture instead of wrapping it
  forever for compatibility.
- Planning, execution, and skill binding should each have their own durable
  artifacts and contracts.

## Package Name

The new package should be named `slicegarden`.

Why this name:

- it suggests turning a broad plan into shaped implementation slices
- it feels repo-neutral and product-like
- it leaves room for both planning and execution capabilities

## Product Definition

`slicegarden` is a standalone package and CLI for:

1. ingesting an implementation plan
2. asking Codex to slice that plan into dependency-aware work items
3. storing the resulting slice backlog in a durable machine-readable format
4. running a worker/reviewer loop over each actionable slice
5. using explicit SKILLS to shape worker and reviewer behavior
6. keeping artifacts, run history, and recovery state inspectable

## Key Design Shift

The current system starts from a hand-authored slice backlog and generates
prompts from it.

`slicegarden` should instead start from a higher-level implementation plan and
own the slice-compilation step itself.

That means there are two loops, not one:

1. a plan-to-slices compilation loop
2. a slice execution loop

Treat them as separate subsystems with separate artifacts, commands, and
failure modes.

## Core User Flow

1. A human provides an implementation plan file or inline prompt.
2. `slicegarden plan compile` calls Codex to produce a structured slice backlog.
3. The compiled backlog is stored under `.slicegarden/plans/<plan-id>/`.
4. `slicegarden run` selects the next dependency-ready slice.
5. The runtime assembles role-specific instructions by combining:
   - the package’s built-in role contract
   - configured host-repo policy text
   - relevant SKILLS
   - slice-specific context
6. A worker agent implements the slice.
7. A reviewer agent checks the result against the slice contract.
8. If revision is needed, the reviewer’s structured findings go back to the
   worker.
9. If accepted, the runtime marks the slice complete and advances.
10. Operators can watch, retry, recover, or stop runs from persisted artifacts.

## Steps / Milestones

1. Finalize the standalone package architecture, contracts, and storage model.
2. Define the compiler, runtime, skill runtime, and host adapter boundaries.
3. Implement the sliced delivery plan in independently reviewable increments.
4. Validate the package in real repo integrations before treating the rewrite
   as stable.

## Design Principles

- Separate planning from execution.
- Keep the runtime event-driven and state-explicit.
- Make SKILLS a formal input, not an incidental prompt mention.
- Prefer structured contracts over prose parsing.
- Let host repos supply policy, verification, and file-layout adapters.
- Keep the package usable from both CLI and Python.
- Make every long-running action resumable from artifacts.

## High-Level Architecture

### 1. Plan Compiler

Responsibility:

- read an implementation plan
- call Codex once to generate normalized slices
- validate and persist the resulting slice graph

Inputs:

- plan markdown file or inline prompt
- optional repo context paths
- optional host policy profile
- optional SKILLS to bias slicing behavior

Outputs:

- `plan.json`
- `slice-graph.json`
- `slice-backlog.md`
- compiler prompt and schema artifacts
- compiler run logs

Notes:

- the compiler should be idempotent for the same plan version unless
  `--recompile` is explicitly requested
- the compiler output should become the durable source of truth for the
  execution loop, not the original free-form plan text

### 2. Slice Runtime

Responsibility:

- schedule actionable slices
- run worker and reviewer passes
- persist round artifacts and state transitions
- stop cleanly on blocked or no-progress states

Inputs:

- compiled slice graph
- runtime configuration
- role skill bindings
- verifier configuration

Outputs:

- run ledger
- worker artifacts
- reviewer artifacts
- status snapshots
- recovery guidance

### 3. Skill Orchestrator

Responsibility:

- load configured SKILLS for each role
- inject the right skill bodies or summaries into the worker/reviewer prompt
- keep skill use explicit and reproducible in artifacts

This should not rely on the model casually noticing a skill name in prose.

Instead, the runtime should maintain explicit role bindings like:

- `planner_skills`
- `slicer_skills`
- `worker_skills`
- `reviewer_skills`
- `recovery_skills`

Each binding should support:

- required skills
- optional skills
- host-repo custom skills
- package-owned default skills

### 4. Host Adapter Layer

Responsibility:

- describe repo-specific defaults without polluting the core engine

Examples:

- where plans live
- where artifacts should be written
- how verification should run
- which docs or paths are authoritative
- which SKILLS should be attached by default
- commit policy and branch policy

## Why SKILLS Must Be First-Class

The current system tells the model what to do entirely through generated prompt
text. That works, but it is fragile and hard to reuse.

In `slicegarden`, skills should become a typed input to the runtime.

That means:

- each role prompt records which skills were applied
- each artifact directory stores the resolved skill list
- host repos can override role skills without forking prompt templates
- the package can ship role-oriented built-in skills

Recommended built-in skills:

- `slicegarden-plan-slicer`
  Teaches Codex how to turn implementation plans into dependency-aware,
  independently reviewable slices.
- `slicegarden-worker`
  Teaches Codex how to execute a single slice tightly and produce structured
  output.
- `slicegarden-reviewer`
  Teaches Codex how to perform scope-aware review and emit actionable revision
  feedback.
- `slicegarden-recovery-operator`
  Teaches Codex how to diagnose timeouts, partial work, and retry/recover
  decisions.

These should follow the `skill-creator` guidance:

- keep the skill bodies concise
- move bulky reference material into references files
- use role-specific instructions rather than giant universal prompts
- make variant-specific content host-configurable instead of duplicating it

## Data Model

### Plan

- `plan_id`
- `source_path`
- `source_hash`
- `compiled_at`
- `compiler_model`
- `status`
- `summary`

### Slice

- `slice_id`
- `title`
- `goal`
- `depends_on`
- `scope_constraints`
- `planned_changes`
- `acceptance_criteria`
- `verification_targets`
- `likely_files`
- `status`
- `priority`

### Role Binding

- `role`
- `required_skills`
- `optional_skills`
- `resolved_skill_paths`
- `host_policy_snippet`

### Run Ledger Entry

- `run_id`
- `plan_id`
- `slice_id`
- `phase`
- `round`
- `status`
- `started_at`
- `updated_at`
- `agent_backend`
- `model`
- `skills_applied`
- `artifacts`
- `error`

## Storage Layout

Prefer a package-owned root like:

```text
.slicegarden/
  config.yaml
  plans/
    <plan-id>/
      source-plan.md
      compile/
        compiler.prompt.txt
        compiler.schema.json
        compiler.output.json
        compiler.stdout.txt
        compiler.stderr.txt
      slices/
        slice-graph.json
        slice-backlog.md
  runs/
    <timestamp>-<slice-id>/
      run-status.json
      role-bindings.json
      worker-round-1.prompt.txt
      worker-round-1.output.json
      review-round-1.prompt.txt
      review-round-1.output.json
      *.stdout.txt
      *.stderr.txt
  history/
    events.jsonl
```

Use machine-readable JSON as the control plane. Markdown should be for humans,
not for internal state transitions.

## CLI Surface

### Planning

- `slicegarden plan compile --plan <path>`
- `slicegarden plan show --plan-id <id>`
- `slicegarden plan export-markdown --plan-id <id>`
- `slicegarden plan recompile --plan-id <id>`

### Slice Inspection

- `slicegarden slices list --plan-id <id>`
- `slicegarden slices next --plan-id <id>`
- `slicegarden slices show --slice <id>`

### Runtime

- `slicegarden run --plan-id <id> --max-slices 1`
- `slicegarden watch --run <id>`
- `slicegarden stop --run <id>`
- `slicegarden retry --run <id>`
- `slicegarden recover --run <id>`

### Skills

- `slicegarden skills show`
- `slicegarden skills resolve --role worker`
- `slicegarden skills doctor`

### Validation

- `slicegarden doctor`
- `slicegarden validate plan --plan-id <id>`

## Runtime Contract

### Compiler Phase

The compiler Codex call must emit structured JSON only. It should produce:

- normalized plan summary
- ordered slices
- dependencies
- acceptance criteria
- suggested file scopes
- reviewer focus notes

### Worker Phase

The worker must emit structured JSON only. It should produce:

- status
- summary
- files touched
- tests run
- docs updated
- notes for reviewer
- open questions

### Reviewer Phase

The reviewer must emit structured JSON only. It should produce:

- recommendation
- summary
- findings
- next step
- progress assessment relative to prior round

### No-Progress Guardrail

Do not rely only on textual signature matching.

Instead, use a combination of:

- reviewer finding signature
- changed-file delta between rounds
- worker self-reported closure map

Stop when the reviewer findings are materially unchanged across consecutive
rounds and the file delta suggests no meaningful movement.

## Recommended Implementation Architecture

Do not rebuild this as one central runner module.

Use these package boundaries instead:

- `slicegarden.plan_compiler`
- `slicegarden.slice_store`
- `slicegarden.scheduler`
- `slicegarden.agent_backend`
- `slicegarden.skill_runtime`
- `slicegarden.execution`
- `slicegarden.ledger`
- `slicegarden.recovery`
- `slicegarden.cli`
- `slicegarden.host_adapter`

Suggested responsibilities:

- `plan_compiler`
  One-shot plan-to-slices compilation and schema validation.
- `slice_store`
  Read/write compiled plans and slice graphs.
- `scheduler`
  Select next actionable slices and track dependency readiness.
- `agent_backend`
  Wrap Codex execution and leave room for future backends.
- `skill_runtime`
  Resolve role-bound skills and build role instruction packets.
- `execution`
  Own the worker/reviewer phase machine.
- `ledger`
  Persist event log plus latest materialized state.
- `recovery`
  Diagnose interrupted runs and rerun verification.
- `host_adapter`
  Translate repo-specific configuration into package-neutral settings.

## Host Configuration

Use a single host config file such as `.slicegarden/config.yaml`.

Recommended shape:

```yaml
plan:
  default_path: docs/exec-plans/completed/2026-03-10-remove-slice-module.md
compiler:
  model: gpt-5-codex
  required_skills:
    - slicegarden-plan-slicer
worker:
  required_skills:
    - slicegarden-worker
reviewer:
  required_skills:
    - slicegarden-reviewer
verification:
  commands:
    - uv run pytest
    - uv run docgarden scan
artifacts:
  root: .slicegarden
policy:
  commit_mode: atomic
  branch_prefix: slicegarden/
```

This should be additive. CLI flags can override config, but config should be
the default source of truth.

## Plan-Slicing Design

The input to the compiler should be the implementation plan, not a pre-sliced
backlog.

Recommended compiler workflow:

1. Read the plan markdown.
2. Optionally read referenced spec docs.
3. Resolve planner and slicer skills.
4. Call Codex with a schema that forces:
   - small, reviewable slices
   - explicit dependencies
   - acceptance criteria per slice
   - likely files per slice
   - anti-spillover notes
5. Validate the slice graph.
6. Reject malformed or contradictory output.
7. Persist the accepted slice graph.

Compiler acceptance rules:

- no circular dependencies
- every queued slice has acceptance criteria
- every slice is independently reviewable
- no slice mixes unrelated themes without justification
- the plan summary remains traceable back to the source plan

## Better Design Choices Than The Current System

### 1. Event-Sourced State Over Ad Hoc Status Files

Keep a materialized `run-status.json`, but treat it as a cache of the event
ledger rather than the only source of truth.

Benefits:

- easier recovery
- easier audits
- easier replay after crashes
- cleaner upgrade path for state schema changes

### 2. Skill Packets Over Monolithic Prompts

Instead of one large prompt builder per role, build a role packet from:

- base role contract
- resolved skills
- host policy
- slice context
- prior round context

Benefits:

- better composability
- smaller, more understandable prompts
- clearer artifact provenance

### 3. Structured Compiler Phase

The current system assumes slices already exist. The new system should own the
plan-slicing stage as a first-class command and artifact set.

Benefits:

- less manual prep
- more reuse across repos
- cleaner source-of-truth model

### 4. Host Adapter Pattern

Do not force every repo to look like `docgarden`.

Benefits:

- easier adoption
- fewer hard-coded defaults
- better long-term package boundaries

## Risks

- the compiler may produce unstable slice boundaries across recompiles unless
  plan versioning and idempotence rules are explicit
- skill-driven prompts can drift if built-in skills and host repo skills
  overlap or contradict one another
- event sourcing adds complexity if overbuilt too early
- a plan compiler that is too flexible can create low-quality slices unless the
  schema and acceptance rules are strict

## Decisions

- Build a fresh standalone package rather than extracting the current runner as
  the package’s primary architecture.
- Make plan compilation a first-class subsystem.
- Make SKILLS explicit runtime inputs by role.
- Use a host adapter/config layer instead of repo-shaped defaults.
- Keep Codex as the first backend, but isolate it behind an agent backend
  boundary.
- Use `.slicegarden/` as the package-owned artifact root.

## Sliced Delivery Plan

### Slice 1: Package Skeleton

Goal:

- create the standalone `slicegarden` package skeleton, CLI root, config
  loading, and artifact root conventions

Acceptance:

- `slicegarden --help` works
- `.slicegarden/` config and artifact roots are recognized

### Slice 2: Host Config And Skill Binding

Goal:

- load host config and resolve role-bound skills into explicit packets

Acceptance:

- `skills show` and `skills resolve` work
- role packets can be materialized for planner, worker, and reviewer

### Slice 3: Plan Compiler

Goal:

- compile an implementation plan into a validated slice graph via Codex

Acceptance:

- `plan compile` produces durable JSON plus markdown backlog output
- compiler artifacts are inspectable and schema-validated

### Slice 4: Scheduler And Slice Store

Goal:

- persist slice graphs and select the next dependency-ready slice

Acceptance:

- `slices list`, `slices next`, and `slices show` work against compiled plans

### Slice 5: Worker Runtime

Goal:

- run a worker against a single slice with skill packets and durable artifacts

Acceptance:

- worker run artifacts persist correctly
- timeout and launch failures are inspectable

### Slice 6: Reviewer Runtime

Goal:

- add structured reviewer passes and revision routing

Acceptance:

- reviewer findings can trigger a second worker round
- accepted slices advance cleanly

### Slice 7: Ledger And Recovery

Goal:

- add event logging, watch/stop/retry/recover behavior, and no-progress
  detection

Acceptance:

- interrupted runs are recoverable from artifacts
- no-progress churn stops deterministically

### Slice 8: Docgarden Adapter

Goal:

- add a compatibility adapter or wrapper so `docgarden` can invoke
  `slicegarden` without preserving the old internal architecture

Acceptance:

- `docgarden` can consume `slicegarden` as a dependency or wrapper path

### Slice 9: Fixture Repo Validation

Goal:

- prove the package works in a non-docgarden temp repo

Acceptance:

- end-to-end compile plus run works with custom config, skills, and verification

### Slice 10: Packaging And Release

Goal:

- publish the package with install docs and migration guidance

Acceptance:

- package builds cleanly
- install and migration docs are complete

## Validation

- `uv run docgarden scan`
- doc-reviewed consistency check of this plan
- before implementation begins, convert this exec plan into a compiled
  `slicegarden` plan once the compiler exists and compare the output slices to
  the sliced delivery plan above

## Progress

- 2026-03-10: Wrote the clean-slate `slicegarden` rewrite plan after removing
  the in-repo slice module from `docgarden`.

## Discoveries

- The biggest missed opportunity in the current system is that slicing is still
  manual. Owning plan compilation is the clearest upgrade.
- Skills should be an explicit orchestration feature, not merely words inside
  prompts.
- A standalone package should own its storage model, not inherit
  repo-maintenance naming like `.docgarden/slice-loops`.

## Decision Log

- 2026-03-10: Build a fresh standalone package rather than extracting the
  current runner as the package’s primary architecture.
- 2026-03-10: Make plan compilation a first-class subsystem.
- 2026-03-10: Make SKILLS explicit runtime inputs by role.
- 2026-03-10: Use a host adapter/config layer instead of repo-shaped defaults.
- 2026-03-10: Keep Codex as the first backend, but isolate it behind an agent
  backend boundary.
- 2026-03-10: Use `.slicegarden/` as the package-owned artifact root.

## Outcomes / Retrospective

Archived on 2026-03-10 because the clean-slate `slicegarden` rewrite is
outside the active scope of this repository. Keep this plan as historical
design context rather than live `docgarden` work.

## Recommended Next Step

Start with a design-only implementation slice that defines:

- the `slicegarden` config schema
- the compiler output schema
- the role skill binding model
- the event ledger schema

That will stabilize the package boundary before any runtime code lands.
