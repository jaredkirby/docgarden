from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from .config import Config
from .markdown import (
    Document,
    normalize_heading,
    parse_document,
    resolve_link_target,
)
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


def _finding_id(kind: str, rel_path: str, suffix: str) -> str:
    path_token = rel_path.replace("/", "::")
    return f"{kind}::{path_token}::{suffix}"


def _make_finding(
    *,
    kind: str,
    severity: str,
    domain: str,
    files: list[str],
    summary: str,
    evidence: list[str],
    recommended_action: str,
    safe_to_autofix: bool,
    cluster: str,
    confidence: str,
    discovered_at: str,
    suffix: str,
    details: dict | None = None,
) -> Finding:
    return Finding(
        id=_finding_id(kind, files[0], suffix),
        kind=kind,
        severity=severity,
        domain=domain,
        status="open",
        files=files,
        summary=summary,
        evidence=evidence,
        recommended_action=recommended_action,
        safe_to_autofix=safe_to_autofix,
        discovered_at=discovered_at,
        cluster=cluster,
        confidence=confidence,
        details=details or {},
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


def scan_repo(
    repo_root: Path, config: Config, scope: str = "all"
) -> tuple[list[Finding], dict[str, int], list[Document]]:
    now = datetime.now()
    discovered_at = now.isoformat(timespec="seconds")
    documents = [
        parse_document(path, repo_root) for path in discover_markdown_files(repo_root)
    ]
    findings: list[Finding] = []
    doc_id_counter: Counter[str] = Counter()
    inbound_links: defaultdict[str, set[str]] = defaultdict(set)
    routed_targets: defaultdict[str, set[str]] = defaultdict(set)
    domain_doc_counts: Counter[str] = Counter()

    for document in documents:
        if document.rel_path.startswith("docs/") and document.frontmatter:
            domain = str(document.frontmatter.get("domain", "unknown"))
            domain_doc_counts[domain] += 1

    for document in documents:
        if document.path.name == "AGENTS.md":
            for routed_path in document.routed_paths:
                routed_targets[routed_path].add(document.rel_path)
            for link in document.links:
                target = resolve_link_target(document.path, repo_root, link)
                if target and target.exists():
                    inbound_links[str(target.relative_to(repo_root))].add(
                        document.rel_path
                    )
            continue

        domain = str(document.frontmatter.get("domain", "unknown"))
        doc_type = document.frontmatter.get("doc_type")

        if not document.frontmatter:
            findings.append(
                _make_finding(
                    kind="missing-frontmatter",
                    severity="high",
                    domain=domain,
                    files=[document.rel_path],
                    summary=f"{document.rel_path} is missing required frontmatter.",
                    evidence=["Non-archive docs must declare metadata."],
                    recommended_action="Add frontmatter with the required metadata contract.",
                    safe_to_autofix=False,
                    cluster="metadata-gaps",
                    confidence="high",
                    discovered_at=discovered_at,
                    suffix="frontmatter",
                )
            )
            continue

        if "doc_id" in document.frontmatter:
            doc_id_counter[str(document.frontmatter["doc_id"])] += 1

        missing_metadata = sorted(REQUIRED_METADATA - set(document.frontmatter))
        if missing_metadata:
            findings.append(
                _make_finding(
                    kind="missing-metadata",
                    severity="high",
                    domain=domain,
                    files=[document.rel_path],
                    summary=f"{document.rel_path} is missing required metadata fields.",
                    evidence=[f"Missing fields: {', '.join(missing_metadata)}"],
                    recommended_action="Fill in the required frontmatter fields.",
                    safe_to_autofix=False,
                    cluster="metadata-gaps",
                    confidence="high",
                    discovered_at=discovered_at,
                    suffix="metadata",
                    details={"missing_metadata": missing_metadata},
                )
            )

        status = document.frontmatter.get("status")
        if status and status not in ALLOWED_STATUS:
            findings.append(
                _make_finding(
                    kind="invalid-metadata",
                    severity="medium",
                    domain=domain,
                    files=[document.rel_path],
                    summary=f"{document.rel_path} uses an unsupported status value.",
                    evidence=[f"status={status}"],
                    recommended_action="Use one of the allowed status values.",
                    safe_to_autofix=False,
                    cluster="metadata-gaps",
                    confidence="high",
                    discovered_at=discovered_at,
                    suffix="status",
                )
            )

        if doc_type in REQUIRED_SECTIONS:
            existing = {normalize_heading(item) for item in document.headings}
            missing_sections = [
                section
                for section in REQUIRED_SECTIONS[doc_type]
                if normalize_heading(section) not in existing
            ]
            if missing_sections:
                findings.append(
                    _make_finding(
                        kind="missing-sections",
                        severity="medium",
                        domain=domain,
                        files=[document.rel_path],
                        summary=f"{document.rel_path} is missing required sections.",
                        evidence=[f"Missing headings: {', '.join(missing_sections)}"],
                        recommended_action="Add the missing required sections for this doc type.",
                        safe_to_autofix=True,
                        cluster="structure-gaps",
                        confidence="high",
                        discovered_at=discovered_at,
                        suffix="sections",
                        details={"missing_sections": missing_sections},
                    )
                )

        review_date = _parse_review_date(str(document.frontmatter.get("last_reviewed")))
        review_cycle = document.frontmatter.get("review_cycle_days")
        if review_date and isinstance(review_cycle, int):
            if review_date + timedelta(days=review_cycle) < now.date():
                findings.append(
                    _make_finding(
                        kind="stale-review",
                        severity="medium" if doc_type == "reference" else "high",
                        domain=domain,
                        files=[document.rel_path],
                        summary=f"{document.rel_path} is past its review cycle.",
                        evidence=[
                            f"last_reviewed={review_date.isoformat()}",
                            f"review_cycle_days={review_cycle}",
                        ],
                        recommended_action="Review the doc and update status or content.",
                        safe_to_autofix=True,
                        cluster="stale-docs",
                        confidence="high",
                        discovered_at=discovered_at,
                        suffix="stale",
                    )
                )

        if doc_type == "canonical" and document.frontmatter.get("status") == "verified":
            if not document.frontmatter.get(
                "source_of_truth"
            ) or not document.frontmatter.get("verification"):
                findings.append(
                    _make_finding(
                        kind="verified-without-sources",
                        severity="high",
                        domain=domain,
                        files=[document.rel_path],
                        summary=f"{document.rel_path} is marked verified without trust metadata.",
                        evidence=[
                            "Canonical verified docs must declare source_of_truth and verification."
                        ],
                        recommended_action="Add trust metadata or lower the status.",
                        safe_to_autofix=False,
                        cluster="trust-gaps",
                        confidence="high",
                        discovered_at=discovered_at,
                        suffix="trust",
                    )
                )

        for routed_path in document.routed_paths:
            routed_targets[routed_path].add(document.rel_path)

        for link in document.links:
            target = resolve_link_target(document.path, repo_root, link)
            if not target:
                continue
            if target.exists():
                try:
                    inbound_links[str(target.relative_to(repo_root))].add(
                        document.rel_path
                    )
                except ValueError:
                    pass
            else:
                findings.append(
                    _make_finding(
                        kind="broken-link",
                        severity="medium",
                        domain=domain,
                        files=[document.rel_path],
                        summary=f"{document.rel_path} links to a missing file.",
                        evidence=[f"Broken link target: {link}"],
                        recommended_action="Update or remove the broken link.",
                        safe_to_autofix=False,
                        cluster="routing-drift",
                        confidence="high",
                        discovered_at=discovered_at,
                        suffix=f"link-{abs(hash(link))}",
                    )
                )

    for doc_id, count in doc_id_counter.items():
        if count < 2:
            continue
        duplicate_docs = [
            document
            for document in documents
            if document.frontmatter.get("doc_id") == doc_id
        ]
        for document in duplicate_docs:
            findings.append(
                _make_finding(
                    kind="duplicate-doc-id",
                    severity="high",
                    domain=str(document.frontmatter.get("domain", "unknown")),
                    files=[document.rel_path],
                    summary=f"{document.rel_path} uses duplicate doc_id `{doc_id}`.",
                    evidence=[f"doc_id `{doc_id}` appears {count} times."],
                    recommended_action="Give each doc a unique doc_id.",
                    safe_to_autofix=False,
                    cluster="metadata-gaps",
                    confidence="high",
                    discovered_at=discovered_at,
                    suffix="duplicate-id",
                )
            )

    for target, referrers in sorted(routed_targets.items()):
        target_path = (
            (repo_root / target) if not Path(target).is_absolute() else Path(target)
        )
        if not target_path.exists():
            source = sorted(referrers)[0]
            findings.append(
                _make_finding(
                    kind="broken-route",
                    severity="high" if source == "AGENTS.md" else "medium",
                    domain="docs",
                    files=[source],
                    summary=f"{source} routes to a missing file.",
                    evidence=[f"Missing route target: {target}"],
                    recommended_action="Update the route to point at an existing canonical doc.",
                    safe_to_autofix=False,
                    cluster="routing-drift",
                    confidence="high",
                    discovered_at=discovered_at,
                    suffix=f"route-{abs(hash(target))}",
                )
            )
        else:
            try:
                inbound_links[str(target_path.relative_to(repo_root))].update(referrers)
            except ValueError:
                pass

    for document in documents:
        if not document.rel_path.startswith("docs/"):
            continue
        if document.rel_path.endswith("QUALITY_SCORE.md"):
            continue
        if document.rel_path not in inbound_links:
            findings.append(
                _make_finding(
                    kind="orphan-doc",
                    severity="low",
                    domain=str(document.frontmatter.get("domain", "unknown")),
                    files=[document.rel_path],
                    summary=f"{document.rel_path} is not linked from any scanned document.",
                    evidence=["No inbound markdown links were found in scanned docs."],
                    recommended_action="Link the doc from an index, canonical doc, or AGENTS route.",
                    safe_to_autofix=False,
                    cluster="routing-drift",
                    confidence="medium",
                    discovered_at=discovered_at,
                    suffix="orphan",
                )
            )

    deduped: dict[str, Finding] = {}
    for finding in sorted(
        findings, key=lambda item: (SEVERITY_ORDER.get(item.severity, 3), item.id)
    ):
        deduped[finding.id] = finding
    return list(deduped.values()), dict(domain_doc_counts), documents
