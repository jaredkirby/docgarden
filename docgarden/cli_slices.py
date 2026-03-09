from __future__ import annotations

import argparse

from .cli_slices_commands import (
    command_slices_kickoff_prompt,
    command_slices_list,
    command_slices_next,
    command_slices_review_prompt,
)
from .cli_slices_runtime import (
    command_slices_prune,
    command_slices_recover,
    command_slices_retry,
    command_slices_run,
    command_slices_stop,
    command_slices_watch,
)


def register_slices_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    slices = subparsers.add_parser(
        "slices",
        help="Inspect or automate the implementation-slice worker/reviewer loop.",
    )
    slices_subparsers = slices.add_subparsers(dest="slices_command", required=True)

    next_parser = slices_subparsers.add_parser(
        "next",
        help="Show the next queued or active implementation slice.",
    )
    _add_slice_path_arguments(next_parser)
    next_parser.set_defaults(func=command_slices_next)

    list_parser = slices_subparsers.add_parser(
        "list",
        help="List slice run artifact directories and their current statuses.",
    )
    _add_slice_path_arguments(list_parser)
    list_parser.set_defaults(func=command_slices_list)

    kickoff_parser = slices_subparsers.add_parser(
        "kickoff-prompt",
        help="Render the implementation prompt for a slice.",
    )
    _add_slice_path_arguments(kickoff_parser)
    kickoff_parser.add_argument(
        "--slice",
        dest="slice_id",
        help="Explicit slice ID. Defaults to the next queued or active slice.",
    )
    kickoff_parser.add_argument(
        "--round",
        type=int,
        default=1,
        help="Implementation round number. Revision rounds can include review context.",
    )
    kickoff_parser.add_argument(
        "--review-feedback",
        help="Path to reviewer feedback JSON when generating a revision prompt.",
    )
    kickoff_parser.add_argument(
        "--previous-worker-output",
        help="Path to the previous worker output JSON when generating a revision prompt.",
    )
    kickoff_parser.set_defaults(func=command_slices_kickoff_prompt)

    review_parser = slices_subparsers.add_parser(
        "review-prompt",
        help="Render the PM review prompt for a slice.",
    )
    _add_slice_path_arguments(review_parser)
    review_parser.add_argument(
        "--slice",
        dest="slice_id",
        help="Explicit slice ID. Defaults to the next queued or active slice.",
    )
    review_parser.add_argument(
        "--worker-output",
        required=True,
        help="Path to the latest worker output JSON.",
    )
    review_parser.add_argument(
        "--round",
        type=int,
        default=1,
        help="Review round number.",
    )
    review_parser.add_argument(
        "--prior-review-output",
        help="Path to the prior reviewer output JSON for re-review context.",
    )
    review_parser.set_defaults(func=command_slices_review_prompt)

    watch_parser = slices_subparsers.add_parser(
        "watch",
        help="Inspect the latest slice run status, optionally polling until it changes.",
    )
    _add_slice_path_arguments(watch_parser)
    _add_run_dir_argument(watch_parser)
    watch_parser.add_argument(
        "--interval-seconds",
        type=float,
        default=2.0,
        help="Polling interval when watching an active run.",
    )
    watch_parser.add_argument(
        "--max-updates",
        type=int,
        default=1,
        help="Maximum status snapshots to print before exiting. Use 0 to keep polling until the run stops.",
    )
    watch_parser.set_defaults(func=command_slices_watch)

    stop_parser = slices_subparsers.add_parser(
        "stop",
        help="Stop an active slice run using the pid recorded in run-status.json.",
    )
    _add_slice_path_arguments(stop_parser)
    _add_run_dir_argument(stop_parser)
    stop_parser.set_defaults(func=command_slices_stop)

    recover_parser = slices_subparsers.add_parser(
        "recover",
        help="Inspect a stopped or failed slice run and optionally rerun verification.",
    )
    _add_slice_path_arguments(recover_parser)
    _add_run_dir_argument(recover_parser)
    recover_parser.add_argument(
        "--skip-verification",
        action="store_true",
        help="Skip `uv run pytest` and `uv run docgarden scan` during recovery.",
    )
    recover_parser.set_defaults(func=command_slices_recover)

    retry_parser = slices_subparsers.add_parser(
        "retry",
        help="Retry a failed or stopped slice run from its existing artifact context.",
    )
    _add_slice_path_arguments(retry_parser)
    _add_run_dir_argument(retry_parser)
    _add_slice_runner_arguments(
        retry_parser,
        max_review_rounds_help="Maximum worker/reviewer revision rounds allowed for the retry run.",
    )
    retry_parser.set_defaults(func=command_slices_retry)

    prune_parser = slices_subparsers.add_parser(
        "prune",
        help="Dry-run or delete old non-running slice run artifact directories.",
    )
    _add_slice_path_arguments(prune_parser)
    prune_parser.add_argument(
        "--keep",
        type=int,
        default=3,
        help="Keep this many most-recent prunable runs. Defaults to 3.",
    )
    prune_parser.add_argument(
        "--status",
        action="append",
        dest="statuses",
        help="Prunable run status to target. Repeat as needed. Defaults to common finished statuses.",
    )
    prune_parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete prune candidates. Without this flag, prune is a dry run.",
    )
    prune_parser.set_defaults(func=command_slices_prune)

    run_parser = slices_subparsers.add_parser(
        "run",
        help="Automate the worker/reviewer loop for one or more implementation slices.",
    )
    _add_slice_path_arguments(run_parser)
    run_parser.add_argument(
        "--from-slice",
        help="Start from a specific slice ID instead of the next queued slice.",
    )
    run_parser.add_argument(
        "--max-slices",
        type=int,
        default=1,
        help="Maximum number of slices to process. Use 0 to continue until no actionable slices remain.",
    )
    _add_slice_runner_arguments(
        run_parser,
        max_review_rounds_help="Maximum worker/reviewer revision rounds per slice.",
    )
    run_parser.set_defaults(func=command_slices_run)


def _add_run_dir_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--run-dir",
        help="Explicit slice run directory. Defaults to the latest run under the artifacts dir.",
    )


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


def _add_slice_runner_arguments(
    parser: argparse.ArgumentParser,
    *,
    max_review_rounds_help: str,
) -> None:
    parser.add_argument(
        "--max-review-rounds",
        type=int,
        default=3,
        help=max_review_rounds_help,
    )
    parser.add_argument(
        "--agent-timeout-seconds",
        type=int,
        default=None,
        help=(
            "Legacy override applied to both worker and reviewer Codex runs. "
            "Use 0 to disable both timeouts."
        ),
    )
    parser.add_argument(
        "--worker-timeout-seconds",
        type=int,
        default=None,
        help=(
            "Maximum runtime for each worker Codex run. "
            "Defaults to 900 seconds. Use 0 to disable the timeout."
        ),
    )
    parser.add_argument(
        "--reviewer-timeout-seconds",
        type=int,
        default=None,
        help=(
            "Maximum runtime for each reviewer Codex run. "
            "Defaults to 300 seconds. Use 0 to disable the timeout."
        ),
    )
    parser.add_argument(
        "--codex-bin",
        default="codex",
        help="Codex CLI binary to invoke for worker and reviewer runs.",
    )
    parser.add_argument(
        "--model",
        help="Optional Codex model override for worker and reviewer runs.",
    )
    parser.add_argument(
        "--codex-arg",
        action="append",
        help="Additional argument to pass through to `codex exec`. Repeat as needed.",
    )
