from __future__ import annotations

import hashlib
import os
import re
import shlex
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from .markdown import (
    Document,
    extract_markdown_links,
    extract_sections,
    normalize_heading,
    resolve_link_target,
    section_content_map,
)
from .models import Finding, FindingContext
from .scan_document_rules import (
    document_context,
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


@dataclass(slots=True)
class GeneratedDocContract:
    issues: list[str]
    generated_at: datetime | None
    upstream_path: Path | None


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
    context = FindingContext(
        rel_path=document.rel_path,
        domain=str(document.frontmatter.get("domain", "unknown")),
        discovered_at=discovered_at,
    )
    for source in sources:
        target = resolve_repo_artifact(repo_root, source)
        if target is None or target.exists():
            continue
        findings.append(
            Finding.open_issue(
                context,
                kind="missing-source-artifact",
                severity="high",
                summary=f"{document.rel_path} references a missing source_of_truth artifact.",
                evidence=[f"Missing artifact: {source}"],
                recommended_action="Point source_of_truth at an existing local artifact.",
                safe_to_autofix=False,
                cluster="artifact-drift",
                suffix=stable_suffix("source", source),
            )
        )
    return findings


def invalid_validation_command_findings(
    document: Document,
    *,
    discovered_at: str,
) -> list[Finding]:
    context = FindingContext(
        rel_path=document.rel_path,
        domain=str(document.frontmatter.get("domain", "unknown")),
        discovered_at=discovered_at,
    )
    findings: list[Finding] = []
    for command in extract_validation_commands(document.body):
        if not is_docgarden_command(command):
            continue
        if is_supported_docgarden_command(command):
            continue
        findings.append(
            Finding.open_issue(
                context,
                kind="invalid-validation-command",
                severity="medium",
                summary=f"{document.rel_path} documents an unsupported docgarden command.",
                evidence=[f"Unsupported command: {command}"],
                recommended_action="Update the validation step to a supported docgarden CLI command.",
                safe_to_autofix=False,
                cluster="workflow-drift",
                suffix=stable_suffix("command", command),
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

    context = document_context(document, discovered_at=discovered_at)
    findings: list[Finding] = []
    for raw_reference, (heading, target) in sorted(references.items()):
        findings.append(
            Finding.open_issue(
                context,
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
                safe_to_autofix=False,
                cluster="workflow-drift",
                suffix=stable_suffix("asset", raw_reference),
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
