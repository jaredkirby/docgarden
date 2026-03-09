---
doc_id: docgarden-slice-loop-automation-exec-plan
doc_type: exec-plan
domain: exec-plans
owner: kirby
status: draft
last_reviewed: 2026-03-09
review_cycle_days: 14
applies_to:
  - repo
source_of_truth:
  - docs/design-docs/docgarden-implementation-slices.md
  - docs/design-docs/docgarden-spec.md
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - exec-plan
  - automation
  - slices
---

# Docgarden Slice Loop Automation Exec Plan

## Purpose

Automate the manual implementation-slice loop so `docgarden` can generate the
next slice prompt, run a Codex worker, run a Codex reviewer, feed revision
findings back into the worker, and advance to the next slice only when review
recommends doing so.

## Context

The repo already has a durable implementation backlog and a manually maintained
prompt pack. The current human loop works, but it is repetitive and vulnerable
to prompt drift. The next step is to make the loop itself a first-class command
inside `docgarden`.

## Assumptions

- The implementation-slice backlog stays the durable source of truth for slice
  order, status, dependencies, and acceptance criteria.
- `codex exec` is available locally when operators choose to run the automated
  loop.
- Structured JSON outputs are a better automation boundary than trying to parse
  free-form prose from worker and reviewer agents.

## Steps / Milestones

1. Parse slice metadata directly from the implementation backlog doc.
2. Generate implementation and review prompts from that metadata.
3. Add a CLI command that can run Codex worker and reviewer passes in a loop.
4. Persist prompts, schemas, outputs, and logs under `.docgarden/`.
5. Update the README and docs routing so the new automation is discoverable.
6. Verify the command surface and loop behavior with tests.

## Validation

- `uv run pytest`
- `uv run docgarden scan`

## Progress

- 2026-03-09: Added a slice-automation module that parses the implementation backlog and derives implementation/review prompts from it.
- 2026-03-09: Added `docgarden slices next`, `kickoff-prompt`, `review-prompt`, and `run` command surfaces.
- 2026-03-09: Wired `docgarden slices run` to call `codex exec` with structured worker and reviewer output schemas and to persist run artifacts under `.docgarden/slice-loops/`.
- 2026-03-09: Added tests covering backlog parsing, prompt rendering, and a multi-round worker/reviewer loop that revises once and then advances to the next slice.
- 2026-03-09: Updated the README and plan routing so the new loop is discoverable from the normal repo entry points.
- 2026-03-09: Repackaged the automation into a reusable `docgarden.slices` module and kept `docgarden.slice_automation` as a compatibility re-export.
- 2026-03-09: Added configurable path resolution for the slice backlog, spec, exec plan, and artifact directory so other project repos can use the loop without copying this repo’s exact docs layout.
- 2026-03-09: Added a default per-agent timeout for `docgarden slices run`, persisted partial stdout/stderr on timeout or nonzero exit, and covered those failure paths with regression tests after the first live run reproduced a stuck `codex exec` child process.
- 2026-03-09: Sanitized parent `CODEX_*` session-control environment variables before spawning nested `codex exec` worker/reviewer runs, which let the first live temp-repo verification progress into real file reads and tool use instead of stalling before structured output.
- 2026-03-09: Reproduced the next live failure mode from the operator skill: nested `codex exec` runs inherited global MCP startup and a network-disabled child sandbox, which combined into macOS `system-configuration` proxy panics and API DNS failures before the worker could return structured JSON.
- 2026-03-09: Updated nested worker/reviewer launches to run as ephemeral sessions, disable the repo-unrelated default MCP servers, and enable child workspace-write network access so `docgarden slices run` can reach the Codex API without tripping the local MCP/proxy startup path.
- 2026-03-09: Tightened worker/reviewer prompts to say explicitly that slice implementation and review should happen directly rather than recursively using the `docgarden-slice-orchestrator` operator skill.
- 2026-03-09: Split the old shared agent timeout into role-specific defaults: 900 seconds for workers and 300 seconds for reviewers, while keeping a compatibility `--agent-timeout-seconds` override for older operator habits.
- 2026-03-09: Switched nested `codex exec` launches from buffered `subprocess.run(...)` capture to streamed `Popen(...)` log files so operators can inspect live stdout/stderr in `.docgarden/slice-loops/...` while a worker is still running.
- 2026-03-09: Added `run-status.json` artifacts and immediate stderr announcements of the slice run directory so timeout triage has a canonical place to look for the current phase, timeout settings, and latest error.
- 2026-03-09: Added timeout-focused regression coverage for role-specific budgets, mixed timeout flag validation, and the real-world case where a timed-out worker leaves useful repo changes behind for manual salvage.
- 2026-03-09: Added heartbeat-driven `run-status.json` updates so long worker/reviewer passes now refresh `phase_started_at`, `last_heartbeat_at`, `elapsed_seconds`, and `agent_pid` while the nested `codex exec` process is still running.
- 2026-03-09: Added operator-facing `docgarden slices watch`, `stop`, and `recover` commands so humans can inspect the latest run, stop an active pid-backed run cleanly, and rerun verification for timed-out or interrupted work without rebuilding the recovery flow manually.

## Discoveries

- The slice backlog is a stronger automation source than the manual prompt pack because it already contains the goal, planned changes, dependencies, and acceptance criteria in a stable structure.
- Structured reviewer output is the critical control point for the loop; once the recommendation is machine-readable, retry vs advance decisions become deterministic.
- The loop still benefits from durable human-readable artifacts, so prompt text, JSON schemas, structured outputs, and stdout/stderr logs should all be kept under `.docgarden/slice-loops/`.
- Advancing to the next slice should not depend on docs being updated in the middle of the same run; the command can progress through the ordered slice catalog it parsed at startup.
- Reuse depends more on configurable document paths than on the prompt text itself; the hardcoded repo-doc locations were the main thing preventing clean adoption in other repos.
- The first live exercise surfaced a gap that mocked tests missed: if `codex exec` panics or stalls after launch, a plain `subprocess.run(...)` without a timeout can hang the whole orchestration loop indefinitely.
- Operators still need logs when an agent launch goes bad, so stdout/stderr persistence cannot wait until a successful subprocess return; timeout and error paths need to flush partial streams too.
- Running `docgarden slices run` from inside an existing Codex session adds another failure mode: the spawned child inherits parent `CODEX_*` sandbox/thread environment variables unless the runner strips them explicitly.
- The next live smoke test showed a second integration seam that mocks missed: even a healthy nested `codex exec` can fail before the model call if it boots the operator’s configured MCP servers, because those startup HTTP clients may still hit macOS proxy discovery.
- Nested worker/reviewer runs also need explicit child-sandbox network access; otherwise they can start cleanly and still fail every API websocket connection with DNS lookup errors while the outer session appears healthy.
- Prompt wording matters for repos that publish operator skills: if the worker prompt sounds like “run the slice loop” instead of “implement the code,” the child agent can recursively choose the orchestration skill and spend time on the wrong job.
- A single timeout budget does not fit both roles well: implementation workers can need 10-15 minutes for a clean slice, while reviewers are usually quick and benefit from a much shorter failure bound.
- Buffered subprocess capture is the wrong UX for long-running agent work because it hides the difference between “healthy but busy” and “stuck before first token”; writing logs live to disk makes the artifact directory genuinely useful during a run.
- Timeout recovery is an operator workflow, not just an error string. The tool and docs need to make it obvious that a timed-out worker may still have produced reviewable repo changes.
- Operators also need positive liveness signals during healthy long runs, not just better failure logs after the fact; heartbeat and elapsed-time fields make the distinction between “slow” and “wedged” much easier.
- Once a run is inspectable, operators also need first-class controls to act on it. Status visibility without `stop` and `recover` still leaves too much ad-hoc shell work when a run needs intervention.

## Decision Log

- 2026-03-09: Generate prompts from `docs/design-docs/docgarden-implementation-slices.md` instead of scraping the manual prompt pack.
- 2026-03-09: Use `codex exec` with `--output-schema` and `--output-last-message` so the loop consumes structured JSON instead of brittle prose parsing.
- 2026-03-09: Keep the default run bounded to one slice at a time with `--max-slices 1`, while allowing `--max-slices 0` for continuous advancement.
- 2026-03-09: Persist run artifacts inside `.docgarden/` because the automation loop is an operational stateful workflow, not just a transient convenience wrapper.
- 2026-03-09: Keep the reusable Python API under `docgarden.slices` and reserve the top-level `docgarden.slice_automation` import as a backwards-compatible shim.
- 2026-03-09: Add a default 300-second timeout per worker/reviewer `codex exec` invocation and allow `--agent-timeout-seconds 0` to disable it, so the loop fails fast instead of silently hanging behind a bad child process.
- 2026-03-09: Persist partial stdout/stderr before raising timeout or nonzero-exit errors, so the artifact directory remains inspectable even when the agent process never produces structured JSON.
- 2026-03-09: Strip inherited `CODEX_CI`, `CODEX_SANDBOX`, `CODEX_SANDBOX_NETWORK_DISABLED`, and `CODEX_THREAD_ID` from nested worker/reviewer launches, because those describe the parent Codex session rather than the child run we want `docgarden` to start.
- 2026-03-09: Launch nested worker/reviewer agents with `--ephemeral`, disable the configured `pencil` and `openaiDeveloperDocs` MCP servers by default, and override `sandbox_workspace_write.network_access=true` so the child Codex process starts with only the capabilities this slice loop actually needs.
- 2026-03-09: Keep the legacy `--agent-timeout-seconds` flag for compatibility, but prefer explicit `--worker-timeout-seconds` and `--reviewer-timeout-seconds` so operators can give implementation work more room without weakening review feedback loops.
- 2026-03-09: Treat timeout observability as a first-class artifact concern by printing the run directory immediately, streaming logs to disk, and persisting `run-status.json` alongside prompts and structured outputs.
- 2026-03-09: Keep `run-status.json` merge-based and heartbeat refreshed so later status transitions like `failed` or `ready_for_next_slice` do not discard the elapsed-time context operators used during the live run.
- 2026-03-09: Treat run directories as the control plane for manual intervention too: the latest-run resolver, `watch`, `stop`, and `recover` all operate from the artifact directory instead of depending on parent-session state.

## Outcomes / Retrospective

The loop now survives the first real-world integration traps better: bad agent
launches fail fast, preserve the captured logs operators need, and no longer
inherit the parent Codex session’s sandbox/thread controls when spawning nested
worker or reviewer runs.
