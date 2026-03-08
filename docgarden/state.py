from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Finding, Scorecard


def ensure_state_dirs(state_dir: Path) -> None:
    for name in ("reviews", "runs", "cache", "locks", "baselines"):
        (state_dir / name).mkdir(parents=True, exist_ok=True)


def load_findings_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def latest_events_by_id(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        latest[event["id"]] = event
    return latest


def append_scan_events(
    findings_path: Path,
    active_findings: list[Finding],
    scan_time: datetime,
) -> dict[str, dict[str, Any]]:
    events = load_findings_history(findings_path)
    latest = latest_events_by_id(events)
    active_by_id = {finding.id: finding for finding in active_findings}
    lines = []

    for finding in active_findings:
        prior = latest.get(finding.id, {})
        payload = finding.to_dict()
        payload["status"] = prior.get("status", finding.status)
        payload["event"] = "observed"
        payload["event_at"] = scan_time.isoformat(timespec="seconds")
        lines.append(json.dumps(payload, sort_keys=True))
        latest[finding.id] = payload

    for finding_id, prior in list(latest.items()):
        if prior.get("status") in {"fixed", "false_positive"}:
            continue
        if finding_id not in active_by_id:
            resolved = dict(prior)
            resolved["status"] = "fixed"
            resolved["event"] = "resolved"
            resolved["event_at"] = scan_time.isoformat(timespec="seconds")
            lines.append(json.dumps(resolved, sort_keys=True))
            latest[finding_id] = resolved

    if lines:
        with findings_path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return latest


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_score(path: Path, scorecard: Scorecard) -> None:
    write_json(path, scorecard.to_dict())


def build_plan(
    active_findings: list[Finding], scan_hash: str, scan_time: datetime
) -> dict[str, Any]:
    clusters: dict[str, list[str]] = defaultdict(list)
    for finding in active_findings:
        clusters[finding.cluster].append(finding.id)

    ordered = sorted(
        active_findings,
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(item.severity, 3),
            item.domain,
            item.id,
        ),
    )
    return {
        "updated_at": scan_time.isoformat(timespec="seconds"),
        "lifecycle_stage": "observe" if ordered else "complete",
        "current_focus": ordered[0].id if ordered else None,
        "ordered_findings": [finding.id for finding in ordered],
        "clusters": dict(clusters),
        "deferred_items": [],
        "last_scan_hash": scan_hash,
    }


def compute_scan_hash(paths: list[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.encode("utf-8"))
    return digest.hexdigest()
