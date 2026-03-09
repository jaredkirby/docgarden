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
- 2026-03-09: Repackaged the automation into concrete `docgarden.slices.*`
  modules and removed the redundant top-level `docgarden.slice_automation`
  shim so callers import the real implementation boundaries directly.
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
- 2026-03-09: Added `docgarden slices retry` so a failed or stopped run can spawn a fresh retry for the same slice while reusing prior worker/reviewer artifact paths to resume from the correct round when context already exists.
- 2026-03-09: Added `docgarden slices list` and dry-run-first `docgarden slices prune` so operators can manage accumulated slice-loop artifact directories without ad-hoc shell cleanup.
- 2026-03-09: Added baseline repo-state snapshots to `run-status.json` and taught `docgarden slices recover` to report post-baseline deltas separately from pre-existing dirty worktree state.
- 2026-03-09: Taught `docgarden slices recover` to separate expected untracked artifact-root paths into `run_artifact_untracked_paths` instead of mixing them into operator-facing `new_untracked_paths`.
- 2026-03-09: Made slice scheduling dependency-aware so `next` and `run`
  skip blocked queued slices, explicit `--from-slice` starts fail fast when
  prerequisites are incomplete, and prompt context still references the next
  planned slice to avoid spillover.
- 2026-03-09: Replaced the slice-loop run-status dict bag with an explicit
  `SliceRunStatusRecord` model plus transition helpers, so runner retries,
  summaries, watch/stop flows, and persisted `run-status.json` all share one
  typed contract.
- 2026-03-09: Added a `stopped_no_progress` review-loop guardrail that halts a
  slice when consecutive review rounds repeat the same findings without
  material change, and bounded recovery verification subprocesses with timeout
  metadata instead of letting `recover` hang behind a stuck verification step.
- 2026-03-09: Split nested `codex exec` process control and heartbeat/log
  management into `docgarden/slices/run_agent.py`, which pulled the biggest
  subprocess chunk out of `runner.py` while keeping the runner focused on
  slice-loop orchestration.
- 2026-03-09: Moved run-request/config dataclasses into `config.py` and
  review-signature artifact helpers into `review_progress.py`, which shrank
  `runner.py` further without changing the slice-loop behavior or CLI
  contract.
- 2026-03-09: Split the per-slice execution engine out into
  `docgarden/slices/run_execution.py`, leaving `runner.py` as the catalog and
  retry entrypoint while the worker/reviewer phase loop, no-progress stop
  handling, and terminal result assembly live behind a dedicated execution
  module.
- 2026-03-09: Split the slice CLI surface into explicit modules:
  `docgarden/cli_slices.py` now owns parser registration,
  `docgarden/cli_slices_commands.py` owns catalog/prompt commands, and
  `docgarden/cli_slices_runtime.py` owns run/retry/recover/watch/prune
  execution. That leaves `cli.py` as the top-level shell and shrinks
  `cli_commands.py` back toward non-slice command families.
- 2026-03-09: Continued the CLI responsibility split by moving review and plan
  parser wiring plus handlers into `docgarden/cli_plan_review.py`, which cut
  `cli.py` and `cli_commands.py` down to the core shell/non-slice command
  surface instead of keeping every command family in the same two files.

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
- Retry ergonomics matter too: after a failed or interrupted run, operators should not have to manually reconstruct revision context from scattered artifact files just to restart the next worker pass.
- Artifact retention matters once the loop becomes useful; without list/prune helpers, the safer control-plane design just pushes operators back into manual filesystem cleanup.
- Recovery recommendations get much more trustworthy when the runner remembers what the repo looked like at launch; otherwise `recover` cannot distinguish “the slice changed this” from “the operator was already mid-edit.”
- Even after baseline diffing, the run’s own artifact directory is expected untracked output, so recovery JSON should label it explicitly instead of presenting it as suspicious repo drift.
- Slice dependencies need two different interpretations: scheduling should look
  for the next dependency-ready slice, while prompts still need the next
  planned slice so workers can avoid spilling into the upcoming backlog item.
- The next orchestration seam after dependency-aware scheduling was the
  persisted run-status contract itself; once the status model became explicit,
  retry/list/watch/stop code stopped having to remember the same keys
  independently.
- Max review rounds alone are not enough operator guardrails. A slice can make
  it through several worker/reviewer passes without any real movement if the
  reviewer keeps emitting the same actionable findings.

## Decision Log

- 2026-03-09: Generate prompts from `docs/design-docs/docgarden-implementation-slices.md` instead of scraping the manual prompt pack.
- 2026-03-09: Use `codex exec` with `--output-schema` and `--output-last-message` so the loop consumes structured JSON instead of brittle prose parsing.
- 2026-03-09: Keep the default run bounded to one slice at a time with `--max-slices 1`, while allowing `--max-slices 0` for continuous advancement.
- 2026-03-09: Persist run artifacts inside `.docgarden/` because the automation loop is an operational stateful workflow, not just a transient convenience wrapper.
- 2026-03-09: Prefer concrete `docgarden.slices.catalog`,
  `docgarden.slices.config`, `docgarden.slices.prompts`, and
  `docgarden.slices.runner` imports over aggregate facade routes so the public
  surface mirrors the actual implementation boundaries.
- 2026-03-09: Add a default 300-second timeout per worker/reviewer `codex exec` invocation and allow `--agent-timeout-seconds 0` to disable it, so the loop fails fast instead of silently hanging behind a bad child process.
- 2026-03-09: Persist partial stdout/stderr before raising timeout or nonzero-exit errors, so the artifact directory remains inspectable even when the agent process never produces structured JSON.
- 2026-03-09: Strip inherited `CODEX_CI`, `CODEX_SANDBOX`, `CODEX_SANDBOX_NETWORK_DISABLED`, and `CODEX_THREAD_ID` from nested worker/reviewer launches, because those describe the parent Codex session rather than the child run we want `docgarden` to start.
- 2026-03-09: Launch nested worker/reviewer agents with `--ephemeral`, disable the configured `pencil` and `openaiDeveloperDocs` MCP servers by default, and override `sandbox_workspace_write.network_access=true` so the child Codex process starts with only the capabilities this slice loop actually needs.
- 2026-03-09: Keep the legacy `--agent-timeout-seconds` flag for compatibility, but prefer explicit `--worker-timeout-seconds` and `--reviewer-timeout-seconds` so operators can give implementation work more room without weakening review feedback loops.
- 2026-03-09: Treat timeout observability as a first-class artifact concern by printing the run directory immediately, streaming logs to disk, and persisting `run-status.json` alongside prompts and structured outputs.
- 2026-03-09: Keep `run-status.json` merge-based and heartbeat refreshed so later status transitions like `failed` or `ready_for_next_slice` do not discard the elapsed-time context operators used during the live run.
- 2026-03-09: Treat run directories as the control plane for manual intervention too: the latest-run resolver, `watch`, `stop`, and `recover` all operate from the artifact directory instead of depending on parent-session state.
- 2026-03-09: Use prior run artifacts as resume context, not as mutable state. `retry` creates a new run directory while threading the earlier worker/reviewer JSON paths into the next worker or reviewer step as appropriate.
- 2026-03-09: Make artifact cleanup dry-run first. `prune` only deletes when `--apply` is passed and otherwise reports which finished runs would be removed after preserving the newest `--keep` entries.
- 2026-03-09: Treat recovery as a diff against a recorded baseline, not just a snapshot of the current worktree, so dirty repos can still get actionable retry-vs-review guidance.
- 2026-03-09: Keep expected slice-loop artifact dirt visible but quarantined in a dedicated recovery field so operators still see it without having to mentally subtract it from actionable repo changes.
- 2026-03-09: Distinguish “next dependency-ready slice” from “next planned
  slice” so scheduling honors prerequisites while worker/reviewer prompts still
  mention the immediate upcoming backlog item for spillover guardrails.
- 2026-03-09: Treat repeated identical `revise_before_next_slice` reviews as a
  control-plane stop condition (`stopped_no_progress`) instead of blindly
  spending the remaining review budget on a churn loop.
- 2026-03-09: Keep recovery verification bounded with a timeout and surfaced
  timeout metadata so `docgarden slices recover` stays inspectable even when
  the follow-up validation commands wedge.

## Outcomes / Retrospective

The loop now survives the first real-world integration traps better: bad agent
launches fail fast, preserve the captured logs operators need, and no longer
inherit the parent Codex session’s sandbox/thread controls when spawning nested
worker or reviewer runs. The runner also has a cleaner status boundary now, so
operator-facing controls (`watch`, `stop`, `recover`, `retry`) share one
explicit persisted contract instead of reconstructing state from ad hoc dict
keys, and repeated no-progress review churn stops early with a named terminal
status instead of quietly burning through the remaining rounds.
