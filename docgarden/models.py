from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FINDING_STATUSES = frozenset(
    {
        "open",
        "in_progress",
        "fixed",
        "accepted_debt",
        "needs_human",
        "false_positive",
    }
)
ACTIONABLE_FINDING_STATUSES = frozenset({"open", "in_progress", "needs_human"})
SCORE_RELEVANT_FINDING_STATUSES = frozenset(
    {"open", "in_progress", "accepted_debt", "needs_human"}
)
AUTO_RESOLVED_FINDING_STATUSES = frozenset(
    {"open", "in_progress", "accepted_debt", "needs_human"}
)
REOPENED_ON_OBSERVATION_STATUSES = frozenset({"fixed", "false_positive"})
ATTESTATION_REQUIRED_FINDING_STATUSES = frozenset(
    {"accepted_debt", "needs_human", "false_positive"}
)
RESOLVED_FINDING_STATUSES = frozenset({"fixed", "accepted_debt", "false_positive"})
PLAN_LIFECYCLE_STAGES = frozenset({"observe", "reflect", "organize", "complete"})
TRIAGE_LIFECYCLE_STAGES = ("observe", "reflect", "organize")


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str) and item
    }


@dataclass(frozen=True, slots=True)
class FindingContext:
    rel_path: str
    domain: str
    discovered_at: str
    confidence: str = "high"
    files: list[str] = field(default_factory=list)

    def finding_id(self, *, kind: str, suffix: str) -> str:
        path_token = "::".join(Path(self.rel_path).parts)
        return f"{kind}::{path_token}::{suffix}"

    def finding_files(self) -> list[str]:
        return list(self.files) if self.files else [self.rel_path]


@dataclass(slots=True)
class Finding:
    id: str
    kind: str
    severity: str
    domain: str
    status: str
    files: list[str]
    summary: str
    evidence: list[str]
    recommended_action: str
    safe_to_autofix: bool
    discovered_at: str
    cluster: str
    confidence: str
    attestation: str | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None
    resolved_at: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def open_issue(
        cls,
        context: FindingContext,
        *,
        kind: str,
        severity: str,
        summary: str,
        evidence: list[str],
        recommended_action: str,
        safe_to_autofix: bool,
        cluster: str,
        suffix: str,
        details: dict[str, Any] | None = None,
    ) -> "Finding":
        return cls(
            id=context.finding_id(kind=kind, suffix=suffix),
            kind=kind,
            severity=severity,
            domain=context.domain,
            status="open",
            files=context.finding_files(),
            summary=summary,
            evidence=evidence,
            recommended_action=recommended_action,
            safe_to_autofix=safe_to_autofix,
            discovered_at=context.discovered_at,
            cluster=cluster,
            confidence=context.confidence,
            details=details or {},
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Finding":
        details = payload.get("details")
        return cls(
            id=str(payload["id"]),
            kind=str(payload["kind"]),
            severity=str(payload["severity"]),
            domain=str(payload["domain"]),
            status=str(payload.get("status", "open")),
            files=_string_list(payload.get("files")),
            summary=str(payload["summary"]),
            evidence=_string_list(payload.get("evidence")),
            recommended_action=str(payload["recommended_action"]),
            safe_to_autofix=bool(payload.get("safe_to_autofix", False)),
            discovered_at=str(payload["discovered_at"]),
            cluster=str(payload["cluster"]),
            confidence=str(payload.get("confidence", "high")),
            attestation=_optional_string(payload.get("attestation")),
            resolved_by=_optional_string(payload.get("resolved_by")),
            resolution_note=_optional_string(payload.get("resolution_note")),
            resolved_at=_optional_string(payload.get("resolved_at")),
            details=details if isinstance(details, dict) else {},
        )


@dataclass(slots=True)
class Scorecard:
    updated_at: str
    overall_score: int
    strict_score: int
    dimensions: dict[str, int]
    domains: dict[str, dict[str, Any]]
    top_gaps: list[str]
    trend: dict[str, Any]


@dataclass(slots=True)
class PlanState:
    updated_at: str
    lifecycle_stage: str
    current_focus: str | None
    ordered_findings: list[str]
    clusters: dict[str, list[str]]
    deferred_items: list[str]
    last_scan_hash: str
    stage_notes: dict[str, str] = field(default_factory=dict)
    strategy_text: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlanState":
        lifecycle_stage = str(payload.get("lifecycle_stage", "complete"))
        if lifecycle_stage not in PLAN_LIFECYCLE_STAGES:
            raise ValueError(f"Unsupported plan lifecycle stage: {lifecycle_stage}.")

        stage_notes = {
            stage: note
            for stage, note in _string_dict(payload.get("stage_notes")).items()
            if stage in TRIAGE_LIFECYCLE_STAGES
        }

        return cls(
            updated_at=str(payload["updated_at"]),
            lifecycle_stage=lifecycle_stage,
            current_focus=_optional_string(payload.get("current_focus")),
            ordered_findings=_string_list(payload.get("ordered_findings")),
            clusters={
                cluster: _string_list(finding_ids)
                for cluster, finding_ids in _string_dict_list(
                    payload.get("clusters")
                ).items()
            },
            deferred_items=_string_list(payload.get("deferred_items")),
            last_scan_hash=str(payload["last_scan_hash"]),
            stage_notes=stage_notes,
            strategy_text=_optional_string(payload.get("strategy_text")),
        )


def _string_dict_list(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    return {
        key: _string_list(item)
        for key, item in value.items()
        if isinstance(key, str)
    }


@dataclass(slots=True)
class RepoPaths:
    repo_root: Path
    state_dir: Path
    config: Path
    findings: Path
    plan: Path
    score: Path
    quality: Path


@dataclass(slots=True)
class ScanRunResult:
    findings: list[Finding]
    scorecard: Scorecard
    latest_events: dict[str, dict[str, Any]]
