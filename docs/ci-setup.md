---
doc_id: ci-setup
doc_type: reference
domain: docs
owner: kirby
status: draft
last_reviewed: 2026-03-10
review_cycle_days: 30
applies_to:
  - repo
source_of_truth:
  - docgarden/automation.py
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - ci
  - automation
  - reference
---

# CI setup

How to integrate docgarden into your CI pipeline so documentation quality is
enforced automatically.

## Overview

Docgarden provides a `docgarden ci check` command designed for CI. It runs
against persisted scan state, evaluates your configured score threshold and
blocking rules, and exits with a clear pass/fail signal. Combined with GitHub
Actions workflows, it gives you PR-level gating, nightly health checks, and
weekly review automation.

## How ci check works

`docgarden ci check` expects a scan to have already run (if no scan state
exists, it triggers one automatically). It then:

1. Loads the strict score from `.docgarden/score.json`.
2. Compares it against `strict_score_fail_threshold` from
   `.docgarden/config.yaml` (default: 70).
3. Evaluates every rule listed in the `block_on` config array against active
   findings.
4. Outputs a structured JSON payload.
5. Exits **0** if all checks pass, or **2** if any check fails.

### Output format

```json
{
  "checked_at": "2026-03-10T14:30:00",
  "passed": true,
  "strict_score": 82,
  "strict_score_fail_threshold": 70,
  "block_on": ["broken_agents_routes", "missing_frontmatter_on_canonical"],
  "active_score_relevant_findings": 4,
  "failures": []
}
```

When a check fails, the `failures` array contains one entry per failure:

```json
{
  "failures": [
    {
      "type": "strict_score_fail_threshold",
      "summary": "Strict score 58 is below the configured threshold of 70.",
      "strict_score": 58,
      "threshold": 70
    },
    {
      "type": "blocking_rule",
      "rule": "broken_agents_routes",
      "summary": "Configured blocking rule `broken_agents_routes` matched 2 finding(s).",
      "description": "Broken or stale routes in `AGENTS.md`.",
      "finding_count": 2,
      "findings": [
        {
          "id": "agents-md-route-broken-123",
          "kind": "broken-route",
          "status": "open",
          "severity": "high",
          "summary": "AGENTS.md links to a missing file.",
          "files": ["AGENTS.md"],
          "recommended_action": "Update or remove the broken route."
        }
      ]
    }
  ]
}
```

## Configuring thresholds

Set `strict_score_fail_threshold` in `.docgarden/config.yaml`:

```yaml
strict_score_fail_threshold: 70
```

This is the minimum strict score that `docgarden ci check` will accept. If the
strict score from the most recent scan falls below this value, the check fails.

Choose a threshold that reflects your current baseline. A common approach:

1. Run `docgarden scan` and note the current strict score.
2. Set the threshold at or slightly below the current score.
3. Raise the threshold as you fix findings and the score improves.

Setting the threshold to `0` effectively disables score-based gating while
still allowing blocking rules to operate.

## Blocking rules

Blocking rules are evaluated by `docgarden ci check` when listed in the
`block_on` config array. Each rule matches specific kinds of active findings.
If any configured rule matches at least one finding, the check fails.

### Available rules

| Rule name | What it blocks |
|---|---|
| `broken_agents_routes` | Broken or stale routes in `AGENTS.md`. Matches findings with kind `broken-route` or `stale-route` on `AGENTS.md`. |
| `missing_frontmatter_on_canonical` | Docs under `docs/` that are missing frontmatter entirely. Matches `missing-frontmatter` findings on files whose path starts with `docs/`. |
| `stale_verified_canonical_docs` | Verified canonical docs that are stale or missing trust metadata. Matches `stale-review` or `verified-without-sources` findings on docs where `doc_type` is `canonical` and `status` is `verified`. |
| `active_exec_plan_missing_progress` | Active exec plans missing the required `Progress` section. Matches `missing-sections` findings where `Progress` is in the missing list, the file is under `docs/exec-plans/active/`, and `doc_type` is `exec-plan`. |

### Configuring block_on

Add the rule names you want enforced to the `block_on` list:

```yaml
block_on:
  - broken_agents_routes
  - missing_frontmatter_on_canonical
  - stale_verified_canonical_docs
  - active_exec_plan_missing_progress
```

If `block_on` is empty (the default), only the score threshold is checked.
Referencing an unknown rule name causes the check to fail with an
`unknown_blocking_rule` failure entry.

## GitHub Actions workflows

Docgarden ships three workflow files under `.github/workflows/`.

### docgarden-pr (PR enforcement)

**File:** `.github/workflows/docgarden-pr.yml`

Triggers on pull requests that touch documentation-related paths (`AGENTS.md`,
`docs/**`, `docgarden/**`, `tests/**`, `.docgarden/config.yaml`,
`pyproject.toml`, `uv.lock`, or workflow files). Also available via manual
dispatch.

Steps:

1. Checks out the repo with full history (`fetch-depth: 0`).
2. Sets up Python 3.12 and uv.
3. Runs `docgarden scan` and saves the output.
4. Runs `docgarden quality write` and `docgarden status` to capture a
   quality snapshot.
5. Runs `docgarden ci check` -- this is the gating step. If the score is
   below threshold or a blocking rule matches, the step fails and the PR
   check turns red.
6. Writes a GitHub step summary with the scan results and any failures.
7. Uploads all artifacts for 14-day retention.

### docgarden-nightly (nightly health check)

**File:** `.github/workflows/docgarden-nightly.yml`

Runs on a cron schedule (daily at 06:17 UTC) and via manual dispatch.

Steps:

1. Full scan with quality and status snapshots.
2. Runs `docgarden fix safe --apply` in the CI workspace and captures a diff
   patch. This does not push changes -- it produces an artifact you can
   review and apply locally.
3. Snapshots persisted state files (`score.json`, `plan.json`,
   `findings.jsonl`) for audit.
4. Writes a step summary showing finding count, strict score, and whether the
   safe autofix produced any changes.
5. Uploads all artifacts for 21-day retention.

The nightly workflow is not a gate -- it runs on `main` to track quality
trends over time. Download the `safe-autofix.patch` artifact to apply
mechanical fixes locally.

### docgarden-weekly-review (weekly review packets)

**File:** `.github/workflows/docgarden-weekly-review.yml`

Runs weekly on Mondays at 07:05 UTC and via manual dispatch.

Steps:

1. Full scan and status snapshot.
2. Runs `docgarden review prepare` to generate a review packet -- a
   deterministic export of docs that are due for subjective review.
3. Groups documents by owner and produces an `owner-nudges.json` listing
   which owners should review which documents.
4. Writes a step summary with the packet ID, document count, and per-owner
   breakdown.
5. Uploads all artifacts for 21-day retention.

Use the weekly review artifacts to coordinate doc reviews across your team.
Each owner can download the packet, review their assigned documents, and
submit structured review findings via `docgarden review import`.

## PR draft publishing

Docgarden can create draft PRs or follow-up issues on GitHub from scan
findings.

### Configuration

Add a `pr_drafts` section to `.docgarden/config.yaml`:

```yaml
pr_drafts:
  enabled: true
  provider: github
  repository: owner/repo-name
  base_branch: main
  token_env_var: DOCGARDEN_GITHUB_TOKEN
```

| Field | Required for publish | Description |
|---|---|---|
| `enabled` | Yes | Must be `true` to allow `--publish`. |
| `provider` | Yes | Only `github` is supported. |
| `repository` | Yes | GitHub repository as `owner/repo`. |
| `base_branch` | Yes | Branch the draft PR targets. |
| `token_env_var` | No | Environment variable name holding the GitHub token. Defaults to `DOCGARDEN_GITHUB_TOKEN`. |
| `api_base_url` | No | GitHub API base URL. Defaults to `https://api.github.com`. Set this for GitHub Enterprise. |

### Setting up the token

Create a GitHub personal access token (or fine-grained token) with
`contents: write` and `pull-requests: write` permissions. Then make it
available:

```bash
export DOCGARDEN_GITHUB_TOKEN=ghp_your_token_here
```

In CI, store the token as a repository secret and pass it via the workflow
environment.

### Usage

Preview a draft PR locally (no publish):

```bash
docgarden pr draft
```

Publish the draft PR to GitHub:

```bash
docgarden pr draft --publish
```

Create a follow-up issue for unsafe findings instead:

```bash
docgarden pr draft --unsafe-as-issue --publish
```

### Fail-closed behavior

Publishing fails cleanly if any prerequisite is missing. The command checks
all of the following before making an API call:

- `pr_drafts.enabled` must be `true`.
- `pr_drafts.provider` must be `github`.
- `pr_drafts.repository` must be set.
- `pr_drafts.base_branch` must be set.
- The token environment variable must be non-empty.
- For draft PRs, at least one actionable finding must exist.
- For draft PRs, the current git HEAD must be on a named branch (not
  detached).

If any check fails, the command prints the specific blockers and exits without
calling the GitHub API.

## Example CI workflow

A minimal GitHub Actions workflow that installs docgarden and runs the CI
check:

```yaml
name: docgarden

on:
  pull_request:
    paths:
      - "AGENTS.md"
      - "docs/**"
      - ".docgarden/config.yaml"

permissions:
  contents: read

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install docgarden
        run: pip install git+https://github.com/jaredkirby/docgarden.git

      - name: Scan
        run: docgarden scan

      - name: Enforce quality gate
        run: docgarden ci check
```

The `fetch-depth: 0` is required because docgarden uses git history for
changed-file detection and route analysis.

If you use [uv](https://docs.astral.sh/uv/) as your package manager (as the
built-in workflows do), replace the install step:

```yaml
      - uses: astral-sh/setup-uv@v5

      - name: Scan
        run: uv run docgarden scan

      - name: Enforce quality gate
        run: uv run docgarden ci check
```
