---
doc_id: docgarden-implementation-slices
doc_type: reference
domain: design-docs
owner: kirby
status: draft
last_reviewed: 2026-03-09
review_cycle_days: 14
applies_to:
  - repo
source_of_truth:
  - docs/design-docs/docgarden-spec.md
  - docs/exec-plans/active/2026-03-09-docgarden-spec-slicing.md
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - implementation
  - slicing
  - roadmap
---

# Docgarden Implementation Slices

## Purpose

Break the full `docgarden` spec into atomic implementation slices that can be
picked up as small, independently verifiable changes.

## Scope

This doc translates the design target in
[`docgarden-spec.md`](docgarden-spec.md) into a sequenced backlog for this
repository. It focuses on implementation order, dependencies, and acceptance
criteria rather than re-explaining the whole product vision.

## Source of Truth

- [Docgarden spec](docgarden-spec.md)
- [Docgarden spec slicing exec plan](../exec-plans/active/2026-03-09-docgarden-spec-slicing.md)
- [Current scanner](../../docgarden/scanner.py)

## How to use this backlog

- Treat each slice as one PR-sized unit of work.
- Do not combine adjacent slices unless their acceptance criteria are already
  naturally satisfied by the same code change.
- When a slice lands, update this doc or move the evidence into an exec plan if
  the next work item changes.
- Prefer finishing a slice end to end: code, tests, docs, and scan verification.

## Rules / Definitions

- `completed`: already implemented in the repo and kept here to show baseline.
- `active`: currently underway or partially shipped.
- `queued`: not started; safe to pick up next when dependencies are satisfied.
- `blocked`: intentionally deferred behind another slice.
- `atomic`: small enough to merge independently without requiring a multi-PR
  coordination window.

## Slice summary

| Slice | Status | Goal | Depends on |
| --- | --- | --- | --- |
| S00 | completed | Mechanical doc scan foundation | none |
| S01 | completed | First alignment checks | S00 |
| S02 | completed | Findings lifecycle with attestation-ready state | S00 |
| S03 | completed | Plan triage commands and lifecycle stages | S02 |
| S04 | completed | Focus and resolve queue operations | S02, S03 |
| S05 | completed | Changed-scope scans | S00 |
| S06 | completed | Generated-doc contract checks | S00 |
| S07 | completed | Workflow drift detector | S01 |
| S08 | completed | Routing quality detector for stale targets | S01 |
| S09 | completed | Score trend and weighted domain rollups | S02 |
| S10 | completed | Review packet preparation and import | S02, S03 |
| S11 | completed | Safe autofix expansion | S07, S08 |
| S12 | completed | CI enforcement and scheduled automation | S03, S09, S11 |
| S13 | queued | Draft PR / issue automation | S12 |
| S14 | blocked | Promotion suggestions from transient docs | S10 |

## Current baseline

The repo has already shipped the Phase 1 core:

- metadata, section, stale-review, link, route, orphan, and trust checks
- persistent findings, plan, score, and run summaries
- score publication to `docs/QUALITY_SCORE.md`
- deterministic safe autofix for stale status, missing headings, metadata
  skeletons, and unambiguous internal link or route repairs

The repo has also completed the first six generic Phase 2 slices:

- missing local `source_of_truth` artifact checks
- unsupported `docgarden` validation command checks on non-draft docs
- findings lifecycle statuses beyond `open` and `fixed`
- attestation-ready status metadata in append-only findings history
- plan triage stages with persisted stage notes and lifecycle state
- focus, resolve, and reopen queue operations with append-only status events
- changed-scope scans that inspect only changed docs and report partial-scan
  limitations explicitly
- generated-doc contract checks that enforce populated provenance details,
  runnable regeneration commands, and freshness against local upstream files
- workflow drift checks that scan workflow-style sections for missing
  repo-owned local asset references while ignoring external references and
  keeping false positives low on design-doc planning content
- routing quality checks that keep `broken-route` findings distinct from
  `stale-route` findings and flag AGENTS/index routes that still point current
  readers at archived, deprecated, or superseded stale docs
- score state trend summaries that persist across scans, configurable
  domain-weighted rollups, and separate critical-domain regression reporting so
  `score.json` and `QUALITY_SCORE.md` show both weighted and raw domain scores
- deterministic `docgarden review prepare` packets that capture targeted docs
  plus current mechanical context without baking in runner-specific prompts
- strict `docgarden review import` ingestion that stores review payloads under
  `.docgarden/reviews/`, appends subjective findings with provenance, and keeps
  them separate from mechanical scan observations during later rescans

## Atomic slices

### S00: Mechanical scan foundation

Status: `completed`

Goal:
- Establish a usable CLI that scans docs, stores findings, calculates scores,
  and publishes a quality report.

Touches:
- `docgarden/scanner.py`
- `docgarden/quality.py`
- `docgarden/state.py`
- `docgarden/cli*.py`

Acceptance:
- `docgarden scan`, `status`, `next`, `plan`, and `quality write` work on this
  repo.
- Findings persist under `.docgarden/`.
- Tests cover baseline mechanical detectors.

### S01: First alignment checks

Status: `completed`

Goal:
- Start giving the "Alignment to artifacts" score real signal.

Changes:
- Detect missing local `source_of_truth` artifacts.
- Detect unsupported `docgarden` validation commands on non-draft docs.

Why atomic:
- It improves trust scoring without changing the wider queue model.

Acceptance:
- Alignment findings appear as their own `kind`s.
- Draft docs are not punished for future CLI examples.
- Repo tests and scans pass cleanly.

### S02: Findings lifecycle and attestation-ready state

Status: `completed`

Goal:
- Expand the finding event model so non-trivial resolution can be tracked
  honestly.

Changes:
- Support statuses beyond `open` and `fixed`: `in_progress`,
  `accepted_debt`, `needs_human`, and `false_positive`.
- Add optional resolution metadata such as `attestation`, `resolved_by`,
  `resolution_note`, and `resolved_at`.
- Preserve append-only history semantics in `findings.jsonl`.

Files likely touched:
- `docgarden/models.py`
- `docgarden/state.py`
- `tests/test_support_modules.py`

Acceptance:
- Event log can represent observation plus manual resolution events.
- `overall_score` excludes `accepted_debt`; `strict_score` still counts it.
- Existing scans remain backward compatible with old event history.

### S03: Plan triage commands and lifecycle stages

Status: `completed`

Goal:
- Turn the current passive plan file into an explicit workflow stage machine.

Changes:
- Add `docgarden plan triage --stage observe|reflect|organize --report ...`.
- Persist triage notes and lifecycle stage in `plan.json`.
- Surface current stage in `docgarden plan`.

Files likely touched:
- `docgarden/cli.py`
- `docgarden/cli_commands.py`
- `docgarden/models.py`
- `docgarden/state.py`

Acceptance:
- Triage commands update plan state without mutating findings history.
- `plan.json` can hold stage notes and strategy text.
- Tests cover stage transitions and state validation errors.

### S04: Focus and resolve queue operations

Status: `completed`

Goal:
- Make the queue actionable instead of read-only.

Changes:
- Add `docgarden plan focus <cluster-or-id>`.
- Add `docgarden plan resolve <finding-id> --result ... --attest ...`.
- Optionally add `reopen` for reversing mistaken resolution.

Files likely touched:
- `docgarden/cli.py`
- `docgarden/cli_commands.py`
- `docgarden/state.py`

Acceptance:
- Focus changes `current_focus` predictably.
- Resolution writes a new append-only event instead of mutating old lines.
- Non-trivial results require attestation text.

### S05: Changed-scope scans

Status: `completed`

Goal:
- Support faster local and CI feedback by scanning only changed files when that
  is safe.

Changes:
- Add `docgarden scan --scope changed`.
- Determine touched docs from git state or a provided file list.
- Recompute score safely for partial scans, or clearly document limitations.

Files likely touched:
- `docgarden/cli.py`
- `docgarden/cli_commands.py`
- `docgarden/scanner.py`

Acceptance:
- Changed-scope scan only inspects the intended subset.
- Full scan behavior remains unchanged.
- Partial-scan output is explicit about what was and was not recomputed.
- Partial scans stay read-only against durable `.docgarden` state and leave
  authoritative score/plan updates to full scans.

### S06: Generated-doc contract checks

Status: `completed`

Goal:
- Enforce the generated-doc rules from the spec rather than only documenting
  them.

Changes:
- Validate required headings for `doc_type: generated`.
- Compare generated doc freshness against upstream artifact or script mtime when
  the path is local.
- Verify regeneration command presence.

Files likely touched:
- `docgarden/scan_document_rules.py`
- `docgarden/scan_alignment.py`
- `tests/test_docgarden.py`

Acceptance:
- Generated docs missing provenance metadata receive findings.
- Local upstream artifact timestamps can mark a generated doc stale.
- Non-local or non-file sources degrade gracefully.

### S07: Workflow drift detector

Status: `completed`

Goal:
- Catch docs that instruct contributors to use scripts, commands, or paths that
  no longer exist.

Changes:
- Scan workflow-like docs for local script/path references.
- Flag references to missing scripts or commands that the repo expects to own.
- Reuse the current parsing helpers where possible instead of adding a second
  markdown parser.

Files likely touched:
- `docgarden/scan_alignment.py`
- `docgarden/markdown.py`
- `tests/test_support_modules.py`

Acceptance:
- Missing workflow assets produce actionable findings with evidence.
- External commands and URLs are ignored.
- False positives stay low on design docs and historical references.

### S08: Routing quality detector for stale targets

Status: `completed`

Goal:
- Move beyond "route exists" toward "route points to the right kind of doc".

Changes:
- Detect AGENTS or index routes that point to archived, deprecated, or stale
  docs when a better canonical route exists.
- Flag archive docs that are still routed as current truth.
- Optionally suggest the canonical replacement when `superseded_by` is present.

Files likely touched:
- `docgarden/scan_linkage.py`
- `docgarden/scanner.py`
- `tests/test_docgarden.py`

Acceptance:
- Broken and low-quality routing are distinguishable finding types.
- Archived docs routed from indexes are flagged.
- Suggested replacements appear in evidence or recommended action when known.

### S09: Score trend and weighted domain rollups

Status: `completed`

Goal:
- Make `score.json` useful for change over time, not just a snapshot.

Changes:
- Persist trend summary points in score state.
- Add configurable domain weights for rollup scoring.
- Highlight critical-domain regressions separately from general score drift.

Files likely touched:
- `docgarden/quality.py`
- `docgarden/models.py`
- `docgarden/state.py`
- `.docgarden/config.yaml`

Acceptance:
- Trend points survive across scans.
- Domain weighting is configurable and tested.
- `QUALITY_SCORE.md` can summarize the weighted rollup without hiding raw scores.

### S10: Review packet preparation and import

Status: `completed`

Goal:
- Create the first subjective-review pathway without coupling it tightly to one
  runner.

Changes:
- Add `docgarden review prepare` to export targeted review packets.
- Add `docgarden review import <file>` to ingest structured findings.
- Store imported reviews under `.docgarden/reviews/`.

Files likely touched:
- `docgarden/cli.py`
- `docgarden/cli_commands.py`
- `docgarden/models.py`
- `docgarden/state.py`

Acceptance:
- Review packets are reproducible and file-based.
- Imported findings preserve provenance and remain distinguishable from
  mechanical scan findings.
- Invalid imports fail closed with clear errors.

### S11: Safe autofix expansion

Status: `completed`

Goal:
- Expand the safe-fix path to cover clearly mechanical doc repairs.

Changes:
- Repair broken internal links when the replacement is unambiguous.
- Add missing metadata skeletons where safe.
- Update indexes or route references when a replacement target is deterministic.

Files likely touched:
- `docgarden/fixers.py`
- `docgarden/scan_alignment.py`
- `tests/test_docgarden.py`

Acceptance:
- Preview mode explains what would change.
- `--apply` only edits deterministic, low-risk cases.
- Fixers never rewrite business rules or truth-bearing prose.

### S12: CI enforcement and scheduled automation

Status: `completed`

Goal:
- Move `docgarden` from a local tool to a repo enforcement loop.

Changes:
- Add PR workflow for scan, score, and blocking checks.
- Add nightly workflow for full scan, quality write, and safe autofix.
- Add weekly workflow for review prompts or owner nudges.

Files likely touched:
- `.github/workflows/docgarden-pr.yml`
- `.github/workflows/docgarden-nightly.yml`
- `.github/workflows/docgarden-weekly-review.yml`
- docs explaining automation behavior

Acceptance:
- CI fails cleanly on configured blocking conditions.
- Nightly automation can run without mutating business-truth docs directly.
- Scheduled runs leave an auditable trail.

### S13: Draft PR and issue automation

Status: `blocked`

Goal:
- Let the tool prepare fix-up PRs or issues once scan, queue, and safe-fix
  behavior are stable.

Changes:
- Add `docgarden pr draft`.
- Generate human-readable summaries from current open findings and changed files.
- Optionally create unsafe-work follow-up issues instead of PRs.

Blocked on:
- S12, because automation is the safe place to prove this behavior.

Acceptance:
- Draft summaries map cleanly to actual findings.
- No PR automation runs without explicit repository support and credentials.

### S14: Promotion suggestions from transient docs

Status: `blocked`

Goal:
- Surface when repeated rules should move from exec plans or notes into
  canonical docs.

Changes:
- Detect repeated business rules across exec plans, workaround notes, or similar
  transient docs.
- Emit "promotion suggestion" findings with candidate destination docs.

Blocked on:
- S10, because the first version likely benefits from subjective review support.

Acceptance:
- Suggestions are explainable and evidence-backed.
- The detector avoids noisy repetition on generic wording.

## Recommended execution order

1. Finish S01 cleanly and treat it as the Phase 2 baseline.
2. Land S02 through S04 before broadening detector coverage further.
3. Add S05 through S08 to deepen scan quality once queue operations exist.
4. Add S09 and S10 before serious CI gating so scores and reviews are stable.
5. Add S11 through S14 only after the lower-risk core loop is dependable.

## Exceptions / Caveats

- Some slices can be merged later if implementation experience shows they are
  inseparable, but that should be the exception rather than the default.
- Domain-specific RMN detectors from the full spec are intentionally excluded
  from the first backlog pass because this repo is still implementing generic
  `docgarden` infrastructure.

## Validation / How to verify

- Read the spec and confirm every major capability has a mapped slice.
- Confirm each slice is independently testable and has explicit dependencies.
- Run `docgarden scan` after updating this backlog.

## Related docs

- [Docgarden spec](docgarden-spec.md)
- [Agent prompts](docgarden-agent-prompts.md)
- [Design docs index](index.md)
- [Docgarden spec slicing exec plan](../exec-plans/active/2026-03-09-docgarden-spec-slicing.md)
- [Docgarden alignment phase 2 exec plan](../exec-plans/active/2026-03-09-docgarden-alignment-phase-2.md)
