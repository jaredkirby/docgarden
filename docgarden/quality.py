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
TREND_POINT_LIMIT = 20
FINDING_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _score_delta(previous: int | None, current: int) -> int | None:
    if previous is None:
        return None
    return current - previous


def _format_delta(delta: int | None) -> str:
    if delta is None:
        return "n/a"
    if delta > 0:
        return f"+{delta}"
    return str(delta)


def _domain_score(domain_payload: dict[str, Any] | None) -> int | None:
    if not isinstance(domain_payload, dict):
        return None
    score = domain_payload.get("score")
    return score if isinstance(score, int) else None


def _weighted_rollup(
    domains: dict[str, dict[str, Any]],
    domain_weights: dict[str, int | float] | None,
) -> tuple[int, int, dict[str, int | float]]:
    configured_weights = domain_weights or {}
    weights_used: dict[str, int | float] = {}
    weighted_total = 0.0
    total_weight = 0.0
    raw_scores: list[int] = []

    for domain, payload in sorted(domains.items()):
        score = _domain_score(payload)
        if score is None:
            continue
        weight = configured_weights.get(domain, 1)
        if not isinstance(weight, (int, float)) or weight < 0:
            weight = 1
        weights_used[domain] = weight
        raw_scores.append(score)
        if weight == 0:
            continue
        weighted_total += score * weight
        total_weight += weight

    raw_average = round(sum(raw_scores) / len(raw_scores)) if raw_scores else 100
    if total_weight <= 0:
        return raw_average, raw_average, weights_used
    return round(weighted_total / total_weight), raw_average, weights_used


def _trend_points(previous_score: Scorecard | None) -> list[dict[str, Any]]:
    if previous_score is None:
        return []
    trend = previous_score.trend if isinstance(previous_score.trend, dict) else {}
    points = trend.get("points")
    if not isinstance(points, list):
        return []
    return [point for point in points if isinstance(point, dict)]


def _previous_weighted_rollup(
    previous_score: Scorecard | None,
    domain_weights: dict[str, int | float] | None,
) -> int | None:
    if previous_score is None:
        return None
    weighted_score = previous_score.rollup.get("weighted_score")
    if isinstance(weighted_score, int):
        return weighted_score
    previous_domains = (
        previous_score.domains if isinstance(previous_score.domains, dict) else {}
    )
    computed_weighted_score, _, _ = _weighted_rollup(previous_domains, domain_weights)
    return computed_weighted_score


def _critical_regressions(
    *,
    current_domains: dict[str, dict[str, Any]],
    previous_score: Scorecard | None,
    critical_domains: list[str] | None,
) -> list[dict[str, Any]]:
    if previous_score is None or not critical_domains:
        return []

    regressions: list[dict[str, Any]] = []
    previous_domains = (
        previous_score.domains if isinstance(previous_score.domains, dict) else {}
    )
    for domain in critical_domains:
        current_score = _domain_score(current_domains.get(domain))
        previous_domain_score = _domain_score(previous_domains.get(domain))
        if current_score is None or previous_domain_score is None:
            continue
        if current_score >= previous_domain_score:
            continue
        regressions.append(
            {
                "domain": domain,
                "score": current_score,
                "previous_score": previous_domain_score,
                "delta": current_score - previous_domain_score,
            }
        )
    regressions.sort(key=lambda item: (item["delta"], item["domain"]))
    return regressions


def build_scorecard(
    findings: list[Finding],
    domain_doc_counts: dict[str, int],
    now: datetime,
    *,
    previous_score: Scorecard | None = None,
    critical_domains: list[str] | None = None,
    domain_weights: dict[str, int | float] | None = None,
) -> Scorecard:
    by_dimension: dict[str, list[Finding]] = defaultdict(list)
    by_domain: dict[str, list[Finding]] = defaultdict(list)

    dimension_map = {
        "missing-frontmatter": "Structure & metadata",
        "missing-metadata": "Structure & metadata",
        "duplicate-doc-id": "Structure & metadata",
        "missing-sections": "Coverage",
        "stale-review": "Freshness",
        "generated-doc-stale": "Freshness",
        "broken-link": "Linking & discoverability",
        "broken-route": "Linking & discoverability",
        "orphan-doc": "Linking & discoverability",
        "verified-without-sources": "Verification & trust",
        "invalid-metadata": "Structure & metadata",
        "missing-source-artifact": "Alignment to artifacts",
        "invalid-validation-command": "Alignment to artifacts",
        "generated-doc-contract": "Alignment to artifacts",
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
                FINDING_SEVERITY_ORDER.get(item.severity, 3),
                item.id,
            ),
        )[:5]
    ]

    weighted_rollup, raw_average, weights_used = _weighted_rollup(
        domains,
        domain_weights,
    )
    critical_regressions = _critical_regressions(
        current_domains=domains,
        previous_score=previous_score,
        critical_domains=critical_domains,
    )
    previous_weighted_rollup = _previous_weighted_rollup(previous_score, domain_weights)

    trend_points = _trend_points(previous_score)
    trend_points.append(
        {
            "updated_at": now.isoformat(timespec="seconds"),
            "overall_score": overall,
            "strict_score": strict,
            "weighted_domain_rollup": weighted_rollup,
            "critical_regressions": [item["domain"] for item in critical_regressions],
        }
    )
    trend_points = trend_points[-TREND_POINT_LIMIT:]

    trend_summary = {
        "overall_delta": _score_delta(
            previous_score.overall_score if previous_score is not None else None,
            overall,
        ),
        "strict_delta": _score_delta(
            previous_score.strict_score if previous_score is not None else None,
            strict,
        ),
        "weighted_rollup_delta": _score_delta(previous_weighted_rollup, weighted_rollup),
    }

    return Scorecard(
        updated_at=now.isoformat(timespec="seconds"),
        overall_score=overall,
        strict_score=strict,
        dimensions=dimensions,
        domains=domains,
        top_gaps=top_gaps,
        trend={"points": trend_points, "summary": trend_summary},
        rollup={
            "weighted_score": weighted_rollup,
            "raw_average_score": raw_average,
            "weights": weights_used,
            "critical_regressions": critical_regressions,
        },
    )


def render_quality_markdown(scorecard: Scorecard) -> str:
    trend_summary = scorecard.trend.get("summary", {})
    weighted_rollup = scorecard.rollup.get("weighted_score")
    raw_average_score = scorecard.rollup.get("raw_average_score")
    critical_regressions = scorecard.rollup.get("critical_regressions", [])

    lines = [
        "# Quality Score",
        "",
        f"Updated: {scorecard.updated_at[:10]}",
        "",
        "## Repo Summary",
        f"- Overall: {scorecard.overall_score}",
        f"- Strict: {scorecard.strict_score}",
        f"- Weighted domain rollup: {weighted_rollup}",
        f"- Raw domain average: {raw_average_score}",
        (
            "- Overall drift vs previous scan: "
            f"{_format_delta(trend_summary.get('overall_delta'))}"
        ),
        (
            "- Strict drift vs previous scan: "
            f"{_format_delta(trend_summary.get('strict_delta'))}"
        ),
        (
            "- Weighted rollup drift vs previous scan: "
            f"{_format_delta(trend_summary.get('weighted_rollup_delta'))}"
        ),
        "",
        "## Critical-Domain Regressions",
    ]
    if critical_regressions:
        for item in critical_regressions:
            lines.append(
                "- "
                f"{item['domain']}: {item['score']} "
                f"({_format_delta(item['delta'])} from {item['previous_score']})"
            )
    else:
        lines.append("- None in this scan.")

    lines.extend(
        [
            "",
            "## Trend",
        ]
    )
    recent_points = scorecard.trend.get("points", [])
    if recent_points:
        for point in recent_points[-5:]:
            regressions = point.get("critical_regressions") or []
            regression_summary = (
                f"; critical regressions: {', '.join(regressions)}"
                if regressions
                else ""
            )
            lines.append(
                "- "
                f"{str(point.get('updated_at', ''))}: "
                f"overall {point.get('overall_score')}, "
                f"strict {point.get('strict_score')}, "
                f"weighted rollup {point.get('weighted_domain_rollup')}"
                f"{regression_summary}"
            )
    else:
        lines.append("- No trend points yet.")

    lines.extend(
        [
            "",
            "## Domains",
        ]
    )
    for domain, data in sorted(scorecard.domains.items()):
        weight = scorecard.rollup.get("weights", {}).get(domain, 1)
        lines.append(
            f"- {domain}: {data['score']} ({data['status']}, weight: {weight})"
        )
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
