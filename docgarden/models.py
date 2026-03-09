from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


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
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def open_issue(
        cls,
        *,
        rel_path: str,
        kind: str,
        severity: str,
        domain: str,
        summary: str,
        evidence: list[str],
        recommended_action: str,
        safe_to_autofix: bool,
        discovered_at: str,
        cluster: str,
        confidence: str,
        suffix: str,
        details: dict[str, Any] | None = None,
    ) -> "Finding":
        path_token = "::".join(Path(rel_path).parts)
        return cls(
            id=f"{kind}::{path_token}::{suffix}",
            kind=kind,
            severity=severity,
            domain=domain,
            status="open",
            files=[rel_path],
            summary=summary,
            evidence=evidence,
            recommended_action=recommended_action,
            safe_to_autofix=safe_to_autofix,
            discovered_at=discovered_at,
            cluster=cluster,
            confidence=confidence,
            details=details or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Scorecard:
    updated_at: str
    overall_score: int
    strict_score: int
    dimensions: dict[str, int]
    domains: dict[str, dict[str, Any]]
    top_gaps: list[str]
    trend: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlanState:
    updated_at: str
    lifecycle_stage: str
    current_focus: str | None
    ordered_findings: list[str]
    clusters: dict[str, list[str]]
    deferred_items: list[str]
    last_scan_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
