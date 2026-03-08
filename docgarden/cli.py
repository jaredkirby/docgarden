from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .config import Config
from .fixers import apply_safe_fixes
from .models import Finding
from .quality import build_scorecard, write_quality_score
from .scanner import scan_repo
from .state import (
    append_scan_events,
    build_plan,
    compute_scan_hash,
    ensure_state_dirs,
    latest_events_by_id,
    load_findings_history,
    write_json,
    write_score,
)


def repo_paths(repo_root: Path) -> dict[str, Path]:
    state_dir = repo_root / ".docgarden"
    ensure_state_dirs(state_dir)
    return {
        "repo_root": repo_root,
        "state_dir": state_dir,
        "config": state_dir / "config.yaml",
        "findings": state_dir / "findings.jsonl",
        "plan": state_dir / "plan.json",
        "score": state_dir / "score.json",
        "quality": repo_root / "docs" / "QUALITY_SCORE.md",
    }


def run_scan(repo_root: Path, scope: str) -> tuple[list[Finding], dict, dict]:
    paths = repo_paths(repo_root)
    config = Config.load(paths["config"])
    findings, domain_doc_counts, documents = scan_repo(repo_root, config, scope=scope)
    now = datetime.now()
    latest = append_scan_events(paths["findings"], findings, now)
    scorecard = build_scorecard(findings, domain_doc_counts, now)
    write_score(paths["score"], scorecard)
    plan = build_plan(
        findings, compute_scan_hash([doc.rel_path for doc in documents]), now
    )
    write_json(paths["plan"], plan)

    run_dir = paths["state_dir"] / "runs" / now.strftime("%Y-%m-%dT%H%M%S")
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
    (run_dir / "changed_files.txt").write_text(
        "\n".join(doc.rel_path for doc in documents) + "\n"
    )
    write_json(
        run_dir / "findings.delta.json",
        {"active_findings": [item.to_dict() for item in findings]},
    )
    return findings, scorecard.to_dict(), latest


def command_scan(args: argparse.Namespace) -> int:
    findings, scorecard, _ = run_scan(Path.cwd(), args.scope)
    print(
        json.dumps(
            {
                "findings": len(findings),
                "overall_score": scorecard["overall_score"],
                "strict_score": scorecard["strict_score"],
            },
            indent=2,
        )
    )
    return 0


def command_status(_: argparse.Namespace) -> int:
    paths = repo_paths(Path.cwd())
    events = load_findings_history(paths["findings"])
    latest = latest_events_by_id(events)
    active = [
        event
        for event in latest.values()
        if event.get("status") not in {"fixed", "false_positive"}
    ]
    score = json.loads(paths["score"].read_text()) if paths["score"].exists() else {}
    print(
        json.dumps(
            {
                "active_findings": len(active),
                "open_ids": [
                    event["id"]
                    for event in sorted(active, key=lambda item: item["id"])[:10]
                ],
                "overall_score": score.get("overall_score"),
                "strict_score": score.get("strict_score"),
            },
            indent=2,
        )
    )
    return 0


def command_next(_: argparse.Namespace) -> int:
    paths = repo_paths(Path.cwd())
    events = load_findings_history(paths["findings"])
    latest = latest_events_by_id(events)
    active = [
        event
        for event in latest.values()
        if event.get("status") not in {"fixed", "false_positive"}
    ]
    if not active:
        print("No open findings.")
        return 0
    next_item = sorted(
        active,
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(item["severity"], 3),
            item["id"],
        ),
    )[0]
    print(json.dumps(next_item, indent=2))
    return 0


def command_plan(_: argparse.Namespace) -> int:
    paths = repo_paths(Path.cwd())
    if not paths["plan"].exists():
        run_scan(Path.cwd(), "all")
    print(paths["plan"].read_text().strip())
    return 0


def command_show(args: argparse.Namespace) -> int:
    paths = repo_paths(Path.cwd())
    events = load_findings_history(paths["findings"])
    latest = latest_events_by_id(events)
    payload = latest.get(args.finding_id)
    if not payload:
        print(f"Finding not found: {args.finding_id}", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2))
    return 0


def command_quality_write(_: argparse.Namespace) -> int:
    _, scorecard, _ = run_scan(Path.cwd(), "all")
    paths = repo_paths(Path.cwd())
    from .models import Scorecard

    score = Scorecard(**scorecard)
    write_quality_score(paths["quality"], score)
    print(f"Wrote {paths['quality']}")
    return 0


def command_fix_safe(args: argparse.Namespace) -> int:
    findings, _, _ = run_scan(Path.cwd(), "all")
    fixable = [item for item in findings if item.safe_to_autofix]
    if not args.apply:
        print(json.dumps({"fixable": [item.id for item in fixable]}, indent=2))
        return 0
    changed = apply_safe_fixes(Path.cwd(), fixable)
    print(json.dumps({"changed_files": changed}, indent=2))
    return 0


def command_config_show(_: argparse.Namespace) -> int:
    paths = repo_paths(Path.cwd())
    config = Config.load(paths["config"])
    print(json.dumps(config.to_dict(), indent=2))
    return 0


def command_doctor(_: argparse.Namespace) -> int:
    paths = repo_paths(Path.cwd())
    status = {
        "repo_root": str(paths["repo_root"]),
        "config_exists": paths["config"].exists(),
        "docs_exists": (paths["repo_root"] / "docs").exists(),
        "agents_exists": (paths["repo_root"] / "AGENTS.md").exists(),
        "state_dir": str(paths["state_dir"]),
    }
    print(json.dumps(status, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docgarden")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan")
    scan.add_argument("--scope", choices=["all", "changed"], default="all")
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
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
