from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
import subprocess

from .errors import DocgardenError
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
from .scan_alignment import alignment_findings
from .scan_linkage import (
    append_inbound_link,
    broken_route_findings,
    collect_domain_doc_counts,
    duplicate_doc_id_findings,
    orphan_doc_findings,
    scan_agents_document,
)

CHANGED_SCOPE_RECOMPUTED_VIEWS = [
    "document-local metadata, section, freshness, and trust checks",
    "alignment checks for scanned files",
    "broken-link checks originating from scanned files",
]
CHANGED_SCOPE_SKIPPED_VIEWS = [
    "repo-wide duplicate doc_id checks",
    "repo-wide broken-route checks",
    "repo-wide orphan-doc checks",
    "durable .docgarden findings, plan, and score updates",
]


@dataclass(slots=True)
class ChangedScopeSelection:
    source: str
    requested_files: list[str]
    scanned_files: list[str]
    deleted_files: list[str]
    notes: list[str] = field(default_factory=list)


def discover_markdown_files(repo_root: Path) -> list[Path]:
    files = []
    agents = repo_root / "AGENTS.md"
    if agents.exists():
        files.append(agents)
    docs_root = repo_root / "docs"
    if docs_root.exists():
        files.extend(sorted(docs_root.rglob("*.md")))
    return files


def _is_supported_doc_rel_path(rel_path: str) -> bool:
    path = Path(rel_path)
    return rel_path == "AGENTS.md" or (
        path.suffix == ".md" and path.parts[:1] == ("docs",)
    )


def _normalize_repo_relative_path(repo_root: Path, raw_path: str) -> str:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(repo_root)
        except ValueError as exc:
            raise DocgardenError(
                f"Changed-scope paths must stay inside the repo: {raw_path}."
            ) from exc

    candidate = repo_root / candidate
    try:
        normalized = candidate.resolve(strict=False).relative_to(
            repo_root.resolve(strict=False)
        )
    except ValueError:
        raise DocgardenError(
            f"Changed-scope paths must stay inside the repo: {raw_path}."
        ) from None

    rel_path = str(normalized)
    if not _is_supported_doc_rel_path(rel_path):
        raise DocgardenError(
            "Changed-scope paths must be `AGENTS.md` or markdown files under "
            f"`docs/`: {raw_path}."
        )
    return rel_path


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _run_git_path_query(repo_root: Path, args: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or "unknown git error"
        raise DocgardenError(
            "Unable to derive changed docs from git state. "
            "Use `docgarden scan --scope changed --files ...` instead. "
            f"Git said: {stderr}"
        )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _changed_doc_paths_from_git(repo_root: Path) -> ChangedScopeSelection:
    tracked_existing = _run_git_path_query(
        repo_root,
        ["diff", "--name-only", "--diff-filter=ACMR", "--relative", "--", "AGENTS.md", "docs"],
    )
    staged_existing = _run_git_path_query(
        repo_root,
        [
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=ACMR",
            "--relative",
            "--",
            "AGENTS.md",
            "docs",
        ],
    )
    untracked = _run_git_path_query(
        repo_root,
        ["ls-files", "--others", "--exclude-standard", "--", "AGENTS.md", "docs"],
    )
    tracked_deleted = _run_git_path_query(
        repo_root,
        ["diff", "--name-only", "--diff-filter=D", "--relative", "--", "AGENTS.md", "docs"],
    )
    staged_deleted = _run_git_path_query(
        repo_root,
        [
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=D",
            "--relative",
            "--",
            "AGENTS.md",
            "docs",
        ],
    )

    existing = _dedupe_preserving_order(
        [
            _normalize_repo_relative_path(repo_root, path)
            for path in [*tracked_existing, *staged_existing, *untracked]
            if _is_supported_doc_rel_path(path)
        ]
    )
    deleted = _dedupe_preserving_order(
        [
            _normalize_repo_relative_path(repo_root, path)
            for path in [*tracked_deleted, *staged_deleted]
            if _is_supported_doc_rel_path(path)
        ]
    )
    notes: list[str] = []
    if not existing and not deleted:
        notes.append("No changed doc files were detected from local git state.")
    return ChangedScopeSelection(
        source="git",
        requested_files=_dedupe_preserving_order(existing + deleted),
        scanned_files=existing,
        deleted_files=deleted,
        notes=notes,
    )


def determine_changed_docs(
    repo_root: Path,
    *,
    provided_files: list[str] | None = None,
) -> ChangedScopeSelection:
    if provided_files is None:
        return _changed_doc_paths_from_git(repo_root)

    normalized = _dedupe_preserving_order(
        [
            _normalize_repo_relative_path(repo_root, raw_path)
            for raw_path in provided_files
        ]
    )
    missing_files = [path for path in normalized if not (repo_root / path).exists()]
    if missing_files:
        missing_display = ", ".join(missing_files)
        raise DocgardenError(
            "Explicit `--files` entries must point to existing docs. "
            "Use local git-derived changed scope to include deletions. "
            f"Missing: {missing_display}."
        )
    notes = [
        "Explicit `--files` scope scans only the listed existing docs and do "
        "not infer deletions."
    ]
    return ChangedScopeSelection(
        source="files",
        requested_files=normalized,
        scanned_files=normalized,
        deleted_files=[],
        notes=notes,
    )


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
    if document.frontmatter.get("status") != "verified":
        return []
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
        alignment_findings(
            document,
            repo_root=repo_root,
            discovered_at=discovered_at,
        )
    )
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


def scan_changed_files(
    repo_root: Path,
    *,
    selection: ChangedScopeSelection,
) -> tuple[list[Finding], dict[str, int], list[Document]]:
    if not selection.scanned_files:
        return [], {}, []

    now = datetime.now()
    discovered_at = now.isoformat(timespec="seconds")
    documents = [
        parse_document(repo_root / rel_path, repo_root)
        for rel_path in selection.scanned_files
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

    deduped: dict[str, Finding] = {}
    for finding in sorted(
        findings, key=lambda item: (SEVERITY_ORDER.get(item.severity, 3), item.id)
    ):
        deduped[finding.id] = finding
    return list(deduped.values()), collect_domain_doc_counts(documents), documents


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
