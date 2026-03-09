from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

FRONTMATTER_BOUNDARY = "---"
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
ROUTE_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])"
    r"(?P<path>(?:AGENTS\.md|docs/[A-Za-z0-9_./-]+(?:\.md)?))"
)


@dataclass(slots=True)
class Document:
    path: Path
    rel_path: str
    frontmatter: dict[str, Any]
    body: str
    headings: list[str]
    links: list[str]
    routed_paths: list[str]
    raw_text: str = field(repr=False)


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith(f"{FRONTMATTER_BOUNDARY}\n"):
        return {}, text

    parts = text.split(f"\n{FRONTMATTER_BOUNDARY}\n", 1)
    if len(parts) != 2:
        return {}, text

    yaml_text = parts[0][len(FRONTMATTER_BOUNDARY) + 1 :]
    body = parts[1]
    data = yaml.safe_load(yaml_text) or {}
    return data, body


def dump_frontmatter(data: dict[str, Any]) -> str:
    return (
        f"{FRONTMATTER_BOUNDARY}\n"
        f"{yaml.safe_dump(data, sort_keys=False).strip()}\n"
        f"{FRONTMATTER_BOUNDARY}\n"
    )


def replace_frontmatter(text: str, data: dict[str, Any]) -> str:
    _, body = split_frontmatter(text)
    return dump_frontmatter(data) + "\n" + body.lstrip("\n")


def normalize_heading(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def parse_document(path: Path, repo_root: Path) -> Document:
    raw_text = path.read_text()
    frontmatter, body = split_frontmatter(raw_text)
    headings = [match.group(2).strip() for match in HEADING_RE.finditer(body)]
    links = [match.group(1).strip() for match in MARKDOWN_LINK_RE.finditer(raw_text)]
    routed_paths = []
    for match in ROUTE_RE.finditer(raw_text):
        candidate = match.group("path").rstrip(".,)")
        if candidate != path.name:
            routed_paths.append(candidate)
    return Document(
        path=path,
        rel_path=str(path.relative_to(repo_root)),
        frontmatter=frontmatter,
        body=body,
        headings=headings,
        links=links,
        routed_paths=sorted(set(routed_paths)),
        raw_text=raw_text,
    )


def resolve_link_target(
    current_file: Path, repo_root: Path, target: str
) -> Path | None:
    if not target or target.startswith(("http://", "https://", "mailto:", "#")):
        return None

    clean_target = target.split("#", 1)[0]
    if not clean_target:
        return None

    candidate = Path(clean_target)
    if candidate.is_absolute():
        return candidate

    if clean_target.startswith("docs/") or clean_target == "AGENTS.md":
        return repo_root / clean_target

    return current_file.parent / clean_target
