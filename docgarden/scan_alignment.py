from __future__ import annotations

import hashlib
import re
import shlex
from pathlib import Path

from .markdown import Document, normalize_heading
from .models import Finding, FindingContext

SECTION_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
FENCED_BLOCK_RE = re.compile(r"```(?:bash|sh|shell)?\n(.*?)```", re.DOTALL)
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
    if not document.frontmatter:
        return []
    if document.frontmatter.get("status") == "draft":
        return []

    findings: list[Finding] = []
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
    if not candidate or candidate.startswith(("http://", "https://", "mailto:")):
        return None
    if any(char.isspace() for char in candidate):
        return None

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


def extract_validation_commands(body: str) -> list[str]:
    sections = extract_sections(body)
    commands: list[str] = []
    for heading, _, content in sections:
        if heading not in {"validation", "validation how to verify"}:
            continue
        commands.extend(extract_commands_from_text(content))
    return sorted(set(commands))


def extract_sections(body: str) -> list[tuple[str, int, str]]:
    matches = list(SECTION_HEADING_RE.finditer(body))
    sections: list[tuple[str, int, str]] = []
    for index, match in enumerate(matches):
        depth = len(match.group(1))
        start = match.end()
        end = len(body)
        for next_match in matches[index + 1 :]:
            next_depth = len(next_match.group(1))
            if next_depth <= depth:
                end = next_match.start()
                break
        sections.append(
            (normalize_heading(match.group(2)), depth, body[start:end].strip())
        )
    return sections


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
    if command_name == "show":
        return len(rest) == 1 and not rest[0].startswith("-")
    if command_name == "quality":
        return rest == ["write"]
    if command_name == "fix":
        return rest in (["safe"], ["safe", "--apply"])
    if command_name == "config":
        return rest == ["show"]
    return False


def tokenize_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []
