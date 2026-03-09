from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .automation import build_ci_check_payload
from .config import Config
from .errors import DocgardenError
from .fixers import apply_safe_fixes, preview_safe_fixes
from .models import RepoPaths
from .pr_drafts import build_pr_draft_payload, publish_pr_draft
from .quality import write_quality_score
from .scan.workflow import run_changed_scan, run_scan
from .state import (
    actionable_findings_from_latest_events,
    ensure_state_dirs,
    load_findings_history,
    load_plan,
    load_score,
    next_active_event,
    ordered_active_events,
    latest_events_by_id,
)


def repo_paths(repo_root: Path, *, ensure_state: bool = True) -> RepoPaths:
    state_dir = repo_root / ".docgarden"
    if ensure_state:
        ensure_state_dirs(state_dir)
    return RepoPaths(
        repo_root=repo_root,
        state_dir=state_dir,
        config=state_dir / "config.yaml",
        findings=state_dir / "findings.jsonl",
        plan=state_dir / "plan.json",
        score=state_dir / "score.json",
        quality=repo_root / "docs" / "QUALITY_SCORE.md",
    )


def _ensure_plan(paths: RepoPaths):
    if not paths.plan.exists():
        run_scan(paths)
    return load_plan(paths.plan)


def _current_actor() -> str | None:
    return os.environ.get("USER") or os.environ.get("LOGNAME")


def command_scan(args: argparse.Namespace) -> None:
    if args.scope != "changed" and args.files:
        raise DocgardenError("`docgarden scan --files` requires `--scope changed`.")

    if args.scope == "changed":
        paths = repo_paths(Path.cwd(), ensure_state=False)
        result = run_changed_scan(paths, changed_files=args.files)
        previous_score = load_score(paths.score)
        payload = {
            "scope": result.scope,
            "findings": len(result.findings),
            "overall_score": None,
            "strict_score": None,
            "last_full_scan_overall_score": (
                previous_score.overall_score if previous_score else None
            ),
            "last_full_scan_strict_score": (
                previous_score.strict_score if previous_score else None
            ),
            "changed_files_source": result.changed_files_source,
            "requested_files": result.requested_files,
            "scanned_files": result.scanned_files,
            "deleted_files": result.deleted_files,
            "recomputed_views": result.recomputed_views,
            "skipped_views": result.skipped_views,
            "notes": result.notes,
        }
    else:
        paths = repo_paths(Path.cwd())
        result = run_scan(paths)
        payload = {
            "scope": result.scope,
            "findings": len(result.findings),
            "overall_score": result.scorecard.overall_score if result.scorecard else None,
            "strict_score": result.scorecard.strict_score if result.scorecard else None,
        }

    print(json.dumps(payload, indent=2))


def command_status(_: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    active = ordered_active_events(paths)
    score = load_score(paths.score)
    print(
        json.dumps(
            {
                "active_findings": len(active),
                "open_ids": [event.id for event in active[:10]],
                "overall_score": score.overall_score if score else None,
                "strict_score": score.strict_score if score else None,
            },
            indent=2,
        )
    )


def command_ci_check(_: argparse.Namespace) -> int:
    paths = repo_paths(Path.cwd())
    payload = build_ci_check_payload(paths)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 2


def command_next(_: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    next_item = next_active_event(paths)
    if next_item is None:
        print("No open findings.")
        return
    print(json.dumps(next_item.to_dict(), indent=2))


def command_show(args: argparse.Namespace) -> int:
    paths = repo_paths(Path.cwd())
    events = load_findings_history(paths.findings)
    latest = latest_events_by_id(events)
    payload = latest.get(args.finding_id)
    if not payload:
        print(f"Finding not found: {args.finding_id}", file=sys.stderr)
        return 1
    print(json.dumps(payload.to_dict(), indent=2))
    return 0


def command_quality_write(_: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    result = run_scan(paths)
    write_quality_score(paths.quality, result.scorecard)
    print(f"Wrote {paths.quality}")


def command_fix_safe(args: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    findings = run_scan(paths).findings
    fixable = [item for item in findings if item.safe_to_autofix]
    if not args.apply:
        print(
            json.dumps(
                {
                    "fixable": [item.id for item in fixable],
                    "planned_changes": preview_safe_fixes(Path.cwd(), fixable),
                },
                indent=2,
            )
        )
        return
    changed = apply_safe_fixes(Path.cwd(), fixable)
    result = run_scan(paths) if changed else None
    print(
        json.dumps(
            {
                "changed_files": changed,
                "active_findings": len(result.findings) if result is not None else len(findings),
            },
            indent=2,
        )
    )


def command_pr_draft(args: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    result = run_scan(paths)
    config = Config.load(paths.config)
    actionable_findings = actionable_findings_from_latest_events(result.latest_events)
    payload = build_pr_draft_payload(
        paths.repo_root,
        config,
        actionable_findings,
        unsafe_as_issue=args.unsafe_as_issue,
    )
    if args.publish:
        payload["remote"] = publish_pr_draft(paths.repo_root, config, payload)
        payload["published"] = True
    print(json.dumps(payload, indent=2, sort_keys=True))


def command_config_show(_: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    config = Config.load(paths.config)
    print(json.dumps(config.to_dict(), indent=2))


def command_doctor(_: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    status = {
        "repo_root": str(paths.repo_root),
        "config_exists": paths.config.exists(),
        "docs_exists": (paths.repo_root / "docs").exists(),
        "agents_exists": (paths.repo_root / "AGENTS.md").exists(),
        "state_dir": str(paths.state_dir),
    }
    print(json.dumps(status, indent=2))
