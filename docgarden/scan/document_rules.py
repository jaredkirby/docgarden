from __future__ import annotations

from datetime import date
from datetime import datetime
from pathlib import Path

from ..markdown import Document
from ..models import Finding
from .findings import (
    FindingSpec,
    build_document_finding,
)

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
    return build_document_finding(
        document,
        FindingSpec(
            kind="missing-frontmatter",
            severity="high",
            summary=f"{document.rel_path} is missing required frontmatter.",
            evidence=["Non-archive docs must declare metadata."],
            recommended_action="Add frontmatter with the required metadata contract.",
            cluster="metadata-gaps",
            suffix="frontmatter",
        ),
        domain=document_domain(document),
        discovered_at=discovered_at,
    )


def missing_metadata_finding(
    document: Document,
    *,
    missing_metadata: list[str],
    metadata_updates: dict[str, object] | None,
    discovered_at: str,
) -> Finding:
    safe_to_autofix = bool(metadata_updates)
    return build_document_finding(
        document,
        FindingSpec(
            kind="missing-metadata",
            severity="high",
            summary=f"{document.rel_path} is missing required metadata fields.",
            evidence=[f"Missing fields: {', '.join(missing_metadata)}"],
            recommended_action="Fill in the required frontmatter fields.",
            safe_to_autofix=safe_to_autofix,
            cluster="metadata-gaps",
            suffix="metadata",
            details={
                "missing_metadata": missing_metadata,
                "metadata_updates": metadata_updates or {},
            },
        ),
        domain=document_domain(document),
        discovered_at=discovered_at,
    )


def invalid_status_finding(
    document: Document,
    *,
    status: str,
    discovered_at: str,
) -> Finding:
    return build_document_finding(
        document,
        FindingSpec(
            kind="invalid-metadata",
            severity="medium",
            summary=f"{document.rel_path} uses an unsupported status value.",
            evidence=[f"status={status}"],
            recommended_action="Use one of the allowed status values.",
            cluster="metadata-gaps",
            suffix="status",
        ),
        domain=document_domain(document),
        discovered_at=discovered_at,
    )


def missing_sections_finding(
    document: Document,
    *,
    missing_sections: list[str],
    discovered_at: str,
) -> Finding:
    return build_document_finding(
        document,
        FindingSpec(
            kind="missing-sections",
            severity="medium",
            summary=f"{document.rel_path} is missing required sections.",
            evidence=[f"Missing headings: {', '.join(missing_sections)}"],
            recommended_action="Add the missing required sections for this doc type.",
            safe_to_autofix=True,
            cluster="structure-gaps",
            suffix="sections",
            details={"missing_sections": missing_sections},
        ),
        domain=document_domain(document),
        discovered_at=discovered_at,
    )


def stale_review_finding(
    document: Document,
    *,
    review_date: date,
    review_cycle_days: int,
    discovered_at: str,
) -> Finding:
    doc_type = document.frontmatter.get("doc_type")
    return build_document_finding(
        document,
        FindingSpec(
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
        ),
        domain=document_domain(document),
        discovered_at=discovered_at,
    )


def verified_without_sources_finding(
    document: Document,
    *,
    discovered_at: str,
) -> Finding:
    return build_document_finding(
        document,
        FindingSpec(
            kind="verified-without-sources",
            severity="high",
            summary=f"{document.rel_path} is marked verified without trust metadata.",
            evidence=[
                "Canonical verified docs must declare source_of_truth and verification."
            ],
            recommended_action="Add trust metadata or lower the status.",
            cluster="trust-gaps",
            suffix="trust",
        ),
        domain=document_domain(document),
        discovered_at=discovered_at,
    )


def broken_link_finding(
    document: Document,
    *,
    link: str,
    replacement_link: str | None,
    discovered_at: str,
) -> Finding:
    evidence = [f"Broken link target: {link}"]
    recommended_action = "Update or remove the broken link."
    if replacement_link is not None:
        evidence.append(f"Deterministic replacement: {replacement_link}")
        recommended_action = f"Update the link to {replacement_link}."
    return build_document_finding(
        document,
        FindingSpec(
            kind="broken-link",
            severity="medium",
            summary=f"{document.rel_path} links to a missing file.",
            evidence=evidence,
            recommended_action=recommended_action,
            safe_to_autofix=replacement_link is not None,
            cluster="routing-drift",
            suffix=f"link-{abs(hash(link))}",
            details={
                "broken_link": link,
                "replacement_link": replacement_link,
            },
        ),
        domain=document_domain(document),
        discovered_at=discovered_at,
    )


def generated_doc_contract_finding(
    document: Document,
    *,
    issues: list[str],
    discovered_at: str,
) -> Finding:
    return build_document_finding(
        document,
        FindingSpec(
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
            cluster="artifact-drift",
            suffix="generated-contract",
            details={"issues": issues},
        ),
        domain=document_domain(document),
        discovered_at=discovered_at,
    )


def generated_doc_stale_finding(
    document: Document,
    *,
    generated_at: datetime,
    upstream_path: Path,
    upstream_mtime: datetime,
    discovered_at: str,
) -> Finding:
    return build_document_finding(
        document,
        FindingSpec(
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
            cluster="stale-docs",
            suffix="generated-stale",
        ),
        domain=document_domain(document),
        discovered_at=discovered_at,
    )
