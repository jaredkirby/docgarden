from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .config import Config
from .files import atomic_write_text
from .fixers import apply_safe_fixes
from .models import Finding, RepoPaths, ScanRunResult
from .quality import build_scorecard, write_quality_score
from .scanner import scan_repo
from .state import (
    append_scan_events,
    build_plan,
    compute_scan_hash,
    ensure_state_dirs,
    load_plan,
    load_score,
    latest_events_by_id,
    load_findings_history,
    write_json,
    write_score,
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


def run_scan(repo_root: Path) -> ScanRunResult:
    paths = repo_paths(repo_root)
    findings, domain_doc_counts, documents = scan_repo(repo_root)
    now = datetime.now()
    latest = append_scan_events(paths.findings, findings, now)
    scorecard = build_scorecard(findings, domain_doc_counts, now)
    write_score(paths.score, scorecard)
    plan = build_plan(
        findings, compute_scan_hash([doc.rel_path for doc in documents]), now
    )
    write_json(paths.plan, plan.to_dict())

    run_dir = paths.state_dir / "runs" / now.strftime("%Y-%m-%dT%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "summary.json",
        {
            "timestamp": now.isoformat(timespec="seconds"),
            "findings": len(findings),
            "overall_score": scorecard.overall_score,
            "strict_score": scorecard.strict_score,
        },
    )
    atomic_write_text(
        run_dir / "changed_files.txt",
        "\n".join(doc.rel_path for doc in documents) + "\n",
    )
    write_json(
        run_dir / "findings.delta.json",
        {"active_findings": [item.to_dict() for item in findings]},
    )
    return ScanRunResult(findings=findings, scorecard=scorecard, latest_events=latest)


def command_scan(_: argparse.Namespace) -> None:
    result = run_scan(Path.cwd())
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
    active = active_events(paths)
    score = load_score(paths.score)
    print(
        json.dumps(
            {
                "active_findings": len(active),
                "open_ids": [
                    event["id"]
                    for event in sorted(active, key=lambda item: item["id"])[:10]
                ],
                "overall_score": score.overall_score if score else None,
                "strict_score": score.strict_score if score else None,
            },
            indent=2,
        )
    )


def active_events(paths: RepoPaths) -> list[dict[str, object]]:
    events = load_findings_history(paths.findings)
    latest = latest_events_by_id(events)
    return [
        event
        for event in latest.values()
        if event.get("status") not in {"fixed", "false_positive"}
    ]


def command_next(_: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    active = active_events(paths)
    if not active:
        print("No open findings.")
        return
    next_item = sorted(
        active,
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(item["severity"], 3),
            item["id"],
        ),
    )[0]
    print(json.dumps(next_item, indent=2))


def command_plan(_: argparse.Namespace) -> None:
    paths = repo_paths(Path.cwd())
    if not paths.plan.exists():
        run_scan(Path.cwd())
    print(json.dumps(load_plan(paths.plan).to_dict(), indent=2, sort_keys=True))


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
    result = run_scan(Path.cwd())
    paths = repo_paths(Path.cwd())
    write_quality_score(paths.quality, result.scorecard)
    print(f"Wrote {paths.quality}")


def command_fix_safe(args: argparse.Namespace) -> None:
    findings = run_scan(Path.cwd()).findings
    fixable = [item for item in findings if item.safe_to_autofix]
    if not args.apply:
        print(json.dumps({"fixable": [item.id for item in fixable]}, indent=2))
        return
    changed = apply_safe_fixes(Path.cwd(), fixable)
    print(json.dumps({"changed_files": changed}, indent=2))


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
