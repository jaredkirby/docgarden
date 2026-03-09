from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
FINDING_SOURCES = frozenset({"mechanical", "subjective_review"})
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
PLAN_RESOLVE_FINDING_STATUSES = (
    "in_progress",
    "fixed",
    "accepted_debt",
    "needs_human",
    "false_positive",
)
REOPENABLE_FINDING_STATUSES = frozenset(
    {"fixed", "accepted_debt", "false_positive"}
)
PLAN_LIFECYCLE_STAGES = frozenset({"observe", "reflect", "organize", "complete"})
TRIAGE_LIFECYCLE_STAGES = ("observe", "reflect", "organize")
REVIEW_PACKET_FORMAT_VERSION = 1
REVIEW_FINDING_SEVERITIES = frozenset({"high", "medium", "low"})
REVIEW_FINDING_CONFIDENCE = frozenset({"high", "medium", "low"})


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
    finding_source: str = "mechanical"
    provenance: dict[str, Any] = field(default_factory=dict)
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
            finding_source="mechanical",
            details=details or {},
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Finding":
        details = payload.get("details")
        provenance = payload.get("provenance")
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
            finding_source=str(payload.get("finding_source", "mechanical")),
            provenance=provenance if isinstance(provenance, dict) else {},
            details=details if isinstance(details, dict) else {},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FindingRecord:
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
    finding_source: str = "mechanical"
    provenance: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    event: str | None = None
    event_at: str | None = None

    @classmethod
    def from_finding(
        cls,
        finding: Finding,
        *,
        event: str | None = None,
        event_at: str | None = None,
    ) -> "FindingRecord":
        return cls(
            id=finding.id,
            kind=finding.kind,
            severity=finding.severity,
            domain=finding.domain,
            status=finding.status,
            files=list(finding.files),
            summary=finding.summary,
            evidence=list(finding.evidence),
            recommended_action=finding.recommended_action,
            safe_to_autofix=finding.safe_to_autofix,
            discovered_at=finding.discovered_at,
            cluster=finding.cluster,
            confidence=finding.confidence,
            attestation=finding.attestation,
            resolved_by=finding.resolved_by,
            resolution_note=finding.resolution_note,
            resolved_at=finding.resolved_at,
            finding_source=finding.finding_source,
            provenance=dict(finding.provenance),
            details=dict(finding.details),
            event=event,
            event_at=event_at,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FindingRecord":
        finding = Finding.from_dict(payload)
        return cls(
            id=finding.id,
            kind=finding.kind,
            severity=finding.severity,
            domain=finding.domain,
            status=finding.status,
            files=list(finding.files),
            summary=finding.summary,
            evidence=list(finding.evidence),
            recommended_action=finding.recommended_action,
            safe_to_autofix=finding.safe_to_autofix,
            discovered_at=finding.discovered_at,
            cluster=finding.cluster,
            confidence=finding.confidence,
            attestation=finding.attestation,
            resolved_by=finding.resolved_by,
            resolution_note=finding.resolution_note,
            resolved_at=finding.resolved_at,
            finding_source=finding.finding_source,
            provenance=dict(finding.provenance),
            details=dict(finding.details),
            event=_optional_string(payload.get("event")),
            event_at=_optional_string(payload.get("event_at")),
        )

    def to_finding(self) -> Finding:
        return Finding(
            id=self.id,
            kind=self.kind,
            severity=self.severity,
            domain=self.domain,
            status=self.status,
            files=list(self.files),
            summary=self.summary,
            evidence=list(self.evidence),
            recommended_action=self.recommended_action,
            safe_to_autofix=self.safe_to_autofix,
            discovered_at=self.discovered_at,
            cluster=self.cluster,
            confidence=self.confidence,
            attestation=self.attestation,
            resolved_by=self.resolved_by,
            resolution_note=self.resolution_note,
            resolved_at=self.resolved_at,
            finding_source=self.finding_source,
            provenance=dict(self.provenance),
            details=dict(self.details),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DomainScore:
    score: int
    status: str
    doc_count: int
    findings: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DomainScore":
        return cls(
            score=int(payload.get("score", 0)),
            status=str(payload.get("status", "")),
            doc_count=int(payload.get("doc_count", 0)),
            findings=int(payload.get("findings", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CriticalRegression:
    domain: str
    score: int
    previous_score: int
    delta: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CriticalRegression":
        return cls(
            domain=str(payload.get("domain", "")),
            score=int(payload.get("score", 0)),
            previous_score=int(payload.get("previous_score", 0)),
            delta=int(payload.get("delta", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScoreTrendPoint:
    updated_at: str
    overall_score: int
    strict_score: int
    weighted_domain_rollup: int
    critical_regressions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScoreTrendPoint":
        return cls(
            updated_at=str(payload.get("updated_at", "")),
            overall_score=int(payload.get("overall_score", 0)),
            strict_score=int(payload.get("strict_score", 0)),
            weighted_domain_rollup=int(payload.get("weighted_domain_rollup", 0)),
            critical_regressions=_string_list(payload.get("critical_regressions")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScoreTrendSummary:
    overall_delta: int | None = None
    strict_delta: int | None = None
    weighted_rollup_delta: int | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScoreTrendSummary":
        return cls(
            overall_delta=(
                int(payload["overall_delta"])
                if isinstance(payload.get("overall_delta"), int)
                else None
            ),
            strict_delta=(
                int(payload["strict_delta"])
                if isinstance(payload.get("strict_delta"), int)
                else None
            ),
            weighted_rollup_delta=(
                int(payload["weighted_rollup_delta"])
                if isinstance(payload.get("weighted_rollup_delta"), int)
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScoreTrend:
    points: list[ScoreTrendPoint] = field(default_factory=list)
    summary: ScoreTrendSummary | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScoreTrend":
        raw_points = payload.get("points")
        points = []
        if isinstance(raw_points, list):
            points = [
                ScoreTrendPoint.from_dict(item)
                for item in raw_points
                if isinstance(item, dict)
            ]
        raw_summary = payload.get("summary")
        summary = (
            ScoreTrendSummary.from_dict(raw_summary)
            if isinstance(raw_summary, dict)
            else None
        )
        return cls(points=points, summary=summary)

    def to_dict(self) -> dict[str, Any]:
        payload = {"points": [point.to_dict() for point in self.points]}
        if self.summary is not None:
            payload["summary"] = self.summary.to_dict()
        return payload


@dataclass(slots=True)
class ScoreRollup:
    weighted_score: int | None = None
    raw_average_score: int | None = None
    weights: dict[str, int | float] = field(default_factory=dict)
    critical_regressions: list[CriticalRegression] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScoreRollup":
        raw_regressions = payload.get("critical_regressions")
        regressions = []
        if isinstance(raw_regressions, list):
            regressions = [
                CriticalRegression.from_dict(item)
                for item in raw_regressions
                if isinstance(item, dict)
            ]
        raw_weights = payload.get("weights")
        weights = {}
        if isinstance(raw_weights, dict):
            weights = {
                str(name): value
                for name, value in raw_weights.items()
                if isinstance(value, (int, float))
            }
        return cls(
            weighted_score=(
                int(payload["weighted_score"])
                if isinstance(payload.get("weighted_score"), int)
                else None
            ),
            raw_average_score=(
                int(payload["raw_average_score"])
                if isinstance(payload.get("raw_average_score"), int)
                else None
            ),
            weights=weights,
            critical_regressions=regressions,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "weighted_score": self.weighted_score,
            "raw_average_score": self.raw_average_score,
            "weights": dict(self.weights),
            "critical_regressions": [
                item.to_dict() for item in self.critical_regressions
            ],
        }


@dataclass(slots=True)
class Scorecard:
    updated_at: str
    overall_score: int
    strict_score: int
    dimensions: dict[str, int]
    domains: dict[str, DomainScore]
    top_gaps: list[str]
    trend: ScoreTrend = field(default_factory=ScoreTrend)
    rollup: ScoreRollup = field(default_factory=ScoreRollup)

    def __post_init__(self) -> None:
        self.domains = {
            name: (
                domain_payload
                if isinstance(domain_payload, DomainScore)
                else DomainScore.from_dict(domain_payload)
            )
            for name, domain_payload in self.domains.items()
        }
        if not isinstance(self.trend, ScoreTrend):
            self.trend = (
                ScoreTrend.from_dict(self.trend)
                if isinstance(self.trend, dict)
                else ScoreTrend()
            )
        if not isinstance(self.rollup, ScoreRollup):
            self.rollup = (
                ScoreRollup.from_dict(self.rollup)
                if isinstance(self.rollup, dict)
                else ScoreRollup()
            )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Scorecard":
        return cls(
            updated_at=str(payload["updated_at"]),
            overall_score=int(payload["overall_score"]),
            strict_score=int(payload["strict_score"]),
            dimensions={
                str(name): int(score)
                for name, score in dict(payload.get("dimensions", {})).items()
            },
            domains={
                str(name): DomainScore.from_dict(domain_payload)
                for name, domain_payload in dict(payload.get("domains", {})).items()
                if isinstance(domain_payload, dict)
            },
            top_gaps=_string_list(payload.get("top_gaps")),
            trend=ScoreTrend.from_dict(payload.get("trend", {}))
            if isinstance(payload.get("trend"), dict)
            else ScoreTrend(),
            rollup=ScoreRollup.from_dict(payload.get("rollup", {}))
            if isinstance(payload.get("rollup"), dict)
            else ScoreRollup(),
        )


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
    scorecard: Scorecard | None
    latest_events: dict[str, FindingRecord]
    scope: str = "all"
    changed_files_source: str | None = None
    requested_files: list[str] = field(default_factory=list)
    scanned_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    recomputed_views: list[str] = field(default_factory=list)
    skipped_views: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
