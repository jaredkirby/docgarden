---
doc_id: concepts
doc_type: canonical
domain: docs
owner: kirby
status: draft
last_reviewed: 2026-03-10
review_cycle_days: 30
applies_to:
  - repo
source_of_truth:
  - docgarden/models.py
  - docgarden/scan/document_rules.py
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - concepts
  - docs
---

# Concepts

## Purpose

Explain the mental model behind docgarden: what it scans, what it produces, and
how the pieces fit together.

## Documents and frontmatter

Docgarden scans markdown files in two locations:

- `AGENTS.md` at the repo root (routing and expectations)
- Everything under `docs/` with a `.md` extension

Every scanned doc (except `AGENTS.md`) should include YAML frontmatter with
these seven required fields:

| Field | Purpose |
|-------|---------|
| `doc_id` | Stable unique identifier across the repo |
| `doc_type` | Document class (see below) |
| `domain` | Grouping for scoring and rollups |
| `owner` | Who is responsible for keeping this doc current |
| `status` | Current trust level (see below) |
| `last_reviewed` | ISO date of last human review |
| `review_cycle_days` | How often this doc should be re-reviewed |

Optional but recommended fields: `applies_to`, `source_of_truth`,
`verification`, `supersedes`, `superseded_by`, `tags`.

## Document types

Every doc declares a `doc_type` that determines which required sections
docgarden checks for:

**canonical** — stable source-of-truth docs. The agent should trust these first.
Required sections: Purpose, Scope, Source of Truth, Rules / Definitions,
Exceptions / Caveats, Validation / How to verify, Related docs.

**exec-plan** — living work artifacts for non-trivial tasks. Required sections:
Purpose, Context, Assumptions, Steps / Milestones, Validation, Progress,
Discoveries, Decision Log, Outcomes / Retrospective.

**generated** — machine-generated reference material. Required sections:
Generation source, Generated timestamp, Upstream artifact path or script,
Regeneration command.

**archive** — historical material that should not be used as current truth.
Required sections: Archived reason, Archived date, Replacement doc (if any).

**reference** — useful supporting material that is not primary truth. No
required sections beyond frontmatter.

## Statuses

The `status` field tracks trust level:

| Status | Meaning |
|--------|---------|
| `verified` | Reviewed and confirmed current. Requires `source_of_truth` and `verification` on canonical docs. |
| `draft` | Work in progress. Not yet reviewed. |
| `needs-review` | Previously verified but now flagged for re-review. |
| `stale` | Known to be out of date. |
| `deprecated` | Superseded by another doc. Should not be used as current truth. |
| `archived` | Historical record only. |

## Domains

Domains group documents for scoring and rollups. Docgarden infers the domain
from the directory structure — a file under `docs/design-docs/` gets domain
`design-docs`, while a file directly under `docs/` gets domain `docs`.

Domains matter for:

- **Domain scores** — each domain gets its own quality score
- **Weighted rollups** — configure `domain_weights` in config to weight
  important domains higher in the overall rollup
- **Critical regressions** — configure `critical_domains` to get called out
  when a domain's score drops, even if the overall score looks healthy

## Findings

A finding is a detected documentation issue. Each finding has:

- **id** — stable identifier like `missing-metadata::docs::design-docs::foo::doc_type`
- **kind** — what type of issue (e.g., `missing-metadata`, `broken-link`, `stale-review`)
- **severity** — `high`, `medium`, or `low`
- **status** — where it is in the lifecycle (see below)
- **safe_to_autofix** — whether `docgarden fix safe` can fix it deterministically
- **summary** — human-readable description
- **evidence** — specific observations that triggered the finding
- **recommended_action** — what to do about it

### Finding kinds

Document-level checks:
- `missing-frontmatter` — no YAML frontmatter at all
- `missing-metadata` — frontmatter exists but required fields are missing
- `invalid-metadata` — status value not in the allowed set
- `missing-sections` — required sections for the doc type are absent
- `stale-review` — verified doc past its `review_cycle_days`
- `verified-without-sources` — canonical verified doc missing `source_of_truth` or `verification`
- `broken-link` — internal markdown link points to a file that doesn't exist

Repo-level checks (run after all documents are scanned):
- `duplicate-doc-id` — two or more docs share the same `doc_id`
- `broken-route` — AGENTS.md or an index routes to a missing doc
- `stale-route` — route points to an archived, deprecated, or stale doc
- `orphan-doc` — doc under `docs/` with no inbound links
- `promotion-suggestion` — same rule-like text appears in 2+ transient docs

Alignment checks:
- `missing-source-artifact` — `source_of_truth` references a file that doesn't exist
- `invalid-validation-command` — validation section references an unsupported docgarden command
- `generated-doc-contract` — generated doc missing required contract fields
- `generated-doc-stale` — generated doc older than its upstream source

### Finding lifecycle

```
open  ->  in_progress  ->  fixed
                        ->  accepted_debt  (requires --attest)
                        ->  needs_human    (requires --attest)
                        ->  false_positive (requires --attest)
```

- **open** — newly detected, not yet addressed
- **in_progress** — someone is working on it
- **fixed** — resolved by changing the docs
- **accepted_debt** — acknowledged but intentionally not fixed
- **needs_human** — requires human judgment, not safe to autofix
- **false_positive** — finding was incorrect

Non-trivial resolutions (`accepted_debt`, `needs_human`, `false_positive`)
require `--attest` text so the audit trail stays honest.

Findings are **auto-resolved** when a subsequent scan no longer detects the
issue. Previously fixed or false-positive findings are **reopened** if the issue
reappears.

### Finding sources

- **mechanical** — detected automatically by scan rules
- **subjective_review** — imported from a human or agent review via
  `docgarden review import`

## Quality scoring

Docgarden scores documentation quality across six weighted dimensions:

| Dimension | Weight | What it measures |
|-----------|--------|-----------------|
| Structure & metadata | 15 | Frontmatter completeness, required sections |
| Freshness | 15 | Review staleness, status currency |
| Linking & discoverability | 15 | Broken links, orphan docs, routing |
| Coverage | 10 | Document count relative to expected domains |
| Alignment to artifacts | 25 | Source-of-truth references, validation commands |
| Verification & trust | 20 | Verified status backed by sources and verification |

### Score types

- **Overall score** — weighted average across dimensions. Findings resolved as
  `accepted_debt` do not penalize this score.
- **Strict score** — same calculation, but `accepted_debt` findings still count
  against it. The gap between overall and strict is your acknowledged debt.

### Severity penalties

Each open finding reduces its dimension's score by a severity-based penalty:
low = 3, medium = 8, high = 15.

### Domain rollups

Beyond the six dimensions, docgarden computes per-domain scores:

- **Raw average** — unweighted average of all domain scores
- **Weighted rollup** — average weighted by `domain_weights` from config
  (omitted domains default to weight 1)
- **Critical regressions** — domains in `critical_domains` whose score dropped
  since the last scan

### Trend tracking

Each full scan appends a trend point with the overall, strict, and weighted
rollup scores. The trend summary shows deltas between the two most recent
points.

## Plans and triage

After scanning, docgarden builds a plan: a prioritized queue of findings ordered
by severity, domain, and discovery time. The plan supports:

### Triage lifecycle

Before working the queue, triage your findings:

1. **observe** — record themes and root causes
2. **reflect** — compare against recent work
3. **organize** — set execution order and rationale

Each stage records a free-text report via
`docgarden plan triage --stage <stage> --report "..."`.

### Working the queue

- `docgarden plan` — see the full ordered queue
- `docgarden plan focus ID_OR_CLUSTER` — narrow `next` to a specific finding or
  cluster
- `docgarden next` — get the highest-priority actionable finding
- `docgarden plan resolve ID --result fixed` — mark resolved
- `docgarden plan reopen ID` — reopen a resolved finding

### Clusters

Related findings are grouped into clusters. Focus on a cluster to batch-fix
related issues together.

## Reviews

Docgarden separates mechanical checks (automated) from subjective review
(human/agent judgment). The review workflow:

1. `docgarden review prepare --domains docs,design-docs` — export a
   deterministic packet with selected docs and their mechanical findings
2. A reviewer (human or agent) evaluates the docs and produces a JSON payload
3. `docgarden review import review.json` — import findings with provenance into
   the findings history

Imported findings get `finding_source: subjective_review` and include
provenance metadata (reviewer, runner, packet ID).

## Safe fixes

`docgarden fix safe` previews deterministic, low-risk repairs. Adding `--apply`
executes them. Safe fixes include:

- Setting `status: needs-review` on stale verified docs
- Adding missing required section headings as TODO stubs
- Inserting metadata skeleton fields with inferred defaults
- Replacing broken internal links with valid alternatives
- Updating broken or stale route references

Unsafe edits — changing metric definitions, platform behavior claims, account
strategies, or merging contradictory sources — always require human review.

## Persistent state

All state lives in `.docgarden/` at the repo root:

| File | Format | Purpose |
|------|--------|---------|
| `config.yaml` | YAML | Configuration (thresholds, weights, blocking rules) |
| `findings.jsonl` | JSONL | Append-only event log of all finding state changes |
| `plan.json` | JSON | Current prioritized queue, clusters, triage stage |
| `score.json` | JSON | Latest scorecard with dimensions, domains, trend |
| `reviews/` | directory | Review packets and imported reviews |

`findings.jsonl` is append-only: every scan, resolution, and reopen appends a
new record. The latest event per finding ID determines current state.

## Scope

This document covers the core concepts that apply across all docgarden commands.
For command-specific details, see the [command reference](commands.md). For
configuration options, see [configuration](configuration.md).

## Source of Truth

- `docgarden/models.py` — finding statuses, lifecycle constants, data structures
- `docgarden/scan/document_rules.py` — required metadata, allowed statuses, required sections
- `docgarden/quality.py` — dimension weights, severity penalties, scoring logic

## Rules / Definitions

- Every scanned doc under `docs/` must include the seven required frontmatter fields.
- Document type determines which sections are required.
- Findings follow the lifecycle: open → in_progress → resolved (fixed, accepted_debt, needs_human, false_positive).
- Non-trivial resolutions require attestation text.
- The strict score always penalizes accepted debt; the overall score does not.

## Exceptions / Caveats

- `AGENTS.md` is scanned for routing but is not required to have frontmatter.
- Changed-scope scans skip repo-wide checks (duplicates, orphans, promotions).
- Safe autofix only applies to deterministic, low-risk repairs. It never modifies
  business-critical content.

## Validation / How to verify

- Run `docgarden scan` and confirm the concepts described here match the scan output.
- Run `docgarden doctor` to verify the repo structure is set up correctly.

## Related docs

- [Getting started](getting-started.md)
- [Command reference](commands.md)
- [Configuration](configuration.md)
- [CI setup](ci-setup.md)
- [Architecture](architecture.md)
