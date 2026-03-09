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

## Current implementation status

The repo currently includes:

- frontmatter validation
- required section checks
- stale review detection
- duplicate `doc_id` detection
- broken route and internal markdown link checks
- source-of-truth artifact alignment checks
- unsupported `docgarden` validation command checks on non-draft docs
- quality scoring and score publication
- append-only findings history and a prioritized plan view
- plan triage stages with persisted notes
- manual queue focus, resolve, and reopen commands
- read-only changed-scope scans for partial local or CI feedback

Next planned slice: workflow drift detection for repo-owned scripts, commands,
and local path references documented in operator-facing docs.
