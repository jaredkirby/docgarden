from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from ..markdown import Document
from ..models import Finding, FindingContext


@dataclass(frozen=True, slots=True)
class FindingSpec:
    kind: str
    severity: str
    summary: str
    evidence: list[str]
    recommended_action: str
    cluster: str
    suffix: str
    safe_to_autofix: bool = False
    details: dict[str, Any] = field(default_factory=dict)


def build_finding(
    spec: FindingSpec,
    *,
    rel_path: str,
    domain: str,
    discovered_at: str,
    confidence: str = "high",
    files: list[str] | None = None,
) -> Finding:
    return Finding.open_issue(
        FindingContext(
            rel_path=rel_path,
            domain=domain,
            discovered_at=discovered_at,
            confidence=confidence,
            files=list(files) if files is not None else [],
        ),
        kind=spec.kind,
        severity=spec.severity,
        summary=spec.summary,
        evidence=list(spec.evidence),
        recommended_action=spec.recommended_action,
        safe_to_autofix=spec.safe_to_autofix,
        cluster=spec.cluster,
        suffix=spec.suffix,
        details=deepcopy(spec.details),
    )


def build_document_finding(
    document: Document,
    spec: FindingSpec,
    *,
    discovered_at: str,
    domain: str,
    confidence: str = "high",
    files: list[str] | None = None,
) -> Finding:
    resolved_files = list(files) if files is not None else [document.rel_path]
    return build_finding(
        spec,
        rel_path=document.rel_path,
        domain=domain,
        discovered_at=discovered_at,
        confidence=confidence,
        files=resolved_files,
    )
