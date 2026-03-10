from __future__ import annotations

import argparse
import sys

from .cli_commands import (
    command_ci_check,
    command_config_show,
    command_doctor,
    command_fix_safe,
    command_next,
    command_pr_draft,
    command_quality_write,
    command_scan,
    command_show,
    command_status,
)
from .cli_plan_review import register_plan_parser, register_review_parser
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

    ci = subparsers.add_parser(
        "ci",
        help="CI-friendly enforcement helpers backed by persisted docgarden state.",
    )
    ci_subparsers = ci.add_subparsers(dest="ci_command", required=True)
    ci_check = ci_subparsers.add_parser(
        "check",
        help="Fail cleanly when the configured score threshold or block-on rules trip.",
    )
    ci_check.set_defaults(func=command_ci_check)

    next_cmd = subparsers.add_parser("next")
    next_cmd.set_defaults(func=command_next)

    register_review_parser(subparsers)
    register_plan_parser(
        subparsers,
        plan_resolve_statuses=PLAN_RESOLVE_FINDING_STATUSES,
    )

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

    pr = subparsers.add_parser(
        "pr",
        help="Prepare or publish draft PR or issue summaries from current docgarden state.",
    )
    pr_subparsers = pr.add_subparsers(dest="pr_command", required=True)
    pr_draft = pr_subparsers.add_parser(
        "draft",
        help=(
            "Generate a human-readable markdown summary from actionable findings "
            "and current changed files. Add `--publish` only when repo support "
            "and credentials are configured explicitly."
        ),
    )
    pr_draft.add_argument(
        "--unsafe-as-issue",
        action="store_true",
        help="Draft an unsafe-work follow-up issue instead of a draft PR.",
    )
    pr_draft.add_argument(
        "--publish",
        action="store_true",
        help=(
            "Create the draft PR or, with `--unsafe-as-issue`, a normal issue "
            "through the configured provider."
        ),
    )
    pr_draft.set_defaults(func=command_pr_draft)

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
