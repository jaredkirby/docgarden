# docgarden 🌱

`docgarden` is a repo-local maintenance harness for agent-facing documentation.
It scans for stale or malformed docs, writes an honest quality score, persists
findings, supports queue-based triage and resolution, and offers a
deterministic safe-fix path for low-risk mechanical hygiene issues.

## Commands

```bash
docgarden scan
docgarden scan --scope changed
docgarden scan --scope changed --files docs/index.md docs/workflows/reporting.md
docgarden status
docgarden ci check
docgarden next
docgarden review prepare --domains docs,design-docs
docgarden review import review.json
docgarden plan
docgarden plan triage --stage observe --report "root causes and themes"
docgarden plan triage --stage reflect --report "comparison against recent work"
docgarden plan triage --stage organize --report "priority order and rationale"
docgarden plan focus FINDING_ID_OR_CLUSTER
docgarden plan resolve FINDING_ID --result fixed
docgarden plan reopen FINDING_ID
docgarden pr draft
docgarden pr draft --unsafe-as-issue
docgarden pr draft --publish
docgarden show FINDING_ID
docgarden quality write
docgarden fix safe --apply
docgarden config show
docgarden doctor
```

`docgarden scan --scope changed` is a fast partial preview. By default it uses
local git state and scans the union of unstaged changes, staged changes,
untracked docs, and deleted doc paths under `AGENTS.md` and `docs/`.

`docgarden scan --scope changed --files ...` scans only the listed existing doc
paths. It does not infer deletions, does not rewrite `.docgarden` state, and
returns the last full-scan score only as a baseline reference.

## Workflow

For a full repo-quality pass:

```bash
docgarden scan
docgarden status
docgarden next
docgarden plan
```

For plan-driven operator flow:

```bash
docgarden plan triage --stage observe --report "themes and root causes"
docgarden plan triage --stage reflect --report "comparison against completed work"
docgarden plan triage --stage organize --report "execution order and rationale"
docgarden plan focus FINDING_ID_OR_CLUSTER
docgarden plan resolve FINDING_ID --result fixed
```

For subjective review prep/import:

```bash
docgarden review prepare --domains docs
docgarden review import review.json
docgarden next
```

`docgarden review prepare` writes a deterministic packet under
`.docgarden/reviews/` containing the selected docs plus stable mechanical
finding context for those files. By default it includes only review-ready docs
under `docs/`; files that are skipped because they lack frontmatter or a
declared domain are listed in the command output and packet scope metadata.
`docgarden review import` accepts a structured JSON payload that references one
of those packet IDs, stores the imported review under `.docgarden/reviews/`,
and appends subjective findings with provenance into `findings.jsonl`.

`docgarden fix safe` previews the exact low-risk edits it would make. Adding
`--apply` limits mutations to deterministic repairs such as stale-status
updates, missing required headings, metadata skeleton insertion, unambiguous
internal link repairs, and exact current-truth route replacements to uniquely
resolved current canonical docs.

Clean review passes are valid imports too. A no-findings payload can look like:

```json
{
  "packet_id": "<prepared-packet-id>",
  "review_id": "docs-clean-pass",
  "provenance": {
    "runner": "manual",
    "reviewer": "kirby"
  },
  "findings": []
}
```

Use `accepted_debt`, `needs_human`, or `false_positive` with
`docgarden plan resolve` when the outcome is not a straightforward fix. Those
non-trivial outcomes should include `--attest` text so the audit trail stays
honest.

Use changed-scope scans for fast local feedback while editing docs, then return
to a full `docgarden scan` before treating the score, queue, or persisted state
as authoritative.

`docgarden pr draft` runs a fresh full scan, then builds a markdown-ready draft
summary from the current actionable findings (`open`, `in_progress`, and
`needs_human`) plus current non-transient git changes. Resolved states such as
`accepted_debt`, `fixed`, and `false_positive` are left out of the draft scope.
The JSON output includes the generated title/body, the exact finding ids in
scope, the changed files list, and explicit publish blockers when remote
automation is not configured or when PR mode has no actionable findings in
scope.

Use `docgarden pr draft --unsafe-as-issue` when the actionable findings are not
safe to autofix and you want a follow-up issue draft instead of a PR draft.
With `--publish`, that path creates a normal GitHub issue, because GitHub does
not have a draft-issue object.

## Automation

`docgarden ci check` evaluates the persisted score after a full scan and exits
nonzero when either the configured strict-score threshold or any configured
`block_on` rule trips. The output is structured JSON so CI can fail clearly
while still uploading an auditable summary.

This repo now includes three GitHub Actions workflows:

- `.github/workflows/docgarden-pr.yml`
  Runs a full scan on PRs, refreshes `QUALITY_SCORE.md`, evaluates
  `docgarden ci check`, and uploads the scan/check artifacts.
- `.github/workflows/docgarden-nightly.yml`
  Runs a nightly full scan, refreshes the quality report, applies
  `docgarden fix safe --apply` only inside the CI workspace, and uploads any
  resulting patch instead of mutating repo truth directly.
- `.github/workflows/docgarden-weekly-review.yml`
  Runs a weekly scan, prepares a review packet, groups in-scope docs by owner,
  and uploads the packet plus owner-nudge artifacts.

`docgarden pr draft --publish` stays fail-closed. Remote PR or issue creation
only runs when `.docgarden/config.yaml` opts into repo support explicitly and a
token is present in the configured environment variable. Example:

```yaml
pr_drafts:
  enabled: true
  provider: github
  repository: owner/repo
  base_branch: main
  token_env_var: DOCGARDEN_GITHUB_TOKEN
```

Without that config and credential, `docgarden pr draft` still generates the
local title/body summary but reports why publish is blocked instead of touching
the hosting provider.

The former slice automation surface has been extracted from this repository.
`docgarden` now focuses on documentation scanning, scoring, review, planning,
safe autofix, and PR-draft support rather than shipping a `docgarden slices`
workflow.

## Score rollups

`docgarden` now records more than just overall and strict scores. Full scans
also persist:

- weighted domain rollups
- raw domain averages
- critical-domain regressions
- trend points across scans

Operators configure those rollups in `.docgarden/config.yaml`. Example:

```yaml
critical_domains:
  - docs
  - exec-plans
domain_weights:
  docs: 4
  exec-plans: 3
  design-docs: 2
```

How the knobs work:

- `domain_weights` changes the weighted rollup only; it does not hide the raw
  per-domain scores
- omitted domains default to weight `1`
- `critical_domains` marks domains that should be called out separately when
  their score regresses, even if the overall score still looks healthy

Where to inspect the outputs:

- `.docgarden/score.json`
  Key fields: `rollup.weighted_score`, `rollup.raw_average_score`,
  `rollup.weights`, `rollup.critical_regressions`, `trend.points`,
  `trend.summary`
- `docs/QUALITY_SCORE.md`
  Human-readable summary of weighted rollup, raw average, trend, and critical
  regressions
- `docgarden scan`
  Refreshes the persisted score state
- `docgarden quality write`
  Regenerates `docs/QUALITY_SCORE.md` from the latest score state

## Current implementation status

The repo currently includes:

- frontmatter validation
- required section checks
- stale review detection
- duplicate `doc_id` detection
- broken route and internal markdown link checks
- source-of-truth artifact alignment checks
- unsupported `docgarden` validation command checks on non-draft docs
- workflow drift checks for missing repo-owned local assets in workflow-style
  sections
- promotion suggestions when the same repo-specific rule repeats across exec
  plans or other transient note-style docs
- quality scoring and score publication
- persisted score trend points, configurable domain-weighted rollups, and
  critical-domain regression summaries
- append-only findings history and a prioritized plan view
- deterministic review packet export plus strict review import backed by
  `.docgarden/reviews/`
- plan triage stages with persisted notes
- manual queue focus, resolve, and reopen commands
- read-only changed-scope scans for partial local or CI feedback
- deterministic safe autofix previews plus low-risk apply support for metadata,
  headings, stale status, unambiguous link repairs, and exact route-reference
  repairs to current canonical docs
- a CI-friendly `docgarden ci check` command for threshold and blocker
  enforcement
- GitHub Actions for PR enforcement, nightly scan plus safe-autofix patch
  capture, and weekly review-packet owner nudges
- draft PR and unsafe-follow-up issue summaries backed by current findings plus
  changed-file context, with explicit GitHub publish gating

The promotion detector only scans transient docs: exec plans plus non-verified
note, workaround, scratch, summary, or temporary docs inferred from their
paths. It only fires on repeated directive, repo-specific wording, and each
finding includes a primary canonical destination plus optional supporting
reference docs with matched-keyword evidence.
