# docgarden 🪴

`docgarden` is a repo-local maintenance harness for agent-facing documentation.
It scans for stale or malformed docs, writes an honest quality score, persists
findings, supports queue-based triage and resolution, and offers a narrow
safe-fix path for mechanical hygiene issues.

## Commands

```bash
docgarden scan
docgarden scan --scope changed
docgarden scan --scope changed --files docs/index.md docs/workflows/reporting.md
docgarden status
docgarden next
docgarden plan
docgarden plan triage --stage observe --report "root causes and themes"
docgarden plan triage --stage reflect --report "comparison against recent work"
docgarden plan triage --stage organize --report "priority order and rationale"
docgarden plan focus FINDING_ID_OR_CLUSTER
docgarden plan resolve FINDING_ID --result fixed
docgarden plan reopen FINDING_ID
docgarden slices next
docgarden slices kickoff-prompt
docgarden slices review-prompt --worker-output .docgarden/slice-loops/.../worker-round-1.output.json
docgarden slices watch --max-updates 1
docgarden slices stop
docgarden slices recover
docgarden slices retry
docgarden slices run --max-slices 1
docgarden slices run --max-slices 1 --worker-timeout-seconds 900
docgarden slices run --max-slices 1 --reviewer-timeout-seconds 300
docgarden slices run --max-slices 1 --agent-timeout-seconds 600
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

Use `accepted_debt`, `needs_human`, or `false_positive` with
`docgarden plan resolve` when the outcome is not a straightforward fix. Those
non-trivial outcomes should include `--attest` text so the audit trail stays
honest.

Use changed-scope scans for fast local feedback while editing docs, then return
to a full `docgarden scan` before treating the score, queue, or persisted state
as authoritative.

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

`run-status.json` now updates during long worker/reviewer runs. The most useful
live fields are:

- `current_phase`: whether the loop is in the worker or reviewer pass
- `current_round`: which revision round is active
- `phase_started_at`: when that worker/reviewer phase began
- `last_heartbeat_at`: the most recent liveness update written by the runner
- `elapsed_seconds`: how long the current phase has been running
- `agent_pid`: the local `codex exec` process id backing the current phase

The operator control commands build on those artifacts:

- `docgarden slices watch`
  Reads the latest run directory by default and prints its current status
  summary. Use `--max-updates 0` to keep polling until the run stops.
- `docgarden slices stop`
  Sends `SIGTERM` to the `agent_pid` recorded in `run-status.json` and marks the
  run as `stopped`.
- `docgarden slices recover`
  Summarizes the run, reports current tracked/untracked repo changes, and by
  default reruns `uv run pytest` plus `uv run docgarden scan` so operators can
  judge whether a timed-out or interrupted run left reviewable work behind.
- `docgarden slices retry`
  Starts a fresh retry run for the same slice using the prior run directory as
  context. If the earlier run already has worker/reviewer JSON artifacts, the
  retry flow reuses them to resume from the right worker or reviewer round
  instead of starting from scratch.

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
- quality scoring and score publication
- persisted score trend points, configurable domain-weighted rollups, and
  critical-domain regression summaries
- append-only findings history and a prioritized plan view
- plan triage stages with persisted notes
- manual queue focus, resolve, and reopen commands
- read-only changed-scope scans for partial local or CI feedback
- automated slice kickoff and review prompt generation from the slice backlog
- a Codex worker/reviewer loop that can continue until a slice is accepted or
  blocked

Next planned slice: review packet preparation and import.
