from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .errors import StateError
from .files import atomic_write_text
from .models import (
    FINDING_STATUSES,
    INACTIVE_FINDING_STATUSES,
    RESOLVED_FINDING_STATUSES,
    Finding,
    PlanState,
    RepoPaths,
    Scorecard,
)

RESOLUTION_METADATA_FIELDS = (
    "attestation",
    "resolved_by",
    "resolution_note",
    "resolved_at",
)


def ensure_state_dirs(state_dir: Path) -> None:
    for name in ("reviews", "runs", "cache", "locks", "baselines"):
        (state_dir / name).mkdir(parents=True, exist_ok=True)


def load_findings_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except JSONDecodeError as exc:
            raise StateError(
                f"Invalid findings history at {path}:{line_number}: "
                f"{exc.msg} (column {exc.colno})."
            ) from exc
        if not isinstance(payload, dict):
            raise StateError(
                f"Invalid findings history at {path}:{line_number}: "
                "expected a JSON object."
            )
        events.append(payload)
    return events


def latest_events_by_id(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        latest[event["id"]] = event
    return latest


def _is_active_event(event: dict[str, Any]) -> bool:
    return event.get("status") not in INACTIVE_FINDING_STATUSES


def _event_priority_key(event: dict[str, Any]) -> tuple[int, str, str]:
    return (
        {"high": 0, "medium": 1, "low": 2}.get(str(event.get("severity")), 3),
        str(event.get("domain", "")),
        str(event.get("id", "")),
    )


def ordered_active_events(paths: RepoPaths) -> list[dict[str, Any]]:
    latest = latest_events_by_id(load_findings_history(paths.findings))
    active = {
        finding_id: event
        for finding_id, event in latest.items()
        if _is_active_event(event)
    }
    if not active:
        return []

    plan = load_plan(paths.plan) if paths.plan.exists() else None
    deferred_items = set(plan.deferred_items) if plan else set()
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    priority_ids: list[str] = []
    if plan is not None:
        if plan.current_focus:
            priority_ids.append(plan.current_focus)
        priority_ids.extend(plan.ordered_findings)

    for finding_id in priority_ids:
        if finding_id in seen or finding_id in deferred_items:
            continue
        event = active.get(finding_id)
        if event is None:
            continue
        ordered.append(event)
        seen.add(finding_id)

    remainder = sorted(
        (
            event
            for finding_id, event in active.items()
            if finding_id not in seen and finding_id not in deferred_items
        ),
        key=_event_priority_key,
    )
    return ordered + remainder


def next_active_event(paths: RepoPaths) -> dict[str, Any] | None:
    ordered = ordered_active_events(paths)
    return ordered[0] if ordered else None


def active_findings_from_latest_events(
    latest: dict[str, dict[str, Any]]
) -> list[Finding]:
    active_events = sorted(
        (event for event in latest.values() if _is_active_event(event)),
        key=_event_priority_key,
    )
    return [Finding.from_dict(event) for event in active_events]


def append_scan_events(
    findings_path: Path,
    active_findings: list[Finding],
    scan_time: datetime,
) -> dict[str, dict[str, Any]]:
    events = load_findings_history(findings_path)
    latest = latest_events_by_id(events)
    active_by_id = {finding.id: finding for finding in active_findings}
    lines = []

    scan_timestamp = scan_time.isoformat(timespec="seconds")
    for finding in active_findings:
        prior = latest.get(finding.id, {})
        payload = asdict(finding)
        payload["status"] = prior.get("status", finding.status)
        for field in RESOLUTION_METADATA_FIELDS:
            if payload.get(field) is None and prior.get(field) is not None:
                payload[field] = prior[field]
        payload["event"] = "observed"
        payload["event_at"] = scan_timestamp
        lines.append(json.dumps(payload, sort_keys=True))
        latest[finding.id] = payload

    for finding_id, prior in list(latest.items()):
        if prior.get("status") in INACTIVE_FINDING_STATUSES:
            continue
        if finding_id not in active_by_id:
            resolved = dict(prior)
            resolved["status"] = "fixed"
            resolved["event"] = "resolved"
            resolved["event_at"] = scan_timestamp
            resolved["resolved_at"] = scan_timestamp
            for field in ("attestation", "resolved_by", "resolution_note"):
                resolved[field] = None
            lines.append(json.dumps(resolved, sort_keys=True))
            latest[finding_id] = resolved

    if lines:
        with findings_path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return latest


def append_finding_status_event(
    findings_path: Path,
    finding_id: str,
    *,
    status: str,
    event_at: datetime,
    attestation: str | None = None,
    resolved_by: str | None = None,
    resolution_note: str | None = None,
) -> dict[str, Any]:
    if status not in FINDING_STATUSES:
        raise StateError(f"Unsupported finding status: {status}.")

    latest = latest_events_by_id(load_findings_history(findings_path))
    prior = latest.get(finding_id)
    if prior is None:
        raise StateError(f"Cannot update unknown finding: {finding_id}.")

    payload = dict(prior)
    payload["status"] = status
    payload["event"] = "status_changed"
    payload["event_at"] = event_at.isoformat(timespec="seconds")
    payload["attestation"] = attestation
    payload["resolved_by"] = resolved_by
    payload["resolution_note"] = resolution_note
    payload["resolved_at"] = (
        payload["event_at"] if status in RESOLVED_FINDING_STATUSES else None
    )

    with findings_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_score(path: Path, scorecard: Scorecard) -> None:
    write_json(path, asdict(scorecard))


def _load_state_object(
    path: Path,
    *,
    label: str,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default
        raise StateError(f"Missing {label} state file at {path}.")
    try:
        payload = json.loads(path.read_text())
    except JSONDecodeError as exc:
        raise StateError(
            f"Invalid {label} state at {path}: {exc.msg} "
            f"(line {exc.lineno}, column {exc.colno})."
        ) from exc
    if not isinstance(payload, dict):
        raise StateError(f"Invalid {label} state at {path}: expected a JSON object.")
    return payload


def load_score(path: Path) -> Scorecard | None:
    payload = _load_state_object(path, label="score", default={})
    if not payload:
        return None
    try:
        return Scorecard(**payload)
    except TypeError as exc:
        raise StateError(
            f"Invalid score state at {path}: payload does not match Scorecard."
        ) from exc


def load_plan(path: Path) -> PlanState:
    payload = _load_state_object(path, label="plan")
    try:
        return PlanState(**payload)
    except TypeError as exc:
        raise StateError(
            f"Invalid plan state at {path}: payload does not match PlanState."
        ) from exc


def build_plan(
    active_findings: list[Finding],
    scan_hash: str,
    scan_time: datetime,
    *,
    previous_plan: PlanState | None = None,
) -> PlanState:
    active_ids = {finding.id for finding in active_findings}
    clusters: dict[str, list[str]] = defaultdict(list)
    for finding in active_findings:
        clusters[finding.cluster].append(finding.id)
    if previous_plan is not None:
        for cluster_name, issue_ids in previous_plan.clusters.items():
            for issue_id in issue_ids:
                if issue_id not in active_ids or issue_id in clusters[cluster_name]:
                    continue
                clusters[cluster_name].append(issue_id)

    ordered = sorted(
        active_findings,
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(item.severity, 3),
            item.domain,
            item.id,
        ),
    )
    ordered_ids = [finding.id for finding in ordered]
    if previous_plan is not None:
        preserved_order = [
            finding_id
            for finding_id in previous_plan.ordered_findings
            if finding_id in active_ids
        ]
        ordered_ids = preserved_order + [
            finding_id
            for finding_id in ordered_ids
            if finding_id not in preserved_order
        ]
    deferred_items = (
        [
            finding_id
            for finding_id in previous_plan.deferred_items
            if finding_id in active_ids
        ]
        if previous_plan is not None
        else []
    )
    next_focus = next(
        (finding_id for finding_id in ordered_ids if finding_id not in deferred_items),
        ordered_ids[0] if ordered_ids else None,
    )
    current_focus = next_focus
    if (
        previous_plan is not None
        and previous_plan.current_focus in active_ids
        and previous_plan.current_focus not in deferred_items
    ):
        current_focus = previous_plan.current_focus
    return PlanState(
        updated_at=scan_time.isoformat(timespec="seconds"),
        lifecycle_stage=(
            previous_plan.lifecycle_stage
            if previous_plan is not None and ordered_ids
            else ("observe" if ordered_ids else "complete")
        ),
        current_focus=current_focus,
        ordered_findings=ordered_ids,
        clusters=dict(clusters),
        deferred_items=deferred_items,
        last_scan_hash=scan_hash,
    )


def compute_scan_hash(paths: list[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.encode("utf-8"))
    return digest.hexdigest()
