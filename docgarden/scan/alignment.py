from __future__ import annotations

import hashlib
import os
import re
import shlex
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..markdown import (
    Document,
    extract_markdown_links,
    extract_sections,
    normalize_heading,
    resolve_link_target,
    section_content_map,
)
from ..models import Finding
from .findings import FindingSpec, build_document_finding, build_finding
from .document_rules import (
    generated_doc_contract_finding,
    generated_doc_stale_finding,
)

INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
FENCED_BLOCK_RE = re.compile(r"```(?:bash|sh|shell)?\n(.*?)```", re.DOTALL)
URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\\\/]")
ROOT_LOCAL_ARTIFACT_NAMES = {
    "AGENTS.md",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "Makefile",
    "Dockerfile",
    "Justfile",
    "Procfile",
}
GENERATED_SOURCE_HEADING = normalize_heading("Generation source")
GENERATED_TIMESTAMP_HEADING = normalize_heading("Generated timestamp")
GENERATED_UPSTREAM_HEADING = normalize_heading("Upstream artifact path or script")
GENERATED_COMMAND_HEADING = normalize_heading("Regeneration command")
WORKFLOW_SECTION_PREFIXES = (
    "validation",
    "how to verify",
    "workflow",
    "commands",
    "usage",
    "how to use",
    "steps",
    "prerequisite",
    "setup",
    "runbook",
)
HIDDEN_NON_REPO_WORKFLOW_ROOTS = {
    ".docgarden",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
}
WORKFLOW_PLACEHOLDER_MARKERS = ("...", "<", ">", "{", "}", "$(", "${", "*")
TRANSIENT_DOC_PATH_KEYWORDS = {
    "handoff",
    "note",
    "notes",
    "scratch",
    "summary",
    "summaries",
    "temp",
    "temporary",
    "workaround",
    "workarounds",
}
PROMOTION_EXCLUDED_SECTION_HEADINGS = {
    normalize_heading("Progress"),
    normalize_heading("Outcomes / Retrospective"),
}
PROMOTION_RULE_SIGNAL_RE = re.compile(
    r"\b("
    r"must|should|needs?\s+to|do\s+not|don't|never|always|prefer|"
    r"keep|treat|require|requires|limit|belongs\s+in|live[s]?\s+in|"
    r"source\s+of\s+truth"
    r")\b"
)
PROMOTION_ANCHOR_KEYWORDS = (
    "agents.md",
    "canonical",
    "docgarden",
    "docs/",
    ".docgarden",
    "exec plan",
    "exec plans",
    "findings.jsonl",
    "plan.json",
    "quality score",
    "review packet",
    "score.json",
    "safe autofix",
    "source of truth",
)
PROMOTION_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "by",
    "for",
    "from",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "them",
    "then",
    "this",
    "to",
    "use",
    "with",
}
CANONICAL_PROMOTION_DESTINATION_HINTS = (
    (
        "docs/design-docs/index.md",
        (
            "docgarden",
            ".docgarden",
            "findings.jsonl",
            "plan.json",
            "quality score",
            "review packet",
            "safe autofix",
            "score.json",
            "strict score",
        ),
    ),
    (
        "docs/index.md",
        (
            "agents.md",
            "canonical",
            "docs/index.md",
            "source of truth",
            "system of record",
            "exec plan",
            "exec plans",
            "exec-plans",
            "note",
            "notes",
            "workaround",
            "workarounds",
        ),
    ),
)
SUPPORTING_PROMOTION_DESTINATION_HINTS = (
    (
        "docs/PLANS.md",
        (
            "exec plan",
            "exec plans",
            "exec-plans",
            "progress",
            "decision log",
            "discoveries",
            "active plans",
        ),
    ),
    (
        "README.md",
        (
            "docgarden",
            ".docgarden",
            "findings.jsonl",
            "plan.json",
            "quality score",
            "review packet",
            "safe autofix",
            "score.json",
        ),
    ),
    (
        "docs/design-docs/docgarden-spec.md",
        (
            "promotion suggestion",
            "review packet",
            "safe autofix",
            "source of truth",
            "strict score",
        ),
    ),
)


@dataclass(slots=True)
class GeneratedDocContract:
    issues: list[str]
    generated_at: datetime | None
    upstream_path: Path | None


@dataclass(frozen=True, slots=True)
class PromotionOccurrence:
    rel_path: str
    section: str
    statement: str
    normalized_rule: str


@dataclass(frozen=True, slots=True)
class PromotionDestinationSuggestion:
    rel_path: str
    reasons: tuple[str, ...]


def stable_suffix(prefix: str, value: str) -> str:
    normalized = value.strip()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-") or "item"
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{slug[:48]}-{digest}"


def alignment_findings(
    document: Document,
    *,
    repo_root: Path,
    discovered_at: str,
) -> list[Finding]:
    findings: list[Finding] = []
    if document.frontmatter and document.frontmatter.get("status") != "draft":
        findings.extend(
            missing_source_of_truth_findings(
                document,
                repo_root=repo_root,
                discovered_at=discovered_at,
            )
        )
        findings.extend(
            invalid_validation_command_findings(
                document,
                discovered_at=discovered_at,
            )
        )
    findings.extend(
        generated_doc_findings(
            document,
            repo_root=repo_root,
            discovered_at=discovered_at,
        )
    )
    findings.extend(
        workflow_asset_findings(
            document,
            repo_root=repo_root,
            discovered_at=discovered_at,
        )
    )
    return findings


def promotion_suggestion_findings(
    documents: list[Document],
    *,
    repo_root: Path,
    discovered_at: str,
) -> list[Finding]:
    occurrences_by_rule: dict[str, list[PromotionOccurrence]] = {}
    for document in documents:
        if not is_transient_knowledge_doc(document):
            continue
        for occurrence in extract_promotion_rule_occurrences(document):
            occurrences_by_rule.setdefault(occurrence.normalized_rule, []).append(
                occurrence
            )

    findings: list[Finding] = []
    for normalized_rule, occurrences in sorted(occurrences_by_rule.items()):
        unique_by_file: dict[str, PromotionOccurrence] = {}
        for occurrence in occurrences:
            unique_by_file.setdefault(occurrence.rel_path, occurrence)
        if len(unique_by_file) < 2:
            continue

        ordered_occurrences = [
            unique_by_file[rel_path] for rel_path in sorted(unique_by_file)
        ]
        source_files = [item.rel_path for item in ordered_occurrences]
        candidate_suggestions = infer_promotion_destination_docs(
            normalized_rule,
            source_files=source_files,
            documents=documents,
            repo_root=repo_root,
        )
        supporting_suggestions = infer_supporting_promotion_destination_docs(
            normalized_rule,
            source_files=source_files,
            repo_root=repo_root,
        )
        candidate_destinations = [item.rel_path for item in candidate_suggestions]
        supporting_destinations = [item.rel_path for item in supporting_suggestions]
        primary_destination = candidate_destinations[0] if candidate_destinations else None
        summary_statement = ordered_occurrences[0].statement
        evidence = [
            (
                f"Repeated transient rule across {len(source_files)} docs: "
                f"{summary_statement}"
            )
        ]
        evidence.extend(
            f"Source: {item.rel_path} [{item.section}]"
            for item in ordered_occurrences[:3]
        )
        if primary_destination:
            evidence.append(
                "Primary canonical destination: "
                + format_promotion_destination_suggestion(candidate_suggestions[0])
            )
        if len(candidate_suggestions) > 1:
            evidence.append(
                "Other canonical destinations: "
                + ", ".join(
                    format_promotion_destination_suggestion(item)
                    for item in candidate_suggestions[1:]
                )
            )
        if supporting_suggestions:
            evidence.append(
                "Supporting reference docs: "
                + ", ".join(
                    format_promotion_destination_suggestion(item)
                    for item in supporting_suggestions
                )
            )

        recommended_action = (
            "Promote the repeated rule into a canonical doc and replace the "
            "transient copies with links or shorter reminders."
        )
        if primary_destination:
            recommended_action = (
                "Promote the repeated rule into "
                + primary_destination
                + ", then replace the transient copies with links or shorter reminders."
            )
            if supporting_destinations:
                recommended_action += (
                    " Align supporting reference docs as needed: "
                    + ", ".join(supporting_destinations)
                    + "."
                )

        findings.append(
            build_finding(
                FindingSpec(
                    kind="promotion-suggestion",
                    severity="low",
                    summary=(
                        "Repeated transient rule should move into a canonical doc: "
                        f"{summary_statement}"
                    ),
                    evidence=evidence,
                    recommended_action=recommended_action,
                    cluster="promotion-opportunities",
                    suffix=stable_suffix("promotion", normalized_rule),
                    details={
                        "candidate_destinations": candidate_destinations,
                        "primary_canonical_destination": primary_destination,
                        "candidate_destination_reasons": {
                            item.rel_path: list(item.reasons)
                            for item in candidate_suggestions
                        },
                        "normalized_rule": normalized_rule,
                        "supporting_destination_docs": supporting_destinations,
                        "supporting_destination_reasons": {
                            item.rel_path: list(item.reasons)
                            for item in supporting_suggestions
                        },
                        "source_occurrences": [
                            {
                                "file": item.rel_path,
                                "section": item.section,
                                "statement": item.statement,
                            }
                            for item in ordered_occurrences
                        ],
                    },
                ),
                rel_path=source_files[0],
                domain="docs",
                discovered_at=discovered_at,
                files=source_files,
            )
        )
    return findings


def generated_doc_findings(
    document: Document,
    *,
    repo_root: Path,
    discovered_at: str,
) -> list[Finding]:
    if document.frontmatter.get("doc_type") != "generated":
        return []

    contract = inspect_generated_doc_contract(document, repo_root=repo_root)
    findings: list[Finding] = []
    if contract.issues:
        findings.append(
            generated_doc_contract_finding(
                document,
                issues=contract.issues,
                discovered_at=discovered_at,
            )
        )

    if not contract.generated_at or contract.upstream_path is None:
        return findings
    if not contract.upstream_path.exists() or not contract.upstream_path.is_file():
        return findings

    upstream_mtime = source_mtime_for(
        contract.upstream_path,
        reference=contract.generated_at,
    )
    if upstream_mtime > contract.generated_at:
        findings.append(
            generated_doc_stale_finding(
                document,
                generated_at=contract.generated_at,
                upstream_path=contract.upstream_path,
                upstream_mtime=upstream_mtime,
                discovered_at=discovered_at,
            )
        )
    return findings


def missing_source_of_truth_findings(
    document: Document,
    *,
    repo_root: Path,
    discovered_at: str,
) -> list[Finding]:
    raw_sources = document.frontmatter.get("source_of_truth")
    if isinstance(raw_sources, str):
        sources = [raw_sources]
    elif isinstance(raw_sources, list):
        sources = [item for item in raw_sources if isinstance(item, str)]
    else:
        sources = []

    findings: list[Finding] = []
    for source in sources:
        target = resolve_repo_artifact(repo_root, source)
        if target is None or target.exists():
            continue
        findings.append(
            build_document_finding(
                document,
                FindingSpec(
                    kind="missing-source-artifact",
                    severity="high",
                    summary=f"{document.rel_path} references a missing source_of_truth artifact.",
                    evidence=[f"Missing artifact: {source}"],
                    recommended_action="Point source_of_truth at an existing local artifact.",
                    cluster="artifact-drift",
                    suffix=stable_suffix("source", source),
                ),
                domain=str(document.frontmatter.get("domain", "unknown")),
                discovered_at=discovered_at,
            )
        )
    return findings


def invalid_validation_command_findings(
    document: Document,
    *,
    discovered_at: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for command in extract_validation_commands(document.body):
        if not is_docgarden_command(command):
            continue
        if is_supported_docgarden_command(command):
            continue
        findings.append(
            build_document_finding(
                document,
                FindingSpec(
                    kind="invalid-validation-command",
                    severity="medium",
                    summary=f"{document.rel_path} documents an unsupported docgarden command.",
                    evidence=[f"Unsupported command: {command}"],
                    recommended_action="Update the validation step to a supported docgarden CLI command.",
                    cluster="workflow-drift",
                    suffix=stable_suffix("command", command),
                ),
                domain=str(document.frontmatter.get("domain", "unknown")),
                discovered_at=discovered_at,
            )
        )
    return findings


def resolve_repo_artifact(repo_root: Path, value: str) -> Path | None:
    candidate = value.strip()
    if not candidate:
        return None
    if any(char.isspace() for char in candidate):
        return None
    if is_non_local_reference(candidate):
        return None
    if candidate.startswith("file://"):
        parsed = urlparse(candidate)
        if parsed.netloc not in {"", "localhost"}:
            return None
        resolved = Path(unquote(parsed.path))
        return resolved if resolved.is_absolute() else repo_root / resolved

    path = Path(candidate)
    if path.is_absolute():
        return path if path.is_absolute() else repo_root / path
    if "/" in candidate or "\\" in candidate:
        return repo_root / path
    if path.suffix:
        return repo_root / path
    if candidate.startswith("."):
        return repo_root / path
    if path.name in ROOT_LOCAL_ARTIFACT_NAMES:
        return repo_root / path
    return None


def repo_markdown_documents(repo_root: Path) -> list[Path]:
    documents: list[Path] = []
    agents = repo_root / "AGENTS.md"
    if agents.exists():
        documents.append(agents)
    docs_root = repo_root / "docs"
    if docs_root.exists():
        documents.extend(sorted(docs_root.rglob("*.md")))
    return documents


def repo_relative_target(repo_root: Path, target: Path) -> str | None:
    try:
        return str(target.relative_to(repo_root))
    except ValueError:
        return None


def format_reference_for_source(
    current_file: Path,
    *,
    repo_root: Path,
    target: Path,
    original_reference: str,
) -> str:
    clean_reference, hash_separator, anchor = original_reference.partition("#")
    if clean_reference.startswith("docs/") or clean_reference == "AGENTS.md":
        replacement = repo_relative_target(repo_root, target)
        if replacement is None:
            return original_reference
    else:
        replacement = Path(
            os.path.relpath(target, start=current_file.parent)
        ).as_posix()
    if hash_separator:
        replacement += f"#{anchor}"
    return replacement


def deterministic_repo_target_replacement(
    repo_root: Path,
    missing_target: str,
) -> str | None:
    candidate = Path(missing_target)
    file_name = candidate.name
    if not file_name:
        return None
    matches = [
        path
        for path in repo_markdown_documents(repo_root)
        if path.name == file_name
    ]
    if len(matches) != 1:
        return None
    return repo_relative_target(repo_root, matches[0])


def deterministic_internal_reference_replacement(
    repo_root: Path,
    *,
    current_file: Path,
    original_reference: str,
) -> str | None:
    target = resolve_link_target(current_file, repo_root, original_reference)
    if target is None or target.exists():
        return None
    replacement_target = deterministic_repo_target_replacement(
        repo_root,
        repo_relative_target(repo_root, target) or target.name,
    )
    if replacement_target is None:
        return None
    replacement_path = repo_root / replacement_target
    return format_reference_for_source(
        current_file,
        repo_root=repo_root,
        target=replacement_path,
        original_reference=original_reference,
    )


def extract_validation_commands(body: str) -> list[str]:
    sections = extract_sections(body)
    commands: list[str] = []
    for heading, _, content in sections:
        if heading not in {"validation", "validation how to verify"}:
            continue
        commands.extend(extract_commands_from_text(content))
    return sorted(set(commands))


def inspect_generated_doc_contract(
    document: Document,
    *,
    repo_root: Path,
) -> GeneratedDocContract:
    sections = section_content_map(document.body)
    issues: list[str] = []

    generation_source = extract_section_value(sections.get(GENERATED_SOURCE_HEADING, ""))
    if generation_source is None:
        issues.append("Generation source section must include provenance details.")

    generated_timestamp_text = extract_section_value(
        sections.get(GENERATED_TIMESTAMP_HEADING, "")
    )
    generated_at = None
    if generated_timestamp_text is None:
        issues.append(
            "Generated timestamp section must include an offset-aware ISO-8601 timestamp."
        )
    else:
        generated_at = parse_generated_timestamp(generated_timestamp_text)
        if generated_at is None:
            issues.append(
                "Generated timestamp section must include a valid offset-aware ISO-8601 timestamp."
            )

    upstream_reference = extract_section_value(
        sections.get(GENERATED_UPSTREAM_HEADING, "")
    )
    upstream_path = None
    if upstream_reference is None:
        issues.append(
            "Upstream artifact path or script section must identify the source input."
        )
    else:
        upstream_path = resolve_repo_artifact(repo_root, upstream_reference)
        if upstream_path is not None and not upstream_path.exists():
            issues.append(
                "Upstream artifact path or script points to a missing local file: "
                f"{upstream_reference}"
            )
            upstream_path = None

    regeneration_commands = extract_commands_from_text(
        sections.get(GENERATED_COMMAND_HEADING, "")
    )
    runnable_commands = [
        command for command in regeneration_commands if is_runnable_command(command)
    ]
    if not runnable_commands:
        issues.append(
            "Regeneration command section must include a runnable command snippet."
        )

    return GeneratedDocContract(
        issues=issues,
        generated_at=generated_at,
        upstream_path=upstream_path,
    )


def extract_commands_from_text(text: str) -> list[str]:
    commands: list[str] = []
    for snippet in INLINE_CODE_RE.findall(text):
        normalized = snippet.strip()
        if normalized:
            commands.append(normalized)

    for block in FENCED_BLOCK_RE.findall(text):
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            commands.append(line)
    return commands


def extract_section_value(text: str) -> str | None:
    for snippet in INLINE_CODE_RE.findall(text):
        normalized = snippet.strip()
        if normalized:
            return normalized

    for target in extract_markdown_links(text):
        normalized = target.split("#", 1)[0].strip()
        if normalized:
            return normalized

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^[-*+]\s+", "", line)
        if line.startswith("`") and line.endswith("`"):
            line = line[1:-1].strip()
        if line:
            return line
    return None


def parse_generated_timestamp(value: str) -> datetime | None:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def source_mtime_for(path: Path, *, reference: datetime) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=reference.tzinfo)


def is_non_local_reference(value: str) -> bool:
    if WINDOWS_DRIVE_RE.match(value):
        return False
    scheme_match = URI_SCHEME_RE.match(value)
    if scheme_match is None:
        return False
    return scheme_match.group(0).lower() != "file:"


def is_runnable_command(command: str) -> bool:
    tokens = tokenize_command(command)
    if not tokens:
        return False
    if len(tokens) > 1:
        return True
    executable = tokens[0]
    if executable.startswith(("./", "../", "/")):
        return True
    return not looks_like_path_reference(executable)


def looks_like_path_reference(value: str) -> bool:
    if value.startswith("."):
        return True
    if "/" in value or "\\" in value:
        return True
    return bool(Path(value).suffix)


def is_docgarden_command(command: str) -> bool:
    tokens = tokenize_command(command)
    if not tokens:
        return False
    if tokens[:2] == ["uv", "run"]:
        tokens = tokens[2:]
    elif tokens[:3] == ["python", "-m", "docgarden.cli"]:
        tokens = tokens[3:]
    return bool(tokens) and tokens[0] == "docgarden"


def is_supported_docgarden_command(command: str) -> bool:
    tokens = tokenize_command(command)
    if not tokens:
        return True
    if tokens[:2] == ["uv", "run"]:
        tokens = tokens[2:]
    elif tokens[:3] == ["python", "-m", "docgarden.cli"]:
        tokens = tokens[3:]

    if not tokens or tokens[0] != "docgarden":
        return True

    args = tokens[1:]
    if not args:
        return False

    command_name = args[0]
    rest = args[1:]
    if command_name in {"scan", "status", "next", "plan", "doctor"}:
        return not rest
    if command_name == "review":
        if not rest:
            return False
        subcommand = rest[0]
        subrest = rest[1:]
        if subcommand == "prepare":
            return _is_supported_review_prepare_args(subrest)
        if subcommand == "import":
            return len(subrest) == 1 and not subrest[0].startswith("-")
        return False
    if command_name == "show":
        return len(rest) == 1 and not rest[0].startswith("-")
    if command_name == "quality":
        return rest == ["write"]
    if command_name == "fix":
        return rest in (["safe"], ["safe", "--apply"])
    if command_name == "config":
        return rest == ["show"]
    return False


def _is_supported_review_prepare_args(args: list[str]) -> bool:
    index = 0
    while index < len(args):
        token = args[index]
        if token.startswith("--domains="):
            index += 1
            continue
        if token == "--domains":
            if index + 1 >= len(args) or args[index + 1].startswith("-"):
                return False
            index += 2
            continue
        return False
    return True


def tokenize_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def workflow_asset_findings(
    document: Document,
    *,
    repo_root: Path,
    discovered_at: str,
) -> list[Finding]:
    references: dict[str, tuple[str, Path]] = {}
    for heading, _, content in extract_sections(document.body):
        if not is_workflow_section(heading):
            continue
        for raw_reference in extract_workflow_asset_references(content):
            target = resolve_repo_artifact(repo_root, raw_reference)
            if target is None or target.exists():
                continue
            if should_ignore_workflow_asset(target, repo_root=repo_root):
                continue
            references.setdefault(raw_reference, (heading, target))

    if not references:
        return []

    findings: list[Finding] = []
    for raw_reference, (heading, target) in sorted(references.items()):
        findings.append(
            build_document_finding(
                document,
                FindingSpec(
                    kind="missing-workflow-asset",
                    severity="medium",
                    summary=f"{document.rel_path} references a missing workflow asset.",
                    evidence=[
                        f"Workflow section: {heading}",
                        f"Missing asset reference: {raw_reference}",
                        f"Resolved local path: {target.relative_to(repo_root)}",
                    ],
                    recommended_action=(
                        "Update the workflow reference to an existing repo-owned script or path, "
                        "or remove the stale instruction."
                    ),
                    cluster="workflow-drift",
                    suffix=stable_suffix("asset", raw_reference),
                ),
                domain=str(document.frontmatter.get("domain", "unknown")),
                discovered_at=discovered_at,
            )
        )
    return findings


def is_workflow_section(heading: str) -> bool:
    return any(
        heading == prefix or heading.startswith(f"{prefix} ")
        for prefix in WORKFLOW_SECTION_PREFIXES
    )


def extract_workflow_asset_references(text: str) -> list[str]:
    references: list[str] = []
    for link in extract_markdown_links(text):
        normalized = normalize_workflow_reference(link)
        if normalized is not None:
            references.append(normalized)

    for snippet in INLINE_CODE_RE.findall(text):
        references.extend(extract_asset_candidates_from_command(snippet))

    for block in FENCED_BLOCK_RE.findall(text):
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            references.extend(extract_asset_candidates_from_command(line))

    return sorted(set(references))


def extract_asset_candidates_from_command(command: str) -> list[str]:
    normalized = normalize_workflow_reference(command)
    references: list[str] = []
    if normalized is not None:
        references.append(normalized)

    for token in tokenize_command(command):
        normalized_token = normalize_workflow_reference(token)
        if normalized_token is not None:
            references.append(normalized_token)
    return references


def normalize_workflow_reference(value: str) -> str | None:
    candidate = value.strip().strip("()[]{}:,;\"'")
    if not candidate:
        return None
    if any(marker in candidate for marker in WORKFLOW_PLACEHOLDER_MARKERS):
        return None
    if is_non_local_reference(candidate):
        return None
    if "." in candidate and "/" not in candidate and "\\" not in candidate:
        if candidate not in ROOT_LOCAL_ARTIFACT_NAMES and not candidate.startswith("."):
            return None
    if resolve_repo_artifact(Path("."), candidate) is None:
        return None
    return candidate.split("#", 1)[0]


def should_ignore_workflow_asset(path: Path, *, repo_root: Path) -> bool:
    try:
        rel_path = path.relative_to(repo_root)
    except ValueError:
        rel_path = path
    root_name = rel_path.parts[0] if rel_path.parts else rel_path.name
    return root_name in HIDDEN_NON_REPO_WORKFLOW_ROOTS


def is_transient_knowledge_doc(document: Document) -> bool:
    if document.path.name == "AGENTS.md":
        return False
    if document.frontmatter.get("doc_type") == "exec-plan":
        return True
    if document.frontmatter.get("doc_type") in {"archive", "generated", "canonical"}:
        return False
    if document.frontmatter.get("status") == "verified":
        return False
    path_tokens = {
        token
        for part in Path(document.rel_path).with_suffix("").parts
        for token in re.split(r"[^a-z0-9]+", part.lower())
        if token
    }
    return bool(path_tokens & TRANSIENT_DOC_PATH_KEYWORDS)


def extract_promotion_rule_occurrences(document: Document) -> list[PromotionOccurrence]:
    seen_rules: set[str] = set()
    occurrences: list[PromotionOccurrence] = []
    for heading, depth, content in extract_sections(document.body):
        if depth < 2:
            continue
        if heading in PROMOTION_EXCLUDED_SECTION_HEADINGS:
            continue
        for block in promotion_candidate_blocks(content):
            statement = clean_promotion_statement(block)
            if not statement or not is_promotion_rule_candidate(statement):
                continue
            normalized_rule = normalize_promotion_rule(statement)
            if normalized_rule in seen_rules:
                continue
            seen_rules.add(normalized_rule)
            occurrences.append(
                PromotionOccurrence(
                    rel_path=document.rel_path,
                    section=heading,
                    statement=statement,
                    normalized_rule=normalized_rule,
                )
            )
    return occurrences


def promotion_candidate_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if current:
                blocks.append(" ".join(current))
                current = []
            continue
        if re.match(r"^[-*+]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            if current:
                blocks.append(" ".join(current))
            current = [stripped]
            continue
        current.append(stripped)
    if current:
        blocks.append(" ".join(current))
    return blocks


def clean_promotion_statement(block: str) -> str:
    cleaned = re.sub(r"^[-*+]\s+", "", block.strip())
    cleaned = re.sub(r"^\d+\.\s+", "", cleaned)
    cleaned = re.sub(r"^\d{4}-\d{2}-\d{2}:\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def is_promotion_rule_candidate(statement: str) -> bool:
    normalized = statement.strip()
    if not normalized:
        return False
    words = re.findall(r"[a-z0-9./-]+", normalized.lower())
    if len(words) < 7 or len(words) > 45:
        return False
    if not PROMOTION_RULE_SIGNAL_RE.search(normalized.lower()):
        return False
    if not any(anchor in normalized.lower() for anchor in PROMOTION_ANCHOR_KEYWORDS):
        return False
    content_words = {
        word
        for word in words
        if len(word) >= 4 and word not in PROMOTION_STOPWORDS
    }
    return len(content_words) >= 3


def normalize_promotion_rule(statement: str) -> str:
    normalized = statement.lower().replace("`", "")
    normalized = re.sub(r"\[[^\]]+\]\(([^)]+)\)", r"\1", normalized)
    normalized = re.sub(r"[^a-z0-9./]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _destination_suggestions_from_hints(
    hint_map: tuple[tuple[str, tuple[str, ...]], ...],
    *,
    normalized_rule: str,
    source_files: list[str],
    repo_root: Path,
) -> list[PromotionDestinationSuggestion]:
    lower_source_paths = " ".join(source_files).lower()
    suggestions: list[tuple[int, str, tuple[str, ...]]] = []
    for doc_path, hints in hint_map:
        if not (repo_root / doc_path).exists():
            continue
        matched_hints = tuple(
            hint for hint in hints if hint in normalized_rule or hint in lower_source_paths
        )
        if not matched_hints:
            continue
        suggestions.append((len(matched_hints), doc_path, matched_hints))

    suggestions.sort(key=lambda item: (-item[0], item[1]))
    return [
        PromotionDestinationSuggestion(rel_path=doc_path, reasons=matched_hints)
        for _, doc_path, matched_hints in suggestions[:3]
    ]


def _fallback_promotion_destination(
    *,
    documents: list[Document],
    source_files: list[str],
) -> list[PromotionDestinationSuggestion]:
    canonical_paths = {
        document.rel_path
        for document in documents
        if document.frontmatter.get("doc_type") == "canonical"
    }
    if not canonical_paths:
        return []

    if (
        any(path.startswith("docs/exec-plans/") for path in source_files)
        and "docs/design-docs/index.md" in canonical_paths
    ):
        return [
            PromotionDestinationSuggestion(
                rel_path="docs/design-docs/index.md",
                reasons=(
                    "fallback: exec-plan rules should promote through the design-docs canonical route",
                ),
            )
        ]

    if (
        any(
            keyword in path.lower()
            for path in source_files
            for keyword in TRANSIENT_DOC_PATH_KEYWORDS
        )
        and "docs/index.md" in canonical_paths
    ):
        return [
            PromotionDestinationSuggestion(
                rel_path="docs/index.md",
                reasons=(
                    "fallback: note and workaround docs should promote durable guidance through the docs index",
                ),
            )
        ]

    for rel_path in ("docs/index.md", "docs/design-docs/index.md"):
        if rel_path in canonical_paths:
            return [
                PromotionDestinationSuggestion(
                    rel_path=rel_path,
                    reasons=("fallback: nearest canonical routing doc in this repo",),
                )
            ]

    rel_path = sorted(canonical_paths)[0]
    return [
        PromotionDestinationSuggestion(
            rel_path=rel_path,
            reasons=("fallback: nearest canonical routing doc in this repo",),
        )
    ]


def infer_promotion_destination_docs(
    normalized_rule: str,
    *,
    source_files: list[str],
    documents: list[Document],
    repo_root: Path,
) -> list[PromotionDestinationSuggestion]:
    lower_source_paths = " ".join(source_files).lower()
    suggestions: list[tuple[int, str, tuple[str, ...]]] = []
    for doc_path, hints in CANONICAL_PROMOTION_DESTINATION_HINTS:
        if not (repo_root / doc_path).exists():
            continue
        matched_hints = tuple(
            hint for hint in hints if hint in normalized_rule or hint in lower_source_paths
        )
        if not matched_hints:
            continue
        suggestions.append((len(matched_hints), doc_path, matched_hints))
    suggestions.sort(key=lambda item: (-item[0], item[1]))
    if suggestions:
        return [
            PromotionDestinationSuggestion(rel_path=doc_path, reasons=matched_hints)
            for _, doc_path, matched_hints in suggestions[:3]
        ]
    return _fallback_promotion_destination(documents=documents, source_files=source_files)


def infer_supporting_promotion_destination_docs(
    normalized_rule: str,
    *,
    source_files: list[str],
    repo_root: Path,
) -> list[PromotionDestinationSuggestion]:
    return _destination_suggestions_from_hints(
        SUPPORTING_PROMOTION_DESTINATION_HINTS,
        normalized_rule=normalized_rule,
        source_files=source_files,
        repo_root=repo_root,
    )


def format_promotion_destination_suggestion(
    suggestion: PromotionDestinationSuggestion,
) -> str:
    return f"{suggestion.rel_path} (matched: {', '.join(suggestion.reasons)})"
