---
doc_id: commands
doc_type: reference
domain: docs
owner: kirby
status: draft
last_reviewed: 2026-03-10
review_cycle_days: 30
applies_to:
  - repo
source_of_truth:
  - docgarden/cli.py
  - docgarden/cli_commands.py
  - docgarden/cli_plan_review.py
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - commands
  - reference
---

# CLI Command Reference

## Global Behavior

All commands operate on the repo rooted at the current working directory. State is
persisted under `.docgarden/` (findings, plan, score, config). Any command that
encounters a `DocgardenError` prints the message to stderr and exits with the
error's `exit_code` (default `1`).

Error classes: `ConfigError`, `StateError`, `MarkdownError` -- all subclass
`DocgardenError` and carry `exit_code = 1`.

---

## docgarden scan

Scan the repo for documentation findings.

### Synopsis

```
docgarden scan [--scope {all,changed}] [--files FILE ...]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--scope` | `{all, changed}` | `all` | `all` scans the whole repo. `changed` scans only the changed-doc subset. |
| `--files` | one or more paths | _(none)_ | Repo-relative doc files to treat as changed. Only valid with `--scope changed`. |

When `--scope changed` is used without `--files`, changed files are derived from
local git state (unstaged, staged, untracked, and deleted doc paths under
`AGENTS.md` and `docs/`).

Using `--files` without `--scope changed` raises a `DocgardenError`.

### Output (JSON)

**Full scan** (`--scope all`):

| Field | Type | Description |
|-------|------|-------------|
| `scope` | string | `"all"` |
| `findings` | int | Total finding count |
| `overall_score` | int or null | Overall quality score |
| `strict_score` | int or null | Strict quality score |

**Changed scan** (`--scope changed`):

| Field | Type | Description |
|-------|------|-------------|
| `scope` | string | `"changed"` |
| `findings` | int | Finding count for changed files |
| `overall_score` | null | Always null for changed scans |
| `strict_score` | null | Always null for changed scans |
| `last_full_scan_overall_score` | int or null | Previous full-scan overall score |
| `last_full_scan_strict_score` | int or null | Previous full-scan strict score |
| `changed_files_source` | string or null | How changed files were determined |
| `requested_files` | list[string] | Files passed via `--files` |
| `scanned_files` | list[string] | Files actually scanned |
| `deleted_files` | list[string] | Deleted files detected |
| `recomputed_views` | list[string] | Views recomputed during scan |
| `skipped_views` | list[string] | Views skipped |
| `notes` | list[string] | Diagnostic notes |

### Example

```bash
docgarden scan
docgarden scan --scope changed
docgarden scan --scope changed --files docs/index.md AGENTS.md
```

---

## docgarden status

Show a summary of the current repo state.

### Synopsis

```
docgarden status
```

### Output (JSON)

| Field | Type | Description |
|-------|------|-------------|
| `active_findings` | int | Count of active (actionable) findings |
| `open_ids` | list[string] | Up to 10 active finding IDs, priority-ordered |
| `overall_score` | int or null | Overall quality score from last full scan |
| `strict_score` | int or null | Strict quality score from last full scan |

### Example

```bash
docgarden status
```

---

## docgarden ci check

CI gate that exits non-zero when score thresholds or blocking rules fail.

### Synopsis

```
docgarden ci check
```

### Output (JSON)

| Field | Type | Description |
|-------|------|-------------|
| `checked_at` | string | ISO timestamp |
| `passed` | bool | `true` if all checks pass |
| `strict_score` | int or null | Current strict score |
| `strict_score_fail_threshold` | int | Configured threshold (default `70`) |
| `block_on` | list[string] | Configured blocking rule names |
| `active_score_relevant_findings` | int | Findings in score-relevant statuses |
| `failures` | list[object] | Array of failure objects (see below) |

Each failure object contains `type`, `summary`, and rule-specific fields. Types:
`strict_score_fail_threshold`, `blocking_rule`, `unknown_blocking_rule`.

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All checks passed |
| `2` | One or more checks failed |

### Example

```bash
docgarden ci check
```

---

## docgarden next

Print the highest-priority active finding.

### Synopsis

```
docgarden next
```

### Output

If there are active findings, prints the top finding as JSON (all `FindingRecord`
fields via `to_dict()`). If no findings are active, prints the string:
`No open findings.`

### Example

```bash
docgarden next
```

---

## docgarden show

Show the latest event for a specific finding by ID.

### Synopsis

```
docgarden show FINDING_ID
```

### Arguments

| Argument | Description |
|----------|-------------|
| `FINDING_ID` | The finding ID to look up |

### Output (JSON)

The full `FindingRecord` payload for the latest event matching the given ID.

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Finding found and printed |
| `1` | Finding not found (message printed to stderr) |

### Example

```bash
docgarden show "missing-frontmatter::docs::index.md::frontmatter"
```

---

## docgarden plan

Print the current plan state. If no plan exists, triggers a full scan first.

### Synopsis

```
docgarden plan
```

### Output (JSON)

The full `PlanState` as a dict:

| Field | Type | Description |
|-------|------|-------------|
| `updated_at` | string | ISO timestamp of last update |
| `lifecycle_stage` | string | One of: `observe`, `reflect`, `organize`, `complete` |
| `current_focus` | string or null | Currently focused finding ID or cluster name |
| `ordered_findings` | list[string] | Priority-ordered finding IDs |
| `clusters` | dict[string, list[string]] | Finding IDs grouped by cluster |
| `deferred_items` | list[string] | Deferred finding IDs |
| `last_scan_hash` | string | Hash of the scan that produced this plan |
| `stage_notes` | dict[string, string] | Notes keyed by triage stage name |
| `strategy_text` | string or null | Overall strategy text |

### Example

```bash
docgarden plan
```

---

## docgarden plan triage

Record a triage stage note in the plan.

### Synopsis

```
docgarden plan triage --stage {observe,reflect,organize} --report REPORT
```

### Options

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `--stage` | `{observe, reflect, organize}` | yes | Workflow stage to record |
| `--report` | string | yes | Non-empty stage note to store |

### Output (JSON)

The updated `PlanState` (same schema as `docgarden plan`).

### Example

```bash
docgarden plan triage --stage observe --report "Found 3 stale docs under docs/design-docs/"
docgarden plan triage --stage reflect --report "Cluster by domain, fix stale-review first"
docgarden plan triage --stage organize --report "Priority: agents routes > design docs > exec plans"
```

---

## docgarden plan focus

Set the plan's `current_focus` to a finding ID or cluster name.

### Synopsis

```
docgarden plan focus ID_OR_CLUSTER
```

### Arguments

| Argument | Description |
|----------|-------------|
| `ID_OR_CLUSTER` | Actionable finding ID or cluster name from `docgarden plan` |

### Output (JSON)

The updated `PlanState` (same schema as `docgarden plan`).

### Example

```bash
docgarden plan focus "missing-frontmatter::docs::index.md::frontmatter"
docgarden plan focus "stale-review"
```

---

## docgarden plan resolve

Resolve an actionable finding by recording a new status event.

### Synopsis

```
docgarden plan resolve FINDING_ID --result {in_progress,fixed,accepted_debt,needs_human,false_positive} [--attest ATTESTATION]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `FINDING_ID` | Actionable finding ID from the current queue |

### Options

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `--result` | `{in_progress, fixed, accepted_debt, needs_human, false_positive}` | yes | Status to record. `needs_human` keeps the finding actionable. |
| `--attest` | string | conditional | Required for `accepted_debt`, `needs_human`, and `false_positive`. Human attestation text. |

### Output (JSON)

| Field | Type | Description |
|-------|------|-------------|
| `event` | object | The recorded `FindingRecord` event |
| `plan` | object | The updated `PlanState` |

### Example

```bash
docgarden plan resolve "stale-review::docs::spec.md::review" --result fixed
docgarden plan resolve "missing-metadata::docs::index.md::owner" --result accepted_debt --attest "Owner field intentionally omitted for generated docs"
docgarden plan resolve "broken-link::docs::guide.md::link" --result false_positive --attest "Link is valid but behind VPN"
```

---

## docgarden plan reopen

Reopen a previously resolved finding by appending a new `open` event.

### Synopsis

```
docgarden plan reopen FINDING_ID
```

### Arguments

| Argument | Description |
|----------|-------------|
| `FINDING_ID` | Previously resolved finding ID (status must be `fixed`, `accepted_debt`, or `false_positive`) |

### Output (JSON)

| Field | Type | Description |
|-------|------|-------------|
| `event` | object | The new `open` event |
| `plan` | object | The updated `PlanState` |

### Example

```bash
docgarden plan reopen "stale-review::docs::spec.md::review"
```

---

## docgarden review prepare

Export a deterministic review packet for targeted subjective review.

### Synopsis

```
docgarden review prepare [--domains DOMAINS]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--domains` | comma-separated string | _(all review-ready docs under `docs/`)_ | Doc domains to include in the packet. Docs that lack packetizable metadata are reported as skipped. |

### Output (JSON)

| Field | Type | Description |
|-------|------|-------------|
| `packet_id` | string | Unique identifier for this review packet |
| `path` | string | Filesystem path where the packet was written |
| `domains` | list[string] | Domains included |
| `documents` | int or list | Documents included in the packet |
| `skipped_documents` | int or list | Documents skipped (missing metadata) |
| `mechanical_findings` | int | Count of mechanical findings bundled |

### Example

```bash
docgarden review prepare
docgarden review prepare --domains docs,design-docs
```

---

## docgarden review import

Import structured review findings from a JSON file that references a prepared packet.

### Synopsis

```
docgarden review import FILE
```

### Arguments

| Argument | Description |
|----------|-------------|
| `FILE` | Path to a structured review JSON file |

### Output (JSON)

| Field | Type | Description |
|-------|------|-------------|
| `review_id` | string | Unique identifier for the imported review |
| `packet_id` | string | Packet ID the review references |
| `stored_review` | string | Filesystem path where the review was stored |
| `finding_ids` | list[string] | IDs of findings created from the review |
| `plan` | object | The updated `PlanState` |

### Example

```bash
docgarden review import review-results.json
```

---

## docgarden fix safe

Preview or apply safe automated fixes for findings marked `safe_to_autofix`.

### Synopsis

```
docgarden fix safe [--apply]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--apply` | flag | `false` | Apply the fixes. Without this flag, only a preview is printed. |

### Output (JSON)

**Preview** (without `--apply`):

| Field | Type | Description |
|-------|------|-------------|
| `fixable` | list[string] | Finding IDs that can be auto-fixed |
| `planned_changes` | list[object] | Each entry has `id`, `kind`, `files`, `changes` |

**Apply** (with `--apply`):

| Field | Type | Description |
|-------|------|-------------|
| `changed_files` | list[string] | Files modified by the fixes |
| `active_findings` | int | Remaining active findings after re-scan |

### Example

```bash
docgarden fix safe
docgarden fix safe --apply
```

---

## docgarden quality write

Run a full scan and write the quality scorecard to `docs/QUALITY_SCORE.md`.

### Synopsis

```
docgarden quality write
```

### Output

Prints: `Wrote docs/QUALITY_SCORE.md`

### Example

```bash
docgarden quality write
```

---

## docgarden pr draft

Generate a markdown PR or issue summary from actionable findings and changed files.

### Synopsis

```
docgarden pr draft [--unsafe-as-issue] [--publish]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--unsafe-as-issue` | flag | `false` | Draft an unsafe-work follow-up issue instead of a PR. Selects only findings where `safe_to_autofix` is `false`. Raises `DocgardenError` if no unsafe findings exist. |
| `--publish` | flag | `false` | Create the draft PR (or issue with `--unsafe-as-issue`) through the configured GitHub provider. Requires `pr_drafts` config in `.docgarden/config.yaml`. |

### Output (JSON)

| Field | Type | Description |
|-------|------|-------------|
| `mode` | string | `"pr"` or `"issue"` |
| `summary` | string | Human-readable summary line |
| `title` | string | Draft title |
| `body` | string | Full markdown body |
| `total_actionable_findings` | int | Total actionable finding count |
| `total_active_findings` | int | Total active finding count |
| `finding_count` | int | Findings included in this draft |
| `finding_ids` | list[string] | IDs of included findings |
| `findings` | list[object] | Each has `id`, `kind`, `status`, `severity`, `summary`, `files`, `recommended_action`, `safe_to_autofix` |
| `safe_finding_ids` | list[string] | IDs of safe-to-autofix findings |
| `unsafe_finding_ids` | list[string] | IDs of unsafe findings |
| `changed_files` | list[string] | Non-transient changed files from git |
| `deleted_files` | list[string] | Deleted files from git |
| `branch` | string or null | Current git branch name |
| `publish_target` | object | Provider config (`enabled`, `provider`, `repository`, `base_branch`, `token_env_var`, `api_base_url`) |
| `publish_ready` | bool | `true` if all publish prerequisites are met |
| `publish_blockers` | list[string] | Reasons publish is blocked |
| `published` | bool | `true` if `--publish` succeeded |
| `remote` | object or null | After publish: `kind`, `number`, `url` (and `head_branch`, `base_branch` for PRs) |
| `notes` | list[string] | Diagnostic notes |

### Example

```bash
docgarden pr draft
docgarden pr draft --unsafe-as-issue
docgarden pr draft --publish
```

---

## docgarden config show

Print the resolved configuration.

### Synopsis

```
docgarden config show
```

### Output (JSON)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `strict_score_fail_threshold` | int | `70` | Score below which `ci check` fails |
| `critical_domains` | list[string] | `[]` | Domains with elevated scoring weight |
| `domain_weights` | dict[string, number] | `{}` | Per-domain weight overrides |
| `block_on` | list[string] | `[]` | Blocking rule names for `ci check` |
| `pr_drafts` | dict | `{}` | PR/issue publish configuration |

### Example

```bash
docgarden config show
```

---

## docgarden doctor

Check that the repo environment is set up correctly.

### Synopsis

```
docgarden doctor
```

### Output (JSON)

| Field | Type | Description |
|-------|------|-------------|
| `repo_root` | string | Absolute path to the repo root |
| `config_exists` | bool | Whether `.docgarden/config.yaml` exists |
| `docs_exists` | bool | Whether `docs/` directory exists |
| `agents_exists` | bool | Whether `AGENTS.md` exists |
| `state_dir` | string | Absolute path to `.docgarden/` |

### Example

```bash
docgarden doctor
```
