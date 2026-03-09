# docgarden 🪴

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
docgarden slices next
docgarden slices list
docgarden slices kickoff-prompt
docgarden slices review-prompt --worker-output .docgarden/slice-loops/.../worker-round-1.output.json
docgarden slices watch --max-updates 1
docgarden slices stop
docgarden slices recover
docgarden slices retry
docgarden slices prune --keep 3
docgarden slices run --max-slices 1
docgarden slices run --max-slices 1 --worker-timeout-seconds 900
docgarden slices run --max-slices 1 --reviewer-timeout-seconds 300
docgarden slices run --max-slices 1 --agent-timeout-seconds 600
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

## Slice automation

`docgarden slices next` shows the next queued implementation slice directly from
`docs/design-docs/docgarden-implementation-slices.md`.

`docgarden slices kickoff-prompt` and `docgarden slices review-prompt` generate
worker and PM-review prompts from the slice backlog itself, so the automation
loop does not depend on the manually maintained prompt pack staying perfectly
current.

The automation now also lives in a reusable Python module:

```python
from docgarden.slices import build_slice_paths, load_slice_catalog, run_slice_loop
```

That makes it usable from other project repos, especially when they want the
same worker/reviewer loop but keep their backlog, spec, or exec plan in
different locations.

`docgarden slices run` automates the worker/reviewer loop by:

1. selecting the next queued or active slice
2. generating the implementation prompt
3. running `codex exec` for the worker with a structured JSON output schema
4. generating the review prompt for that same slice
5. running a second `codex exec` reviewer with a structured recommendation schema
6. feeding reviewer findings back into the worker until the recommendation is
   `ready_for_next_slice`, or stopping on `blocked_pending_product_clarification`

Each run writes prompts, schemas, agent outputs, and stdout/stderr logs under
`.docgarden/slice-loops/` so the loop stays inspectable and restartable by
humans.

As soon as a slice starts, the CLI prints its artifact directory to stderr.
That makes it easier to inspect a long-running worker in real time instead of
waiting for the final JSON summary.

Use `docgarden slices run --max-slices 0` to keep advancing until no queued
slices remain. The safer default is `--max-slices 1`, which automates one slice
at a time.

Worker and reviewer runs now use separate default timeouts: 900 seconds for the
implementation worker and 300 seconds for the reviewer. Use
`--worker-timeout-seconds`, `--reviewer-timeout-seconds`, or the legacy
`--agent-timeout-seconds` override to tune them. Use `0` on any of those flags
to disable that timeout.

When a Codex run times out or exits nonzero, `docgarden` keeps the run
inspectable:

1. it writes live stdout/stderr streams directly into the current
   `.docgarden/slice-loops/...` run directory
2. it persists `run-status.json` with the current phase, timeout settings, and
   any terminal error
3. it leaves any repo changes the worker already made in place for manual
   verification or review

Nested runs also strip parent `CODEX_*` session-control environment variables,
start as ephemeral one-shot sessions, disable repo-unrelated MCP servers by
default, and explicitly enable network access inside the child workspace-write
sandbox so the worker or reviewer can reach the Codex API without inheriting
the parent session’s tool startup or sandbox state.

If a worker times out, do not assume the slice is a total loss. Check the
printed run directory, inspect `run-status.json`, run `git status`, and then
verify any partial work with `uv run pytest` and `uv run docgarden scan` before
you decide whether to retry or recover manually.

`docgarden slices recover` is baseline-aware. Its `tracked_changes` and
`untracked_paths` fields report only changes that appeared after the run
started, while `preexisting_*` and `current_*` fields show the full picture for
operators working in already-dirty repos.
Expected untracked slice-loop artifact paths are broken out separately as
`run_artifact_untracked_paths` so retry guidance stays focused on operator
changes rather than the run directory itself.

`run-status.json` now updates during long worker/reviewer runs. The most useful
live fields are:

- `current_phase`: whether the loop is in the worker or reviewer pass
- `current_round`: which revision round is active
- `phase_started_at`: when that worker/reviewer phase began
- `last_heartbeat_at`: the most recent liveness update written by the runner
- `elapsed_seconds`: how long the current phase has been running
- `agent_pid`: the local `codex exec` process id backing the current phase

The same status file also snapshots repo state when the run starts:

- `baseline_recorded_at`: when the runner captured the starting repo state
- `baseline_tracked_changes`: tracked-file diffs that already existed before the run
- `baseline_untracked_paths`: untracked paths that already existed before the run

The operator control commands build on those artifacts:

- `docgarden slices watch`
  Reads the latest run directory by default and prints its current status
  summary. Use `--max-updates 0` to keep polling until the run stops.
- `docgarden slices stop`
  Sends `SIGTERM` to the `agent_pid` recorded in `run-status.json` and marks the
  run as `stopped`.
- `docgarden slices recover`
  Summarizes the run, compares current repo state against the baseline captured
  at run start, and by default reruns `uv run pytest` plus
  `uv run docgarden scan` so operators can judge whether a timed-out or
  interrupted run left reviewable work behind.
- `docgarden slices retry`
  Starts a fresh retry run for the same slice using the prior run directory as
  context. If the earlier run already has worker/reviewer JSON artifacts, the
  retry flow reuses them to resume from the right worker or reviewer round
  instead of starting from scratch.
- `docgarden slices list`
  Shows the run directories under the configured artifacts root, newest first,
  with their slice ids, statuses, and basic timing fields.
- `docgarden slices prune`
  Cleans up old run directories. It is a dry run by default; add `--apply` to
  actually delete older non-running runs after the most recent `--keep` runs are
  preserved.

For other repos, the `slices` CLI also accepts path overrides such as
`--catalog-path`, `--spec-path`, `--plan-path`, `--artifacts-dir`,
`--worker-timeout-seconds`, and `--reviewer-timeout-seconds`.

There is also a repo-owned operator skill at
`.agents/skills/docgarden-slice-orchestrator/SKILL.md` for agents that need to
run the loop the way a human user would.

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
- automated slice kickoff and review prompt generation from the slice backlog
- a Codex worker/reviewer loop that can continue until a slice is accepted or
  blocked

The current published slice backlog is fully implemented through S14.
