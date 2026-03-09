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
docgarden slices run --max-slices 1
docgarden slices run --max-slices 1 --agent-timeout-seconds 300
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

Use `docgarden slices run --max-slices 0` to keep advancing until no queued
slices remain. The safer default is `--max-slices 1`, which automates one slice
at a time.

Each worker or reviewer `codex exec` call now has a 300-second timeout by
default. Use `--agent-timeout-seconds 0` to disable that guardrail. When a
Codex run times out or exits nonzero, `docgarden` still writes whatever
stdout/stderr it captured to the current `.docgarden/slice-loops/...` run
directory before failing, so operators have something concrete to inspect.
Nested runs also strip parent `CODEX_*` session-control environment variables,
start as ephemeral one-shot sessions, disable repo-unrelated MCP servers by
default, and explicitly enable network access inside the child workspace-write
sandbox so the worker or reviewer can reach the Codex API without inheriting
the parent session’s tool startup or sandbox state.

For other repos, the `slices` CLI also accepts path overrides such as
`--catalog-path`, `--spec-path`, `--plan-path`, `--artifacts-dir`, and
`--agent-timeout-seconds`.

There is also a repo-owned operator skill at
`.agents/skills/docgarden-slice-orchestrator/SKILL.md` for agents that need to
run the loop the way a human user would.

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
- append-only findings history and a prioritized plan view
- plan triage stages with persisted notes
- manual queue focus, resolve, and reopen commands
- read-only changed-scope scans for partial local or CI feedback
- automated slice kickoff and review prompt generation from the slice backlog
- a Codex worker/reviewer loop that can continue until a slice is accepted or
  blocked

Next planned slice: routing quality detection for stale or low-signal targets
from AGENTS/index routes.
