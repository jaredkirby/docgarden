---
doc_id: docgarden-agent-prompts
doc_type: reference
domain: design-docs
owner: kirby
status: draft
last_reviewed: 2026-03-09
review_cycle_days: 14
applies_to:
  - repo
source_of_truth:
  - docs/design-docs/docgarden-implementation-slices.md
  - docs/design-docs/docgarden-spec.md
  - docs/exec-plans/active/2026-03-09-docgarden-spec-slicing.md
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - prompts
  - handoff
  - implementation
---

# Docgarden Agent Prompts

## Purpose

Provide reusable handoff prompts for implementation and review agents working
through the `docgarden` implementation slices.

## Scope

These prompts are written for the current repository state after the design
backlog and slice decomposition landed. They are intended to help separate
implementation work from spec-conformance review work.

For current automated runs, prefer `docgarden slices kickoff-prompt`,
`docgarden slices review-prompt`, or `docgarden slices run`. Those commands
derive prompts directly from the slice backlog and are less likely to drift
than this manually maintained reference pack.

For implementation slices, assume the worker may need a longer time budget than
the reviewer. In live operator runs, prefer `docgarden slices run
--worker-timeout-seconds 900` over the older symmetric 300-second default so
the implementation agent has room to finish a reviewable end-to-end cut before
timing out.

## Source of Truth

- [Implementation slices](docgarden-implementation-slices.md)
- [Docgarden spec](docgarden-spec.md)
- [Spec slicing exec plan](../exec-plans/active/2026-03-09-docgarden-spec-slicing.md)

## Rules / Definitions

- `implementation prompt`: for the agent expected to change code and tests.
- `PM review prompt`: for an agent acting like a product/technical reviewer that
  checks whether the implementation matches the spec and the intended slice.
- `completed slice review`: a review pass against a slice that is already
  believed to be shipped.
- `next agent`: the implementation agent starting the next queued slice after
  S07.
- `bounded worker run`: an implementation pass that should prioritize the
  smallest acceptance-complete change before optional cleanup so the slice stays
  reviewable within its time budget.

## Prompt pack

### 1. Implementation kickoff for the next agent after S07

Use this when S01 through S07 have already been completed, reviewed, and
accepted as the current baseline.

```text
You’re implementing the next docgarden slice in /Users/kirby/Projects/docgarden.

Start by reading:
- docs/design-docs/docgarden-implementation-slices.md
- docs/design-docs/docgarden-spec.md
- docs/exec-plans/active/2026-03-09-docgarden-spec-slicing.md

Your target slice is S08: “Routing quality detector for stale targets”.

Primary goal:
- move beyond "route exists" toward "route points to the right kind of doc"

Required changes:
1. Detect AGENTS or index routes that point to archived, deprecated, or stale
   docs when a better canonical route exists.
2. Flag archive docs that are still routed as current truth.
3. Optionally suggest the canonical replacement when `superseded_by` is
   present.

Likely files:
- docgarden/scan/linkage.py
- docgarden/scan/scanner.py
- tests/test_docgarden.py

Working style:
- keep this slice tight; do not jump ahead into S09 score trend and weighted
  domain rollups
- implement the code changes directly; do not run `docgarden slices` commands
  or use the `docgarden-slice-orchestrator` skill inside this worker
- do not revert unrelated user changes
- if the current worktree contains unrelated dirty files, work around them
  carefully and commit only your touched paths

Verification:
- uv run pytest
- uv run docgarden scan

Documentation:
- if the behavior changed durably, update the active exec plan progress,
  discoveries, and decision log

Definition of done:
- broken and low-quality routing are distinguishable finding types
- archived docs routed from indexes are flagged
- suggested replacements appear in evidence or recommended action when known
- tests cover success paths and validation failures
- repo scan remains clean after the change

Commit:
- make an atomic commit with only the files you touched
```

### 2. PM review prompt for the completed S01 work

Use this when you want a product/spec review of the shipped first alignment
slice.

```text
Act as a PM-style reviewer for the docgarden spec implementation in
/Users/kirby/Projects/docgarden.

Your job is not to rewrite code. Your job is to review whether the first
implementation slice matches the intended product behavior from the spec and the
slice backlog.

Read first:
- docs/design-docs/docgarden-spec.md
- docs/design-docs/docgarden-implementation-slices.md
- docs/exec-plans/active/2026-03-09-docgarden-alignment-phase-2.md

Focus specifically on S01: “First alignment checks”.

Review questions:
1. Did the implementation add real “Alignment to artifacts” signal, or is it
   still mostly mechanical scanning dressed up as alignment?
2. Does it correctly detect:
   - missing local source_of_truth artifacts
   - unsupported docgarden validation commands on non-draft docs
3. Does it avoid punishing draft docs that intentionally describe future CLI
   behavior from the spec?
4. Are the findings and evidence phrased clearly enough for an agent or
   maintainer to act on them?
5. Did the implementation stay slice-sized, or did it accidentally expand into
   later work like plan lifecycle redesign?
6. Are tests and docs sufficient for the slice, or is important behavior still
   implicit?

Deliverable:
- findings first, ordered by severity
- each finding should say whether it is:
  - spec mismatch
  - product ambiguity
  - implementation risk
  - testing/documentation gap
- if there are no material issues, say so clearly
- end with a short “ship / revise / block” recommendation

Be strict about scope:
- review against the spec and S01 acceptance criteria
- do not demand later-slice behavior from S02 or beyond unless the lack of it
  breaks S01 itself
```

### 3. PM review prompt for the completed S02 work

Use this when you want a product/spec review of the shipped findings-lifecycle
slice.

```text
Act as a PM-style reviewer for the docgarden spec implementation in
/Users/kirby/Projects/docgarden.

You are reviewing the implementation of S02: “Findings lifecycle and
attestation-ready state”.

Read first:
- docs/design-docs/docgarden-spec.md
- docs/design-docs/docgarden-implementation-slices.md
- docs/exec-plans/active/2026-03-09-docgarden-spec-slicing.md

Review the implementation specifically against the S02 slice definition.

Questions to answer:
1. Can the findings event model now represent:
   - open observation
   - in_progress work
   - accepted_debt
   - needs_human
   - false_positive
   - fixed / resolved state
2. Does the implementation preserve append-only history, or does it mutate old
   state in a way that weakens auditability?
3. Is attestation-ready metadata actually modeled clearly enough to support
   future resolve commands, or was it only partially sketched?
4. Are score semantics honest?
   - accepted_debt should still hurt strict_score
   - accepted_debt should not hurt overall_score
5. Is backward compatibility preserved for existing findings history?
6. Did the implementation stay within the S02 boundary, or did it drift into S03
   and S04 command work unnecessarily?

Deliverable:
- list findings first, ordered by severity
- explicitly call out any mismatch between the slice acceptance criteria and the
  implementation
- identify any hidden product decisions the implementation made without the spec
  saying so
- end with a short recommendation:
  - ready for next slice
  - revise before next slice
- blocked pending product clarification

Do not grade the work on later-slice features unless their absence creates a
real product risk for S02.
```

### 4. PM review prompt for the completed S03 work

Use this when you want a product/spec review of the shipped plan-triage slice.

```text
Act as a PM-style reviewer for the docgarden spec implementation in
/Users/kirby/Projects/docgarden.

You are reviewing the implementation of S03: “Plan triage commands and
lifecycle stages”.

Read first:
- docs/design-docs/docgarden-spec.md
- docs/design-docs/docgarden-implementation-slices.md
- docs/exec-plans/active/2026-03-09-docgarden-spec-slicing.md

Review the implementation specifically against the S03 slice definition.

Questions to answer:
1. Did the implementation add the intended triage workflow stages:
   - observe
   - reflect
   - organize
2. Can users record stage reports without mutating findings history?
3. Does `plan.json` now carry meaningful lifecycle-stage information and
   stage-specific notes?
4. Does `docgarden plan` surface the current stage and enough stored context to
   guide the next operator?
5. Did the implementation stay within the S03 boundary, or did it drift into S04
   focus/resolve workflow prematurely?
6. Are the command UX and error messages clear enough for repeatable use?

Deliverable:
- list findings first, ordered by severity
- classify each issue as:
  - spec mismatch
  - product ambiguity
  - implementation risk
  - testing/documentation gap
- explicitly call out any hidden product decisions not stated in the slice
- end with a short recommendation:
  - ready for S04
  - revise before S04
- blocked pending product clarification

Do not require focus/resolve behavior unless the lack of it prevents S03 from
being useful on its own.
```

### 5. PM review prompt for the completed S04 work

Use this when you want a product/spec review of the shipped S04 queue slice.

```text
Act as a PM-style reviewer for the docgarden spec implementation in
/Users/kirby/Projects/docgarden.

You are reviewing the implementation of S04: “Focus and resolve queue
operations”.

Read first:
- docs/design-docs/docgarden-spec.md
- docs/design-docs/docgarden-implementation-slices.md
- docs/exec-plans/active/2026-03-09-docgarden-spec-slicing.md

Review the implementation specifically against the S04 slice definition.

Questions to answer:
1. Can users explicitly change queue focus in a way that is visible and
   predictable?
2. Does resolution create new append-only finding events rather than mutating
   historical state?
3. Are status outcomes mapped sensibly to the existing lifecycle model:
   - fixed
   - accepted_debt
   - needs_human
   - false_positive
4. Is attestation required anywhere the spec expects honest friction?
5. Did the implementation stay within S04, or did it sprawl into changed-scope
   scans, CI automation, or review imports?
6. Are the operator-facing commands and errors clear enough to use in a
   repetitive workflow?

Deliverable:
- findings first, ordered by severity
- classify each issue as:
  - spec mismatch
  - product ambiguity
  - implementation risk
  - testing/documentation gap
- explicitly call out any hidden product decisions not stated in the slice
- end with a short recommendation:
  - ready for S05
  - revise before S05
  - blocked pending product clarification

Do not require changed-scope scanning or review-packet behavior unless their
absence prevents S04 from being useful on its own.
```

### 6. PM review prompt for the completed S05 work

Use this when you want a product/spec review of the shipped changed-scope scan
slice.

```text
Act as a PM-style reviewer for the docgarden spec implementation in
/Users/kirby/Projects/docgarden.

You are reviewing the implementation of S05: “Changed-scope scans”.

Read first:
- docs/design-docs/docgarden-spec.md
- docs/design-docs/docgarden-implementation-slices.md
- docs/exec-plans/active/2026-03-09-docgarden-spec-slicing.md

Review the implementation specifically against the S05 slice definition.

Questions to answer:
1. Does `docgarden scan --scope changed` actually limit work to the intended
   changed subset?
2. Is the changed-set derivation understandable and predictable?
   - from git state
   - from an explicit file list, if supported
3. Does the implementation preserve honest score semantics for partial scans?
4. Is full-scan behavior unchanged and still the source of truth for complete
   repo health?
5. Did the implementation stay within S05, or did it sprawl into generated-doc
   rules, workflow drift detection, or CI policy?
6. Are the operator-facing messages clear about what partial scans can and
   cannot guarantee?

Deliverable:
- findings first, ordered by severity
- classify each issue as:
  - spec mismatch
  - product ambiguity
  - implementation risk
  - testing/documentation gap
- explicitly call out any hidden product decisions not stated in the slice
- end with a short recommendation:
  - ready for S06
  - revise before S06
  - blocked pending product clarification

Do not require generated-doc or workflow-drift behavior unless their absence
prevents S05 from being useful on its own.
```

### 7. PM review prompt for the next agent’s work against S08

Use this after the next implementation agent finishes S08.

```text
Act as a PM-style reviewer for the docgarden spec implementation in
/Users/kirby/Projects/docgarden.

You are reviewing the implementation of S08: “Routing quality detector for
stale targets”.

Read first:
- docs/design-docs/docgarden-spec.md
- docs/design-docs/docgarden-implementation-slices.md
- docs/exec-plans/active/2026-03-09-docgarden-spec-slicing.md

Review the implementation specifically against the S06 slice definition.

Questions to answer:
1. Are broken routes and low-quality-but-existing routes clearly distinguishable
   in the findings model?
2. Does the implementation catch AGENTS or index routes that still point to
   archived, deprecated, or stale docs when a better canonical target exists?
3. If a routed doc is archived or superseded, does the finding evidence or
   recommended action point maintainers toward the better replacement when
   available?
4. Does the detector avoid spurious routing findings for healthy canonical
   routes?
5. Did the implementation stay within S08, or did it sprawl into S09 score
   rollups, autofix expansion, or CI automation?
6. Are the routing-quality findings actionable enough for an agent or
   maintainer to update the doc routes without re-reading the full spec?

Deliverable:
- findings first, ordered by severity
- classify each issue as:
  - spec mismatch
  - product ambiguity
  - implementation risk
  - testing/documentation gap
- explicitly call out any hidden product decisions not stated in the slice
- end with a short recommendation:
  - ready for S09
  - revise before S09
  - blocked pending product clarification

Do not require S09 score-rollup behavior unless its absence prevents S08 from
being useful on its own.
```

## Exceptions / Caveats

- These prompts assume the repository keeps using the current slice numbering.
- If the backlog is reordered materially, update these prompts instead of trying
  to reinterpret them ad hoc.

## Validation / How to verify

- Confirm the prompts reference the current slice IDs and docs.
- Confirm each prompt maps cleanly to one implementation or review job.
- Run `docgarden scan` after editing this file.

## Related docs

- [Implementation slices](docgarden-implementation-slices.md)
- [Docgarden spec](docgarden-spec.md)
- [Design docs index](index.md)
- [Spec slicing exec plan](../exec-plans/active/2026-03-09-docgarden-spec-slicing.md)
