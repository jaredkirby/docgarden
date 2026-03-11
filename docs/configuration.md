---
doc_id: configuration
doc_type: reference
domain: docs
owner: kirby
status: draft
last_reviewed: 2026-03-10
review_cycle_days: 30
applies_to:
  - repo
source_of_truth:
  - docgarden/config.py
  - docgarden/automation.py
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - configuration
  - reference
---

# Configuration Reference

Docgarden is configured through a single YAML file at `.docgarden/config.yaml` in the repository root. If the file is missing or empty, all fields use their defaults. If the file exists but contains invalid YAML or an unexpected top-level type, docgarden raises a `ConfigError` and refuses to proceed.

## Config fields

### `strict_score_fail_threshold`

| Property | Value |
|----------|-------|
| Type | `int` |
| Default | `70` |
| Validation | Must be an integer. |

The minimum acceptable strict score for the `docgarden ci check` command. When a scan produces a strict score below this threshold, `ci check` includes a `strict_score_fail_threshold` failure in its output and exits with code 2.

The strict score differs from the overall score in that it does not exclude `accepted_debt` findings from its penalty calculation -- every open finding counts, regardless of whether the team has acknowledged it.

### `critical_domains`

| Property | Value |
|----------|-------|
| Type | `list[str]` |
| Default | `[]` (empty list) |
| Validation | Must be a list of strings. |

Domain names that are monitored for score regressions between consecutive scans. When a domain listed here has a lower score than the previous scan, docgarden records a `CriticalRegression` entry in the scorecard rollup. These regressions appear in the quality report under "Critical-Domain Regressions" and in the trend point history.

Critical domain tracking is purely informational -- it does not block CI on its own. It flags domains where any score drop deserves attention.

### `domain_weights`

| Property | Value |
|----------|-------|
| Type | `dict[str, int \| float]` |
| Default | `{}` (empty dict) |
| Validation | Keys must be strings. Values must be non-negative numbers (`int` or `float`, >= 0). |

Controls how per-domain scores are combined into the weighted domain rollup score. Each key is a domain name and its value is the weight applied to that domain's score.

**How the weighted rollup is calculated:**

1. For each domain with a computed score, the weight is looked up in `domain_weights`. If the domain is not listed, a default weight of `1` is used.
2. Domains with a weight of `0` are excluded from the weighted average but still appear in the raw average.
3. The weighted rollup is `round(sum(score * weight) / sum(weights))` across all domains with weight > 0.
4. If no domains have positive weight (or no domains exist), the weighted rollup falls back to the raw (unweighted) average.
5. The raw average is always `round(sum(scores) / count)` regardless of weights.

Both the weighted rollup and raw average appear in the quality score output. Setting higher weights on important domains causes their scores to have more influence on the rollup number.

### `block_on`

| Property | Value |
|----------|-------|
| Type | `list[str]` |
| Default | `[]` (empty list) |
| Validation | Must be a list of strings. |

A list of blocking rule names that `docgarden ci check` evaluates against all active, score-relevant findings. When any listed rule matches one or more findings, `ci check` reports a `blocking_rule` failure and exits with code 2.

If a rule name in `block_on` does not match any entry in the built-in `BLOCKING_RULES` registry, `ci check` reports an `unknown_blocking_rule` failure for that name. This fail-closed behavior ensures typos or stale rule names do not silently skip enforcement.

**Available blocking rules:**

#### `broken_agents_routes`

Matches findings of kind `broken-route` or `stale-route` where any of the finding's files is `AGENTS.md`. Blocks when the `AGENTS.md` routing table contains links that are broken or have gone stale.

#### `missing_frontmatter_on_canonical`

Matches findings of kind `missing-frontmatter` where any of the finding's files starts with `docs/`. Blocks when documents under the `docs/` tree lack YAML frontmatter entirely, preventing them from carrying canonical metadata (doc_id, doc_type, owner, etc.).

#### `stale_verified_canonical_docs`

Matches findings of kind `stale-review` or `verified-without-sources` where the primary document has `doc_type: canonical` and `status: verified` in its frontmatter. Blocks when a document that claims to be a verified canonical source has fallen out of its review window or is missing the trust metadata that supports its verified status.

#### `active_exec_plan_missing_progress`

Matches findings of kind `missing-sections` where the missing sections include `Progress`, and the primary document lives under `docs/exec-plans/active/` with `doc_type: exec-plan` in its frontmatter. Blocks when an active execution plan does not have the required `Progress` section to track completion.

### `pr_drafts`

| Property | Value |
|----------|-------|
| Type | `dict` (sub-configuration mapping) |
| Default | `{}` (empty dict) |
| Validation | Must be a mapping. |

Configures the `docgarden pr draft` command for generating and optionally publishing draft PRs or follow-up issues. All sub-fields are read from this mapping by `DraftPublishTarget.from_config()`.

#### `pr_drafts.enabled`

| Property | Value |
|----------|-------|
| Type | `bool` |
| Default | `false` |

Master switch for remote publish capability. When `false`, `docgarden pr draft --publish` reports a blocker and refuses to create anything on the remote provider. Local draft generation (without `--publish`) always works regardless of this setting.

#### `pr_drafts.provider`

| Property | Value |
|----------|-------|
| Type | `str \| null` |
| Default | `null` |

The hosting provider to publish to. Currently only `"github"` is supported. Any other value (or omission) causes a publish blocker.

#### `pr_drafts.repository`

| Property | Value |
|----------|-------|
| Type | `str \| null` |
| Default | `null` |

The target repository in `owner/repo` format (e.g., `"kirby/docgarden"`). Required for publishing. Omission causes a publish blocker.

#### `pr_drafts.base_branch`

| Property | Value |
|----------|-------|
| Type | `str \| null` |
| Default | `null` |

The branch that draft PRs target as their base. Required for publishing. Omission causes a publish blocker.

#### `pr_drafts.token_env_var`

| Property | Value |
|----------|-------|
| Type | `str` |
| Default | `"DOCGARDEN_GITHUB_TOKEN"` |

The name of the environment variable that holds the GitHub API token. At publish time, docgarden reads `os.environ[token_env_var]`. If the variable is unset or empty, publishing is blocked.

This is the variable *name*, not the token itself. Tokens are never stored in the config file.

#### `pr_drafts.api_base_url`

| Property | Value |
|----------|-------|
| Type | `str` |
| Default | `"https://api.github.com"` |

The base URL for the GitHub API. Override this for GitHub Enterprise Server instances.

#### Fail-closed publish behavior

The `--publish` flag checks all of the following before making any API call. If any check fails, the draft is not published and the blocker messages are returned in the `publish_blockers` list:

1. `enabled` must be `true`.
2. `provider` must be `"github"`.
3. `repository` must be set.
4. `base_branch` must be set.
5. The environment variable named by `token_env_var` must be set and non-empty.
6. For PR mode (not `--unsafe-as-issue`), at least one actionable finding must be in scope.

Without `--publish`, the command generates the draft payload locally and prints it as JSON regardless of these checks.

## Complete example

This config enables all blocking rules, weights three domains, tracks two critical domains, and configures GitHub PR drafts:

```yaml
strict_score_fail_threshold: 70
critical_domains:
  - docs
  - exec-plans
domain_weights:
  docs: 4
  exec-plans: 3
  design-docs: 2
block_on:
  - broken_agents_routes
  - missing_frontmatter_on_canonical
  - stale_verified_canonical_docs
  - active_exec_plan_missing_progress
pr_drafts:
  enabled: true
  provider: github
  repository: kirby/docgarden
  base_branch: main
  token_env_var: DOCGARDEN_GITHUB_TOKEN
  api_base_url: https://api.github.com
```

## Minimal config

An empty file (or no file at all) is valid. Every field falls back to its default:

```yaml
# .docgarden/config.yaml
# All defaults apply:
#   strict_score_fail_threshold: 70
#   critical_domains: []
#   domain_weights: {}
#   block_on: []
#   pr_drafts: {}
```

With no `block_on` rules and no `critical_domains`, `docgarden ci check` only enforces the strict score threshold (default 70). The weighted domain rollup treats all domains equally (weight 1). PR draft publishing is disabled.
