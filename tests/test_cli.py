from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from docgarden.cli import build_parser, main
from docgarden.cli_commands import repo_paths
from docgarden.scan_workflow import run_scan
from docgarden.state import (
    append_finding_status_event,
    load_findings_history,
    load_plan,
    load_score,
)

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


def make_repo(tmp_path: Path) -> Path:
    write(
        tmp_path / ".docgarden" / "config.yaml",
        "repo_name: test-docgarden\nstrict_score_fail_threshold: 70\n",
    )
    write(
        tmp_path / "AGENTS.md",
        "# AGENTS.md\n\n- Overview: docs/index.md\n",
    )
    write(
        tmp_path / "docs" / "index.md",
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
    return tmp_path


def write_exec_plan(repo: Path, rel_path: str, *, include_progress: bool = True) -> None:
    progress_section = (
        """
## Progress
Text.
"""
        if include_progress
        else ""
    )
    write(
        repo / rel_path,
        """---
doc_id: active-plan
doc_type: exec-plan
domain: exec-plans
owner: kirby
status: draft
last_reviewed: 2026-03-09
review_cycle_days: 14
source_of_truth:
  - docs/design-docs/docgarden-spec.md
verification:
  method: doc-reviewed
  confidence: medium
---

# Active Plan

## Purpose
Text.

## Context
Text.

## Assumptions
Text.

## Steps / Milestones
Text.

## Validation
Text.
"""
        + progress_section
        + """
## Discoveries
Text.

## Decision Log
Text.

## Outcomes / Retrospective
Text.
""",
    )


def init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "docgarden@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Docgarden Tests"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_cli_scan_status_and_plan_commands(tmp_path, monkeypatch, capsys) -> None:
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)

    assert main(["scan"]) == 0
    scan_output = json.loads(capsys.readouterr().out)
    assert scan_output["findings"] == 0

    assert main(["status"]) == 0
    status_output = json.loads(capsys.readouterr().out)
    assert status_output["active_findings"] == 0

    assert main(["plan"]) == 0
    plan_output = json.loads(capsys.readouterr().out)
    assert plan_output["current_focus"] is None
    assert plan_output["stage_notes"] == {}
    assert plan_output["strategy_text"] is None

    assert main(["doctor"]) == 0
    doctor_output = json.loads(capsys.readouterr().out)
    assert doctor_output["docs_exists"] is True
    assert doctor_output["agents_exists"] is True


def test_cli_ci_check_passes_clean_repo(tmp_path, monkeypatch, capsys) -> None:
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)

    assert main(["scan"]) == 0
    capsys.readouterr()

    assert main(["ci", "check"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["passed"] is True
    assert payload["failures"] == []
    assert payload["strict_score"] == 100


def test_cli_ci_check_reports_threshold_and_blocking_rules(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / ".docgarden" / "config.yaml",
        """repo_name: test-docgarden
strict_score_fail_threshold: 95
block_on:
  - broken_agents_routes
  - missing_frontmatter_on_canonical
  - stale_verified_canonical_docs
  - active_exec_plan_missing_progress
""",
    )
    write(
        repo / "AGENTS.md",
        "# AGENTS.md\n\n- Overview: docs/index.md\n- Broken route: docs/missing.md\n",
    )
    write(
        repo / "docs" / "index.md",
        CANONICAL_FRONTMATTER.replace("2026-03-08", "2025-01-01")
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
    write(repo / "docs" / "missing-frontmatter.md", "# Missing Frontmatter\n")
    write_exec_plan(
        repo,
        "docs/exec-plans/active/2026-03-09-missing-progress.md",
        include_progress=False,
    )
    monkeypatch.chdir(repo)

    assert main(["scan"]) == 0
    capsys.readouterr()

    assert main(["ci", "check"]) == 2
    payload = json.loads(capsys.readouterr().out)

    assert payload["passed"] is False
    failure_types = {item["type"] for item in payload["failures"]}
    assert "strict_score_fail_threshold" in failure_types
    blocking_rules = {
        item["rule"]
        for item in payload["failures"]
        if item["type"] == "blocking_rule"
    }
    assert blocking_rules == {
        "broken_agents_routes",
        "missing_frontmatter_on_canonical",
        "stale_verified_canonical_docs",
        "active_exec_plan_missing_progress",
    }


def test_cli_review_prepare_and_import_commands(tmp_path, monkeypatch, capsys) -> None:
    repo = make_repo(tmp_path)
    write(repo / "docs" / "notes.md", "# Scratch Notes\n\nMissing frontmatter.\n")
    monkeypatch.chdir(repo)

    assert main(["review", "prepare", "--domains", "docs"]) == 0
    prepare_output = json.loads(capsys.readouterr().out)
    packet_path = Path(prepare_output["path"])

    assert prepare_output["domains"] == ["docs"]
    assert prepare_output["documents"] == ["docs/index.md"]
    assert prepare_output["skipped_documents"] == [
        {"rel_path": "docs/notes.md", "reason": "missing_frontmatter"}
    ]
    assert packet_path.exists()

    import_path = repo / "review.json"
    import_path.write_text(
        json.dumps(
            {
                "packet_id": prepare_output["packet_id"],
                "review_id": "docs-review",
                "provenance": {"runner": "manual", "reviewer": "kirby"},
                "findings": [
                    {
                        "id": "clarify-purpose",
                        "summary": "The purpose section is too terse.",
                        "severity": "medium",
                        "files": ["docs/index.md"],
                        "evidence": ["The Purpose section only says `Text.`"],
                        "recommended_action": "Describe the contract for readers.",
                        "confidence": "high",
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )

    assert main(["review", "import", str(import_path)]) == 0
    import_output = json.loads(capsys.readouterr().out)

    assert import_output["review_id"] == "docs-review"
    assert import_output["packet_id"] == prepare_output["packet_id"]
    assert len(import_output["finding_ids"]) == 1
    assert Path(import_output["stored_review"]).exists()
    latest = load_findings_history(repo_paths(repo).findings)
    assert latest[-1]["finding_source"] == "subjective_review"
    assert latest[-1]["event"] == "review_imported"


def test_cli_review_import_accepts_zero_finding_review(tmp_path, monkeypatch, capsys) -> None:
    repo = make_repo(tmp_path)
    monkeypatch.chdir(repo)

    assert main(["review", "prepare", "--domains", "docs"]) == 0
    prepare_output = json.loads(capsys.readouterr().out)

    import_path = repo / "review.json"
    import_path.write_text(
        json.dumps(
            {
                "packet_id": prepare_output["packet_id"],
                "review_id": "docs-clean-pass",
                "provenance": {"runner": "manual", "reviewer": "kirby"},
                "findings": [],
            },
            indent=2,
        )
        + "\n"
    )

    assert main(["review", "import", str(import_path)]) == 0
    import_output = json.loads(capsys.readouterr().out)

    assert import_output["review_id"] == "docs-clean-pass"
    assert import_output["packet_id"] == prepare_output["packet_id"]
    assert import_output["finding_ids"] == []
    assert Path(import_output["stored_review"]).exists()
    assert not repo_paths(repo).findings.exists()


def test_cli_scan_changed_scope_uses_git_state_and_keeps_full_scan_state(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    init_git_repo(repo)
    monkeypatch.chdir(repo)

    assert main(["scan"]) == 0
    capsys.readouterr()

    paths = repo_paths(repo)
    baseline_findings = paths.findings.read_text() if paths.findings.exists() else ""
    baseline_plan = paths.plan.read_text()
    baseline_score = paths.score.read_text()

    write(
        repo / "docs" / "index.md",
        CANONICAL_FRONTMATTER
        + """
# Docs Index

## Purpose
Text.
""",
    )

    assert main(["scan", "--scope", "changed"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["scope"] == "changed"
    assert payload["findings"] == 1
    assert payload["overall_score"] is None
    assert payload["strict_score"] is None
    assert payload["last_full_scan_overall_score"] == 100
    assert payload["last_full_scan_strict_score"] == 100
    assert payload["changed_files_source"] == "git"
    assert payload["requested_files"] == ["docs/index.md"]
    assert payload["scanned_files"] == ["docs/index.md"]
    assert payload["deleted_files"] == []
    assert "repo-wide orphan-doc checks" in payload["skipped_views"]
    assert any(
        "Git-derived changed scope includes unstaged, staged, untracked, and deleted"
        in note
        for note in payload["notes"]
    )
    assert any(
        "do not rewrite `.docgarden/findings.jsonl`" in note
        for note in payload["notes"]
    )

    assert (paths.findings.read_text() if paths.findings.exists() else "") == baseline_findings
    assert paths.plan.read_text() == baseline_plan
    assert paths.score.read_text() == baseline_score


def test_cli_scan_persists_score_trends_and_weighted_rollups(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / ".docgarden" / "config.yaml",
        """repo_name: test-docgarden
strict_score_fail_threshold: 70
critical_domains:
  - docs
domain_weights:
  docs: 4
""",
    )
    monkeypatch.chdir(repo)

    assert main(["scan"]) == 0
    capsys.readouterr()

    first_score = load_score(repo_paths(repo).score)
    assert first_score is not None
    assert first_score.rollup["weighted_score"] == 100
    assert len(first_score.trend["points"]) == 1

    write(
        repo / "docs" / "index.md",
        CANONICAL_FRONTMATTER
        + """
# Docs Index

## Purpose
Text.
""",
    )

    assert main(["scan"]) == 0
    scan_output = json.loads(capsys.readouterr().out)
    updated_score = load_score(repo_paths(repo).score)

    assert scan_output["overall_score"] == 99
    assert updated_score is not None
    assert updated_score.rollup["weighted_score"] == 92
    assert updated_score.rollup["weights"] == {"docs": 4}
    assert updated_score.rollup["critical_regressions"] == [
        {"domain": "docs", "score": 92, "previous_score": 100, "delta": -8}
    ]
    assert updated_score.trend["summary"]["weighted_rollup_delta"] == -8
    assert len(updated_score.trend["points"]) == 2


def test_cli_next_show_and_fix_safe_commands(tmp_path, monkeypatch, capsys) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "docs" / "stale.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "stale-doc").replace(
            "2026-03-08", "2026-01-01"
        )
        + """
# Stale Doc

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
    monkeypatch.chdir(repo)

    assert main(["scan"]) == 0
    capsys.readouterr()

    assert main(["next"]) == 0
    next_payload = json.loads(capsys.readouterr().out)
    assert next_payload["kind"] == "stale-review"

    assert main(["show", next_payload["id"]]) == 0
    show_payload = json.loads(capsys.readouterr().out)
    assert show_payload["files"] == ["docs/stale.md"]

    assert main(["fix", "safe"]) == 0
    preview_payload = json.loads(capsys.readouterr().out)
    assert next_payload["id"] in preview_payload["fixable"]
    assert preview_payload["planned_changes"] == [
        {
            "changes": ["Set `status` to `needs-review`."],
            "files": ["docs/stale.md"],
            "id": next_payload["id"],
            "kind": "stale-review",
        }
    ]

    assert main(["fix", "safe", "--apply"]) == 0
    applied_payload = json.loads(capsys.readouterr().out)
    assert applied_payload["changed_files"] == ["docs/stale.md"]
    assert next_payload["id"] not in set(applied_payload.get("fixable", []))
    assert "status: needs-review" in (repo / "docs" / "stale.md").read_text()

    assert main(["show", next_payload["id"]]) == 0
    refreshed_payload = json.loads(capsys.readouterr().out)
    assert refreshed_payload["status"] == "fixed"
    assert refreshed_payload["event"] == "resolved"


def test_cli_pr_draft_summarizes_active_findings_and_changed_files(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    init_git_repo(repo)
    write(
        repo / "docs" / "stale.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "stale-doc").replace(
            "2026-03-08", "2026-01-01"
        )
        + """
# Stale Doc

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
    monkeypatch.chdir(repo)

    assert main(["pr", "draft"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["mode"] == "pr"
    assert payload["finding_count"] == 2
    assert payload["changed_files"] == ["docs/stale.md"]
    assert payload["publish_ready"] is False
    assert payload["publish_target"]["enabled"] is False
    finding_ids = {finding["id"] for finding in payload["findings"]}
    assert "stale-review::docs::stale.md::stale" in finding_ids
    assert "orphan-doc::docs::stale.md::orphan" in finding_ids
    assert "stale-review::docs::stale.md::stale" in payload["body"]
    assert "`docs/stale.md`" in payload["body"]
    assert ".docgarden/score.json" not in payload["body"]


def test_cli_pr_draft_can_focus_unsafe_findings_as_issue(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    init_git_repo(repo)
    write(
        repo / "docs" / "stale.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "stale-doc").replace(
            "2026-03-08", "2026-01-01"
        )
        + """
# Stale Doc

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
    write(repo / "docs" / "notes.md", "# Scratch Notes\n\nMissing frontmatter.\n")
    monkeypatch.chdir(repo)

    assert main(["pr", "draft", "--unsafe-as-issue"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["mode"] == "issue"
    assert payload["finding_count"] == len(payload["unsafe_finding_ids"])
    assert payload["finding_ids"] == payload["unsafe_finding_ids"]
    assert len(payload["safe_finding_ids"]) == 1
    assert set(payload["changed_files"]) == {"docs/notes.md", "docs/stale.md"}
    assert "missing required frontmatter" in payload["body"]
    assert "past its review cycle" not in payload["body"]


def test_cli_pr_draft_omits_accepted_debt_findings_from_scope(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    init_git_repo(repo)
    write(
        repo / "docs" / "stale.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "stale-doc").replace(
            "2026-03-08", "2026-01-01"
        )
        + """
# Stale Doc

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
    write(repo / "docs" / "notes.md", "# Scratch Notes\n\nMissing frontmatter.\n")
    monkeypatch.chdir(repo)

    assert main(["scan"]) == 0
    capsys.readouterr()

    paths = repo_paths(repo)
    stale_finding = next(
        event
        for event in load_findings_history(paths.findings)
        if event["kind"] == "stale-review"
    )
    append_finding_status_event(
        paths.findings,
        stale_finding["id"],
        status="accepted_debt",
        event_at=datetime(2026, 3, 8, 13, 0, 0),
        attestation="Known stale doc accepted until manual review lands.",
        resolved_by="kirby",
    )

    assert main(["pr", "draft"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert stale_finding["id"] not in payload["finding_ids"]
    assert all(
        finding["status"] in {"open", "in_progress", "needs_human"}
        for finding in payload["findings"]
    )
    assert "accepted_debt" not in payload["body"]
    assert "missing-frontmatter" in {
        finding["kind"] for finding in payload["findings"]
    }


def test_cli_pr_draft_publish_requires_explicit_support_and_credentials(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    init_git_repo(repo)
    write(
        repo / "docs" / "stale.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "stale-doc").replace(
            "2026-03-08", "2026-01-01"
        )
        + """
# Stale Doc

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
    monkeypatch.chdir(repo)

    assert main(["pr", "draft", "--publish"]) == 1
    error_output = capsys.readouterr().err

    assert "Cannot publish draft" in error_output
    assert "pr_drafts.enabled: true" in error_output


def test_cli_pr_draft_publish_rejects_empty_pr_scope(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / ".docgarden" / "config.yaml",
        """repo_name: test-docgarden
strict_score_fail_threshold: 70
pr_drafts:
  enabled: true
  provider: github
  repository: acme/docgarden
  base_branch: main
  token_env_var: DOCGARDEN_GITHUB_TOKEN
""",
    )
    init_git_repo(repo)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("DOCGARDEN_GITHUB_TOKEN", "test-token")

    assert main(["pr", "draft"]) == 0
    preview_payload = json.loads(capsys.readouterr().out)

    assert preview_payload["finding_count"] == 0
    assert preview_payload["publish_ready"] is False
    assert any(
        "at least one actionable finding in scope" in blocker
        for blocker in preview_payload["publish_blockers"]
    )

    assert main(["pr", "draft", "--publish"]) == 1
    error_output = capsys.readouterr().err

    assert "Cannot publish draft" in error_output
    assert "at least one actionable finding in scope" in error_output


def test_cli_pr_draft_publish_reports_remote_result(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / ".docgarden" / "config.yaml",
        """repo_name: test-docgarden
strict_score_fail_threshold: 70
pr_drafts:
  enabled: true
  provider: github
  repository: acme/docgarden
  base_branch: main
  token_env_var: DOCGARDEN_GITHUB_TOKEN
""",
    )
    init_git_repo(repo)
    write(
        repo / "docs" / "stale.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "stale-doc").replace(
            "2026-03-08", "2026-01-01"
        )
        + """
# Stale Doc

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
    monkeypatch.chdir(repo)
    monkeypatch.setenv("DOCGARDEN_GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        "docgarden.cli_commands.publish_pr_draft",
        lambda repo_root, config, payload: {
            "kind": "pull_request",
            "number": 7,
            "url": "https://github.com/acme/docgarden/pull/7",
            "head_branch": "feature/s13",
            "base_branch": "main",
        },
    )

    assert main(["pr", "draft", "--publish"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["published"] is True
    assert payload["publish_ready"] is True
    assert payload["publish_target"]["repository"] == "acme/docgarden"
    assert payload["remote"]["kind"] == "pull_request"
    assert payload["remote"]["number"] == 7


def test_cli_pr_draft_publish_reports_remote_issue_result(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / ".docgarden" / "config.yaml",
        """repo_name: test-docgarden
strict_score_fail_threshold: 70
pr_drafts:
  enabled: true
  provider: github
  repository: acme/docgarden
  base_branch: main
  token_env_var: DOCGARDEN_GITHUB_TOKEN
""",
    )
    init_git_repo(repo)
    write(repo / "docs" / "notes.md", "# Scratch Notes\n\nMissing frontmatter.\n")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("DOCGARDEN_GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(
        "docgarden.cli_commands.publish_pr_draft",
        lambda repo_root, config, payload: {
            "kind": "issue",
            "number": 9,
            "url": "https://github.com/acme/docgarden/issues/9",
        },
    )

    assert main(["pr", "draft", "--unsafe-as-issue", "--publish"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["mode"] == "issue"
    assert payload["published"] is True
    assert payload["publish_ready"] is True
    assert payload["remote"]["kind"] == "issue"
    assert payload["remote"]["number"] == 9


def test_cli_fix_safe_previews_and_applies_metadata_skeleton(tmp_path, monkeypatch, capsys) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "docs" / "reference.md",
        """---
doc_type: reference
---

# Reference Doc
""",
    )
    monkeypatch.chdir(repo)

    assert main(["fix", "safe"]) == 0
    preview_payload = json.loads(capsys.readouterr().out)
    planned = next(
        item for item in preview_payload["planned_changes"] if item["kind"] == "missing-metadata"
    )

    assert planned["files"] == ["docs/reference.md"]
    assert planned["changes"] == [
        "Add metadata skeleton fields: doc_id, domain, last_reviewed, owner, review_cycle_days, status."
    ]

    assert main(["fix", "safe", "--apply"]) == 0
    applied_payload = json.loads(capsys.readouterr().out)
    assert applied_payload["changed_files"] == ["docs/reference.md"]
    content = (repo / "docs" / "reference.md").read_text()
    assert "owner: TODO" in content
    assert "status: draft" in content


def test_cli_fix_safe_previews_and_applies_broken_link_repair(tmp_path, monkeypatch, capsys) -> None:
    repo = make_repo(tmp_path)
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
- [Guide](guide.md)
""",
    )
    write(
        repo / "docs" / "reference" / "guide.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "guide-doc")
        + """
# Guide

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
    monkeypatch.chdir(repo)

    assert main(["fix", "safe"]) == 0
    preview_payload = json.loads(capsys.readouterr().out)
    planned = next(
        item for item in preview_payload["planned_changes"] if item["kind"] == "broken-link"
    )

    assert planned["files"] == ["docs/index.md"]
    assert planned["changes"] == [
        "Replace markdown link target `guide.md` with `reference/guide.md`."
    ]

    assert main(["fix", "safe", "--apply"]) == 0
    applied_payload = json.loads(capsys.readouterr().out)
    assert applied_payload["changed_files"] == ["docs/index.md"]
    assert "[Guide](reference/guide.md)" in (repo / "docs" / "index.md").read_text()


def test_cli_fix_safe_route_preview_preserves_prose_mentions(tmp_path, monkeypatch, capsys) -> None:
    repo = make_repo(tmp_path)
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
- [Legacy Plan](docs/archive/legacy-plan.md)

Keep the prose mention docs/archive/legacy-plan.md as a historical note.
""",
    )
    write(
        repo / "docs" / "archive" / "legacy-plan.md",
        """---
doc_id: legacy-plan
doc_type: archive
domain: archive
owner: kirby
status: archived
last_reviewed: 2026-03-08
review_cycle_days: 30
superseded_by:
  - docs/current.md
---

# Legacy Plan

## Archived reason
Text.

## Archived date
2026-03-08

## Replacement doc, if any
- [Current](docs/current.md)
""",
    )
    write(
        repo / "docs" / "current.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "current-doc")
        + """
# Current

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
    monkeypatch.chdir(repo)

    assert main(["fix", "safe"]) == 0
    preview_payload = json.loads(capsys.readouterr().out)
    planned = next(
        item for item in preview_payload["planned_changes"] if item["kind"] == "stale-route"
    )

    assert planned["changes"] == [
        "Replace route reference `docs/archive/legacy-plan.md` with `docs/current.md`."
    ]

    assert main(["fix", "safe", "--apply"]) == 0
    applied_payload = json.loads(capsys.readouterr().out)
    assert applied_payload["changed_files"] == ["docs/index.md"]
    content = (repo / "docs" / "index.md").read_text()
    assert "[Legacy Plan](docs/current.md)" in content
    assert "docs/archive/legacy-plan.md as a historical note." in content


def test_cli_fix_safe_skips_non_canonical_route_replacement(tmp_path, monkeypatch, capsys) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "AGENTS.md",
        "# AGENTS.md\n\n- Overview: docs/index.md\n- Missing: docs/missing.md\n",
    )
    write(
        repo / "docs" / "archive" / "missing.md",
        """---
doc_id: archived-missing
doc_type: archive
domain: archive
owner: kirby
status: archived
last_reviewed: 2026-03-08
review_cycle_days: 30
---

# Missing
""",
    )
    monkeypatch.chdir(repo)

    assert main(["fix", "safe"]) == 0
    preview_payload = json.loads(capsys.readouterr().out)

    assert all(item["kind"] != "broken-route" for item in preview_payload["planned_changes"])


def test_cli_scan_changed_scope_supports_explicit_files_and_validates_paths(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "docs" / "extra.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "extra-doc")
        + """
# Extra Doc

## Purpose
Text.
""",
    )
    monkeypatch.chdir(repo)

    assert main(["scan", "--scope", "changed", "--files", "docs/extra.md"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "changed"
    assert payload["changed_files_source"] == "files"
    assert payload["requested_files"] == ["docs/extra.md"]
    assert payload["scanned_files"] == ["docs/extra.md"]
    assert payload["deleted_files"] == []
    assert payload["findings"] == 1
    assert any(
        "do not infer deletions" in note for note in payload["notes"]
    )

    assert main(["scan", "--scope", "changed", "--files", "README.md"]) == 1
    assert (
        "Changed-scope paths must be `AGENTS.md` or markdown files under `docs/`"
        in capsys.readouterr().err
    )

    assert main(["scan", "--scope", "changed", "--files", "docs/missing.md"]) == 1
    assert (
        "Explicit `--files` entries must point to existing docs."
        in capsys.readouterr().err
    )


def test_cli_scan_changed_scope_does_not_create_state_dir(tmp_path, monkeypatch, capsys) -> None:
    write(
        tmp_path / "AGENTS.md",
        "# AGENTS.md\n\n- Overview: docs/index.md\n",
    )
    write(
        tmp_path / "docs" / "index.md",
        CANONICAL_FRONTMATTER
        + """
# Docs Index

## Purpose
Text.
""",
    )
    monkeypatch.chdir(tmp_path)

    assert not (tmp_path / ".docgarden").exists()
    assert main(["scan", "--scope", "changed", "--files", "docs/index.md"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["scope"] == "changed"
    assert not (tmp_path / ".docgarden").exists()


def test_cli_commands_module_is_directly_exercised(tmp_path) -> None:
    repo = make_repo(tmp_path)
    paths = repo_paths(repo)
    run_result = run_scan(paths)

    assert run_result.findings == []
    assert run_result.scorecard.strict_score == 100
    assert run_result.latest_events == {}
    assert paths.quality == repo / "docs" / "QUALITY_SCORE.md"


def test_cli_next_and_status_follow_persisted_plan_order(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    for name in ("alpha", "beta"):
        write(
            repo / "docs" / f"{name}.md",
            CANONICAL_FRONTMATTER.replace("docs-index", f"{name}-doc").replace(
                "2026-03-08", "2026-01-01"
            )
            + f"""
# {name.title()} Doc

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

    monkeypatch.chdir(repo)
    assert main(["scan"]) == 0
    capsys.readouterr()

    paths = repo_paths(repo)
    plan = load_plan(paths.plan)
    beta_id = next(
        finding_id for finding_id in plan.ordered_findings if "docs::beta.md" in finding_id
    )
    alpha_id = next(
        finding_id for finding_id in plan.ordered_findings if "docs::alpha.md" in finding_id
    )
    reordered = plan.__class__(
        updated_at=plan.updated_at,
        lifecycle_stage=plan.lifecycle_stage,
        current_focus=beta_id,
        ordered_findings=[beta_id, alpha_id],
        clusters=plan.clusters,
        deferred_items=plan.deferred_items,
        last_scan_hash=plan.last_scan_hash,
    )
    paths.plan.write_text(json.dumps(asdict(reordered), indent=2, sort_keys=True) + "\n")

    assert main(["next"]) == 0
    next_payload = json.loads(capsys.readouterr().out)
    assert next_payload["id"] == beta_id

    assert main(["status"]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["open_ids"][:2] == [beta_id, alpha_id]


def test_cli_status_and_next_hide_accepted_debt_from_action_queue(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "docs" / "index.md",
        CANONICAL_FRONTMATTER
        + """
# Docs Index

See [Stale](stale.md).

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
    write(
        repo / "docs" / "stale.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "stale-doc").replace(
            "2026-03-08", "2026-01-01"
        )
        + """
# Stale Doc

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
    monkeypatch.chdir(repo)
    assert main(["scan"]) == 0
    capsys.readouterr()

    paths = repo_paths(repo)
    finding_id = json.loads(paths.findings.read_text().splitlines()[0])["id"]
    append_finding_status_event(
        paths.findings,
        finding_id,
        status="accepted_debt",
        event_at=datetime(2026, 3, 8, 13, 0, 0),
        attestation="Known gap accepted until the next planning cycle.",
        resolved_by="kirby",
    )
    run_scan(paths, scan_time=datetime(2026, 3, 8, 14, 0, 0))

    assert main(["status"]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["active_findings"] == 0
    assert status_payload["open_ids"] == []
    assert status_payload["strict_score"] < status_payload["overall_score"]

    assert main(["next"]) == 0
    assert capsys.readouterr().out.strip() == "No open findings."


def test_scan_preserves_existing_plan_state(tmp_path) -> None:
    repo = make_repo(tmp_path)
    for name in ("alpha", "beta"):
        write(
            repo / "docs" / f"{name}.md",
            CANONICAL_FRONTMATTER.replace("docs-index", f"{name}-doc").replace(
                "2026-03-08", "2026-01-01"
            )
            + f"""
# {name.title()} Doc

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

    paths = repo_paths(repo)
    run_scan(paths)

    original_plan = load_plan(paths.plan)
    beta_id = next(
        finding_id for finding_id in original_plan.ordered_findings if "docs::beta.md" in finding_id
    )
    alpha_id = next(
        finding_id for finding_id in original_plan.ordered_findings if "docs::alpha.md" in finding_id
    )
    preserved_plan = original_plan.__class__(
        updated_at=original_plan.updated_at,
        lifecycle_stage="organize",
        current_focus=beta_id,
        ordered_findings=[beta_id, alpha_id],
        clusters={**original_plan.clusters, "manual/review": [beta_id]},
        deferred_items=[alpha_id],
        last_scan_hash=original_plan.last_scan_hash,
        stage_notes={
            "observe": "Reviewed the scan and pulled out the main queue themes.",
            "reflect": "Compared the queue with the last round of fixes.",
            "organize": "Front-loaded beta before alpha for the next pass.",
        },
        strategy_text="Work the stale docs cluster before any lower-severity cleanup.",
    )
    paths.plan.write_text(json.dumps(asdict(preserved_plan), indent=2, sort_keys=True) + "\n")

    run_scan(paths)
    updated_plan = load_plan(paths.plan)

    assert updated_plan.lifecycle_stage == "organize"
    assert updated_plan.current_focus == beta_id
    assert updated_plan.ordered_findings[:2] == [beta_id, alpha_id]
    assert updated_plan.deferred_items == [alpha_id]
    assert updated_plan.clusters["manual/review"] == [beta_id]
    assert updated_plan.stage_notes == preserved_plan.stage_notes
    assert updated_plan.strategy_text == preserved_plan.strategy_text


def test_cli_plan_triage_updates_plan_without_mutating_findings_history(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "docs" / "stale.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "stale-doc").replace(
            "2026-03-08", "2026-01-01"
        )
        + """
# Stale Doc

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
    monkeypatch.chdir(repo)

    assert main(["scan"]) == 0
    capsys.readouterr()

    paths = repo_paths(repo)
    findings_before = paths.findings.read_text()

    assert main(
        [
            "plan",
            "triage",
            "--stage",
            "observe",
            "--report",
            "Reviewed the queue and confirmed the stale-doc issue is the immediate priority.",
        ]
    ) == 0
    observe_output = json.loads(capsys.readouterr().out)
    assert observe_output["lifecycle_stage"] == "observe"
    assert observe_output["stage_notes"]["observe"].startswith("Reviewed the queue")
    assert paths.findings.read_text() == findings_before

    assert main(
        [
            "plan",
            "triage",
            "--stage",
            "reflect",
            "--report",
            "Compared the current stale-doc work against the last scan and kept the queue narrow.",
        ]
    ) == 0
    reflect_output = json.loads(capsys.readouterr().out)
    assert reflect_output["lifecycle_stage"] == "reflect"
    assert set(reflect_output["stage_notes"]) == {"observe", "reflect"}
    assert paths.findings.read_text() == findings_before

    assert main(["plan"]) == 0
    plan_output = json.loads(capsys.readouterr().out)
    assert plan_output["lifecycle_stage"] == "reflect"
    assert plan_output["stage_notes"]["observe"].startswith("Reviewed the queue")
    assert plan_output["stage_notes"]["reflect"].startswith("Compared the current")


def test_cli_plan_triage_reports_validation_failures(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "docs" / "stale.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "stale-doc").replace(
            "2026-03-08", "2026-01-01"
        )
        + """
# Stale Doc

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
    monkeypatch.chdir(repo)

    assert main(["scan"]) == 0
    capsys.readouterr()

    assert main(
        [
            "plan",
            "triage",
            "--stage",
            "organize",
            "--report",
            "Skipping directly to organization should fail.",
        ]
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (
        "Cannot move plan triage from observe to organize; allowed stages: observe, reflect."
        in captured.err
    )


def test_cli_plan_focus_updates_current_focus_by_id_and_cluster(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "docs" / "stale.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "stale-doc").replace(
            "2026-03-08", "2026-01-01"
        )
        + """
# Stale Doc

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
    write(
        repo / "docs" / "partial.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "partial-doc")
        + """
# Partial Doc
""",
    )
    monkeypatch.chdir(repo)

    assert main(["scan"]) == 0
    capsys.readouterr()

    paths = repo_paths(repo)
    original_plan = load_plan(paths.plan)
    partial_id = next(
        finding_id
        for finding_id in original_plan.ordered_findings
        if "docs::partial.md" in finding_id
    )
    stale_id = next(
        finding_id
        for finding_id in original_plan.ordered_findings
        if "docs::stale.md" in finding_id
    )
    stale_cluster = next(
        cluster_name
        for cluster_name, finding_ids in original_plan.clusters.items()
        if stale_id in finding_ids
    )

    assert main(["plan", "focus", partial_id]) == 0
    focused_by_id = json.loads(capsys.readouterr().out)
    assert focused_by_id["current_focus"] == partial_id

    assert main(["next"]) == 0
    next_payload = json.loads(capsys.readouterr().out)
    assert next_payload["id"] == partial_id

    assert main(["plan", "focus", stale_cluster]) == 0
    focused_by_cluster = json.loads(capsys.readouterr().out)
    assert focused_by_cluster["current_focus"] == stale_id

    assert main(["next"]) == 0
    next_payload = json.loads(capsys.readouterr().out)
    assert next_payload["id"] == stale_id


def test_cli_plan_resolve_appends_event_and_advances_focus(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    for name in ("alpha", "beta"):
        write(
            repo / "docs" / f"{name}.md",
            CANONICAL_FRONTMATTER.replace("docs-index", f"{name}-doc").replace(
                "2026-03-08", "2026-01-01"
            )
            + f"""
# {name.title()} Doc

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
    monkeypatch.chdir(repo)

    assert main(["scan"]) == 0
    capsys.readouterr()

    paths = repo_paths(repo)
    original_plan = load_plan(paths.plan)
    focus_id = original_plan.current_focus
    assert focus_id is not None
    other_id = next(
        finding_id
        for finding_id in original_plan.ordered_findings
        if finding_id != focus_id
    )
    before_history = paths.findings.read_text().splitlines()

    assert main(["plan", "resolve", focus_id, "--result", "fixed"]) == 0
    resolve_output = json.loads(capsys.readouterr().out)
    assert resolve_output["event"]["status"] == "fixed"
    assert resolve_output["event"]["event"] == "status_changed"
    assert resolve_output["plan"]["current_focus"] == other_id

    after_history = paths.findings.read_text().splitlines()
    assert len(after_history) == len(before_history) + 1
    assert json.loads(after_history[-1])["id"] == focus_id
    assert json.loads(after_history[-1])["status"] == "fixed"

    assert main(["show", focus_id]) == 0
    show_payload = json.loads(capsys.readouterr().out)
    assert show_payload["status"] == "fixed"

    assert main(["next"]) == 0
    next_payload = json.loads(capsys.readouterr().out)
    assert next_payload["id"] == other_id


def test_cli_plan_resolve_requires_attestation_and_reopen_restores_queue(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "docs" / "index.md",
        CANONICAL_FRONTMATTER
        + """
# Docs Index

See [Stale](stale.md).

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
    write(
        repo / "docs" / "stale.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "stale-doc").replace(
            "2026-03-08", "2026-01-01"
        )
        + """
# Stale Doc

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
    monkeypatch.chdir(repo)

    assert main(["scan"]) == 0
    capsys.readouterr()

    paths = repo_paths(repo)
    finding_id = load_plan(paths.plan).current_focus
    assert finding_id is not None

    assert (
        main(["plan", "resolve", finding_id, "--result", "needs_human"]) == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Status needs_human requires a non-empty attestation." in captured.err

    assert (
        main(
            [
                "plan",
                "resolve",
                finding_id,
                "--result",
                "false_positive",
                "--attest",
                "Confirmed locally that this detector is a false alarm.",
            ]
        )
        == 0
    )
    resolve_output = json.loads(capsys.readouterr().out)
    assert resolve_output["event"]["status"] == "false_positive"
    assert resolve_output["plan"]["current_focus"] is None

    history_before_reopen = list(load_findings_history(paths.findings))

    assert main(["plan", "reopen", finding_id]) == 0
    reopen_output = json.loads(capsys.readouterr().out)
    assert reopen_output["event"]["status"] == "open"
    assert reopen_output["plan"]["current_focus"] == finding_id
    assert len(load_findings_history(paths.findings)) == len(history_before_reopen) + 1

    assert main(["next"]) == 0
    next_payload = json.loads(capsys.readouterr().out)
    assert next_payload["id"] == finding_id


def test_cli_plan_resolve_rejects_non_actionable_finding_ids(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    write(
        repo / "docs" / "index.md",
        CANONICAL_FRONTMATTER
        + """
# Docs Index

See [Stale](stale.md).

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
    write(
        repo / "docs" / "stale.md",
        CANONICAL_FRONTMATTER.replace("docs-index", "stale-doc").replace(
            "2026-03-08", "2026-01-01"
        )
        + """
# Stale Doc

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
    monkeypatch.chdir(repo)

    assert main(["scan"]) == 0
    capsys.readouterr()

    paths = repo_paths(repo)
    finding_id = load_plan(paths.plan).current_focus
    assert finding_id is not None

    assert main(["plan", "resolve", finding_id, "--result", "fixed"]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "plan",
                "resolve",
                finding_id,
                "--result",
                "accepted_debt",
                "--attest",
                "Should fail because the finding is already resolved.",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"Cannot resolve non-actionable finding: {finding_id}." in captured.err


def test_cli_plan_subcommand_help_mentions_queue_rules(capsys) -> None:
    parser = build_parser()

    try:
        parser.parse_args(["plan", "focus", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("Expected argparse help to exit cleanly.")

    focus_help = capsys.readouterr().out
    assert "Actionable finding ID or cluster name" in focus_help

    try:
        parser.parse_args(["plan", "resolve", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("Expected argparse help to exit cleanly.")

    resolve_help = capsys.readouterr().out
    assert "Resolve an actionable queue item." in resolve_help
    assert "`needs_human` stays" in resolve_help
    assert "accepted_debt" in resolve_help
    assert "false_positive" in resolve_help


def test_cli_config_show_reports_invalid_config_with_nonzero_exit(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    write(repo / ".docgarden" / "config.yaml", "repo_name: [broken\n")
    monkeypatch.chdir(repo)

    assert main(["config", "show"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Invalid config at" in captured.err
    assert ".docgarden/config.yaml" in captured.err


def test_cli_status_reports_corrupt_findings_history(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    write(repo / ".docgarden" / "findings.jsonl", "{broken json\n")
    monkeypatch.chdir(repo)

    assert main(["status"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Invalid findings history" in captured.err
    assert "findings.jsonl:1" in captured.err


def test_cli_status_reports_corrupt_score_state(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_repo(tmp_path)
    write(repo / ".docgarden" / "score.json", "{broken json\n")
    monkeypatch.chdir(repo)

    assert main(["status"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Invalid score state" in captured.err
    assert "score.json" in captured.err


def test_cli_plan_reports_corrupt_plan_state(tmp_path, monkeypatch, capsys) -> None:
    repo = make_repo(tmp_path)
    write(repo / ".docgarden" / "plan.json", "{broken json\n")
    monkeypatch.chdir(repo)

    assert main(["plan"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Invalid plan state" in captured.err
    assert "plan.json" in captured.err
