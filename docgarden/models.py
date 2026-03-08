from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
