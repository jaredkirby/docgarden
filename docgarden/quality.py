from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .files import atomic_write_text
from .markdown import replace_frontmatter, split_frontmatter
from .models import Finding, Scorecard

DIMENSION_WEIGHTS = {
    "Structure & metadata": 15,
    "Freshness": 15,
    "Linking & discoverability": 15,
    "Coverage": 10,
    "Alignment to artifacts": 25,
    "Verification & trust": 20,
}

SEVERITY_PENALTIES = {"low": 3, "medium": 8, "high": 15}


def build_scorecard(
    findings: list[Finding],
    domain_doc_counts: dict[str, int],
    now: datetime,
) -> Scorecard:
    by_dimension: dict[str, list[Finding]] = defaultdict(list)
    by_domain: dict[str, list[Finding]] = defaultdict(list)

    dimension_map = {
        "missing-frontmatter": "Structure & metadata",
        "missing-metadata": "Structure & metadata",
        "duplicate-doc-id": "Structure & metadata",
        "missing-sections": "Coverage",
        "stale-review": "Freshness",
        "broken-link": "Linking & discoverability",
        "broken-route": "Linking & discoverability",
        "orphan-doc": "Linking & discoverability",
        "verified-without-sources": "Verification & trust",
        "invalid-metadata": "Structure & metadata",
        "missing-source-artifact": "Alignment to artifacts",
        "invalid-validation-command": "Alignment to artifacts",
    }

    for finding in findings:
        dimension = dimension_map.get(finding.kind, "Alignment to artifacts")
        by_dimension[dimension].append(finding)
        by_domain[finding.domain].append(finding)

    dimensions: dict[str, int] = {}
    strict_dimensions: dict[str, int] = {}
    for name in DIMENSION_WEIGHTS:
        findings_for_dimension = by_dimension.get(name, [])
        score = 100
        strict_score = 100
        for finding in findings_for_dimension:
            penalty = SEVERITY_PENALTIES.get(finding.severity, 3)
            if finding.status != "accepted_debt":
                score -= penalty
            strict_score -= penalty
        dimensions[name] = max(0, score)
        strict_dimensions[name] = max(0, strict_score)

    overall = round(
        sum(dimensions[name] * weight for name, weight in DIMENSION_WEIGHTS.items())
        / sum(DIMENSION_WEIGHTS.values())
    )
    strict = round(
        sum(
            strict_dimensions[name] * weight
            for name, weight in DIMENSION_WEIGHTS.items()
        )
        / sum(DIMENSION_WEIGHTS.values())
    )

    domains: dict[str, dict[str, Any]] = {}
    for domain, count in domain_doc_counts.items():
        domain_findings = by_domain.get(domain, [])
        penalties = sum(
            SEVERITY_PENALTIES.get(item.severity, 3) for item in domain_findings
        )
        score = max(0, 100 - penalties)
        trust_label = (
            "high trust" if score >= 90 else "good" if score >= 75 else "needs work"
        )
        if any(item.kind == "stale-review" for item in domain_findings):
            trust_label = "stale review window exceeded"
        domains[domain] = {
            "score": score,
            "status": trust_label,
            "doc_count": count,
            "findings": len(domain_findings),
        }

    top_gaps = [
        finding.summary
        for finding in sorted(
            findings,
            key=lambda item: (
                {"high": 0, "medium": 1, "low": 2}.get(item.severity, 3),
                item.id,
            ),
        )[:5]
    ]

    return Scorecard(
        updated_at=now.isoformat(timespec="seconds"),
        overall_score=overall,
        strict_score=strict,
        dimensions=dimensions,
        domains=domains,
        top_gaps=top_gaps,
        trend={"points": []},
    )


def render_quality_markdown(scorecard: Scorecard) -> str:
    lines = [
        "# Quality Score",
        "",
        f"Updated: {scorecard.updated_at[:10]}",
        "",
        "## Repo Summary",
        f"- Overall: {scorecard.overall_score}",
        f"- Strict: {scorecard.strict_score}",
        "",
        "## Domains",
    ]
    for domain, data in sorted(scorecard.domains.items()):
        lines.append(f"- {domain}: {data['score']} ({data['status']})")
    lines.extend(["", "## Top Gaps"])
    if scorecard.top_gaps:
        for index, gap in enumerate(scorecard.top_gaps, start=1):
            lines.append(f"{index}. {gap}")
    else:
        lines.append("1. No open findings.")
    lines.extend(["", "## Dimensions"])
    for name, score in scorecard.dimensions.items():
        lines.append(f"- {name}: {score}")
    return "\n".join(lines) + "\n"


def write_quality_score(path: Path, scorecard: Scorecard) -> None:
    body = render_quality_markdown(scorecard)
    if path.exists():
        raw = path.read_text()
        frontmatter, _ = split_frontmatter(raw)
        if frontmatter:
            frontmatter["last_reviewed"] = scorecard.updated_at[:10]
            atomic_write_text(path, replace_frontmatter(body, frontmatter))
            return
    atomic_write_text(path, body)
