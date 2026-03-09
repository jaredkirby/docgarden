---
name: docgarden-slice-orchestrator
description: Operate the docgarden implementation-slice loop as a human user would. Use when asked to run the next slice, generate kickoff or review prompts, orchestrate Codex worker and reviewer passes, retry revisions until review is satisfied, or monitor `docgarden slices run` progress. Works for this repository and other repos that expose the same `docgarden slices` CLI, especially when they use custom backlog or spec paths.
---

# Docgarden Slice Orchestrator

Use this skill when the job is to operate `docgarden` itself, not to manually
do the implementation work of a slice.

## What you operate

`docgarden` already exposes the loop:

```bash
docgarden slices next
docgarden slices kickoff-prompt
docgarden slices review-prompt --worker-output <json>
docgarden slices run --max-slices 1
```

In this repo, the default source of truth is
`docs/design-docs/docgarden-implementation-slices.md`.

In other repos, the same loop can be pointed at custom paths with:

```bash
docgarden slices next --catalog-path <slice-backlog.md>
docgarden slices kickoff-prompt --catalog-path <slice-backlog.md> --spec-path <spec.md> --plan-path <exec-plan.md>
docgarden slices run --catalog-path <slice-backlog.md> --spec-path <spec.md> --plan-path <exec-plan.md> --artifacts-dir <artifacts-dir>
```

## Default workflow

1. Confirm repo state first.
   Run:
   ```bash
   git status --short --branch
   uv run docgarden slices next
   ```
   If the worktree has unrelated dirty files, call that out before starting an
   automated loop.

2. Prefer the built-in loop for normal operation.
   Run:
   ```bash
   uv run docgarden slices run --max-slices 1 --worker-timeout-seconds 900
   ```
   This should be the default path when the user wants the next slice advanced.
   In another repo, add `--catalog-path`, `--spec-path`, and `--plan-path` if
   the defaults do not match that project’s docs layout.
   Reviewer runs are usually shorter, so keep the default reviewer timeout
   unless you have evidence that review itself is the slow step.

3. Inspect the loop result.
   The command returns structured JSON and writes artifacts under
   `.docgarden/slice-loops/<timestamp-slice>/`.
   Read:
   - worker output JSON
   - review output JSON
   - `run-status.json` for the current phase, timeout settings, latest error,
     heartbeat, and elapsed time
   - stdout/stderr logs if something failed
   The CLI now prints the artifact directory to stderr as soon as each slice
   starts, so you can inspect the live run before the final JSON summary lands.

4. Decide what to do from the reviewer recommendation.
   - `ready_for_next_slice`: report success and, if asked, run the next slice.
   - `revise_before_next_slice`: let the built-in loop continue if it already
     has more review rounds available.
   - `blocked_pending_product_clarification`: stop and surface the blocker to
     the user clearly.

5. Verify the repo after meaningful work.
   Run:
   ```bash
   uv run pytest
   uv run docgarden scan
   ```

## Manual control mode

Use manual prompt generation only when:
- you need to inspect the exact prompt text
- you need to run worker and reviewer separately
- the built-in loop stopped and you need to diagnose the state

Commands:

```bash
uv run docgarden slices kickoff-prompt
uv run docgarden slices review-prompt --worker-output <path-to-worker-output.json>
```

For revision rounds, the CLI supports explicit context paths:

```bash
uv run docgarden slices kickoff-prompt \
  --review-feedback <review-round-n.output.json> \
  --previous-worker-output <worker-round-n.output.json>

uv run docgarden slices review-prompt \
  --worker-output <worker-round-n-plus-1.output.json> \
  --prior-review-output <review-round-n.output.json> \
  --round 2
```

## Smooth-operation guardrails

- Treat the configured slice backlog as authoritative.
  In this repo that is `docs/design-docs/docgarden-implementation-slices.md`.
  In other repos, prefer the explicit `--catalog-path` you were given.
  Do not infer the next slice from a manually maintained prompt pack if it
  disagrees with the backlog.
- The built-in loop launches isolated nested `codex exec` runs. It should not
  depend on your global MCP server list or an existing Codex session state to
  make worker/reviewer progress.
- Prefer `uv run docgarden ...` over invoking installed console scripts
  directly, so the repo-local package version is used.
- Keep the loop bounded unless the user explicitly wants continuous advancement.
  `--max-slices 1` is the safe default.
- If a loop run stops with a blocked recommendation, do not auto-push into the
  next slice.
- If `codex exec` fails, inspect `.docgarden/slice-loops/.../*.stderr.txt`
  before retrying.
- Long worker rounds may spend several minutes implementing code with little or
  no terminal output. That is not, by itself, a failure signal.
- If a worker times out, inspect the run directory, `git status`, `uv run
  pytest`, and `uv run docgarden scan` before assuming the slice failed
  completely; the child agent may have produced reviewable work before missing
  the structured-output deadline.
- If docs or prompts drift behind the implementation state, update the durable
  docs after the slice is accepted.

## Useful commands

```bash
uv run docgarden slices next
uv run docgarden slices kickoff-prompt
uv run docgarden slices review-prompt --worker-output .docgarden/slice-loops/.../worker-round-1.output.json
uv run docgarden slices run --max-slices 1 --worker-timeout-seconds 900
uv run docgarden slices run --catalog-path path/to/slices.md --spec-path path/to/spec.md --plan-path path/to/exec-plan.md
uv run pytest
uv run docgarden scan
```

## Timeout triage

When `docgarden slices run` times out:

1. Read the printed artifact directory path and inspect `run-status.json`.
   Focus on `current_phase`, `phase_started_at`, `last_heartbeat_at`, and
   `elapsed_seconds` before deciding whether the run is merely busy or truly
   wedged.
2. Check whether the worker wrote partial progress to the repo with `git status`.
3. Read `.stdout.txt` / `.stderr.txt` to distinguish a slow implementation from
   an actual launch failure.
4. If repo changes exist, run:
   ```bash
   uv run pytest
   uv run docgarden scan
   ```
5. Only after that decide whether to retry, review the partial work manually,
   or escalate a real blocker.

## When to pause and escalate

Pause and ask the user instead of pushing through when:
- the reviewer returns `blocked_pending_product_clarification`
- the worktree contains unexpected conflicting edits
- the next actionable slice in the backlog looks wrong for the user’s stated goal
- the loop exceeds the configured review-round limit

## References

Read these only when you need deeper context:
- `README.md`
- `docs/design-docs/docgarden-implementation-slices.md`
- `docs/exec-plans/active/2026-03-09-docgarden-slice-loop-automation.md`
- `docgarden/slices/`
