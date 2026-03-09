from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path

from .cli_commands import _current_actor, _ensure_plan, repo_paths
from .state import (
    import_review,
    prepare_review_packet,
    record_plan_resolution,
    record_plan_triage_stage,
    reopen_plan_finding,
    set_plan_focus,
)


def register_review_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    review = subparsers.add_parser("review")
    review_subparsers = review.add_subparsers(dest="review_command", required=True)
    review_prepare = review_subparsers.add_parser(
        "prepare",
        help="Export a deterministic review packet for targeted subjective review.",
    )
    review_prepare.add_argument(
        "--domains",
        help=(
            "Optional comma-separated doc domains to include in the packet. "
            "Defaults to review-ready docs under `docs/`; skipped docs that "
            "lack packetizable metadata are reported in the output."
        ),
    )
    review_prepare.set_defaults(func=command_review_prepare)
    review_import = review_subparsers.add_parser(
        "import",
        help="Import structured review findings from a JSON file.",
    )
    review_import.add_argument(
        "file",
        help="Path to a structured review JSON file that references a prepared packet.",
    )
    review_import.set_defaults(func=command_review_import)


def register_plan_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    plan_resolve_statuses: list[str] | tuple[str, ...],
) -> None:
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
        choices=plan_resolve_statuses,
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


def command_review_prepare(args: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    packet_path, payload = prepare_review_packet(
        paths.repo_root,
        paths.state_dir,
        domains=_parse_domain_args(args.domains),
    )
    print(
        json.dumps(
            {
                "packet_id": payload["packet_id"],
                "path": str(packet_path),
                "domains": payload["scope"]["domains"],
                "documents": payload["scope"]["documents"],
                "skipped_documents": payload["scope"]["skipped_documents"],
                "mechanical_findings": len(payload["mechanical_findings"]),
            },
            indent=2,
            sort_keys=True,
        )
    )


def command_review_import(args: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    stored_review_path, stored_payload, findings, plan = import_review(
        paths,
        Path(args.file),
        imported_at=datetime.now(),
    )
    print(
        json.dumps(
            {
                "review_id": stored_payload["review_id"],
                "packet_id": stored_payload["packet_id"],
                "stored_review": str(stored_review_path),
                "finding_ids": [finding.id for finding in findings],
                "plan": asdict(plan),
            },
            indent=2,
            sort_keys=True,
        )
    )


def command_plan(_: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    print(json.dumps(asdict(_ensure_plan(paths)), indent=2, sort_keys=True))


def command_plan_triage(args: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    _ensure_plan(paths)
    updated_plan = record_plan_triage_stage(
        paths.plan,
        stage=args.stage,
        report=args.report,
        updated_at=datetime.now(),
    )
    print(json.dumps(asdict(updated_plan), indent=2, sort_keys=True))


def command_plan_focus(args: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    _ensure_plan(paths)
    updated_plan = set_plan_focus(
        paths.plan,
        paths.findings,
        target=args.target,
        updated_at=datetime.now(),
    )
    print(json.dumps(asdict(updated_plan), indent=2, sort_keys=True))


def command_plan_resolve(args: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    _ensure_plan(paths)
    event, updated_plan = record_plan_resolution(
        paths.plan,
        paths.findings,
        args.finding_id,
        status=args.result,
        event_at=datetime.now(),
        attestation=args.attest,
        resolved_by=_current_actor(),
    )
    print(
        json.dumps(
            {
                "event": event.to_dict(),
                "plan": asdict(updated_plan),
            },
            indent=2,
            sort_keys=True,
        )
    )


def command_plan_reopen(args: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    _ensure_plan(paths)
    event, updated_plan = reopen_plan_finding(
        paths.plan,
        paths.findings,
        args.finding_id,
        event_at=datetime.now(),
        resolved_by=_current_actor(),
    )
    print(
        json.dumps(
            {
                "event": event.to_dict(),
                "plan": asdict(updated_plan),
            },
            indent=2,
            sort_keys=True,
        )
    )


def _parse_domain_args(raw_domains: str | None) -> list[str]:
    if not raw_domains:
        return []
    return [domain.strip() for domain in raw_domains.split(",") if domain.strip()]
