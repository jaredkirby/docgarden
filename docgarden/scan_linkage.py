from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from .markdown import Document, resolve_link_target
from .models import Finding
from .scan_document_rules import document_domain


def is_docs_rel_path(rel_path: str) -> bool:
    return Path(rel_path).parts[:1] == ("docs",)


def repo_relative_path(repo_root: Path, target: Path) -> str | None:
    if not target.is_relative_to(repo_root):
        return None
    return str(target.relative_to(repo_root))


def append_inbound_link(
    repo_root: Path,
    target: Path,
    source_rel_path: str,
    inbound_links: defaultdict[str, set[str]],
) -> None:
    relative_target = repo_relative_path(repo_root, target)
    if relative_target is not None:
        inbound_links[relative_target].add(source_rel_path)


def collect_domain_doc_counts(documents: list[Document]) -> dict[str, int]:
    domain_doc_counts: Counter[str] = Counter()
    for document in documents:
        if is_docs_rel_path(document.rel_path) and document.frontmatter:
            domain_doc_counts[document_domain(document)] += 1
    return dict(domain_doc_counts)


def scan_agents_document(
    document: Document,
    *,
    repo_root: Path,
    inbound_links: defaultdict[str, set[str]],
    routed_targets: defaultdict[str, set[str]],
) -> None:
    for routed_path in document.routed_paths:
        routed_targets[routed_path].add(document.rel_path)
    for link in document.links:
        target = resolve_link_target(document.path, repo_root, link)
        if target and target.exists():
            append_inbound_link(repo_root, target, document.rel_path, inbound_links)


def duplicate_doc_id_findings(
    documents: list[Document],
    doc_id_counter: Counter[str],
    *,
    discovered_at: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for doc_id, count in doc_id_counter.items():
        if count < 2:
            continue
        for document in documents:
            if document.frontmatter.get("doc_id") != doc_id:
                continue
            findings.append(
                Finding.open_issue(
                    rel_path=document.rel_path,
                    kind="duplicate-doc-id",
                    severity="high",
                    domain=document_domain(document),
                    summary=f"{document.rel_path} uses duplicate doc_id `{doc_id}`.",
                    evidence=[f"doc_id `{doc_id}` appears {count} times."],
                    recommended_action="Give each doc a unique doc_id.",
                    safe_to_autofix=False,
                    discovered_at=discovered_at,
                    cluster="metadata-gaps",
                    confidence="high",
                    suffix="duplicate-id",
                )
            )
    return findings


def broken_route_findings(
    repo_root: Path,
    routed_targets: defaultdict[str, set[str]],
    inbound_links: defaultdict[str, set[str]],
    *,
    discovered_at: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for target, referrers in sorted(routed_targets.items()):
        target_path = (
            Path(target) if Path(target).is_absolute() else repo_root / target
        )
        if target_path.exists():
            for referrer in referrers:
                append_inbound_link(repo_root, target_path, referrer, inbound_links)
            continue

        source = sorted(referrers)[0]
        findings.append(
            Finding.open_issue(
                rel_path=source,
                kind="broken-route",
                severity="high" if source == "AGENTS.md" else "medium",
                domain="docs",
                summary=f"{source} routes to a missing file.",
                evidence=[f"Missing route target: {target}"],
                recommended_action="Update the route to point at an existing canonical doc.",
                safe_to_autofix=False,
                discovered_at=discovered_at,
                cluster="routing-drift",
                confidence="high",
                suffix=f"route-{abs(hash(target))}",
            )
        )
    return findings


def orphan_doc_findings(
    documents: list[Document],
    inbound_links: defaultdict[str, set[str]],
    *,
    discovered_at: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for document in documents:
        if not is_docs_rel_path(document.rel_path):
            continue
        if document.path.name == "QUALITY_SCORE.md":
            continue
        if document.rel_path in inbound_links:
            continue
        findings.append(
            Finding.open_issue(
                rel_path=document.rel_path,
                kind="orphan-doc",
                severity="low",
                domain=document_domain(document),
                summary=f"{document.rel_path} is not linked from any scanned document.",
                evidence=["No inbound markdown links were found in scanned docs."],
                recommended_action="Link the doc from an index, canonical doc, or AGENTS route.",
                safe_to_autofix=False,
                discovered_at=discovered_at,
                cluster="routing-drift",
                confidence="medium",
                suffix="orphan",
            )
        )
    return findings
