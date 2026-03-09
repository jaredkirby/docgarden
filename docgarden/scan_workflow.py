from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from .files import atomic_write_text
from .models import RepoPaths, ScanRunResult
from .quality import build_scorecard
from .scanner import scan_repo
from .state import (
    active_findings_from_latest_events,
    actionable_findings_from_latest_events,
    append_scan_events,
    build_plan,
    compute_scan_hash,
    load_plan,
    write_json,
    write_score,
)


def _write_run_artifacts(
    paths: RepoPaths,
    *,
    findings,
    documents,
    scorecard,
    scan_time: datetime,
) -> None:
    run_dir = paths.state_dir / "runs" / scan_time.strftime("%Y-%m-%dT%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "summary.json",
        {
            "timestamp": scan_time.isoformat(timespec="seconds"),
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
        {"active_findings": [asdict(item) for item in findings]},
    )


def run_scan(paths: RepoPaths, *, scan_time: datetime | None = None) -> ScanRunResult:
    now = scan_time or datetime.now()
    findings, domain_doc_counts, documents = scan_repo(paths.repo_root)
    latest = append_scan_events(paths.findings, findings, now)
    score_tracked_findings = active_findings_from_latest_events(latest)
    actionable_findings = actionable_findings_from_latest_events(latest)
    scorecard = build_scorecard(score_tracked_findings, domain_doc_counts, now)
    write_score(paths.score, scorecard)
    previous_plan = load_plan(paths.plan) if paths.plan.exists() else None
    plan = build_plan(
        actionable_findings,
        compute_scan_hash([doc.rel_path for doc in documents]),
        now,
        previous_plan=previous_plan,
    )
    write_json(paths.plan, asdict(plan))
    _write_run_artifacts(
        paths,
        findings=findings,
        documents=documents,
        scorecard=scorecard,
        scan_time=now,
    )
    return ScanRunResult(findings=findings, scorecard=scorecard, latest_events=latest)
