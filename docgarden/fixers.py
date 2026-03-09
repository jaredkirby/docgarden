from __future__ import annotations

import re
from pathlib import Path

from .files import atomic_write_text
from .markdown import replace_frontmatter, split_frontmatter
from .models import Finding

MARKDOWN_LINK_RE = re.compile(r"(\[[^\]]+\]\()([^)]+)(\))")
ROUTE_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])(?P<path>(?:AGENTS\.md|docs/[A-Za-z0-9_./-]+(?:\.md)?))"
)


def preview_safe_fixes(repo_root: Path, findings: list[Finding]) -> list[dict[str, object]]:
    planned: list[dict[str, object]] = []
    for finding in findings:
        file_name = finding.files[0] if finding.files else None
        if file_name is None or not (repo_root / file_name).exists():
            continue
        changes = describe_safe_fix(finding)
        if not changes:
            continue
        planned.append(
            {
                "id": finding.id,
                "kind": finding.kind,
                "files": finding.files,
                "changes": changes,
            }
        )
    return planned


def apply_safe_fixes(repo_root: Path, findings: list[Finding]) -> list[str]:
    changed_files: set[str] = set()

    for finding in findings:
        for file_name in finding.files:
            file_path = repo_root / file_name
            if not file_path.exists():
                continue

            if finding.kind == "stale-review":
                raw = file_path.read_text()
                frontmatter, _ = split_frontmatter(raw)
                if not frontmatter:
                    continue
                if frontmatter.get("status") != "needs-review":
                    frontmatter["status"] = "needs-review"
                    atomic_write_text(file_path, replace_frontmatter(raw, frontmatter))
                    changed_files.add(file_name)

            elif finding.kind == "missing-sections":
                raw = file_path.read_text()
                missing_sections = finding.details.get("missing_sections", [])
                if not missing_sections:
                    continue
                additions = []
                for section in missing_sections:
                    additions.append(f"## {section}\n\nTODO: fill in.\n")
                updated = raw.rstrip() + "\n\n" + "\n".join(additions)
                atomic_write_text(file_path, updated + "\n")
                changed_files.add(file_name)

            elif finding.kind == "missing-metadata":
                raw = file_path.read_text()
                frontmatter, _ = split_frontmatter(raw)
                if not frontmatter:
                    continue
                metadata_updates = finding.details.get("metadata_updates", {})
                if not isinstance(metadata_updates, dict) or not metadata_updates:
                    continue
                changed = False
                for key, value in metadata_updates.items():
                    if key in frontmatter:
                        continue
                    frontmatter[key] = value
                    changed = True
                if changed:
                    atomic_write_text(file_path, replace_frontmatter(raw, frontmatter))
                    changed_files.add(file_name)

            elif finding.kind == "broken-link":
                raw = file_path.read_text()
                original_link = finding.details.get("broken_link")
                replacement_link = finding.details.get("replacement_link")
                if not isinstance(original_link, str) or not isinstance(
                    replacement_link, str
                ):
                    continue
                updated = _replace_markdown_link_targets(
                    raw,
                    original=original_link,
                    replacement=replacement_link,
                )
                if updated != raw:
                    atomic_write_text(file_path, updated)
                    changed_files.add(file_name)

            elif finding.kind in {"broken-route", "stale-route"}:
                raw = file_path.read_text()
                replacements = finding.details.get("route_replacements", [])
                if not isinstance(replacements, list) or not replacements:
                    continue
                updated = raw
                for replacement in replacements:
                    if not isinstance(replacement, dict):
                        continue
                    original = replacement.get("from")
                    new_value = replacement.get("to")
                    if not isinstance(original, str) or not isinstance(new_value, str):
                        continue
                    updated = _replace_markdown_link_targets(
                        updated,
                        original=original,
                        replacement=new_value,
                    )
                    updated = _replace_route_tokens(
                        updated,
                        original=original,
                        replacement=new_value,
                    )
                if updated != raw:
                    atomic_write_text(file_path, updated)
                    changed_files.add(file_name)

    return sorted(changed_files)


def describe_safe_fix(finding: Finding) -> list[str]:
    if finding.kind == "stale-review":
        return ["Set `status` to `needs-review`."]
    if finding.kind == "missing-sections":
        missing_sections = finding.details.get("missing_sections", [])
        if not missing_sections:
            return []
        return ["Add required headings: " + ", ".join(missing_sections) + "."]
    if finding.kind == "missing-metadata":
        metadata_updates = finding.details.get("metadata_updates", {})
        if not isinstance(metadata_updates, dict) or not metadata_updates:
            return []
        fields = ", ".join(sorted(metadata_updates))
        return [f"Add metadata skeleton fields: {fields}."]
    if finding.kind == "broken-link":
        original = finding.details.get("broken_link")
        replacement = finding.details.get("replacement_link")
        if isinstance(original, str) and isinstance(replacement, str):
            return [f"Replace markdown link target `{original}` with `{replacement}`."]
        return []
    if finding.kind in {"broken-route", "stale-route"}:
        replacements = finding.details.get("route_replacements", [])
        if not isinstance(replacements, list):
            return []
        changes: list[str] = []
        for replacement in replacements:
            if not isinstance(replacement, dict):
                continue
            original = replacement.get("from")
            new_value = replacement.get("to")
            if isinstance(original, str) and isinstance(new_value, str):
                changes.append(
                    f"Replace route reference `{original}` with `{new_value}`."
                )
        return changes
    return []


def _replace_markdown_link_targets(text: str, *, original: str, replacement: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        if match.group(2) != original:
            return match.group(0)
        return f"{match.group(1)}{replacement}{match.group(3)}"

    return MARKDOWN_LINK_RE.sub(_replace, text)


def _replace_route_tokens(text: str, *, original: str, replacement: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        if match.group("path") != original:
            return match.group(0)
        return replacement

    return ROUTE_TOKEN_RE.sub(_replace, text)
