from __future__ import annotations

import json
from pathlib import Path

from docgarden.cli import main
from docgarden.cli_commands import repo_paths, run_scan

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

    assert main(["doctor"]) == 0
    doctor_output = json.loads(capsys.readouterr().out)
    assert doctor_output["docs_exists"] is True
    assert doctor_output["agents_exists"] is True


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

    assert main(["fix", "safe", "--apply"]) == 0
    applied_payload = json.loads(capsys.readouterr().out)
    assert applied_payload["changed_files"] == ["docs/stale.md"]
    assert "status: needs-review" in (repo / "docs" / "stale.md").read_text()


def test_cli_commands_module_is_directly_exercised(tmp_path) -> None:
    repo = make_repo(tmp_path)
    paths = repo_paths(repo)
    run_result = run_scan(repo)

    assert run_result.findings == []
    assert run_result.scorecard.strict_score == 100
    assert run_result.latest_events == {}
    assert paths.quality == repo / "docs" / "QUALITY_SCORE.md"


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
