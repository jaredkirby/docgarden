Below is a **proposed spec** for a `docgarden` tool: a doc-specific sibling to desloppify, designed for an agent-first repo where repository knowledge is the system of record. It borrows OpenAI’s published patterns around a short `AGENTS.md`, progressive disclosure, versioned plans, and recurring doc-gardening, plus desloppify’s scan → plan → execute → rescan loop, persistent state, and honest scoring. OpenAI has described the concept, but not a full public schema or rubric, so the structure below is my concrete implementation proposal rather than an official template. ([OpenAI][1])

## 1. What `docgarden` is

`docgarden` is a repo-local tool that keeps agent-facing knowledge trustworthy.

Its job is to:

* find stale, missing, contradictory, or poorly routed docs
* score the repo’s knowledge quality honestly
* maintain a persistent backlog of doc debt
* propose or open safe fix-up PRs
* tell agents what to fix next
* enforce minimum doc hygiene in CI

Its job is **not** to become a giant knowledge base of its own. The repo docs stay the source of truth; `docgarden` is the maintenance harness around them.

---

## 2. Design goals

### Primary goals

* Keep repo knowledge usable by agents with minimal prompt bloat.
* Make canonical docs visibly more trustworthy than stale docs.
* Turn repeated doc drift into tracked, prioritized work.
* Separate safe mechanical fixes from higher-risk truth edits.
* Work well with Codex-style `AGENTS.md` routing and living exec plans.

### Non-goals

* Replace human judgment on business strategy or platform interpretation.
* Auto-rewrite important canonical docs without review.
* Store raw business data exports as long-term memory.
* Compete with your assistant’s task skills or planning docs.

---

## 3. Recommended repo structure

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

### Why this shape

OpenAI’s public guidance is to keep `AGENTS.md` small, use it as an entry map, and push durable knowledge into deeper repo files. Codex also loads AGENTS guidance hierarchically and stops once the combined size limit is reached, 32 KiB by default, so this layout keeps the top level lightweight and routes the agent to deeper sources only when needed. ([OpenAI Developers][2])

---

## 4. Document classes

Every doc in `docs/` should declare one of these types.

### `canonical`

Stable source-of-truth docs the agent is expected to trust first.

Examples:

* `metrics/metric-definitions.md`
* `platforms/walmart-connect.md`
* `workflows/reporting.md`

### `exec-plan`

Living work artifacts for non-trivial tasks.

Examples:

* `exec-plans/active/2026-03-08-tai-pei-pacing.md`

### `generated`

Machine-generated reference material derived from real artifacts.

Examples:

* schema docs generated from exports
* command inventories
* field maps

### `reference`

Supporting material that is useful but not primary truth.

Examples:

* glossary
* external tool notes
* copied vendor references

### `archive`

Historical material that should not be used as current truth unless explicitly requested.

---

## 5. Frontmatter contract

Every non-archive doc should start with frontmatter like this:

```yaml
---
doc_id: metrics-pacing-rules
doc_type: canonical
domain: metrics
owner: jared
status: verified
last_reviewed: 2026-03-08
review_cycle_days: 30
applies_to:
  - walmart-connect
  - instacart
source_of_truth:
  - docs/generated/walmart/campaign-export-schema.md
  - transforms/metrics/pacing.py
verification:
  method: code-linked
  confidence: high
supersedes: []
superseded_by: null
tags:
  - pacing
  - metrics
  - rmn
---
```

### Required fields

* `doc_id`
* `doc_type`
* `domain`
* `owner`
* `status`
* `last_reviewed`
* `review_cycle_days`

### Allowed `status`

* `verified`
* `draft`
* `needs-review`
* `stale`
* `deprecated`
* `archived`

### Rule

If a doc claims to be canonical and does **not** declare a source of truth or verification method, `docgarden` should score it down and likely flag it for human review.

---

## 6. Required sections by doc type

### Canonical doc

Must contain:

* Purpose
* Scope
* Source of Truth
* Rules / Definitions
* Exceptions / Caveats
* Validation / How to verify
* Related docs

### Exec plan

Must contain:

* Purpose
* Context
* Assumptions
* Steps / Milestones
* Validation
* Progress
* Discoveries
* Decision Log
* Outcomes / Retrospective

This matches OpenAI’s public ExecPlan pattern: self-contained, living, updated as work progresses, with explicit progress and decision logs. ([OpenAI Developers][3])

### Generated doc

Must contain:

* Generation source
* Generated timestamp
* Upstream artifact path or script
* Regeneration command

### Archive doc

Must contain:

* Archived reason
* Archived date
* Replacement doc, if any

---

## 7. `QUALITY_SCORE.md` model

OpenAI says they keep a quality document that grades domains and layers, but they do not publish the rubric. This is a proposed scoring model for your repo. ([OpenAI][1])

### Two scores

* **Overall score**: useful health score for routine progress
* **Strict score**: harder-to-game score; accepted debt and stale truth still count against it

That mirrors desloppify’s idea that the score should be honest and that “wontfix” debt should still widen the gap between lenient and strict quality. ([GitHub][4])

### Dimensions

```text
Structure & metadata      15
Freshness                 15
Linking & discoverability 15
Coverage                  10
Alignment to artifacts    25
Verification & trust      20
```

### Scoring rules

`overall_score`
Weighted average of all dimensions, excluding findings explicitly marked `accepted_debt`.

`strict_score`
Weighted average including `accepted_debt`, stale canonical docs, and unresolved contradiction findings.

### Domain rollups

Each domain gets its own score:

* architecture
* metrics
* platforms
* workflows
* accounts
* exec-plans
* generated references

Suggested criticality multipliers for repo rollup:

* metrics: `1.5`
* platforms: `1.5`
* workflows: `1.2`
* accounts: `1.2`
* exec-plans: `1.0`
* architecture: `1.0`
* references: `0.5`

### Example `QUALITY_SCORE.md`

```md
# Quality Score

Updated: 2026-03-08

## Repo Summary
- Overall: 83
- Strict: 71

## Domains
- Metrics: 92 (verified, high trust)
- Walmart platform: 76 (stale review window exceeded)
- Workflows: 81 (good routing, minor drift)
- Accounts: 63 (2 current plans expired)
- Exec plans: 88 (good structure, 1 active plan missing outcomes)

## Top Gaps
1. docs/platforms/walmart-connect.md is 47 days past review cycle
2. docs/accounts/tai-pei/current-plan.md end date passed with no replacement
3. docs/workflows/reporting.md references a retired export field
4. AGENTS.md routes to docs/metrics.md, but canonical metric definitions now live in docs/metrics/metric-definitions.md
```

---

## 8. Findings model

Use JSONL for append-friendly state.

Example finding:

```json
{
  "id": "alignment::metrics-pacing-rules::0012",
  "kind": "alignment",
  "severity": "high",
  "domain": "metrics",
  "status": "open",
  "files": [
    "docs/metrics/pacing-rules.md",
    "transforms/metrics/pacing.py"
  ],
  "summary": "Pacing rule in canonical doc disagrees with current implementation.",
  "evidence": [
    "Doc says spend target is monthly-weighted only.",
    "Code applies weekly override when account plan is present."
  ],
  "recommended_action": "Update canonical doc or change code; requires human review.",
  "safe_to_autofix": false,
  "discovered_at": "2026-03-08T18:12:00Z",
  "cluster": "metrics-drift",
  "confidence": "high"
}
```

### Allowed statuses

* `open`
* `in_progress`
* `fixed`
* `accepted_debt`
* `needs_human`
* `false_positive`

### Resolution rule

Any non-trivial resolution requires an attestation note. That is directly worth borrowing from desloppify because it reduces score gaming. ([GitHub][5])

---

## 9. Detector model

`docgarden` should use three detector families.

### A. Mechanical detectors

Cheap, deterministic, run on every scan.

* broken links
* missing frontmatter
* invalid metadata values
* missing required sections
* orphan docs not linked from any index
* AGENTS route points to missing file
* stale review dates
* duplicate `doc_id`
* active exec plan missing required sections
* generated doc older than source artifact timestamp
* archive docs still routed from AGENTS or index

### B. Alignment detectors

Compare docs to repo artifacts.

* command drift: docs reference commands/scripts/files that do not exist
* schema drift: canonical docs reference missing or renamed fields
* metric drift: metric definitions disagree with code or query logic
* workflow drift: workflow steps disagree with scripts/templates
* routing drift: AGENTS/index points to deprecated docs
* contradiction detection inside a domain

### C. Subjective review detectors

Run with LLM review only on selected docs.

* unclear source of truth
* ambiguous or conflicting guidance
* too much routing friction
* duplicated content split across multiple “truth” docs
* outdated assumptions not visible to the agent
* weak validation instructions
* business rules hidden in old exec plans instead of canonical docs

This is the direct transfer from desloppify: combine mechanical detection with subjective review, then persist and prioritize the results. ([GitHub][6])

---

## 10. Safe vs unsafe edits

### Safe autofix

Allowed for bot PRs without human content review:

* fix broken internal links
* update indexes
* add missing metadata skeleton
* mark stale docs as `needs-review`
* update `last_reviewed` only when verification is genuinely re-run
* move obviously replaced docs to archive
* repair AGENTS routing paths
* add missing required headings
* regenerate generated docs from source

### Unsafe changes

Must open PR with `needs-human-review` label:

* changing metric definitions
* changing platform behavior claims
* changing account strategy or targets
* merging contradictory truth sources
* changing workflow rules that affect operations
* promoting findings from an exec plan into canonical docs without review

---

## 11. CLI surface

This should feel close to desloppify, but doc-specific.

### Core commands

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

### Review commands

```bash
docgarden review prepare --domains metrics,platforms
docgarden review run --runner codex
docgarden review import review.json
```

### Plan commands

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

### Utility commands

```bash
docgarden show alignment::metrics-pacing-rules::0012
docgarden doctor
docgarden config show
docgarden cache clear
```

### Recommended loop

```text
scan → review (if needed) → triage → next → fix → resolve → quality write → rescan
```

That is deliberately modeled on desloppify’s published scan → plan → execute → rescan cycle and persistent queue model. ([GitHub][4])

---

## 12. Persistent state

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

### `plan.json`

Should include:

* ordered findings
* clusters
* deferred items
* current focus
* lifecycle stage
* last scan hash

### `score.json`

Should include:

* overall score
* strict score
* per-dimension scores
* per-domain scores
* trend history summary

### `findings.jsonl`

Append-only event log of discovered and resolved findings.

---

## 13. Lifecycle

### Phase 1: Scan

Run mechanical + alignment detectors.

### Phase 2: Review

If certain domains are low confidence, stale, or materially changed, run targeted LLM review.

### Phase 3: Triage

Group findings into clusters like:

* routing drift
* stale canonical docs
* metric contradictions
* expired account plans
* exec-plan hygiene

### Phase 4: Execute

Apply safe fixes or open focused PRs.

### Phase 5: Verify

Regenerate score, rescan touched areas, ensure no new contradictions.

### Phase 6: Persist

Update `QUALITY_SCORE.md`, state files, and PR summary.

This matches the public pattern from both OpenAI’s living plan workflow and desloppify’s structured queueing. ([OpenAI Developers][3])

---

## 14. CI and automation

### `docgarden-pr.yml`

Run on every PR.

Checks:

* metadata validity
* link integrity
* required sections
* AGENTS/index target existence
* no canonical doc marked `verified` without source-of-truth field
* no active exec plan missing Progress or Decision Log
* no drop in strict score greater than threshold in critical domains unless labeled `doc-debt-approved`

### `docgarden-nightly.yml`

Run nightly.

Steps:

* `docgarden scan --scope all`
* `docgarden quality write`
* `docgarden fix safe --apply`
* open or update a cleanup PR if safe fixes exist
* create issue for unsafe high-severity findings

### `docgarden-weekly-review.yml`

Run weekly.

Steps:

* run targeted subjective review for low-score domains
* refresh domain trend lines
* update `QUALITY_SCORE.md`
* create “review needed” issues for owners

OpenAI explicitly says they use dedicated linters, CI jobs, and a recurring doc-gardening agent that opens fix-up PRs. Their customization docs also recommend automating drift checks and pairing AGENTS guidance with enforcement like hooks and linters. ([OpenAI][1])

---

## 15. `AGENTS.md` integration

Your root `AGENTS.md` should stay short and routing-heavy.

Example:

```md
# AGENTS.md

## Repo expectations
- Treat docs/ as the system of record for durable project knowledge.
- Keep this file small; use it as a map, not a full manual.
- When a task changes durable behavior, update the relevant canonical doc before closing work.
- For multi-step work, create or update an exec plan in docs/exec-plans/active/.
- Run `docgarden scan --scope changed` after significant documentation or workflow changes.

## Where to look first
- Metrics: docs/metrics/metric-definitions.md
- Walmart rules: docs/platforms/walmart-connect.md
- Workflow procedures: docs/workflows/
- Active work: docs/exec-plans/active/
- Quality/trust map: docs/QUALITY_SCORE.md
```

This fits the public Codex guidance: keep `AGENTS.md` small, use it for durable repo rules, codify repeated mistakes there, and let deeper files carry richer domain detail. ([OpenAI Developers][2])

---

## 16. RMN-specific rules

This is where `docgarden` becomes genuinely useful for your assistant instead of generic.

### Critical domains

* metrics
* Walmart platform behavior
* workflow rules
* account current plans
* active exec plans

### RMN-specific detectors

#### Metric contract drift

Compare:

* `docs/metrics/metric-definitions.md`
* transform code
* report templates
* sample exports

Flag when “featured sales,” “ROAS,” “conversion,” or pacing rules disagree.

#### Platform drift

Flag when `docs/platforms/walmart-connect.md` references:

* deprecated tactic names
* outdated export fields
* retired workflow steps
* obsolete approval paths

#### Account freshness

Flag when `current-plan.md`:

* is past end date
* is older than review window
* has no weekly target section
* conflicts with `current-state.md`

#### Workflow drift

Flag when `docs/workflows/*.md` mention scripts, exports, or SOP steps no longer present in the repo.

#### Routing drift

Flag when AGENTS or index routes agents into stale docs instead of canonical ones.

---

## 17. Safe promotion rule

One especially useful rule for your repo:

If the same business rule appears in:

* 2 or more exec plans, or
* 1 exec plan + 1 PR comment summary, or
* 1 exec plan + 1 workflow workaround note

then `docgarden` should propose promoting that rule into a canonical doc.

That is how temporary session knowledge becomes repo knowledge.

---

## 18. Suggested initial config

```yaml
repo_name: rmn-assistant
strict_score_fail_threshold: 70
critical_domains:
  - metrics
  - platforms
  - workflows
  - accounts
review_defaults:
  canonical_review_cycle_days: 30
  account_plan_review_cycle_days: 7
  workflow_review_cycle_days: 45
safe_autofix:
  enabled: true
  allow:
    - links
    - indexes
    - metadata
    - headings
    - generated_docs
block_on:
  - broken_agents_routes
  - missing_frontmatter_on_canonical
  - stale_verified_canonical_docs
  - active_exec_plan_missing_progress
```

---

## 19. MVP build order

### Phase 1

Build the boring but high-value parts first.

* metadata parser
* link checker
* required-section checker
* AGENTS/index route checker
* stale-review checker
* score generator
* `QUALITY_SCORE.md` writer

### Phase 2

Add alignment checks.

* command drift
* schema drift
* metric drift
* workflow drift

### Phase 3

Add persistent queue and fix flow.

* findings store
* plan clustering
* `next`
* resolution attestation
* safe autofix PRs

### Phase 4

Add subjective review.

* targeted LLM review for low-trust domains
* contradiction classification
* promotion suggestions

### Phase 5

Add RMN-specific intelligence.

* retailer export diffs
* account-plan freshness logic
* metric/report consistency checks

---

## 20. Best short definition

If you need the one-line design target:

**`docgarden` is a repo-local maintenance harness that keeps agent-facing documentation current, discoverable, and trustworthy, using persistent findings, honest quality scores, safe fix-up PRs, and CI enforcement.**

The strongest version of this for your RMN assistant is not “write more docs.” It is:

**make the right docs canonical, keep them routable from `AGENTS.md`, grade their trustworthiness, and continuously repair drift before it poisons the agent.**


[1]: https://openai.com/index/harness-engineering/ "Harness engineering: leveraging Codex in an agent-first world | OpenAI"
[2]: https://developers.openai.com/codex/guides/agents-md/ "Custom instructions with AGENTS.md"
[3]: https://developers.openai.com/cookbook/articles/codex_exec_plans/ "Using PLANS.md for multi-hour problem solving"
[4]: https://raw.githubusercontent.com/peteromallet/desloppify/main/docs/SKILL.md "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/peteromallet/desloppify/main/docs/DEVELOPMENT_PHILOSOPHY.md "raw.githubusercontent.com"
[6]: https://github.com/peteromallet/desloppify "GitHub - peteromallet/desloppify: Agent harness to make your slop code well-engineered and beautiful. · GitHub"
