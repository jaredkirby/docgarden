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
from .slices import (
    build_implementation_prompt,
    build_review_prompt,
    build_slice_paths,
    load_slice_catalog,
    run_slice_loop,
)
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


def command_slices_next(args: argparse.Namespace) -> int:
    repo_root = Path.cwd()
    paths = _slice_paths_from_args(repo_root, args)
    catalog = load_slice_catalog(repo_root, paths=paths)
    next_slice = catalog.next_actionable_slice()
    if next_slice is None:
        print("No queued or active slices remain.")
        return 0
    upcoming = catalog.next_after(next_slice.slice_id)
    print(
        json.dumps(
            {
                "slice_id": next_slice.slice_id,
                "title": next_slice.title,
                "status": next_slice.status,
                "goal": next_slice.goal,
                "depends_on": next_slice.depends_on,
                "changes": next_slice.changes,
                "acceptance": next_slice.acceptance,
                "next_slice": upcoming.slice_id if upcoming is not None else None,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def command_slices_kickoff_prompt(args: argparse.Namespace) -> None:
    repo_root = Path.cwd()
    paths = _slice_paths_from_args(repo_root, args)
    catalog = load_slice_catalog(repo_root, paths=paths)
    slice_def = (
        catalog.by_id(args.slice_id)
        if args.slice_id is not None
        else catalog.next_actionable_slice()
    )
    if slice_def is None:
        raise DocgardenError("No queued or active slices remain.")
    next_slice = catalog.next_after(slice_def.slice_id)
    print(
        build_implementation_prompt(
            repo_root,
            slice_def,
            next_slice=next_slice,
            paths=paths,
            round_number=args.round,
            review_feedback_path=Path(args.review_feedback)
            if args.review_feedback
            else None,
            previous_worker_output_path=Path(args.previous_worker_output)
            if args.previous_worker_output
            else None,
        ),
        end="",
    )


def command_slices_review_prompt(args: argparse.Namespace) -> None:
    repo_root = Path.cwd()
    paths = _slice_paths_from_args(repo_root, args)
    catalog = load_slice_catalog(repo_root, paths=paths)
    slice_def = (
        catalog.by_id(args.slice_id)
        if args.slice_id is not None
        else catalog.next_actionable_slice()
    )
    if slice_def is None:
        raise DocgardenError("No queued or active slices remain.")
    next_slice = catalog.next_after(slice_def.slice_id)
    print(
        build_review_prompt(
            repo_root,
            slice_def,
            next_slice=next_slice,
            paths=paths,
            worker_output_path=Path(args.worker_output),
            round_number=args.round,
            prior_review_path=Path(args.prior_review_output)
            if args.prior_review_output
            else None,
        ),
        end="",
    )


def command_slices_run(args: argparse.Namespace) -> int:
    if args.max_slices < 0:
        raise DocgardenError("`docgarden slices run --max-slices` must be 0 or greater.")
    if args.max_review_rounds < 1:
        raise DocgardenError(
            "`docgarden slices run --max-review-rounds` must be at least 1."
        )
    if args.agent_timeout_seconds < 0:
        raise DocgardenError(
            "`docgarden slices run --agent-timeout-seconds` must be 0 or greater."
        )

    slice_paths = _slice_paths_from_args(Path.cwd(), args)
    summary = run_slice_loop(
        Path.cwd(),
        paths=slice_paths,
        start_slice=args.from_slice,
        max_slices=args.max_slices,
        max_review_rounds=args.max_review_rounds,
        agent_timeout_seconds=(
            None if args.agent_timeout_seconds == 0 else args.agent_timeout_seconds
        ),
        codex_bin=args.codex_bin,
        model=args.model,
        codex_args=args.codex_arg or [],
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("status") in {"completed", "noop"} else 1


def _slice_paths_from_args(repo_root: Path, args: argparse.Namespace):
    return build_slice_paths(
        repo_root,
        implementation_slices=getattr(args, "catalog_path", None),
        spec=getattr(args, "spec_path", None),
        spec_slicing_plan=getattr(args, "plan_path", None),
        artifacts_dir=getattr(args, "artifacts_dir", None),
    )
