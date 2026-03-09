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

    return parser


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
