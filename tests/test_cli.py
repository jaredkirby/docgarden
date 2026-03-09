from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from docgarden.cli import main
from docgarden.cli_commands import repo_paths
from docgarden.scan_workflow import run_scan
from docgarden.state import (
    append_finding_status_event,
    load_findings_history,
    load_plan,
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
