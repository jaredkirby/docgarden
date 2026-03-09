from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys
from pathlib import Path

from .config import Config
from .fixers import apply_safe_fixes
from .models import RepoPaths
from .quality import write_quality_score
from .scan_workflow import run_scan
from .state import (
    ensure_state_dirs,
    load_findings_history,
    load_plan,
    load_score,
    next_active_event,
    ordered_active_events,
    latest_events_by_id,
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


def command_scan(_: argparse.Namespace) -> None:
    result = run_scan(repo_paths(Path.cwd()))
    print(
        json.dumps(
            {
                "findings": len(result.findings),
                "overall_score": result.scorecard.overall_score,
                "strict_score": result.scorecard.strict_score,
            },
            indent=2,
        )
    )


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
    if not paths.plan.exists():
        run_scan(paths)
    print(json.dumps(asdict(load_plan(paths.plan)), indent=2, sort_keys=True))


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
