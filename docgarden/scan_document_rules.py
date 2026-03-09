from __future__ import annotations

from datetime import date
from datetime import datetime
from pathlib import Path

from .markdown import Document
from .models import Finding, FindingContext

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


def document_context(
    document: Document,
    *,
    discovered_at: str,
    confidence: str = "high",
) -> FindingContext:
    return FindingContext(
        rel_path=document.rel_path,
        domain=document_domain(document),
        discovered_at=discovered_at,
        confidence=confidence,
    )


def missing_frontmatter_finding(
    document: Document,
    *,
    discovered_at: str,
) -> Finding:
    context = document_context(document, discovered_at=discovered_at)
    return Finding.open_issue(
        context,
        kind="missing-frontmatter",
        severity="high",
        summary=f"{document.rel_path} is missing required frontmatter.",
        evidence=["Non-archive docs must declare metadata."],
        recommended_action="Add frontmatter with the required metadata contract.",
        safe_to_autofix=False,
        cluster="metadata-gaps",
        suffix="frontmatter",
    )


def missing_metadata_finding(
    document: Document,
    *,
    missing_metadata: list[str],
    discovered_at: str,
) -> Finding:
    context = document_context(document, discovered_at=discovered_at)
    return Finding.open_issue(
        context,
        kind="missing-metadata",
        severity="high",
        summary=f"{document.rel_path} is missing required metadata fields.",
        evidence=[f"Missing fields: {', '.join(missing_metadata)}"],
        recommended_action="Fill in the required frontmatter fields.",
        safe_to_autofix=False,
        cluster="metadata-gaps",
        suffix="metadata",
        details={"missing_metadata": missing_metadata},
    )


def invalid_status_finding(
    document: Document,
    *,
    status: str,
    discovered_at: str,
) -> Finding:
    context = document_context(document, discovered_at=discovered_at)
    return Finding.open_issue(
        context,
        kind="invalid-metadata",
        severity="medium",
        summary=f"{document.rel_path} uses an unsupported status value.",
        evidence=[f"status={status}"],
        recommended_action="Use one of the allowed status values.",
        safe_to_autofix=False,
        cluster="metadata-gaps",
        suffix="status",
    )


def missing_sections_finding(
    document: Document,
    *,
    missing_sections: list[str],
    discovered_at: str,
) -> Finding:
    context = document_context(document, discovered_at=discovered_at)
    return Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary=f"{document.rel_path} is missing required sections.",
        evidence=[f"Missing headings: {', '.join(missing_sections)}"],
        recommended_action="Add the missing required sections for this doc type.",
        safe_to_autofix=True,
        cluster="structure-gaps",
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
    context = document_context(document, discovered_at=discovered_at)
    return Finding.open_issue(
        context,
        kind="stale-review",
        severity="medium" if doc_type == "reference" else "high",
        summary=f"{document.rel_path} is past its review cycle.",
        evidence=[
            f"last_reviewed={review_date.isoformat()}",
            f"review_cycle_days={review_cycle_days}",
        ],
        recommended_action="Review the doc and update status or content.",
        safe_to_autofix=True,
        cluster="stale-docs",
        suffix="stale",
    )


def verified_without_sources_finding(
    document: Document,
    *,
    discovered_at: str,
) -> Finding:
    context = document_context(document, discovered_at=discovered_at)
    return Finding.open_issue(
        context,
        kind="verified-without-sources",
        severity="high",
        summary=f"{document.rel_path} is marked verified without trust metadata.",
        evidence=[
            "Canonical verified docs must declare source_of_truth and verification."
        ],
        recommended_action="Add trust metadata or lower the status.",
        safe_to_autofix=False,
        cluster="trust-gaps",
        suffix="trust",
    )


def broken_link_finding(
    document: Document,
    *,
    link: str,
    discovered_at: str,
) -> Finding:
    context = document_context(document, discovered_at=discovered_at)
    return Finding.open_issue(
        context,
        kind="broken-link",
        severity="medium",
        summary=f"{document.rel_path} links to a missing file.",
        evidence=[f"Broken link target: {link}"],
        recommended_action="Update or remove the broken link.",
        safe_to_autofix=False,
        cluster="routing-drift",
        suffix=f"link-{abs(hash(link))}",
    )


def generated_doc_contract_finding(
    document: Document,
    *,
    issues: list[str],
    discovered_at: str,
) -> Finding:
    context = document_context(document, discovered_at=discovered_at)
    return Finding.open_issue(
        context,
        kind="generated-doc-contract",
        severity="high",
        summary=(
            f"{document.rel_path} is missing required generated-doc provenance details."
        ),
        evidence=issues,
        recommended_action=(
            "Fill in the generated-doc provenance sections with a generation "
            "source, generated timestamp, upstream artifact path or script, "
            "and a runnable regeneration command."
        ),
        safe_to_autofix=False,
        cluster="artifact-drift",
        suffix="generated-contract",
        details={"issues": issues},
    )


def generated_doc_stale_finding(
    document: Document,
    *,
    generated_at: datetime,
    upstream_path: Path,
    upstream_mtime: datetime,
    discovered_at: str,
) -> Finding:
    context = document_context(document, discovered_at=discovered_at)
    return Finding.open_issue(
        context,
        kind="generated-doc-stale",
        severity="medium",
        summary=f"{document.rel_path} is older than its local upstream source.",
        evidence=[
            f"generated_timestamp={generated_at.isoformat()}",
            f"upstream_path={upstream_path}",
            f"upstream_mtime={upstream_mtime.isoformat()}",
        ],
        recommended_action=(
            "Regenerate the doc from the referenced local artifact or script, "
            "or update the provenance metadata if the source changed."
        ),
        safe_to_autofix=False,
        cluster="stale-docs",
        suffix="generated-stale",
    )
