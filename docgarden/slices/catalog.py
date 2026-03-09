from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any

from ..errors import DocgardenError
from .config import SliceAutomationPaths, build_slice_paths


@dataclass(frozen=True, slots=True)
class SliceDefinition:
    slice_id: str
    title: str
    status: str
    goal: str
    depends_on: list[str]
    changes: list[str]
    likely_files: list[str]
    acceptance: list[str]


@dataclass(frozen=True, slots=True)
class SliceCatalog:
    ordered_slices: list[SliceDefinition]

    def by_id(self, slice_id: str) -> SliceDefinition:
        for item in self.ordered_slices:
            if item.slice_id == slice_id:
                return item
        raise DocgardenError(f"Unknown slice: {slice_id}.")

    def next_actionable_slice(self, *, start_at: str | None = None) -> SliceDefinition | None:
        seen_start = start_at is None
        for item in self.ordered_slices:
            if not seen_start:
                if item.slice_id != start_at:
                    continue
                seen_start = True
            if item.status in {"queued", "active"}:
                return item
        return None

    def next_after(self, slice_id: str) -> SliceDefinition | None:
        found = False
        for item in self.ordered_slices:
            if not found:
                if item.slice_id == slice_id:
                    found = True
                continue
            if item.status in {"queued", "active"}:
                return item
        return None


SUMMARY_ROW_RE = re.compile(
    r"^\|\s*(S\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$"
)
SECTION_RE = re.compile(r"^### (S\d+): (.+)$", re.MULTILINE)


def load_slice_catalog(
    repo_root: Path,
    *,
    paths: SliceAutomationPaths | None = None,
) -> SliceCatalog:
    resolved_paths = paths or build_slice_paths(repo_root)
    doc_path = resolved_paths.implementation_slices
    if not doc_path.exists():
        raise DocgardenError(
            f"Missing slice backlog doc: {doc_path.relative_to(repo_root) if doc_path.is_relative_to(repo_root) else doc_path}."
        )

    text = doc_path.read_text(encoding="utf-8")
    summaries = _parse_slice_summary(text)
    sections = _parse_slice_sections(text)

    ordered: list[SliceDefinition] = []
    for slice_id, summary in summaries.items():
        section = sections.get(slice_id)
        if section is None:
            raise DocgardenError(
                f"Slice backlog is missing a detailed section for {slice_id}."
            )
        ordered.append(
            SliceDefinition(
                slice_id=slice_id,
                title=summary["title"],
                status=summary["status"],
                goal=section["goal"],
                depends_on=summary["depends_on"],
                changes=section["changes"],
                likely_files=section["likely_files"],
                acceptance=section["acceptance"],
            )
        )
    return SliceCatalog(ordered_slices=ordered)


def _parse_slice_summary(text: str) -> dict[str, dict[str, Any]]:
    in_summary = False
    summary: dict[str, dict[str, Any]] = {}
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line == "## Slice summary":
            in_summary = True
            continue
        if in_summary and line.startswith("## ") and line != "## Slice summary":
            break
        if not in_summary or not line.startswith("|"):
            continue
        match = SUMMARY_ROW_RE.match(line)
        if not match:
            continue
        slice_id, status, title, depends_raw = match.groups()
        if slice_id == "Slice":
            continue
        depends_on = [] if depends_raw.strip() == "none" else [
            item.strip() for item in depends_raw.split(",") if item.strip()
        ]
        summary[slice_id] = {
            "status": status.strip(),
            "title": title.strip(),
            "depends_on": depends_on,
        }
    if not summary:
        raise DocgardenError("Could not parse any slices from the summary table.")
    return summary


def _parse_slice_sections(text: str) -> dict[str, dict[str, Any]]:
    matches = list(SECTION_RE.finditer(text))
    sections: dict[str, dict[str, Any]] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end]
        sections[match.group(1)] = {
            "goal": _extract_single_value(body, "Goal:"),
            "changes": _extract_bullets(body, "Changes:"),
            "likely_files": _extract_bullets(body, "Files likely touched:"),
            "acceptance": _extract_bullets(body, "Acceptance:"),
        }
    return sections


def _extract_single_value(section_text: str, header: str) -> str:
    lines = section_text.splitlines()
    for index, raw_line in enumerate(lines):
        if raw_line.strip() != header:
            continue
        collected: list[str] = []
        for candidate in lines[index + 1 :]:
            stripped = candidate.strip()
            if not stripped:
                if collected:
                    break
                continue
            if stripped.endswith(":") and not stripped.startswith("- "):
                break
            if stripped.startswith("- "):
                collected.append(stripped[2:].strip())
            else:
                collected.append(stripped)
        value = " ".join(part for part in collected if part).strip()
        if value:
            return value
    raise DocgardenError(f"Could not parse `{header}` from slice backlog.")


def _extract_bullets(section_text: str, header: str) -> list[str]:
    lines = section_text.splitlines()
    for index, raw_line in enumerate(lines):
        if raw_line.strip() != header:
            continue
        bullets: list[str] = []
        for candidate in lines[index + 1 :]:
            stripped = candidate.strip()
            if not stripped:
                if bullets:
                    break
                continue
            if stripped.endswith(":") and not stripped.startswith("- "):
                break
            if stripped.startswith("- "):
                bullets.append(stripped[2:].strip())
                continue
            if bullets:
                bullets[-1] = f"{bullets[-1]} {stripped}"
        return bullets
    return []
