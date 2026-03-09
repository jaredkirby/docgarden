from __future__ import annotations

import argparse
import sys

from .cli_commands import (
    command_config_show,
    command_doctor,
    command_fix_safe,
    command_next,
    command_plan,
    command_quality_write,
    command_scan,
    command_show,
    command_status,
)
from .errors import DocgardenError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docgarden")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan")
    scan.set_defaults(func=command_scan)

    status = subparsers.add_parser("status")
    status.set_defaults(func=command_status)

    next_cmd = subparsers.add_parser("next")
    next_cmd.set_defaults(func=command_next)

    plan = subparsers.add_parser("plan")
    plan.set_defaults(func=command_plan)

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
