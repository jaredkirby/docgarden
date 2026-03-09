from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
import os
import sys
from pathlib import Path

from .config import Config
from .errors import DocgardenError
from .fixers import apply_safe_fixes
from .models import RepoPaths
from .quality import write_quality_score
from .scan_workflow import run_changed_scan, run_scan
from .state import (
    ensure_state_dirs,
    load_findings_history,
    load_plan,
    load_score,
    next_active_event,
    ordered_active_events,
    latest_events_by_id,
    record_plan_resolution,
    record_plan_triage_stage,
    reopen_plan_finding,
    set_plan_focus,
)


def repo_paths(repo_root: Path) -> RepoPaths:
    state_dir = repo_root / ".docgarden"
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
    paths = repo_paths(Path.cwd())
    if args.scope != "changed" and args.files:
        raise DocgardenError("`docgarden scan --files` requires `--scope changed`.")

    if args.scope == "changed":
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
                "open_ids": [event["id"] for event in active[:10]],
                "overall_score": score.overall_score if score else None,
                "strict_score": score.strict_score if score else None,
            },
            indent=2,
        )
    )


def command_next(_: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    next_item = next_active_event(paths)
    if next_item is None:
        print("No open findings.")
        return
    print(json.dumps(next_item, indent=2))


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
                "event": event,
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
                "event": event,
                "plan": asdict(updated_plan),
            },
            indent=2,
            sort_keys=True,
        )
    )


def command_show(args: argparse.Namespace) -> int:
    paths = repo_paths(Path.cwd())
    events = load_findings_history(paths.findings)
    latest = latest_events_by_id(events)
    payload = latest.get(args.finding_id)
    if not payload:
        print(f"Finding not found: {args.finding_id}", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2))
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
        print(json.dumps({"fixable": [item.id for item in fixable]}, indent=2))
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
