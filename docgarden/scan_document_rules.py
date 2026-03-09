from __future__ import annotations

from datetime import date

from .markdown import Document
from .models import Finding

REQUIRED_METADATA = {
    "doc_id",
    "doc_type",
    "domain",
    "owner",
    "status",
    "last_reviewed",
    "review_cycle_days",
}
ALLOWED_STATUS = {
    "verified",
    "draft",
    "needs-review",
    "stale",
    "deprecated",
    "archived",
}
REQUIRED_SECTIONS = {
    "canonical": [
        "Purpose",
        "Scope",
        "Source of Truth",
        "Rules / Definitions",
        "Exceptions / Caveats",
        "Validation / How to verify",
        "Related docs",
    ],
    "exec-plan": [
        "Purpose",
        "Context",
        "Assumptions",
        "Steps / Milestones",
        "Validation",
        "Progress",
        "Discoveries",
        "Decision Log",
        "Outcomes / Retrospective",
    ],
    "generated": [
        "Generation source",
        "Generated timestamp",
        "Upstream artifact path or script",
        "Regeneration command",
    ],
    "archive": [
        "Archived reason",
        "Archived date",
        "Replacement doc, if any",
    ],
}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def document_domain(document: Document) -> str:
    return str(document.frontmatter.get("domain", "unknown"))


def missing_frontmatter_finding(
    document: Document,
    *,
    discovered_at: str,
) -> Finding:
    return Finding.open_issue(
        rel_path=document.rel_path,
        kind="missing-frontmatter",
        severity="high",
        domain=document_domain(document),
        summary=f"{document.rel_path} is missing required frontmatter.",
        evidence=["Non-archive docs must declare metadata."],
        recommended_action="Add frontmatter with the required metadata contract.",
        safe_to_autofix=False,
        discovered_at=discovered_at,
        cluster="metadata-gaps",
        confidence="high",
        suffix="frontmatter",
    )


def missing_metadata_finding(
    document: Document,
    *,
    missing_metadata: list[str],
    discovered_at: str,
) -> Finding:
    return Finding.open_issue(
        rel_path=document.rel_path,
        kind="missing-metadata",
        severity="high",
        domain=document_domain(document),
        summary=f"{document.rel_path} is missing required metadata fields.",
        evidence=[f"Missing fields: {', '.join(missing_metadata)}"],
        recommended_action="Fill in the required frontmatter fields.",
        safe_to_autofix=False,
        discovered_at=discovered_at,
        cluster="metadata-gaps",
        confidence="high",
        suffix="metadata",
        details={"missing_metadata": missing_metadata},
    )


def invalid_status_finding(
    document: Document,
    *,
    status: str,
    discovered_at: str,
) -> Finding:
    return Finding.open_issue(
        rel_path=document.rel_path,
        kind="invalid-metadata",
        severity="medium",
        domain=document_domain(document),
        summary=f"{document.rel_path} uses an unsupported status value.",
        evidence=[f"status={status}"],
        recommended_action="Use one of the allowed status values.",
        safe_to_autofix=False,
        discovered_at=discovered_at,
        cluster="metadata-gaps",
        confidence="high",
        suffix="status",
    )


def missing_sections_finding(
    document: Document,
    *,
    missing_sections: list[str],
    discovered_at: str,
) -> Finding:
    return Finding.open_issue(
        rel_path=document.rel_path,
        kind="missing-sections",
        severity="medium",
        domain=document_domain(document),
        summary=f"{document.rel_path} is missing required sections.",
        evidence=[f"Missing headings: {', '.join(missing_sections)}"],
        recommended_action="Add the missing required sections for this doc type.",
        safe_to_autofix=True,
        discovered_at=discovered_at,
        cluster="structure-gaps",
        confidence="high",
        suffix="sections",
        details={"missing_sections": missing_sections},
    )


def stale_review_finding(
    document: Document,
    *,
    review_date: date,
    review_cycle_days: int,
    discovered_at: str,
) -> Finding:
    doc_type = document.frontmatter.get("doc_type")
    return Finding.open_issue(
        rel_path=document.rel_path,
        kind="stale-review",
        severity="medium" if doc_type == "reference" else "high",
        domain=document_domain(document),
        summary=f"{document.rel_path} is past its review cycle.",
        evidence=[
            f"last_reviewed={review_date.isoformat()}",
            f"review_cycle_days={review_cycle_days}",
        ],
        recommended_action="Review the doc and update status or content.",
        safe_to_autofix=True,
        discovered_at=discovered_at,
        cluster="stale-docs",
        confidence="high",
        suffix="stale",
    )


def verified_without_sources_finding(
    document: Document,
    *,
    discovered_at: str,
) -> Finding:
    return Finding.open_issue(
        rel_path=document.rel_path,
        kind="verified-without-sources",
        severity="high",
        domain=document_domain(document),
        summary=f"{document.rel_path} is marked verified without trust metadata.",
        evidence=[
            "Canonical verified docs must declare source_of_truth and verification."
        ],
        recommended_action="Add trust metadata or lower the status.",
        safe_to_autofix=False,
        discovered_at=discovered_at,
        cluster="trust-gaps",
        confidence="high",
        suffix="trust",
    )


def broken_link_finding(
    document: Document,
    *,
    link: str,
    discovered_at: str,
) -> Finding:
    return Finding.open_issue(
        rel_path=document.rel_path,
        kind="broken-link",
        severity="medium",
        domain=document_domain(document),
        summary=f"{document.rel_path} links to a missing file.",
        evidence=[f"Broken link target: {link}"],
        recommended_action="Update or remove the broken link.",
        safe_to_autofix=False,
        discovered_at=discovered_at,
        cluster="routing-drift",
        confidence="high",
        suffix=f"link-{abs(hash(link))}",
    )
