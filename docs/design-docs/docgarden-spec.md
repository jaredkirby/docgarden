---
doc_id: docgarden-full-spec
doc_type: reference
domain: design-docs
owner: kirby
status: draft
last_reviewed: 2026-03-09
review_cycle_days: 30
applies_to:
  - repo
source_of_truth:
  - SPEC-FULL.md
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - design
  - spec
  - roadmap
---

# Docgarden Full Spec

## Purpose

Keep the full proposed product spec inside the scanned `docs/` tree so it can
be routed, reviewed, and evolved as part of the repository's durable knowledge.

## Status of this doc

This is a durable mirror of the repo-root working draft in
[`SPEC-FULL.md`](../../SPEC-FULL.md). It is intentionally ahead of the current
implementation. Treat it as a design target, not a statement that every command
or detector already exists.

## Full proposed specification

Below is a proposed spec for a `docgarden` tool: a doc-specific sibling to
desloppify, designed for an agent-first repo where repository knowledge is the
system of record. It borrows OpenAI's published patterns around a short
`AGENTS.md`, progressive disclosure, versioned plans, and recurring
doc-gardening, plus desloppify's scan -> plan -> execute -> rescan loop,
persistent state, and honest scoring.

### 1. What `docgarden` is

`docgarden` is a repo-local tool that keeps agent-facing knowledge trustworthy.

Its job is to:

- find stale, missing, contradictory, or poorly routed docs
- score the repo's knowledge quality honestly
- maintain a persistent backlog of doc debt
- propose or open safe fix-up PRs
- tell agents what to fix next
- enforce minimum doc hygiene in CI

Its job is not to become a giant knowledge base of its own. The repo docs stay
the source of truth; `docgarden` is the maintenance harness around them.

### 2. Design goals

Primary goals:

- keep repo knowledge usable by agents with minimal prompt bloat
- make canonical docs visibly more trustworthy than stale docs
- turn repeated doc drift into tracked, prioritized work
- separate safe mechanical fixes from higher-risk truth edits
- work well with Codex-style `AGENTS.md` routing and living exec plans

Non-goals:

- replace human judgment on business strategy or platform interpretation
- auto-rewrite important canonical docs without review
- store raw business data exports as long-term memory
- compete with task skills or planning docs

### 3. Recommended repo structure

```text
repo-root/
  AGENTS.md
  ARCHITECTURE.md

  docs/
    index.md
    QUALITY_SCORE.md
    DESIGN.md
    PLANS.md
    RELIABILITY.md
    SECURITY.md

    design-docs/
      index.md
      core-beliefs.md
      assistant-operating-model.md
      docgarden-spec.md

    architecture/
      index.md
      domains.md
      repo-map.md
      package-layering.md

    platforms/
      walmart-connect.md
      instacart.md
      kroger.md

    metrics/
      index.md
      metric-definitions.md
      pacing-rules.md
      attribution-notes.md

    workflows/
      weekly-pacing.md
      reporting.md
      keyword-triage.md
      launch-qa.md
      anomaly-review.md

    accounts/
      tai-pei/
        current-plan.md
        current-state.md
        known-quirks.md
      jose-ole/
        current-plan.md
        current-state.md
        known-quirks.md

    exec-plans/
      active/
      completed/
      tech-debt-tracker.md

    generated/
      walmart/
        campaign-export-schema.md
        search-term-export-schema.md
      shopperations/
        budget-export-schema.md

    references/
      walmart-llms.txt
      instacart-llms.txt
      retailer-glossary.txt

    archive/
      2025/
      2026/

  .docgarden/
    config.yaml
    findings.jsonl
    plan.json
    score.json
    baselines/
    reviews/
    runs/
    cache/
    locks/

  scripts/
    docgarden/
      generate_schemas.py
      sync_quality_score.py
      safe_fixers.py

  .github/
    workflows/
      docgarden-nightly.yml
      docgarden-pr.yml
      docgarden-weekly-review.yml
```

Why this shape:

- keep `AGENTS.md` lightweight and routing-heavy
- push durable details into deeper docs
- keep spec, plans, and generated state visibly separate

### 4. Document classes

Every doc in `docs/` should declare one of these types:

- `canonical`: stable source-of-truth docs the agent should trust first
- `exec-plan`: living work artifacts for non-trivial tasks
- `generated`: machine-generated reference material derived from real artifacts
- `reference`: useful supporting material that is not primary truth
- `archive`: historical material that should not be used as current truth

### 5. Frontmatter contract

Every non-archive doc should include:

- `doc_id`
- `doc_type`
- `domain`
- `owner`
- `status`
- `last_reviewed`
- `review_cycle_days`

Recommended additional fields:

- `applies_to`
- `source_of_truth`
- `verification`
- `supersedes`
- `superseded_by`
- `tags`

Allowed statuses:

- `verified`
- `draft`
- `needs-review`
- `stale`
- `deprecated`
- `archived`

Key rule:

- if a canonical doc is marked `verified` without `source_of_truth` and
  `verification`, `docgarden` should score it down and likely flag it for human
  review

### 6. Required sections by doc type

Canonical docs should contain:

- Purpose
- Scope
- Source of Truth
- Rules / Definitions
- Exceptions / Caveats
- Validation / How to verify
- Related docs

Exec plans should contain:

- Purpose
- Context
- Assumptions
- Steps / Milestones
- Validation
- Progress
- Discoveries
- Decision Log
- Outcomes / Retrospective

Generated docs should contain:

- Generation source
- Generated timestamp
- Upstream artifact path or script
- Regeneration command

Archive docs should contain:

- Archived reason
- Archived date
- Replacement doc, if any

### 7. `QUALITY_SCORE.md` model

Two scores:

- overall score: useful health score for routine progress
- strict score: harder-to-game score; accepted debt and stale truth still count
  against it

Dimensions:

```text
Structure & metadata      15
Freshness                 15
Linking & discoverability 15
Coverage                  10
Alignment to artifacts    25
Verification & trust      20
```

Suggested domain rollups:

- architecture
- metrics
- platforms
- workflows
- accounts
- exec-plans
- generated references

### 8. Findings model

Use JSONL for append-friendly state. Findings should capture:

- stable identifier
- kind
- severity
- domain
- status
- files
- summary
- evidence
- recommended action
- safe autofix eligibility
- discovery timestamp
- cluster
- confidence

Suggested statuses:

- `open`
- `in_progress`
- `fixed`
- `accepted_debt`
- `needs_human`
- `false_positive`

Non-trivial resolutions should require an attestation note.

### 9. Detector model

Three detector families:

- mechanical detectors for metadata, links, required sections, routing, stale
  reviews, duplicate `doc_id`, and similar cheap checks
- alignment detectors that compare docs to repo artifacts, commands, schemas,
  workflows, and routing
- subjective review detectors for ambiguity, contradictions, trust gaps, and
  promotion opportunities

### 10. Safe vs unsafe edits

Safe autofix candidates:

- fix broken internal links
- update indexes
- add missing metadata skeleton
- mark stale docs as `needs-review`
- repair AGENTS routing paths
- add missing required headings
- regenerate generated docs from source

Unsafe edits that should require human review:

- changing metric definitions
- changing platform behavior claims
- changing account strategy or targets
- merging contradictory truth sources
- changing workflow rules that affect operations
- promoting exec-plan findings into canonical docs without review

### 11. CLI surface

Proposed core commands:

```bash
docgarden scan --scope all
docgarden scan --scope changed
docgarden status
docgarden next
docgarden plan
docgarden quality write
docgarden fix safe --apply
docgarden pr draft
```

Proposed review commands:

```bash
docgarden review prepare --domains metrics,platforms
docgarden review run --runner codex
docgarden review import review.json
```

Proposed plan commands:

```bash
docgarden plan triage --stage observe --report "..."
docgarden plan triage --stage reflect --report "..."
docgarden plan triage --stage organize --report "..."
docgarden plan triage --complete --strategy "..."
docgarden plan focus metrics-drift
docgarden plan resolve alignment::metrics-pacing-rules::0012 \
  --result needs_human \
  --attest "Doc and implementation differ; escalation required."
```

Recommended loop:

```text
scan -> review (if needed) -> triage -> next -> fix -> resolve -> quality write -> rescan
```

### 12. Persistent state

Suggested state tree:

```text
.docgarden/
  config.yaml
  findings.jsonl
  plan.json
  score.json
  baselines/
    domains.json
  reviews/
    2026-03-08-metrics.json
  runs/
    2026-03-08T181200Z/
      summary.json
      changed_files.txt
      findings.delta.json
  locks/
    plan.lock
```

`plan.json` should include:

- ordered findings
- clusters
- deferred items
- current focus
- lifecycle stage
- last scan hash

`score.json` should include:

- overall score
- strict score
- per-dimension scores
- per-domain scores
- trend history summary

`findings.jsonl` should remain an append-only event log.

### 13. Lifecycle

Suggested lifecycle:

1. scan
2. review
3. triage
4. execute
5. verify
6. persist

Target clusters include routing drift, stale canonical docs, metric
contradictions, expired account plans, and exec-plan hygiene.

### 14. CI and automation

Suggested workflows:

- `docgarden-pr.yml` for PR-time metadata, link, routing, and score checks
- `docgarden-nightly.yml` for scheduled scans, score refresh, safe autofix, and
  cleanup PRs
- `docgarden-weekly-review.yml` for targeted subjective review and owner nudges

### 15. `AGENTS.md` integration

The root `AGENTS.md` should stay short and routing-heavy:

- treat `docs/` as the system of record
- keep `AGENTS.md` as a map rather than a manual
- update canonical docs when durable behavior changes
- create or update exec plans for multi-step work
- run `docgarden scan --scope changed` after meaningful doc or workflow changes

### 16. Domain-specific rules

The full spec describes a domain-specific mode for RMN assistant repos, with
critical domains such as metrics, platform rules, workflows, account plans, and
active exec plans. It proposes detectors for metric drift, platform drift,
account freshness, workflow drift, and routing drift.

### 17. Safe promotion rule

If the same business rule appears repeatedly across exec plans, PR summaries, or
workaround notes, `docgarden` should propose promoting it into a canonical doc.

### 18. Suggested initial config

The working draft proposes a config shaped like:

```yaml
strict_score_fail_threshold: 70
critical_domains:
  - metrics
  - platforms
  - workflows
  - accounts
block_on:
  - broken_agents_routes
  - missing_frontmatter_on_canonical
  - stale_verified_canonical_docs
  - active_exec_plan_missing_progress
```

Only live runtime knobs belong in this file. Fields like `repo_name`,
`review_defaults`, and `safe_autofix` were removed from the suggested config
surface because the current package does not honor them.

### 19. MVP build order

Proposed implementation phases:

1. mechanical checks, scoring, and quality writing
2. alignment checks
3. queue and fix flow
4. subjective review
5. domain-specific intelligence

### 20. Best short definition

`docgarden` is a repo-local maintenance harness that keeps agent-facing
documentation current, discoverable, and trustworthy, using persistent
findings, honest quality scores, safe fix-up PRs, and CI enforcement.

## Adoption notes

- Current repo code implements the documentation-maintenance tooling described
  in the README and active exec plans.
- Slice automation was extracted from `docgarden`; active implementation status
  belongs in the exec plans, not in this reference mirror.

## Related docs

- [Design docs index](index.md)
- [Docs index](../index.md)
- [Domain intelligence prioritization exec plan](../exec-plans/active/2026-03-10-domain-intelligence-prioritization.md)
