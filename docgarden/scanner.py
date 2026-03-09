from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from .markdown import Document, normalize_heading, parse_document, resolve_link_target
from .models import Finding
from .scan_document_rules import (
    ALLOWED_STATUS,
    REQUIRED_METADATA,
    REQUIRED_SECTIONS,
    SEVERITY_ORDER,
    broken_link_finding,
    missing_frontmatter_finding,
    invalid_status_finding,
    missing_metadata_finding,
    missing_sections_finding,
    stale_review_finding,
    verified_without_sources_finding,
)
from .scan_linkage import (
    append_inbound_link,
    broken_route_findings,
    collect_domain_doc_counts,
    duplicate_doc_id_findings,
    orphan_doc_findings,
    scan_agents_document,
)


def discover_markdown_files(repo_root: Path) -> list[Path]:
    files = []
    agents = repo_root / "AGENTS.md"
    if agents.exists():
        files.append(agents)
    docs_root = repo_root / "docs"
    if docs_root.exists():
        files.extend(sorted(docs_root.rglob("*.md")))
    return files


def _parse_review_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _record_doc_id(document: Document, doc_id_counter: Counter[str]) -> None:
    doc_id = document.frontmatter.get("doc_id")
    if isinstance(doc_id, str) and doc_id:
        doc_id_counter[doc_id] += 1


def _metadata_findings(document: Document, *, discovered_at: str) -> list[Finding]:
    findings: list[Finding] = []
    missing_metadata = sorted(REQUIRED_METADATA - set(document.frontmatter))
    if missing_metadata:
        findings.append(
            missing_metadata_finding(
                document,
                missing_metadata=missing_metadata,
                discovered_at=discovered_at,
            )
        )

    status = document.frontmatter.get("status")
    if isinstance(status, str) and status not in ALLOWED_STATUS:
        findings.append(
            invalid_status_finding(
                document,
                status=status,
                discovered_at=discovered_at,
            )
        )
    return findings


def _section_findings(document: Document, *, discovered_at: str) -> list[Finding]:
    doc_type = document.frontmatter.get("doc_type")
    if doc_type not in REQUIRED_SECTIONS:
        return []

    existing = {normalize_heading(item) for item in document.headings}
    missing_sections = [
        section
        for section in REQUIRED_SECTIONS[doc_type]
        if normalize_heading(section) not in existing
    ]
    if not missing_sections:
        return []
    return [
        missing_sections_finding(
            document,
            missing_sections=missing_sections,
            discovered_at=discovered_at,
        )
    ]


def _freshness_findings(
    document: Document,
    *,
    now: datetime,
    discovered_at: str,
) -> list[Finding]:
    review_date = _parse_review_date(str(document.frontmatter.get("last_reviewed")))
    review_cycle = document.frontmatter.get("review_cycle_days")
    if not review_date or not isinstance(review_cycle, int):
        return []
    if review_date + timedelta(days=review_cycle) >= now.date():
        return []
    return [
        stale_review_finding(
            document,
            review_date=review_date,
            review_cycle_days=review_cycle,
            discovered_at=discovered_at,
        )
    ]


def _trust_findings(document: Document, *, discovered_at: str) -> list[Finding]:
    if document.frontmatter.get("doc_type") != "canonical":
        return []
    if document.frontmatter.get("status") != "verified":
        return []
    if document.frontmatter.get("source_of_truth") and document.frontmatter.get(
        "verification"
    ):
        return []
    return [
        verified_without_sources_finding(
            document,
            discovered_at=discovered_at,
        )
    ]


def _link_findings(
    document: Document,
    *,
    repo_root: Path,
    inbound_links: defaultdict[str, set[str]],
    routed_targets: defaultdict[str, set[str]],
    discovered_at: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for routed_path in document.routed_paths:
        routed_targets[routed_path].add(document.rel_path)

    for link in document.links:
        target = resolve_link_target(document.path, repo_root, link)
        if not target:
            continue
        if target.exists():
            append_inbound_link(repo_root, target, document.rel_path, inbound_links)
            continue
        findings.append(
            broken_link_finding(
                document,
                link=link,
                discovered_at=discovered_at,
            )
        )
    return findings


def _scan_document(
    document: Document,
    *,
    now: datetime,
    repo_root: Path,
    doc_id_counter: Counter[str],
    inbound_links: defaultdict[str, set[str]],
    routed_targets: defaultdict[str, set[str]],
    discovered_at: str,
) -> list[Finding]:
    if not document.frontmatter:
        return [missing_frontmatter_finding(document, discovered_at=discovered_at)]

    _record_doc_id(document, doc_id_counter)

    findings: list[Finding] = []
    findings.extend(_metadata_findings(document, discovered_at=discovered_at))
    findings.extend(_section_findings(document, discovered_at=discovered_at))
    findings.extend(_freshness_findings(document, now=now, discovered_at=discovered_at))
    findings.extend(_trust_findings(document, discovered_at=discovered_at))
    findings.extend(
        _link_findings(
            document,
            repo_root=repo_root,
            inbound_links=inbound_links,
            routed_targets=routed_targets,
            discovered_at=discovered_at,
        )
    )
    return findings


def scan_repo(repo_root: Path) -> tuple[list[Finding], dict[str, int], list[Document]]:
    now = datetime.now()
    discovered_at = now.isoformat(timespec="seconds")
    documents = [
        parse_document(path, repo_root) for path in discover_markdown_files(repo_root)
    ]
    findings: list[Finding] = []
    doc_id_counter: Counter[str] = Counter()
    inbound_links: defaultdict[str, set[str]] = defaultdict(set)
    routed_targets: defaultdict[str, set[str]] = defaultdict(set)

    for document in documents:
        if document.path.name == "AGENTS.md":
            scan_agents_document(
                document,
                repo_root=repo_root,
                inbound_links=inbound_links,
                routed_targets=routed_targets,
            )
            continue
        findings.extend(
            _scan_document(
                document,
                now=now,
                repo_root=repo_root,
                doc_id_counter=doc_id_counter,
                inbound_links=inbound_links,
                routed_targets=routed_targets,
                discovered_at=discovered_at,
            )
        )

    findings.extend(
        duplicate_doc_id_findings(
            documents,
            doc_id_counter,
            discovered_at=discovered_at,
        )
    )
    findings.extend(
        broken_route_findings(
            repo_root,
            routed_targets,
            inbound_links,
            discovered_at=discovered_at,
        )
    )
    findings.extend(
        orphan_doc_findings(
            documents,
            inbound_links,
            discovered_at=discovered_at,
        )
    )

    deduped: dict[str, Finding] = {}
    for finding in sorted(
        findings, key=lambda item: (SEVERITY_ORDER.get(item.severity, 3), item.id)
    ):
        deduped[finding.id] = finding
    return list(deduped.values()), collect_domain_doc_counts(documents), documents
