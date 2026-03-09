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
    ACTIONABLE_FINDING_STATUSES,
    ATTESTATION_REQUIRED_FINDING_STATUSES,
    AUTO_RESOLVED_FINDING_STATUSES,
    FINDING_STATUSES,
    PLAN_RESOLVE_FINDING_STATUSES,
    REOPENED_ON_OBSERVATION_STATUSES,
    REOPENABLE_FINDING_STATUSES,
    RESOLVED_FINDING_STATUSES,
    SCORE_RELEVANT_FINDING_STATUSES,
    Finding,
    PLAN_LIFECYCLE_STAGES,
    PlanState,
    RepoPaths,
    Scorecard,
    TRIAGE_LIFECYCLE_STAGES,
)

RESOLUTION_METADATA_FIELDS = (
    "attestation",
    "resolved_by",
    "resolution_note",
    "resolved_at",
)
TRIAGE_STAGE_TRANSITIONS = {
    "observe": frozenset({"observe", "reflect"}),
    "reflect": frozenset({"reflect", "organize"}),
    "organize": frozenset({"organize"}),
    "complete": frozenset({"observe"}),
}


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


def _is_actionable_event(event: dict[str, Any]) -> bool:
    return event.get("status") in ACTIONABLE_FINDING_STATUSES


def _is_score_relevant_event(event: dict[str, Any]) -> bool:
    return event.get("status") in SCORE_RELEVANT_FINDING_STATUSES


def _event_priority_key(event: dict[str, Any]) -> tuple[int, str, str]:
    return (
        {"high": 0, "medium": 1, "low": 2}.get(str(event.get("severity")), 3),
        str(event.get("domain", "")),
        str(event.get("id", "")),
    )


def _ordered_actionable_ids(
    plan: PlanState | None,
    latest: dict[str, dict[str, Any]],
    *,
    include_deferred: bool = False,
) -> list[str]:
    active = {
        finding_id: event
        for finding_id, event in latest.items()
        if _is_actionable_event(event)
    }
    if not active:
        return []

    deferred_items = (
        set(plan.deferred_items) if plan is not None and not include_deferred else set()
    )
    ordered: list[str] = []
    seen: set[str] = set()
    priority_ids: list[str] = []
    if plan is not None:
        if plan.current_focus:
            priority_ids.append(plan.current_focus)
        priority_ids.extend(plan.ordered_findings)

    for finding_id in priority_ids:
        if finding_id in seen or finding_id in deferred_items:
            continue
        if finding_id not in active:
            continue
        ordered.append(finding_id)
        seen.add(finding_id)

    remainder = [
        event["id"]
        for event in sorted(
            (
                event
                for finding_id, event in active.items()
                if finding_id not in seen and finding_id not in deferred_items
            ),
            key=_event_priority_key,
        )
    ]
    return ordered + remainder


def _write_plan_state(path: Path, plan: PlanState) -> PlanState:
    write_json(path, asdict(plan))
    return plan


def _copy_plan_state(
    plan: PlanState,
    *,
    updated_at: datetime,
    current_focus: str | None,
    deferred_items: list[str] | None = None,
) -> PlanState:
    return PlanState(
        updated_at=updated_at.isoformat(timespec="seconds"),
        lifecycle_stage=plan.lifecycle_stage,
        current_focus=current_focus,
        ordered_findings=list(plan.ordered_findings),
        clusters=dict(plan.clusters),
        deferred_items=(
            list(plan.deferred_items) if deferred_items is None else list(deferred_items)
        ),
        last_scan_hash=plan.last_scan_hash,
        stage_notes=dict(plan.stage_notes),
        strategy_text=plan.strategy_text,
    )


def ordered_active_events(paths: RepoPaths) -> list[dict[str, Any]]:
    latest = latest_events_by_id(load_findings_history(paths.findings))
    plan = load_plan(paths.plan) if paths.plan.exists() else None
    return [latest[finding_id] for finding_id in _ordered_actionable_ids(plan, latest)]


def next_active_event(paths: RepoPaths) -> dict[str, Any] | None:
    ordered = ordered_active_events(paths)
    return ordered[0] if ordered else None


def active_findings_from_latest_events(
    latest: dict[str, dict[str, Any]]
) -> list[Finding]:
    active_events = sorted(
        (event for event in latest.values() if _is_score_relevant_event(event)),
        key=_event_priority_key,
    )
    return [Finding.from_dict(event) for event in active_events]


def actionable_findings_from_latest_events(
    latest: dict[str, dict[str, Any]]
) -> list[Finding]:
    active_events = sorted(
        (event for event in latest.values() if _is_actionable_event(event)),
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
        if prior.get("status") in REOPENED_ON_OBSERVATION_STATUSES:
            payload["status"] = finding.status
            for field in RESOLUTION_METADATA_FIELDS:
                payload[field] = None
        else:
            payload["status"] = prior.get("status", finding.status)
            for field in RESOLUTION_METADATA_FIELDS:
                if payload.get(field) is None and prior.get(field) is not None:
                    payload[field] = prior[field]
        payload["event"] = "observed"
        payload["event_at"] = scan_timestamp
        lines.append(json.dumps(payload, sort_keys=True))
        latest[finding.id] = payload

    for finding_id, prior in list(latest.items()):
        if prior.get("status") not in AUTO_RESOLVED_FINDING_STATUSES:
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
    if (
        status in ATTESTATION_REQUIRED_FINDING_STATUSES
        and not (attestation and attestation.strip())
    ):
        raise StateError(f"Status {status} requires a non-empty attestation.")

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
        return PlanState.from_dict(payload)
    except (TypeError, ValueError) as exc:
        raise StateError(
            f"Invalid plan state at {path}: payload does not match PlanState."
        ) from exc


def set_plan_focus(
    plan_path: Path,
    findings_path: Path,
    *,
    target: str,
    updated_at: datetime,
) -> PlanState:
    plan = load_plan(plan_path)
    latest = latest_events_by_id(load_findings_history(findings_path))
    if not any(_is_actionable_event(event) for event in latest.values()):
        raise StateError("Cannot focus a plan with no actionable findings.")

    focus_id: str | None = None
    deferred_items = list(plan.deferred_items)
    target_event = latest.get(target)
    if target_event is not None:
        if not _is_actionable_event(target_event):
            raise StateError(f"Cannot focus non-actionable finding: {target}.")
        focus_id = target
    elif target in plan.clusters:
        cluster_ids = set(plan.clusters[target])
        candidate_ids = [
            finding_id
            for finding_id in _ordered_actionable_ids(plan, latest)
            if finding_id in cluster_ids
        ]
        if not candidate_ids:
            candidate_ids = [
                finding_id
                for finding_id in _ordered_actionable_ids(
                    plan,
                    latest,
                    include_deferred=True,
                )
                if finding_id in cluster_ids
            ]
        if not candidate_ids:
            raise StateError(
                f"Cannot focus cluster with no actionable findings: {target}."
            )
        focus_id = candidate_ids[0]
    else:
        raise StateError(f"Unknown focus target: {target}.")

    deferred_items = [finding_id for finding_id in deferred_items if finding_id != focus_id]
    return _write_plan_state(
        plan_path,
        _copy_plan_state(
            plan,
            updated_at=updated_at,
            current_focus=focus_id,
            deferred_items=deferred_items,
        ),
    )


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
    lifecycle_stage = "complete"
    if ordered_ids:
        if previous_plan is None:
            lifecycle_stage = "observe"
        elif previous_plan.lifecycle_stage == "complete":
            lifecycle_stage = "observe"
        else:
            lifecycle_stage = previous_plan.lifecycle_stage
    return PlanState(
        updated_at=scan_time.isoformat(timespec="seconds"),
        lifecycle_stage=lifecycle_stage,
        current_focus=current_focus,
        ordered_findings=ordered_ids,
        clusters=dict(clusters),
        deferred_items=deferred_items,
        last_scan_hash=scan_hash,
        stage_notes=(
            dict(previous_plan.stage_notes) if previous_plan is not None else {}
        ),
        strategy_text=previous_plan.strategy_text if previous_plan is not None else None,
    )


def compute_scan_hash(paths: list[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.encode("utf-8"))
    return digest.hexdigest()


def record_plan_triage_stage(
    plan_path: Path,
    *,
    stage: str,
    report: str,
    updated_at: datetime,
) -> PlanState:
    if stage not in TRIAGE_LIFECYCLE_STAGES:
        raise StateError(f"Unsupported triage stage: {stage}.")

    normalized_report = report.strip()
    if not normalized_report:
        raise StateError("Triage report must be a non-empty string.")

    plan = load_plan(plan_path)
    if not plan.ordered_findings:
        raise StateError(
            "Cannot record triage stages when there are no actionable findings."
        )

    if plan.lifecycle_stage not in PLAN_LIFECYCLE_STAGES:
        raise StateError(
            f"Cannot transition plan with unsupported lifecycle stage: {plan.lifecycle_stage}."
        )

    allowed_transitions = TRIAGE_STAGE_TRANSITIONS[plan.lifecycle_stage]
    if stage not in allowed_transitions:
        allowed = ", ".join(sorted(allowed_transitions))
        raise StateError(
            f"Cannot move plan triage from {plan.lifecycle_stage} to {stage}; "
            f"allowed stages: {allowed}."
        )

    updated_notes = dict(plan.stage_notes)
    updated_notes[stage] = normalized_report
    updated_plan = PlanState(
        updated_at=updated_at.isoformat(timespec="seconds"),
        lifecycle_stage=stage,
        current_focus=plan.current_focus,
        ordered_findings=list(plan.ordered_findings),
        clusters=dict(plan.clusters),
        deferred_items=list(plan.deferred_items),
        last_scan_hash=plan.last_scan_hash,
        stage_notes=updated_notes,
        strategy_text=plan.strategy_text,
    )
    return _write_plan_state(plan_path, updated_plan)


def record_plan_resolution(
    plan_path: Path,
    findings_path: Path,
    finding_id: str,
    *,
    status: str,
    event_at: datetime,
    attestation: str | None = None,
    resolved_by: str | None = None,
    resolution_note: str | None = None,
) -> tuple[dict[str, Any], PlanState]:
    if status not in PLAN_RESOLVE_FINDING_STATUSES:
        raise StateError(f"Unsupported plan resolve result: {status}.")

    event = append_finding_status_event(
        findings_path,
        finding_id,
        status=status,
        event_at=event_at,
        attestation=attestation,
        resolved_by=resolved_by,
        resolution_note=resolution_note,
    )
    plan = load_plan(plan_path)
    latest = latest_events_by_id(load_findings_history(findings_path))
    deferred_items = [
        queued_id for queued_id in plan.deferred_items if queued_id != finding_id
    ]

    next_focus: str | None
    if status in ACTIONABLE_FINDING_STATUSES:
        next_focus = finding_id
    else:
        current_focus = (
            plan.current_focus
            if plan.current_focus != finding_id
            and plan.current_focus not in deferred_items
            and plan.current_focus in latest
            and _is_actionable_event(latest[plan.current_focus])
            else None
        )
        candidate_plan = _copy_plan_state(
            plan,
            updated_at=event_at,
            current_focus=current_focus,
            deferred_items=deferred_items,
        )
        ordered_actionable_ids = _ordered_actionable_ids(candidate_plan, latest)
        next_focus = current_focus or (
            ordered_actionable_ids[0] if ordered_actionable_ids else None
        )

    updated_plan = _copy_plan_state(
        plan,
        updated_at=event_at,
        current_focus=next_focus,
        deferred_items=deferred_items,
    )
    return event, _write_plan_state(plan_path, updated_plan)


def reopen_plan_finding(
    plan_path: Path,
    findings_path: Path,
    finding_id: str,
    *,
    event_at: datetime,
    resolved_by: str | None = None,
    resolution_note: str | None = None,
) -> tuple[dict[str, Any], PlanState]:
    latest = latest_events_by_id(load_findings_history(findings_path))
    prior = latest.get(finding_id)
    if prior is None:
        raise StateError(f"Cannot update unknown finding: {finding_id}.")
    if prior.get("status") not in REOPENABLE_FINDING_STATUSES:
        raise StateError(
            f"Cannot reopen finding with status {prior.get('status')}: {finding_id}."
        )

    event = append_finding_status_event(
        findings_path,
        finding_id,
        status="open",
        event_at=event_at,
        resolved_by=resolved_by,
        resolution_note=resolution_note,
    )
    plan = load_plan(plan_path)
    updated_plan = _copy_plan_state(
        plan,
        updated_at=event_at,
        current_focus=finding_id,
        deferred_items=[
            queued_id for queued_id in plan.deferred_items if queued_id != finding_id
        ],
    )
    return event, _write_plan_state(plan_path, updated_plan)
