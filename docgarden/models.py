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
RESOLVED_FINDING_STATUSES = frozenset(
    {"fixed", "accepted_debt", "needs_human", "false_positive"}
)


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


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
