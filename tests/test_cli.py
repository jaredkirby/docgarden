from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from docgarden.cli import main
from docgarden.cli_commands import repo_paths
from docgarden.scan_workflow import run_scan
from docgarden.state import append_finding_status_event, load_plan

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
    assert next_payload["id"] not in set(applied_payload.get("fixable", []))
    assert "status: needs-review" in (repo / "docs" / "stale.md").read_text()

    assert main(["show", next_payload["id"]]) == 0
    refreshed_payload = json.loads(capsys.readouterr().out)
    assert refreshed_payload["status"] == "fixed"
    assert refreshed_payload["event"] == "resolved"


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
    )
    paths.plan.write_text(json.dumps(asdict(preserved_plan), indent=2, sort_keys=True) + "\n")

    run_scan(paths)
    updated_plan = load_plan(paths.plan)

    assert updated_plan.lifecycle_stage == "organize"
    assert updated_plan.current_focus == beta_id
    assert updated_plan.ordered_findings[:2] == [beta_id, alpha_id]
    assert updated_plan.deferred_items == [alpha_id]
    assert updated_plan.clusters["manual/review"] == [beta_id]


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
