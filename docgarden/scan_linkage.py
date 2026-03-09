from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import re

from .markdown import Document, ROUTE_RE, resolve_link_target
from .models import Finding, FindingContext
from .scan_alignment import (
    format_reference_for_source,
    stable_suffix,
)
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


def is_current_truth_router(rel_path: str) -> bool:
    path = Path(rel_path)
    return rel_path == "AGENTS.md" or (
        path.parts[:1] == ("docs",) and path.name == "index.md"
    )


def current_truth_route_targets(document: Document, *, repo_root: Path) -> list[str]:
    targets = {
        routed_path
        for routed_path in document.routed_paths
        if routed_path == "AGENTS.md" or is_docs_rel_path(routed_path)
    }
    for link in document.links:
        target = resolve_link_target(document.path, repo_root, link)
        if not target or not target.exists():
            continue
        relative_target = repo_relative_path(repo_root, target)
        if relative_target is None:
            continue
        if relative_target == "AGENTS.md" or is_docs_rel_path(relative_target):
            targets.add(relative_target)
    return sorted(targets)


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
            context = FindingContext(
                rel_path=document.rel_path,
                domain=document_domain(document),
                discovered_at=discovered_at,
            )
            findings.append(
                Finding.open_issue(
                    context,
                    kind="duplicate-doc-id",
                    severity="high",
                    summary=f"{document.rel_path} uses duplicate doc_id `{doc_id}`.",
                    evidence=[f"doc_id `{doc_id}` appears {count} times."],
                    recommended_action="Give each doc a unique doc_id.",
                    safe_to_autofix=False,
                    cluster="metadata-gaps",
                    suffix="duplicate-id",
                )
            )
    return findings


def broken_route_findings(
    repo_root: Path,
    routed_targets: defaultdict[str, set[str]],
    inbound_links: defaultdict[str, set[str]],
    *,
    documents_by_rel_path: dict[str, Document],
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
        source_document = documents_by_rel_path.get(source)
        replacement_target = deterministic_current_truth_route_replacement(
            target,
            documents_by_rel_path=documents_by_rel_path,
        )
        route_replacements = (
            route_reference_replacements(
                source_document,
                repo_root=repo_root,
                target_rel_path=target,
                replacement_rel_path=replacement_target,
            )
            if source_document is not None and replacement_target is not None
            else []
        )
        evidence = [f"Missing route target: {target}"]
        recommended_action = "Update the route to point at an existing canonical doc."
        if replacement_target is not None:
            evidence.append(f"Deterministic replacement: {replacement_target}")
            recommended_action = (
                f"Update the route to point at {replacement_target} instead."
            )
        context = FindingContext(
            rel_path=source,
            domain="docs",
            discovered_at=discovered_at,
        )
        findings.append(
            Finding.open_issue(
                context,
                kind="broken-route",
                severity="high" if source == "AGENTS.md" else "medium",
                summary=f"{source} routes to a missing file.",
                evidence=evidence,
                recommended_action=recommended_action,
                safe_to_autofix=bool(route_replacements),
                cluster="routing-drift",
                suffix=f"route-{abs(hash(target))}",
                details={
                    "original_target": target,
                    "replacement_target": replacement_target,
                    "route_replacements": route_replacements,
                },
            )
        )
    return findings


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def canonical_route_replacements(
    document: Document,
    *,
    repo_root: Path,
    documents_by_rel_path: dict[str, Document],
) -> list[str]:
    replacements: list[str] = []
    for raw_target in _string_list(document.frontmatter.get("superseded_by")):
        target = resolve_link_target(document.path, repo_root, raw_target)
        if not target or not target.exists():
            continue
        relative_target = repo_relative_path(repo_root, target)
        if relative_target is None:
            continue
        replacement = documents_by_rel_path.get(relative_target)
        if not replacement or not replacement.frontmatter:
            continue
        if replacement.frontmatter.get("doc_type") != "canonical":
            continue
        if replacement.frontmatter.get("status") in {"stale", "deprecated", "archived"}:
            continue
        replacements.append(replacement.rel_path)
    return sorted(set(replacements))


def is_current_canonical_doc(document: Document) -> bool:
    if not document.frontmatter:
        return False
    if document.frontmatter.get("doc_type") != "canonical":
        return False
    return document.frontmatter.get("status") not in {
        "stale",
        "deprecated",
        "archived",
    }


def deterministic_current_truth_route_replacement(
    missing_target: str,
    *,
    documents_by_rel_path: dict[str, Document],
) -> str | None:
    file_name = Path(missing_target).name
    if not file_name:
        return None
    matches = sorted(
        {
            document.rel_path
            for document in documents_by_rel_path.values()
            if Path(document.rel_path).name == file_name
            and is_current_canonical_doc(document)
        }
    )
    if len(matches) != 1:
        return None
    return matches[0]


def route_quality_findings(
    repo_root: Path,
    documents: list[Document],
    *,
    discovered_at: str,
) -> list[Finding]:
    findings: list[Finding] = []
    documents_by_rel_path = {document.rel_path: document for document in documents}

    for source, source_document in sorted(documents_by_rel_path.items()):
        if not is_current_truth_router(source):
            continue
        for target in current_truth_route_targets(source_document, repo_root=repo_root):
            target_document = documents_by_rel_path.get(target)
            if not target_document or not target_document.frontmatter:
                continue

            target_doc_type = str(target_document.frontmatter.get("doc_type", "unknown"))
            target_status = str(target_document.frontmatter.get("status", "unknown"))
            replacements = canonical_route_replacements(
                target_document,
                repo_root=repo_root,
                documents_by_rel_path=documents_by_rel_path,
            )

            route_issue: str | None = None
            if target_doc_type == "archive" or target_status == "archived":
                route_issue = "archived"
            elif target_status == "deprecated":
                route_issue = "deprecated"
            elif target_status == "stale" and replacements:
                route_issue = "stale"

            if route_issue is None:
                continue

            issue_label = (
                "an archived"
                if route_issue == "archived"
                else f"a {route_issue}"
            )

            evidence = [
                f"Route target: {target_document.rel_path}",
                f"Target doc_type={target_doc_type}",
                f"Target status={target_status}",
            ]
            if replacements:
                evidence.append(
                    "Suggested canonical replacement: " + ", ".join(replacements)
                )

            recommended_action = (
                "Update the route to point at "
                + ", ".join(replacements)
                + f" instead of {target_document.rel_path}."
                if replacements
                else "Replace the route with a current canonical doc or remove it from the current-truth index."
            )
            route_replacements = (
                route_reference_replacements(
                    source_document,
                    repo_root=repo_root,
                    target_rel_path=target_document.rel_path,
                    replacement_rel_path=replacements[0],
                )
                if len(replacements) == 1
                else []
            )
            context = FindingContext(
                rel_path=source,
                domain="docs",
                discovered_at=discovered_at,
            )
            findings.append(
                Finding.open_issue(
                    context,
                    kind="stale-route",
                    severity="high" if source == "AGENTS.md" else "medium",
                    summary=(
                        f"{source} routes current readers to {issue_label} doc: "
                        f"{target_document.rel_path}."
                    ),
                    evidence=evidence,
                    recommended_action=recommended_action,
                    safe_to_autofix=bool(route_replacements),
                    cluster="routing-drift",
                    suffix=stable_suffix(
                        "route-quality", f"{source}->{target_document.rel_path}"
                    ),
                    details={
                        "original_target": target_document.rel_path,
                        "replacement_target": replacements[0] if len(replacements) == 1 else None,
                        "route_replacements": route_replacements,
                    },
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
        context = FindingContext(
            rel_path=document.rel_path,
            domain=document_domain(document),
            discovered_at=discovered_at,
            confidence="medium",
        )
        findings.append(
            Finding.open_issue(
                context,
                kind="orphan-doc",
                severity="low",
                summary=f"{document.rel_path} is not linked from any scanned document.",
                evidence=["No inbound markdown links were found in scanned docs."],
                recommended_action="Link the doc from an index, canonical doc, or AGENTS route.",
                safe_to_autofix=False,
                cluster="routing-drift",
                suffix="orphan",
            )
        )
    return findings


def route_reference_replacements(
    document: Document,
    *,
    repo_root: Path,
    target_rel_path: str,
    replacement_rel_path: str | None,
) -> list[dict[str, str]]:
    if replacement_rel_path is None:
        return []

    replacement_path = repo_root / replacement_rel_path
    replacements: list[dict[str, str]] = []

    for link in document.links:
        target = resolve_link_target(document.path, repo_root, link)
        if target is None:
            continue
        if repo_relative_path(repo_root, target) != target_rel_path:
            continue
        replacements.append(
            {
                "kind": "markdown_link",
                "from": link,
                "to": format_reference_for_source(
                    document.path,
                    repo_root=repo_root,
                    target=replacement_path,
                    original_reference=link,
                ),
            }
        )

    replacements.extend(
        route_line_replacements(
            document,
            target_rel_path=target_rel_path,
            replacement_rel_path=replacement_rel_path,
        )
    )

    deduped: list[dict[str, str]] = []
    seen: set[tuple[object, ...]] = set()
    for item in replacements:
        key = tuple(sorted(item.items()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


ROUTE_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")


def route_line_replacements(
    document: Document,
    *,
    target_rel_path: str,
    replacement_rel_path: str,
) -> list[dict[str, str]]:
    if document.rel_path != "AGENTS.md":
        return []

    replacements: list[dict[str, str]] = []
    for line_number, line in enumerate(document.raw_text.splitlines(keepends=True), start=1):
        if "](" in line or not ROUTE_LIST_ITEM_RE.match(line):
            continue
        updated_line = _replace_route_token_in_line(
            line,
            original=target_rel_path,
            replacement=replacement_rel_path,
        )
        if updated_line == line:
            continue
        replacements.append(
            {
                "kind": "route_line",
                "from": target_rel_path,
                "to": replacement_rel_path,
                "line": str(line_number),
                "before": line,
                "after": updated_line,
            }
        )
    return replacements


def _replace_route_token_in_line(line: str, *, original: str, replacement: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        if match.group("path") != original:
            return match.group(0)
        return replacement

    return ROUTE_RE.sub(_replace, line)
