from __future__ import annotations

import argparse
import sys

from .cli_commands import (
    command_config_show,
    command_doctor,
    command_fix_safe,
    command_next,
    command_plan,
    command_plan_focus,
    command_plan_reopen,
    command_plan_resolve,
    command_plan_triage,
    command_quality_write,
    command_scan,
    command_show,
    command_slices_kickoff_prompt,
    command_slices_next,
    command_slices_retry,
    command_slices_recover,
    command_slices_review_prompt,
    command_slices_run,
    command_slices_stop,
    command_slices_watch,
    command_status,
)
from .errors import DocgardenError
from .models import PLAN_RESOLVE_FINDING_STATUSES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docgarden")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser(
        "scan",
        description=(
            "Scan the full repo or a changed-doc subset. Changed scope uses "
            "local git state (unstaged, staged, untracked, and deleted doc "
            "paths under `AGENTS.md` and `docs/`) unless `--files` is passed."
        ),
    )
    scan.add_argument(
        "--scope",
        choices=["all", "changed"],
        default="all",
        help=(
            "Scan the whole repo or only the changed doc subset derived from "
            "local git state or `--files`."
        ),
    )
    scan.add_argument(
        "--files",
        nargs="+",
        help=(
            "Existing repo-relative doc files to treat as changed. Only valid "
            "with `--scope changed`."
        ),
    )
    scan.set_defaults(func=command_scan)

    status = subparsers.add_parser("status")
    status.set_defaults(func=command_status)

    next_cmd = subparsers.add_parser("next")
    next_cmd.set_defaults(func=command_next)

    plan = subparsers.add_parser("plan")
    plan.set_defaults(func=command_plan)
    plan_subparsers = plan.add_subparsers(dest="plan_command")
    plan_triage = plan_subparsers.add_parser(
        "triage",
        help="Record observe, reflect, or organize notes in plan.json.",
    )
    plan_triage.add_argument(
        "--stage",
        choices=["observe", "reflect", "organize"],
        required=True,
        help="Workflow stage to record in the persisted plan state.",
    )
    plan_triage.add_argument(
        "--report",
        required=True,
        help="Non-empty stage note to store for the selected triage stage.",
    )
    plan_triage.set_defaults(func=command_plan_triage)
    plan_focus = plan_subparsers.add_parser(
        "focus",
        help="Set current_focus to an actionable finding ID or cluster name.",
    )
    plan_focus.add_argument(
        "target",
        help="Actionable finding ID or cluster name from `docgarden plan`.",
    )
    plan_focus.set_defaults(func=command_plan_focus)
    plan_resolve = plan_subparsers.add_parser(
        "resolve",
        help=(
            "Write a new status event for an actionable queue item and update "
            "current_focus."
        ),
        description=(
            "Resolve an actionable queue item. `needs_human` stays actionable; "
            "`accepted_debt`, `needs_human`, and `false_positive` require "
            "`--attest`."
        ),
    )
    plan_resolve.add_argument(
        "finding_id",
        help="Actionable finding ID from the current queue.",
    )
    plan_resolve.add_argument(
        "--result",
        choices=PLAN_RESOLVE_FINDING_STATUSES,
        required=True,
        help="Queue result to record; `needs_human` stays actionable.",
    )
    plan_resolve.add_argument(
        "--attest",
        help=(
            "Required for `accepted_debt`, `needs_human`, and `false_positive`."
        ),
    )
    plan_resolve.set_defaults(func=command_plan_resolve)
    plan_reopen = plan_subparsers.add_parser(
        "reopen",
        help="Reopen a previously resolved finding by appending a new open event.",
    )
    plan_reopen.add_argument(
        "finding_id",
        help="Previously resolved finding ID to return to the queue.",
    )
    plan_reopen.set_defaults(func=command_plan_reopen)

    show = subparsers.add_parser("show")
    show.add_argument("finding_id")
    show.set_defaults(func=command_show)

    quality = subparsers.add_parser("quality")
    quality_subparsers = quality.add_subparsers(dest="quality_command", required=True)
    quality_write = quality_subparsers.add_parser("write")
    quality_write.set_defaults(func=command_quality_write)

    fix = subparsers.add_parser("fix")
    fix_subparsers = fix.add_subparsers(dest="fix_command", required=True)
    fix_safe = fix_subparsers.add_parser("safe")
    fix_safe.add_argument("--apply", action="store_true")
    fix_safe.set_defaults(func=command_fix_safe)

    config = subparsers.add_parser("config")
    config_subparsers = config.add_subparsers(dest="config_command", required=True)
    config_show = config_subparsers.add_parser("show")
    config_show.set_defaults(func=command_config_show)

    doctor = subparsers.add_parser("doctor")
    doctor.set_defaults(func=command_doctor)

    slices = subparsers.add_parser(
        "slices",
        help="Inspect or automate the implementation-slice worker/reviewer loop.",
    )
    slices_subparsers = slices.add_subparsers(dest="slices_command", required=True)
    slices_next = slices_subparsers.add_parser(
        "next",
        help="Show the next queued or active implementation slice.",
    )
    _add_slice_path_arguments(slices_next)
    slices_next.set_defaults(func=command_slices_next)
    slices_kickoff = slices_subparsers.add_parser(
        "kickoff-prompt",
        help="Render the implementation prompt for a slice.",
    )
    _add_slice_path_arguments(slices_kickoff)
    slices_kickoff.add_argument(
        "--slice",
        dest="slice_id",
        help="Explicit slice ID. Defaults to the next queued or active slice.",
    )
    slices_kickoff.add_argument(
        "--round",
        type=int,
        default=1,
        help="Implementation round number. Revision rounds can include review context.",
    )
    slices_kickoff.add_argument(
        "--review-feedback",
        help="Path to reviewer feedback JSON when generating a revision prompt.",
    )
    slices_kickoff.add_argument(
        "--previous-worker-output",
        help="Path to the previous worker output JSON when generating a revision prompt.",
    )
    slices_kickoff.set_defaults(func=command_slices_kickoff_prompt)
    slices_review = slices_subparsers.add_parser(
        "review-prompt",
        help="Render the PM review prompt for a slice.",
    )
    _add_slice_path_arguments(slices_review)
    slices_review.add_argument(
        "--slice",
        dest="slice_id",
        help="Explicit slice ID. Defaults to the next queued or active slice.",
    )
    slices_review.add_argument(
        "--worker-output",
        required=True,
        help="Path to the latest worker output JSON.",
    )
    slices_review.add_argument(
        "--round",
        type=int,
        default=1,
        help="Review round number.",
    )
    slices_review.add_argument(
        "--prior-review-output",
        help="Path to the prior reviewer output JSON for re-review context.",
    )
    slices_review.set_defaults(func=command_slices_review_prompt)
    slices_watch = slices_subparsers.add_parser(
        "watch",
        help="Inspect the latest slice run status, optionally polling until it changes.",
    )
    _add_slice_path_arguments(slices_watch)
    slices_watch.add_argument(
        "--run-dir",
        help="Explicit slice run directory. Defaults to the latest run under the artifacts dir.",
    )
    slices_watch.add_argument(
        "--interval-seconds",
        type=float,
        default=2.0,
        help="Polling interval when watching an active run.",
    )
    slices_watch.add_argument(
        "--max-updates",
        type=int,
        default=1,
        help="Maximum status snapshots to print before exiting. Use 0 to keep polling until the run stops.",
    )
    slices_watch.set_defaults(func=command_slices_watch)
    slices_stop = slices_subparsers.add_parser(
        "stop",
        help="Stop an active slice run using the pid recorded in run-status.json.",
    )
    _add_slice_path_arguments(slices_stop)
    slices_stop.add_argument(
        "--run-dir",
        help="Explicit slice run directory. Defaults to the latest run under the artifacts dir.",
    )
    slices_stop.set_defaults(func=command_slices_stop)
    slices_recover = slices_subparsers.add_parser(
        "recover",
        help="Inspect a stopped or failed slice run and optionally rerun verification.",
    )
    _add_slice_path_arguments(slices_recover)
    slices_recover.add_argument(
        "--run-dir",
        help="Explicit slice run directory. Defaults to the latest run under the artifacts dir.",
    )
    slices_recover.add_argument(
        "--skip-verification",
        action="store_true",
        help="Skip `uv run pytest` and `uv run docgarden scan` during recovery.",
    )
    slices_recover.set_defaults(func=command_slices_recover)
    slices_retry = slices_subparsers.add_parser(
        "retry",
        help="Retry a failed or stopped slice run from its existing artifact context.",
    )
    _add_slice_path_arguments(slices_retry)
    slices_retry.add_argument(
        "--run-dir",
        help="Explicit slice run directory. Defaults to the latest run under the artifacts dir.",
    )
    slices_retry.add_argument(
        "--max-review-rounds",
        type=int,
        default=3,
        help="Maximum worker/reviewer revision rounds allowed for the retry run.",
    )
    slices_retry.add_argument(
        "--agent-timeout-seconds",
        type=int,
        default=None,
        help=(
            "Legacy override applied to both worker and reviewer Codex runs. "
            "Use 0 to disable both timeouts."
        ),
    )
    slices_retry.add_argument(
        "--worker-timeout-seconds",
        type=int,
        default=None,
        help=(
            "Maximum runtime for each worker Codex run. "
            "Defaults to 900 seconds. Use 0 to disable the timeout."
        ),
    )
    slices_retry.add_argument(
        "--reviewer-timeout-seconds",
        type=int,
        default=None,
        help=(
            "Maximum runtime for each reviewer Codex run. "
            "Defaults to 300 seconds. Use 0 to disable the timeout."
        ),
    )
    slices_retry.add_argument(
        "--codex-bin",
        default="codex",
        help="Codex CLI binary to invoke for worker and reviewer runs.",
    )
    slices_retry.add_argument(
        "--model",
        help="Optional Codex model override for worker and reviewer runs.",
    )
    slices_retry.add_argument(
        "--codex-arg",
        action="append",
        help="Additional argument to pass through to `codex exec`. Repeat as needed.",
    )
    slices_retry.set_defaults(func=command_slices_retry)
    slices_run = slices_subparsers.add_parser(
        "run",
        help="Automate the worker/reviewer loop for one or more implementation slices.",
    )
    _add_slice_path_arguments(slices_run)
    slices_run.add_argument(
        "--from-slice",
        help="Start from a specific slice ID instead of the next queued slice.",
    )
    slices_run.add_argument(
        "--max-slices",
        type=int,
        default=1,
        help="Maximum number of slices to process. Use 0 to continue until no actionable slices remain.",
    )
    slices_run.add_argument(
        "--max-review-rounds",
        type=int,
        default=3,
        help="Maximum worker/reviewer revision rounds per slice.",
    )
    slices_run.add_argument(
        "--agent-timeout-seconds",
        type=int,
        default=None,
        help=(
            "Legacy override applied to both worker and reviewer Codex runs. "
            "Use 0 to disable both timeouts."
        ),
    )
    slices_run.add_argument(
        "--worker-timeout-seconds",
        type=int,
        default=None,
        help=(
            "Maximum runtime for each worker Codex run. "
            "Defaults to 900 seconds. Use 0 to disable the timeout."
        ),
    )
    slices_run.add_argument(
        "--reviewer-timeout-seconds",
        type=int,
        default=None,
        help=(
            "Maximum runtime for each reviewer Codex run. "
            "Defaults to 300 seconds. Use 0 to disable the timeout."
        ),
    )
    slices_run.add_argument(
        "--codex-bin",
        default="codex",
        help="Codex CLI binary to invoke for worker and reviewer runs.",
    )
    slices_run.add_argument(
        "--model",
        help="Optional Codex model override for worker and reviewer runs.",
    )
    slices_run.add_argument(
        "--codex-arg",
        action="append",
        help="Additional argument to pass through to `codex exec`. Repeat as needed.",
    )
    slices_run.set_defaults(func=command_slices_run)

    return parser


def _add_slice_path_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--catalog-path",
        help=(
            "Repo-relative or absolute path to the implementation-slice backlog. "
            "Defaults to docs/design-docs/docgarden-implementation-slices.md."
        ),
    )
    parser.add_argument(
        "--spec-path",
        help=(
            "Repo-relative or absolute path to the product spec referenced in prompts. "
            "Defaults to docs/design-docs/docgarden-spec.md."
        ),
    )
    parser.add_argument(
        "--plan-path",
        help=(
            "Repo-relative or absolute path to the active exec plan referenced in prompts. "
            "Defaults to docs/exec-plans/active/2026-03-09-docgarden-spec-slicing.md."
        ),
    )
    parser.add_argument(
        "--artifacts-dir",
        help=(
            "Repo-relative or absolute directory for slice-loop artifacts. "
            "Defaults to .docgarden/slice-loops."
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except DocgardenError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
