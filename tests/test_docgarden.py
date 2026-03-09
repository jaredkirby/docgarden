from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docgarden.errors import DocgardenError
from docgarden.fixers import apply_safe_fixes
from docgarden.scanner import determine_changed_docs, scan_changed_files, scan_repo


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

        findings, domain_counts, _ = scan_repo(repo)

        self.assertEqual(findings, [])
        self.assertEqual(domain_counts["docs"], 1)

    def test_scan_changed_files_only_reports_requested_subset(self) -> None:
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
        write(
            repo / "docs" / "extra.md",
            CANONICAL_FRONTMATTER.replace("doc_id: docs-index", "doc_id: extra-doc")
            + """
# Extra Doc

## Purpose
Text.
""",
        )

        selection = determine_changed_docs(repo, provided_files=["docs/extra.md"])
        findings, domain_counts, documents = scan_changed_files(repo, selection=selection)

        self.assertEqual(selection.scanned_files, ["docs/extra.md"])
        self.assertEqual([document.rel_path for document in documents], ["docs/extra.md"])
        self.assertEqual(domain_counts["docs"], 1)
        self.assertTrue(findings)
        self.assertTrue(all(item.files == ["docs/extra.md"] for item in findings))

    def test_determine_changed_docs_rejects_non_doc_paths(self) -> None:
        repo = self.make_repo()

        with self.assertRaises(DocgardenError):
            determine_changed_docs(repo, provided_files=["README.md"])

    def test_determine_changed_docs_rejects_missing_explicit_files(self) -> None:
        repo = self.make_repo()

        with self.assertRaises(DocgardenError):
            determine_changed_docs(repo, provided_files=["docs/missing.md"])

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

        findings, _, _ = scan_repo(repo)
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

        findings, _, _ = scan_repo(repo)
        changed = apply_safe_fixes(repo, [item for item in findings if item.kind == "missing-sections"])
        content = (repo / "docs" / "index.md").read_text()

        self.assertEqual(changed, ["docs/index.md"])
        self.assertIn("## Scope", content)
        self.assertIn("## Validation / How to verify", content)

    def test_scan_flags_missing_source_of_truth_artifact(self) -> None:
        repo = self.make_repo()
        write(
            repo / "docs" / "index.md",
            CANONICAL_FRONTMATTER.replace("- AGENTS.md", "- scripts/missing.sh")
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

        findings, _, _ = scan_repo(repo)

        self.assertEqual([item.kind for item in findings], ["missing-source-artifact"])
        self.assertEqual(
            findings[0].id,
            "missing-source-artifact::docs::index.md::"
            "source-scripts-missing-sh-0d86f33576",
        )

    def test_scan_flags_invalid_docgarden_validation_command(self) -> None:
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

- `docgarden review prepare`

## Related docs
Text.
""",
        )

        findings, _, _ = scan_repo(repo)

        self.assertEqual([item.kind for item in findings], ["invalid-validation-command"])
        self.assertEqual(
            findings[0].id,
            "invalid-validation-command::docs::index.md::"
            "command-docgarden-review-prepare-a6b2277df6",
        )

    def test_scan_flags_invalid_docgarden_validation_command_in_subheading(self) -> None:
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

### Commands

- `docgarden review prepare`

## Related docs
Text.
""",
        )

        findings, _, _ = scan_repo(repo)

        self.assertEqual([item.kind for item in findings], ["invalid-validation-command"])

    def test_scan_skips_alignment_checks_for_draft_docs(self) -> None:
        repo = self.make_repo()
        write(
            repo / "docs" / "proposal.md",
            CANONICAL_FRONTMATTER.replace("doc_id: docs-index", "doc_id: proposal-doc")
            .replace("status: verified", "status: draft")
            .replace("- AGENTS.md", "- scripts/future.py")
            + """
# Proposal

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

- `docgarden review prepare --domains docs`

## Related docs
Text.
""",
        )
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

- [Proposal](proposal.md)
""",
        )

        findings, _, _ = scan_repo(repo)

        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
