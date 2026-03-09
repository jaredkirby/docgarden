from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .markdown import parse_document
from .scanner import discover_markdown_files, scan_repo
from .errors import StateError
from .files import atomic_write_text
from .models import (
    ACTIONABLE_FINDING_STATUSES,
    ATTESTATION_REQUIRED_FINDING_STATUSES,
    AUTO_RESOLVED_FINDING_STATUSES,
    FINDING_SOURCES,
    FINDING_STATUSES,
    PLAN_RESOLVE_FINDING_STATUSES,
    REOPENED_ON_OBSERVATION_STATUSES,
    REOPENABLE_FINDING_STATUSES,
    REVIEW_FINDING_CONFIDENCE,
    REVIEW_FINDING_SEVERITIES,
    REVIEW_PACKET_FORMAT_VERSION,
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
REVIEW_PACKET_PREFIX = "review-packet-"
REVIEW_IMPORT_PREFIX = "review-import-"
REVIEW_FINDING_KIND = "subjective-review"
REVIEW_FINDING_CLUSTER = "subjective-review"
REVIEW_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


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


def _is_mechanical_event(event: dict[str, Any]) -> bool:
    source = str(event.get("finding_source", "mechanical"))
    return source == "mechanical"


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


def _ensure_actionable_queue_finding(
    plan: PlanState,
    latest: dict[str, dict[str, Any]],
    finding_id: str,
) -> None:
    prior = latest.get(finding_id)
    if prior is None:
        raise StateError(f"Cannot update unknown finding: {finding_id}.")
    if not _is_actionable_event(prior):
        raise StateError(f"Cannot resolve non-actionable finding: {finding_id}.")

    queued_ids = set(_ordered_actionable_ids(plan, latest, include_deferred=True))
    if finding_id not in queued_ids:
        raise StateError(f"Cannot resolve finding outside the current queue: {finding_id}.")


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
        if not _is_mechanical_event(prior):
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
    atomic_write_text(path, json.dumps(_json_ready(payload), indent=2, sort_keys=True) + "\n")


def write_score(path: Path, scorecard: Scorecard) -> None:
    write_json(path, asdict(scorecard))


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(_json_ready(payload), sort_keys=True, separators=(",", ":"))


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return value


def _review_dir(state_dir: Path) -> Path:
    return state_dir / "reviews"


def _stable_review_token(value: str) -> str:
    normalized = value.strip()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-") or "item"
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    return f"{slug[:48]}-{digest}"


def _review_packet_path(review_dir: Path, packet_id: str) -> Path:
    return review_dir / f"{REVIEW_PACKET_PREFIX}{packet_id}.json"


def _review_import_path(review_dir: Path, review_id: str) -> Path:
    return review_dir / f"{REVIEW_IMPORT_PREFIX}{review_id}.json"


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
        return Scorecard.from_dict(payload)
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


def prepare_review_packet(
    repo_root: Path,
    state_dir: Path,
    *,
    domains: list[str] | None = None,
) -> tuple[Path, dict[str, Any]]:
    normalized_domains = sorted(
        {domain.strip() for domain in (domains or []) if domain.strip()}
    )
    findings, _, documents = scan_repo(repo_root)
    selected_documents = [
        document
        for document in documents
        if document.rel_path.startswith("docs/")
        and document.frontmatter
        and (
            not normalized_domains
            or str(document.frontmatter.get("domain", "")) in normalized_domains
        )
    ]
    if not selected_documents:
        scope = ", ".join(normalized_domains) if normalized_domains else "all docs"
        raise StateError(f"No documents matched review packet scope: {scope}.")

    selected_paths = {document.rel_path for document in selected_documents}
    selected_findings = [
        finding
        for finding in findings
        if any(path in selected_paths for path in finding.files)
    ]
    mechanical_findings = [
        {
            "id": finding.id,
            "kind": finding.kind,
            "severity": finding.severity,
            "domain": finding.domain,
            "files": list(finding.files),
            "summary": finding.summary,
            "evidence": list(finding.evidence),
            "recommended_action": finding.recommended_action,
            "safe_to_autofix": finding.safe_to_autofix,
            "cluster": finding.cluster,
            "confidence": finding.confidence,
            "finding_source": "mechanical",
        }
        for finding in sorted(selected_findings, key=lambda item: item.id)
    ]
    payload_without_id = {
        "format_version": REVIEW_PACKET_FORMAT_VERSION,
        "scope": {
            "domains": normalized_domains,
            "documents": [document.rel_path for document in selected_documents],
        },
        "documents": [
            {
                "rel_path": document.rel_path,
                "doc_id": document.frontmatter.get("doc_id"),
                "domain": document.frontmatter.get("domain"),
                "doc_type": document.frontmatter.get("doc_type"),
                "status": document.frontmatter.get("status"),
                "frontmatter": document.frontmatter,
                "headings": document.headings,
                "links": document.links,
                "routed_paths": document.routed_paths,
                "raw_text": document.raw_text,
            }
            for document in sorted(selected_documents, key=lambda item: item.rel_path)
        ],
        "mechanical_findings": mechanical_findings,
    }
    packet_id = hashlib.sha256(
        _canonical_json(payload_without_id).encode("utf-8")
    ).hexdigest()[:16]
    payload = {"packet_id": packet_id, **payload_without_id}

    review_dir = _review_dir(state_dir)
    review_dir.mkdir(parents=True, exist_ok=True)
    packet_path = _review_packet_path(review_dir, packet_id)
    write_json(packet_path, payload)
    return packet_path, payload


def _require_string(
    value: Any,
    *,
    field_name: str,
    context: str,
) -> str:
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized
    raise StateError(f"{context} must provide a non-empty `{field_name}` string.")


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _require_string_list(
    value: Any,
    *,
    field_name: str,
    context: str,
) -> list[str]:
    if not isinstance(value, list) or not value:
        raise StateError(f"{context} must provide a non-empty `{field_name}` list.")
    normalized = [
        item.strip() for item in value if isinstance(item, str) and item.strip()
    ]
    if len(normalized) != len(value):
        raise StateError(
            f"{context} must provide `{field_name}` as non-empty strings only."
        )
    return normalized


def _require_review_packet(packet_path: Path, packet_id: str) -> dict[str, Any]:
    packet_payload = _load_state_object(packet_path, label="review packet")
    format_version = packet_payload.get("format_version")
    if format_version != REVIEW_PACKET_FORMAT_VERSION:
        raise StateError(
            f"Unsupported review packet format at {packet_path}: {format_version}."
        )
    stored_packet_id = packet_payload.get("packet_id")
    if stored_packet_id != packet_id:
        raise StateError(
            f"Review packet mismatch at {packet_path}: expected `{packet_id}`."
        )
    return packet_payload


def _packet_document_index(packet_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_documents = packet_payload.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise StateError("Review packet must contain a non-empty `documents` list.")

    document_index: dict[str, dict[str, Any]] = {}
    for index, raw_document in enumerate(raw_documents, start=1):
        context = f"Review packet document {index}"
        if not isinstance(raw_document, dict):
            raise StateError(f"{context} must be a JSON object.")
        rel_path = _require_string(
            raw_document.get("rel_path"),
            field_name="rel_path",
            context=context,
        )
        domain = _require_string(
            raw_document.get("domain"),
            field_name="domain",
            context=context,
        )
        document_index[rel_path] = {"domain": domain}
    return document_index


def _normalize_review_import(
    payload: dict[str, Any],
    *,
    import_path: Path,
    packet_payload: dict[str, Any],
    imported_at: datetime,
) -> tuple[str, dict[str, Any], list[Finding]]:
    format_version = payload.get("format_version", REVIEW_PACKET_FORMAT_VERSION)
    if format_version != REVIEW_PACKET_FORMAT_VERSION:
        raise StateError(
            f"Unsupported review import format at {import_path}: {format_version}."
        )

    packet_id = _require_string(
        payload.get("packet_id"),
        field_name="packet_id",
        context=f"Review import {import_path}",
    )
    if packet_payload.get("packet_id") != packet_id:
        raise StateError(
            f"Review import {import_path} references packet `{packet_id}`, "
            "but the stored packet payload does not match."
        )

    provenance = payload.get("provenance")
    if not isinstance(provenance, dict) or not provenance:
        raise StateError(
            f"Review import {import_path} must provide a non-empty `provenance` object."
        )

    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list) or not raw_findings:
        raise StateError(
            f"Review import {import_path} must provide a non-empty `findings` list."
        )

    review_id = _optional_string(payload.get("review_id"))
    if review_id is None:
        review_id = hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()[:16]
    if not REVIEW_ID_RE.match(review_id):
        raise StateError(
            f"Review import {import_path} must use a filesystem-safe `review_id`."
        )

    packet_documents = _packet_document_index(packet_payload)
    normalized_findings: list[dict[str, Any]] = []
    imported_findings: list[Finding] = []
    seen_identifiers: set[str] = set()
    timestamp = imported_at.isoformat(timespec="seconds")

    for index, raw_finding in enumerate(raw_findings, start=1):
        context = f"Review import {import_path} finding {index}"
        if not isinstance(raw_finding, dict):
            raise StateError(f"{context} must be a JSON object.")
        identifier = _require_string(
            raw_finding.get("id") or raw_finding.get("identifier"),
            field_name="id",
            context=context,
        )
        if identifier in seen_identifiers:
            raise StateError(f"{context} repeats finding id `{identifier}`.")
        seen_identifiers.add(identifier)

        summary = _require_string(
            raw_finding.get("summary"),
            field_name="summary",
            context=context,
        )
        evidence = _require_string_list(
            raw_finding.get("evidence"),
            field_name="evidence",
            context=context,
        )
        recommended_action = _require_string(
            raw_finding.get("recommended_action") or raw_finding.get("suggestion"),
            field_name="recommended_action",
            context=context,
        )
        files = _require_string_list(
            raw_finding.get("files") or raw_finding.get("related_files"),
            field_name="files",
            context=context,
        )
        unknown_files = [path for path in files if path not in packet_documents]
        if unknown_files:
            unknown_display = ", ".join(sorted(unknown_files))
            raise StateError(
                f"{context} references files outside packet `{packet_id}`: "
                f"{unknown_display}."
            )

        severity = str(raw_finding.get("severity", "medium")).strip()
        if severity not in REVIEW_FINDING_SEVERITIES:
            raise StateError(
                f"{context} must use severity one of: "
                f"{', '.join(sorted(REVIEW_FINDING_SEVERITIES))}."
            )

        confidence = str(raw_finding.get("confidence", "medium")).strip()
        if confidence not in REVIEW_FINDING_CONFIDENCE:
            raise StateError(
                f"{context} must use confidence one of: "
                f"{', '.join(sorted(REVIEW_FINDING_CONFIDENCE))}."
            )

        explicit_domain = _optional_string(raw_finding.get("domain"))
        inferred_domains = {packet_documents[path]["domain"] for path in files}
        if explicit_domain is not None:
            if explicit_domain not in inferred_domains:
                allowed = ", ".join(sorted(inferred_domains))
                raise StateError(
                    f"{context} declared domain `{explicit_domain}`, but packet files map "
                    f"to: {allowed}."
                )
            domain = explicit_domain
        else:
            if len(inferred_domains) != 1:
                raise StateError(
                    f"{context} must declare `domain` when files span multiple domains."
                )
            domain = next(iter(inferred_domains))

        category = _optional_string(raw_finding.get("category"))
        normalized = {
            "id": identifier,
            "summary": summary,
            "severity": severity,
            "domain": domain,
            "files": files,
            "evidence": evidence,
            "recommended_action": recommended_action,
            "confidence": confidence,
        }
        if category is not None:
            normalized["category"] = category
        normalized_findings.append(normalized)

        detail_payload = {"imported_identifier": identifier}
        if category is not None:
            detail_payload["category"] = category

        imported_findings.append(
            Finding(
                id=(
                    f"{REVIEW_FINDING_KIND}::{review_id}::"
                    f"{_stable_review_token(identifier)}"
                ),
                kind=REVIEW_FINDING_KIND,
                severity=severity,
                domain=domain,
                status="open",
                files=files,
                summary=summary,
                evidence=evidence,
                recommended_action=recommended_action,
                safe_to_autofix=False,
                discovered_at=timestamp,
                cluster=REVIEW_FINDING_CLUSTER,
                confidence=confidence,
                finding_source="subjective_review",
                provenance={
                    "review_id": review_id,
                    "packet_id": packet_id,
                    "import_path": str(import_path),
                    "provenance": provenance,
                },
                details=detail_payload,
            )
        )

    stored_payload = {
        "format_version": REVIEW_PACKET_FORMAT_VERSION,
        "review_id": review_id,
        "packet_id": packet_id,
        "imported_at": timestamp,
        "source_file": str(import_path),
        "provenance": provenance,
        "findings": normalized_findings,
    }
    return review_id, stored_payload, imported_findings


def _append_imported_review_findings(
    findings_path: Path,
    findings: list[Finding],
    *,
    imported_at: datetime,
) -> None:
    latest = latest_events_by_id(load_findings_history(findings_path))
    timestamp = imported_at.isoformat(timespec="seconds")
    lines: list[str] = []
    for finding in findings:
        existing = latest.get(finding.id)
        if existing is not None:
            raise StateError(f"Review finding already exists: {finding.id}.")
        payload = asdict(finding)
        payload["event"] = "review_imported"
        payload["event_at"] = timestamp
        lines.append(json.dumps(payload, sort_keys=True))
    if lines:
        with findings_path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def rebuild_plan_from_findings(
    paths: RepoPaths,
    *,
    updated_at: datetime,
) -> PlanState:
    documents = [
        parse_document(path, paths.repo_root)
        for path in discover_markdown_files(paths.repo_root)
    ]
    latest = latest_events_by_id(load_findings_history(paths.findings))
    actionable_findings = actionable_findings_from_latest_events(latest)
    previous_plan = load_plan(paths.plan) if paths.plan.exists() else None
    plan = build_plan(
        actionable_findings,
        compute_scan_hash([document.rel_path for document in documents]),
        updated_at,
        previous_plan=previous_plan,
    )
    write_json(paths.plan, asdict(plan))
    return plan


def import_review(
    paths: RepoPaths,
    import_path: Path,
    *,
    imported_at: datetime,
) -> tuple[Path, dict[str, Any], list[Finding], PlanState]:
    payload = _load_state_object(import_path, label="review import")
    packet_id = _require_string(
        payload.get("packet_id"),
        field_name="packet_id",
        context=f"Review import {import_path}",
    )
    review_dir = _review_dir(paths.state_dir)
    review_dir.mkdir(parents=True, exist_ok=True)
    packet_path = _review_packet_path(review_dir, packet_id)
    if not packet_path.exists():
        raise StateError(
            f"Missing review packet for import at {import_path}: "
            f"expected {packet_path}."
        )

    packet_payload = _require_review_packet(packet_path, packet_id)
    review_id, stored_payload, findings = _normalize_review_import(
        payload,
        import_path=import_path,
        packet_payload=packet_payload,
        imported_at=imported_at,
    )
    if any(
        finding.finding_source not in FINDING_SOURCES
        or finding.finding_source != "subjective_review"
        for finding in findings
    ):
        raise StateError(
            "Imported review findings must use the `subjective_review` source."
        )

    stored_review_path = _review_import_path(review_dir, review_id)
    if stored_review_path.exists():
        raise StateError(f"Review already imported: {stored_review_path}.")

    write_json(stored_review_path, stored_payload)
    _append_imported_review_findings(
        paths.findings,
        findings,
        imported_at=imported_at,
    )
    plan = rebuild_plan_from_findings(paths, updated_at=imported_at)
    return stored_review_path, stored_payload, findings, plan


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

    plan = load_plan(plan_path)
    latest = latest_events_by_id(load_findings_history(findings_path))
    _ensure_actionable_queue_finding(plan, latest, finding_id)

    event = append_finding_status_event(
        findings_path,
        finding_id,
        status=status,
        event_at=event_at,
        attestation=attestation,
        resolved_by=resolved_by,
        resolution_note=resolution_note,
    )
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
