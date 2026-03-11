---
doc_id: getting-started
doc_type: canonical
domain: docs
owner: kirby
status: draft
last_reviewed: 2026-03-10
review_cycle_days: 30
applies_to:
  - repo
source_of_truth:
  - docgarden/cli.py
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - getting-started
  - docs
---

# Getting started with docgarden

This walkthrough takes you from a fresh install to a working docgarden setup
with scanned findings, a quality score, and a plan for fixing your docs.

## Purpose

Teach a new user how to install docgarden, add it to a repo, run a scan,
read findings, apply safe fixes, and publish a quality score.

## Scope

First-time setup and the core scan-plan-fix-rescan loop. For deeper topics
see the linked references at the end.

## Source of Truth

The CLI surface is defined in `docgarden/cli.py`. Command behavior is
implemented in `docgarden/cli_commands.py`.

## Rules / Definitions

- **Finding** -- a single detected documentation issue (missing frontmatter,
  stale review, broken link, etc.).
- **Score** -- a numeric quality rating. `overall_score` is lenient;
  `strict_score` penalizes unresolved findings more aggressively.
- **Plan** -- the prioritized queue of findings to work through.

## Prerequisites

You need:

- **Python 3.11 or later** (3.12 recommended).
- **git** -- docgarden uses local git state for changed-file detection.

## Installation

Install directly from the repository:

```bash
pip install git+https://github.com/jaredkirby/docgarden.git
```

For development (editable install):

```bash
git clone https://github.com/jaredkirby/docgarden.git
cd docgarden
pip install -e .
```

After installing, confirm the CLI is available:

```bash
docgarden --help
```

## Adding docgarden to your repo

Docgarden stores its configuration and state under a `.docgarden/` directory
at the repo root. At minimum you need a config file.

### 1. Create the config file

Create `.docgarden/config.yaml` with defaults:

```yaml
strict_score_fail_threshold: 70
critical_domains: []
domain_weights: {}
block_on: []
pr_drafts: {}
```

All fields are optional. If the file is empty or missing, docgarden uses the
defaults shown above. `strict_score_fail_threshold` is the minimum strict
score that `docgarden ci check` will accept (default 70).

### 2. Make sure you have the expected directories

Docgarden scans every markdown file under `docs/` and also `AGENTS.md` at
the repo root. If either is missing, the scan still runs but will report
fewer findings. You can verify your setup with:

```bash
docgarden doctor
```

This prints a JSON object showing whether `config.yaml`, `docs/`, and
`AGENTS.md` exist:

```json
{
  "repo_root": "/path/to/your/repo",
  "config_exists": true,
  "docs_exists": true,
  "agents_exists": true,
  "state_dir": "/path/to/your/repo/.docgarden"
}
```

## Your first scan

Run a full scan from the repo root:

```bash
docgarden scan
```

The output is JSON:

```json
{
  "scope": "all",
  "findings": 12,
  "overall_score": 64,
  "strict_score": 51
}
```

- **scope** -- `"all"` for a full scan, `"changed"` for a partial scan.
- **findings** -- total number of issues detected.
- **overall_score** -- lenient quality score (0--100).
- **strict_score** -- stricter score that penalizes unresolved findings more
  heavily. This is the number compared against
  `strict_score_fail_threshold` during CI checks.

The scan also persists findings to `.docgarden/findings.jsonl`, the score to
`.docgarden/score.json`, and the plan to `.docgarden/plan.json`. These files
are used by every subsequent command.

For faster feedback while editing, scan only locally changed files:

```bash
docgarden scan --scope changed
```

Changed-file detection uses local git state (unstaged, staged, untracked, and
deleted doc paths). You can also pass explicit files:

```bash
docgarden scan --scope changed --files docs/getting-started.md AGENTS.md
```

Always return to a full scan (`docgarden scan`) before treating scores as
authoritative.

## Reading findings

### Status overview

```bash
docgarden status
```

Returns a summary of active findings and current scores:

```json
{
  "active_findings": 12,
  "open_ids": [
    "docs-getting-started-md-frontmatter",
    "docs-concepts-md-stale",
    "agents-md-route-broken-123"
  ],
  "overall_score": 64,
  "strict_score": 51
}
```

- **active_findings** -- count of unresolved findings.
- **open_ids** -- the first 10 finding IDs, sorted by priority.
- **overall_score** / **strict_score** -- same as from `docgarden scan`.

### Next finding

```bash
docgarden next
```

Returns the single highest-priority finding as JSON:

```json
{
  "id": "docs-getting-started-md-frontmatter",
  "kind": "missing-frontmatter",
  "status": "open",
  "severity": "high",
  "summary": "docs/getting-started.md is missing required frontmatter.",
  "files": ["docs/getting-started.md"],
  "recommended_action": "Add frontmatter with the required metadata contract.",
  "safe_to_autofix": false
}
```

Key fields:

- **id** -- unique finding identifier used with `show`, `plan resolve`, etc.
- **kind** -- the rule that flagged this finding (e.g., `missing-frontmatter`,
  `stale-review`, `broken-link`, `missing-sections`, `missing-metadata`).
- **severity** -- `high`, `medium`, or `low`.
- **safe_to_autofix** -- `true` if `docgarden fix safe` can handle it.
- **recommended_action** -- what to do about it.

### Show a specific finding

```bash
docgarden show docs-getting-started-md-frontmatter
```

Returns the full finding record including evidence, details, and file paths.

## Fixing mechanical issues

Some findings are safe to fix automatically. These include:

- **stale-review** -- sets `status` to `needs-review` in frontmatter.
- **missing-sections** -- appends required section headings with `TODO: fill
  in.` placeholders.
- **missing-metadata** -- adds skeleton frontmatter fields with default values.
- **broken-link** -- replaces a broken link target with its deterministic
  replacement.
- **broken-route** / **stale-route** -- replaces stale route references in
  `AGENTS.md` and index docs.

### Preview what would change

```bash
docgarden fix safe
```

Output:

```json
{
  "fixable": [
    "docs-concepts-md-stale",
    "docs-index-md-sections"
  ],
  "planned_changes": [
    {
      "id": "docs-concepts-md-stale",
      "kind": "stale-review",
      "files": ["docs/concepts.md"],
      "changes": ["Set `status` to `needs-review`."]
    },
    {
      "id": "docs-index-md-sections",
      "kind": "missing-sections",
      "files": ["docs/index.md"],
      "changes": ["Add required headings: Exceptions / Caveats, Validation / How to verify."]
    }
  ]
}
```

### Apply the fixes

```bash
docgarden fix safe --apply
```

Output:

```json
{
  "changed_files": ["docs/concepts.md", "docs/index.md"],
  "active_findings": 10
}
```

After applying, a rescan runs automatically and the finding count updates.
Review the changes with `git diff` before committing.

## Working the plan

The plan is docgarden's prioritized queue of findings. Every scan rebuilds it.

### View the plan

```bash
docgarden plan
```

Returns the full plan state including the actionable queue, triage stages,
and current focus.

### Triage workflow

Before diving into fixes, record your observations:

```bash
docgarden plan triage --stage observe --report "Most findings are stale-review on exec plans."
docgarden plan triage --stage reflect --report "Exec plans under active/ need Progress sections."
docgarden plan triage --stage organize --report "Focus on metadata-gaps cluster first."
```

The three triage stages (`observe`, `reflect`, `organize`) help you think
through the work before acting.

### Set focus

```bash
docgarden plan focus metadata-gaps
```

Sets `current_focus` to a cluster name or finding ID.

### Resolve a finding

After fixing a finding manually:

```bash
docgarden plan resolve docs-getting-started-md-frontmatter --result fixed
```

Valid `--result` values:

- `fixed` -- the issue is resolved.
- `needs_human` -- stays in the actionable queue (requires `--attest`).
- `accepted_debt` -- acknowledged but not fixing (requires `--attest`).
- `false_positive` -- not a real issue (requires `--attest`).

For results that require attestation:

```bash
docgarden plan resolve some-finding-id --result accepted_debt \
  --attest "This doc is intentionally minimal."
```

### Reopen a resolved finding

```bash
docgarden plan reopen some-finding-id
```

### Confirm with a rescan

```bash
docgarden scan
```

After resolving findings and rescanning, the scores should improve.

## Publishing the quality score

Generate a human-readable quality score page:

```bash
docgarden quality write
```

This runs a full scan and writes `docs/QUALITY_SCORE.md` with the current
scores. Commit this file so it is visible in your repo.

## Exceptions / Caveats

- `docgarden scan --scope changed` does not compute `overall_score` or
  `strict_score` -- it only reports findings for the changed files. Always
  use a full scan for authoritative scores.
- The `fix safe --apply` command only touches findings flagged with
  `safe_to_autofix: true`. It will not modify files for findings that require
  human judgment.
- The `.docgarden/` directory (except `config.yaml`) contains generated state.
  You can safely delete `findings.jsonl`, `plan.json`, and `score.json` and
  rescan to regenerate them.

## Validation / How to verify

Run `docgarden doctor` to confirm your repo is set up correctly. Run
`docgarden scan` and verify the output contains `scope`, `findings`,
`overall_score`, and `strict_score` fields.

## Related docs

- [Concepts](concepts.md) -- findings, scores, plans, domains, document types
- [CI setup](ci-setup.md) -- GitHub Actions integration
- [Configuration](configuration.md) -- `.docgarden/config.yaml` reference
- [Command reference](commands.md) -- every command with options and examples
- [Full spec](design-docs/docgarden-spec.md) -- design target
