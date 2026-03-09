from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
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

GENERATED_FRONTMATTER = """---
doc_id: generated-reference
doc_type: generated
domain: generated
owner: kirby
status: verified
last_reviewed: 2026-03-08
review_cycle_days: 30
---
"""


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def write_docs_index(repo: Path, *, extra_body: str = "") -> None:
    write(
        repo / "docs" / "index.md",
        CANONICAL_FRONTMATTER
        + f"""
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
{extra_body}
""",
    )


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

    def test_scan_flags_missing_workflow_asset_reference(self) -> None:
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

- Run `scripts/check.sh`
- See [workflow helper](scripts/check.sh)

## Related docs
Text.
""",
        )

        findings, _, _ = scan_repo(repo)

        self.assertIn("missing-workflow-asset", [item.kind for item in findings])
        workflow_finding = next(item for item in findings if item.kind == "missing-workflow-asset")
        self.assertEqual(
            workflow_finding.id,
            "missing-workflow-asset::docs::index.md::"
            "asset-scripts-check-sh-d2dded7b17",
        )
        self.assertEqual(
            workflow_finding.evidence,
            [
                "Workflow section: validation how to verify",
                "Missing asset reference: scripts/check.sh",
                "Resolved local path: scripts/check.sh",
            ],
        )

    def test_scan_ignores_external_workflow_references(self) -> None:
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

- `curl https://example.com/install.sh`
- `python -m pytest`
- `.venv/bin/desloppify scan --path .`
- `python -m docgarden.cli scan`
- [Hosted guide](https://example.com/runbook)

## Related docs
Text.
""",
        )

        findings, _, _ = scan_repo(repo)

        self.assertEqual(findings, [])

    def test_scan_keeps_false_positives_low_for_design_doc_references(self) -> None:
        repo = self.make_repo()
        write_docs_index(repo)
        write(
            repo / "docs" / "design-docs" / "plan.md",
            CANONICAL_FRONTMATTER.replace("doc_id: docs-index", "doc_id: design-plan")
            + """
# Design Plan

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

- `uv run pytest`

## Related docs
Text.

## Atomic slices

- Files likely touched:
  - `scripts/missing.sh`
""",
        )

        findings, _, _ = scan_repo(repo)

        self.assertEqual(
            [
                item.kind
                for item in findings
                if item.files == ["docs/design-docs/plan.md"]
                and item.kind == "missing-workflow-asset"
            ],
            [],
        )

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

    def test_scan_flags_generated_doc_contract_issues(self) -> None:
        repo = self.make_repo()
        write_docs_index(repo, extra_body="\n- [Generated Schema](generated/schema.md)\n")
        write(
            repo / "docs" / "generated" / "schema.md",
            GENERATED_FRONTMATTER
            + """
# Generated Schema

## Generation source

## Generated timestamp

not-a-timestamp

## Upstream artifact path or script

`scripts/missing-generator.py`

## Regeneration command

Run the generator from CI.
""",
        )

        findings, _, _ = scan_repo(repo)

        self.assertEqual([item.kind for item in findings], ["generated-doc-contract"])
        self.assertEqual(
            findings[0].details["issues"],
            [
                "Generation source section must include provenance details.",
                "Generated timestamp section must include a valid offset-aware ISO-8601 timestamp.",
                "Upstream artifact path or script points to a missing local file: scripts/missing-generator.py",
                "Regeneration command section must include a runnable command snippet.",
            ],
        )

    def test_scan_flags_stale_generated_doc_against_local_upstream_file(self) -> None:
        repo = self.make_repo()
        write_docs_index(repo, extra_body="\n- [Generated Schema](generated/schema.md)\n")
        upstream = repo / "scripts" / "generate_schema.py"
        write(upstream, "print('schema')\n")
        upstream_time = datetime(2026, 3, 9, 14, 0, tzinfo=timezone.utc).timestamp()
        os.utime(upstream, (upstream_time, upstream_time))
        write(
            repo / "docs" / "generated" / "schema.md",
            GENERATED_FRONTMATTER
            + """
# Generated Schema

## Generation source

`scripts/generate_schema.py`

## Generated timestamp

`2026-03-09T12:00:00+00:00`

## Upstream artifact path or script

`scripts/generate_schema.py`

## Regeneration command

`uv run python scripts/generate_schema.py`
""",
        )

        findings, _, _ = scan_repo(repo)

        self.assertEqual([item.kind for item in findings], ["generated-doc-stale"])
        self.assertEqual(
            findings[0].evidence,
            [
                "generated_timestamp=2026-03-09T12:00:00+00:00",
                f"upstream_path={upstream}",
                "upstream_mtime=2026-03-09T14:00:00+00:00",
            ],
        )

    def test_scan_accepts_fresh_generated_doc_with_local_upstream_file(self) -> None:
        repo = self.make_repo()
        write_docs_index(repo, extra_body="\n- [Generated Schema](generated/schema.md)\n")
        upstream = repo / "scripts" / "generate_schema.py"
        write(upstream, "print('schema')\n")
        upstream_time = datetime(2026, 3, 9, 10, 0, tzinfo=timezone.utc).timestamp()
        os.utime(upstream, (upstream_time, upstream_time))
        write(
            repo / "docs" / "generated" / "schema.md",
            GENERATED_FRONTMATTER
            + """
# Generated Schema

## Generation source

`scripts/generate_schema.py`

## Generated timestamp

`2026-03-09T12:00:00+00:00`

## Upstream artifact path or script

`scripts/generate_schema.py`

## Regeneration command

`uv run python scripts/generate_schema.py`
""",
        )

        findings, _, _ = scan_repo(repo)

        self.assertEqual(findings, [])

    def test_scan_skips_generated_doc_freshness_for_non_local_source(self) -> None:
        repo = self.make_repo()
        write_docs_index(repo, extra_body="\n- [Generated Schema](generated/schema.md)\n")
        write(
            repo / "docs" / "generated" / "schema.md",
            GENERATED_FRONTMATTER
            + """
# Generated Schema

## Generation source

Partner export API

## Generated timestamp

`2026-03-09T12:00:00+00:00`

## Upstream artifact path or script

`https://example.com/schema.json`

## Regeneration command

`make docs-generated`
""",
        )

        findings, _, _ = scan_repo(repo)

        self.assertEqual(findings, [])

    def test_scan_skips_generated_doc_freshness_for_non_http_uri_source(self) -> None:
        repo = self.make_repo()
        write_docs_index(repo, extra_body="\n- [Generated Schema](generated/schema.md)\n")
        write(
            repo / "docs" / "generated" / "schema.md",
            GENERATED_FRONTMATTER
            + """
# Generated Schema

## Generation source

Partner object storage

## Generated timestamp

`2026-03-09T12:00:00+00:00`

## Upstream artifact path or script

`s3://bucket/schema.json`

## Regeneration command

`make docs-generated`
""",
        )

        findings, _, _ = scan_repo(repo)

        self.assertEqual(findings, [])

    def test_scan_skips_generated_doc_freshness_for_local_directory_source(self) -> None:
        repo = self.make_repo()
        write_docs_index(repo, extra_body="\n- [Generated Schema](generated/schema.md)\n")
        (repo / "scripts").mkdir(parents=True, exist_ok=True)
        write(
            repo / "docs" / "generated" / "schema.md",
            GENERATED_FRONTMATTER
            + """
# Generated Schema

## Generation source

`scripts`

## Generated timestamp

`2026-03-09T12:00:00+00:00`

## Upstream artifact path or script

`scripts`

## Regeneration command

`make docs-generated`
""",
        )

        findings, _, _ = scan_repo(repo)

        self.assertEqual(findings, [])

    def test_scan_flags_non_runnable_generated_doc_command_snippet(self) -> None:
        repo = self.make_repo()
        write_docs_index(repo, extra_body="\n- [Generated Schema](generated/schema.md)\n")
        write(
            repo / "docs" / "generated" / "schema.md",
            GENERATED_FRONTMATTER
            + """
# Generated Schema

## Generation source

`scripts/generate_schema.py`

## Generated timestamp

`2026-03-09T12:00:00+00:00`

## Upstream artifact path or script

`https://example.com/schema.json`

## Regeneration command

`scripts/generate_schema.py`
""",
        )

        findings, _, _ = scan_repo(repo)

        self.assertEqual([item.kind for item in findings], ["generated-doc-contract"])
        self.assertEqual(
            findings[0].details["issues"],
            [
                "Regeneration command section must include a runnable command snippet."
            ],
        )

    def test_scan_flags_naive_generated_timestamp(self) -> None:
        repo = self.make_repo()
        write_docs_index(repo, extra_body="\n- [Generated Schema](generated/schema.md)\n")
        upstream = repo / "scripts" / "generate_schema.py"
        write(upstream, "print('schema')\n")
        upstream_time = datetime(2026, 3, 9, 14, 0, tzinfo=timezone.utc).timestamp()
        os.utime(upstream, (upstream_time, upstream_time))
        write(
            repo / "docs" / "generated" / "schema.md",
            GENERATED_FRONTMATTER
            + """
# Generated Schema

## Generation source

`scripts/generate_schema.py`

## Generated timestamp

`2026-03-09T12:00:00`

## Upstream artifact path or script

`scripts/generate_schema.py`

## Regeneration command

`uv run python scripts/generate_schema.py`
""",
        )

        findings, _, _ = scan_repo(repo)

        self.assertEqual([item.kind for item in findings], ["generated-doc-contract"])
        self.assertEqual(
            findings[0].details["issues"],
            [
                "Generated timestamp section must include a valid offset-aware ISO-8601 timestamp."
            ],
        )


if __name__ == "__main__":
    unittest.main()
