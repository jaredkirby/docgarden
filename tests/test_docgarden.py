from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docgarden.config import Config
from docgarden.fixers import apply_safe_fixes
from docgarden.scanner import scan_repo


CANONICAL_FRONTMATTER = """---
doc_id: docs-index
doc_type: canonical
domain: docs
owner: kirby
status: verified
last_reviewed: 2026-03-08
review_cycle_days: 30
source_of_truth:
  - AGENTS.md
verification:
  method: doc-reviewed
  confidence: medium
---
"""


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class DocgardenTests(unittest.TestCase):
    def make_repo(self) -> Path:
        temp_dir = Path(tempfile.mkdtemp())
        write(
            temp_dir / ".docgarden" / "config.yaml",
            "repo_name: test-docgarden\nstrict_score_fail_threshold: 70\n",
        )
        write(
            temp_dir / "AGENTS.md",
            "# AGENTS.md\n\n- Overview: docs/index.md\n",
        )
        return temp_dir

    def test_scan_clean_repo_has_no_findings(self) -> None:
        repo = self.make_repo()
        write(
            repo / "docs" / "index.md",
            CANONICAL_FRONTMATTER
            + """
# Docs Index

## Purpose
Text.

## Scope
Text.

## Source of Truth
Text.

## Rules / Definitions
Text.

## Exceptions / Caveats
Text.

## Validation / How to verify
Text.

## Related docs
Text.
""",
        )

        findings, domain_counts, _ = scan_repo(repo, Config.load(repo / ".docgarden" / "config.yaml"))

        self.assertEqual(findings, [])
        self.assertEqual(domain_counts["docs"], 1)

    def test_safe_fix_marks_stale_doc_needs_review(self) -> None:
        repo = self.make_repo()
        write(
            repo / "docs" / "index.md",
            CANONICAL_FRONTMATTER.replace("2026-03-08", "2026-01-01")
            + """
# Docs Index

## Purpose
Text.

## Scope
Text.

## Source of Truth
Text.

## Rules / Definitions
Text.

## Exceptions / Caveats
Text.

## Validation / How to verify
Text.

## Related docs
Text.
""",
        )

        findings, _, _ = scan_repo(repo, Config.load(repo / ".docgarden" / "config.yaml"))
        changed = apply_safe_fixes(repo, [item for item in findings if item.kind == "stale-review"])

        self.assertEqual(changed, ["docs/index.md"])
        self.assertIn("status: needs-review", (repo / "docs" / "index.md").read_text())

    def test_safe_fix_adds_missing_sections(self) -> None:
        repo = self.make_repo()
        write(
            repo / "docs" / "index.md",
            CANONICAL_FRONTMATTER
            + """
# Docs Index

## Purpose
Text.
""",
        )

        findings, _, _ = scan_repo(repo, Config.load(repo / ".docgarden" / "config.yaml"))
        changed = apply_safe_fixes(repo, [item for item in findings if item.kind == "missing-sections"])
        content = (repo / "docs" / "index.md").read_text()

        self.assertEqual(changed, ["docs/index.md"])
        self.assertIn("## Scope", content)
        self.assertIn("## Validation / How to verify", content)


if __name__ == "__main__":
    unittest.main()
