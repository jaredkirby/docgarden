from __future__ import annotations

from pathlib import Path

from .markdown import replace_frontmatter, split_frontmatter
from .models import Finding


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
                    file_path.write_text(replace_frontmatter(raw, frontmatter))
                    changed_files.add(file_name)

            if finding.kind == "missing-sections":
                raw = file_path.read_text()
                missing_sections = finding.details.get("missing_sections", [])
                if not missing_sections:
                    continue
                additions = []
                for section in missing_sections:
                    additions.append(f"## {section}\n\nTODO: fill in.\n")
                updated = raw.rstrip() + "\n\n" + "\n".join(additions)
                file_path.write_text(updated + "\n")
                changed_files.add(file_name)

    return sorted(changed_files)
