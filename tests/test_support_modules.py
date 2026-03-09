from __future__ import annotations

from dataclasses import asdict
import json
from datetime import datetime
from pathlib import Path

from docgarden.errors import ConfigError, DocgardenError, StateError
from docgarden.files import atomic_write_text
from docgarden.markdown import parse_document, replace_frontmatter, resolve_link_target
from docgarden.models import (
    Finding,
    FindingContext,
    PlanState,
    RepoPaths,
    Scorecard,
)
from docgarden.quality import build_scorecard, write_quality_score
from docgarden.scan_alignment import (
    extract_validation_commands,
    is_supported_docgarden_command,
    resolve_repo_artifact,
    stable_suffix,
)
from docgarden.scan_document_rules import missing_frontmatter_finding
from docgarden.scan_linkage import collect_domain_doc_counts, repo_relative_path
from docgarden.state import (
    active_findings_from_latest_events,
    append_finding_status_event,
    append_scan_events,
    build_plan,
    ensure_state_dirs,
    import_review,
    latest_events_by_id,
    load_findings_history,
    load_plan,
    load_score,
    ordered_active_events,
    prepare_review_packet,
    record_plan_resolution,
    record_plan_triage_stage,
    reopen_plan_finding,
    set_plan_focus,
    write_json,
)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_finding_open_issue_builds_stable_identifier() -> None:
    context = FindingContext(
        rel_path="docs/exec-plans/active/plan.md",
        domain="exec-plans",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Validation"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )

    assert finding.id == "missing-sections::docs::exec-plans::active::plan.md::sections"
    assert finding.files == ["docs/exec-plans/active/plan.md"]


def test_markdown_helpers_parse_routes_and_replace_frontmatter(tmp_path) -> None:
    repo = tmp_path
    doc_path = repo / "docs" / "index.md"
    write(
        doc_path,
        """---
doc_id: docs-index
doc_type: canonical
domain: docs
owner: kirby
status: verified
last_reviewed: 2026-03-08
review_cycle_days: 30
---

# Docs Index

See [Plan](exec-plans/active/plan.md) and docs/reference.md.
""",
    )

    document = parse_document(doc_path, repo)
    assert document.rel_path == "docs/index.md"
    assert document.links == ["exec-plans/active/plan.md"]
    assert "docs/reference.md" in document.routed_paths
    assert "docs/plan.md" not in document.routed_paths

    replaced = replace_frontmatter(document.raw_text, {**document.frontmatter, "status": "draft"})
    assert "status: draft" in replaced
    assert "# Docs Index" in replaced

    assert resolve_link_target(doc_path, repo, "docs/reference.md") == repo / "docs/reference.md"
    assert resolve_link_target(doc_path, repo, "exec-plans/active/plan.md") == (
        repo / "docs" / "exec-plans" / "active" / "plan.md"
    )


def test_atomic_write_text_replaces_existing_file(tmp_path) -> None:
    target = tmp_path / "state" / "note.txt"

    atomic_write_text(target, "first\n")
    atomic_write_text(target, "second\n")

    assert target.read_text() == "second\n"


def test_docgarden_errors_expose_stable_exit_codes() -> None:
    base_error = DocgardenError("base failure", exit_code=7)
    config_error = ConfigError("config failure")
    state_error = StateError("state failure")

    assert str(base_error) == "base failure"
    assert base_error.exit_code == 7
    assert config_error.exit_code == 1
    assert state_error.exit_code == 1


def test_scan_rule_helpers_cover_new_modules(tmp_path) -> None:
    repo = tmp_path
    doc_path = repo / "docs" / "index.md"
    write(doc_path, "# Docs Index\n")
    document = parse_document(doc_path, repo)

    finding = missing_frontmatter_finding(
        document,
        discovered_at="2026-03-08T12:00:00",
    )
    assert finding.kind == "missing-frontmatter"
    assert repo_relative_path(repo, doc_path) == "docs/index.md"
    assert collect_domain_doc_counts([document]) == {}


def test_alignment_helpers_handle_repo_artifacts_and_commands(tmp_path) -> None:
    repo = tmp_path

    assert resolve_repo_artifact(repo, "pyproject.toml") == repo / "pyproject.toml"
    assert resolve_repo_artifact(repo, "docs/index.md") == repo / "docs" / "index.md"
    assert resolve_repo_artifact(repo, "scripts/check.sh") == repo / "scripts" / "check.sh"
    assert resolve_repo_artifact(repo, "data/schema.csv") == repo / "data" / "schema.csv"
    assert resolve_repo_artifact(repo, "Makefile") == repo / "Makefile"
    assert resolve_repo_artifact(repo, "implementation linked") is None

    commands = extract_validation_commands(
        """
## Validation / How to verify

- `docgarden scan`

### Commands

- `docgarden review prepare`

```bash
uv run docgarden quality write
```
"""
    )
    assert commands == [
        "docgarden review prepare",
        "docgarden scan",
        "uv run docgarden quality write",
    ]
    assert is_supported_docgarden_command("docgarden scan") is True
    assert is_supported_docgarden_command("python -m docgarden.cli quality write") is True
    assert is_supported_docgarden_command("docgarden review prepare") is True
    assert is_supported_docgarden_command("docgarden review prepare --domains docs,metrics") is True
    assert is_supported_docgarden_command("docgarden review import review.json") is True
    assert stable_suffix("source", "scripts/missing.py") == (
        "source-scripts-missing-py-0ea0f4190a"
    )


def test_active_findings_from_latest_events_supports_legacy_history_payloads() -> None:
    latest = {
        "missing-sections::docs::index.md::sections": {
            "id": "missing-sections::docs::index.md::sections",
            "kind": "missing-sections",
            "severity": "medium",
            "domain": "docs",
            "status": "open",
            "files": ["docs/index.md"],
            "summary": "Missing headings.",
            "evidence": ["Missing headings: Scope"],
            "recommended_action": "Add the missing section.",
            "safe_to_autofix": True,
            "discovered_at": "2026-03-08T12:00:00",
            "cluster": "structure-gaps",
            "confidence": "high",
        }
    }

    findings = active_findings_from_latest_events(latest)

    assert [finding.id for finding in findings] == [
        "missing-sections::docs::index.md::sections"
    ]
    assert findings[0].attestation is None
    assert findings[0].resolved_at is None


def test_state_helpers_persist_findings_and_plan(tmp_path) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"

    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )
    scan_time = datetime(2026, 3, 8, 12, 0, 0)

    latest = append_scan_events(findings_path, [finding], scan_time)
    assert latest[finding.id]["event"] == "observed"

    history = load_findings_history(findings_path)
    assert latest_events_by_id(history)[finding.id]["summary"] == "Missing headings."

    plan = build_plan([finding], "abc123", scan_time)
    assert plan.current_focus == finding.id
    assert isinstance(plan, PlanState)
    assert plan.stage_notes == {}
    assert plan.strategy_text is None

    output_path = state_dir / "score.json"
    write_json(output_path, {"strict_score": 91})
    assert json.loads(output_path.read_text())["strict_score"] == 91


def test_load_plan_supports_stage_notes_and_strategy_text_defaults(tmp_path) -> None:
    plan_path = tmp_path / ".docgarden" / "plan.json"
    write_json(
        plan_path,
        {
            "updated_at": "2026-03-09T10:00:00",
            "lifecycle_stage": "observe",
            "current_focus": "finding::1",
            "ordered_findings": ["finding::1"],
            "clusters": {"docs": ["finding::1"]},
            "deferred_items": [],
            "last_scan_hash": "abc123",
        },
    )

    plan = load_plan(plan_path)

    assert plan.stage_notes == {}
    assert plan.strategy_text is None


def test_record_plan_triage_stage_updates_only_plan_state(tmp_path) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"
    plan_path = state_dir / "plan.json"

    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )
    append_scan_events(findings_path, [finding], datetime(2026, 3, 8, 12, 0, 0))
    initial_plan = build_plan([finding], "abc123", datetime(2026, 3, 8, 12, 5, 0))
    write_json(plan_path, asdict(initial_plan))

    before_history = findings_path.read_text()
    updated_plan = record_plan_triage_stage(
        plan_path,
        stage="observe",
        report="Confirmed the actionable queue and grouped the obvious themes.",
        updated_at=datetime(2026, 3, 8, 12, 10, 0),
    )

    assert findings_path.read_text() == before_history
    assert updated_plan.lifecycle_stage == "observe"
    assert updated_plan.stage_notes == {
        "observe": "Confirmed the actionable queue and grouped the obvious themes."
    }
    assert load_plan(plan_path).stage_notes == updated_plan.stage_notes


def test_record_plan_triage_stage_validates_stage_transitions(tmp_path) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    plan_path = state_dir / "plan.json"
    write_json(
        plan_path,
        {
            "updated_at": "2026-03-09T10:00:00",
            "lifecycle_stage": "observe",
            "current_focus": "finding::1",
            "ordered_findings": ["finding::1"],
            "clusters": {"docs": ["finding::1"]},
            "deferred_items": [],
            "last_scan_hash": "abc123",
            "stage_notes": {},
            "strategy_text": "Keep the first pass small and mechanical.",
        },
    )

    try:
        record_plan_triage_stage(
            plan_path,
            stage="organize",
            report="Skipping directly to an execution plan.",
            updated_at=datetime(2026, 3, 9, 10, 5, 0),
        )
    except StateError as exc:
        assert str(exc) == (
            "Cannot move plan triage from observe to organize; "
            "allowed stages: observe, reflect."
        )
    else:
        raise AssertionError("Expected triage transition validation to fail.")

    try:
        record_plan_triage_stage(
            plan_path,
            stage="observe",
            report="   ",
            updated_at=datetime(2026, 3, 9, 10, 5, 0),
        )
    except StateError as exc:
        assert str(exc) == "Triage report must be a non-empty string."
    else:
        raise AssertionError("Expected blank triage report validation to fail.")


def test_build_plan_preserves_notes_and_restarts_complete_cycle_on_new_findings(
    tmp_path,
) -> None:
    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )
    previous_plan = PlanState(
        updated_at="2026-03-09T09:00:00",
        lifecycle_stage="complete",
        current_focus=None,
        ordered_findings=[],
        clusters={},
        deferred_items=[],
        last_scan_hash="oldhash",
        stage_notes={"organize": "Prior queue was already shaped."},
        strategy_text="Resume with the highest-signal doc cluster.",
    )

    plan = build_plan(
        [finding],
        "newhash",
        datetime(2026, 3, 9, 10, 0, 0),
        previous_plan=previous_plan,
    )

    assert plan.lifecycle_stage == "observe"
    assert plan.stage_notes == {"organize": "Prior queue was already shaped."}
    assert plan.strategy_text == "Resume with the highest-signal doc cluster."


def test_set_plan_focus_updates_current_focus_for_id_and_cluster(tmp_path) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"
    plan_path = state_dir / "plan.json"

    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    alpha = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="cluster/alpha",
        suffix="alpha",
    )
    beta = Finding.open_issue(
        context,
        kind="stale-review",
        severity="high",
        summary="Review date is stale.",
        evidence=["last_reviewed is older than the review cycle."],
        recommended_action="Review the doc and refresh last_reviewed.",
        safe_to_autofix=False,
        cluster="cluster/beta",
        suffix="beta",
    )

    append_scan_events(findings_path, [alpha, beta], datetime(2026, 3, 8, 12, 0, 0))
    plan = build_plan([alpha, beta], "abc123", datetime(2026, 3, 8, 12, 5, 0))
    write_json(plan_path, asdict(plan))

    focused_by_id = set_plan_focus(
        plan_path,
        findings_path,
        target=alpha.id,
        updated_at=datetime(2026, 3, 8, 12, 10, 0),
    )
    assert focused_by_id.current_focus == alpha.id

    focused_by_cluster = set_plan_focus(
        plan_path,
        findings_path,
        target="cluster/beta",
        updated_at=datetime(2026, 3, 8, 12, 15, 0),
    )
    assert focused_by_cluster.current_focus == beta.id


def test_set_plan_focus_validates_unknown_targets(tmp_path) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"
    plan_path = state_dir / "plan.json"

    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )

    append_scan_events(findings_path, [finding], datetime(2026, 3, 8, 12, 0, 0))
    write_json(
        plan_path,
        asdict(build_plan([finding], "abc123", datetime(2026, 3, 8, 12, 5, 0))),
    )

    try:
        set_plan_focus(
            plan_path,
            findings_path,
            target="missing-cluster",
            updated_at=datetime(2026, 3, 8, 12, 10, 0),
        )
    except StateError as exc:
        assert str(exc) == "Unknown focus target: missing-cluster."
    else:
        raise AssertionError("Expected invalid focus target validation to fail.")


def test_record_plan_resolution_appends_event_and_advances_focus(tmp_path) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"
    plan_path = state_dir / "plan.json"

    alpha_context = FindingContext(
        rel_path="docs/alpha.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    beta_context = FindingContext(
        rel_path="docs/beta.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    alpha = Finding.open_issue(
        alpha_context,
        kind="stale-review",
        severity="high",
        summary="Review date is stale.",
        evidence=["Alpha is past review."],
        recommended_action="Refresh the doc review.",
        safe_to_autofix=False,
        cluster="freshness",
        suffix="alpha",
    )
    beta = Finding.open_issue(
        beta_context,
        kind="stale-review",
        severity="medium",
        summary="Review date is stale.",
        evidence=["Beta is past review."],
        recommended_action="Refresh the doc review.",
        safe_to_autofix=False,
        cluster="freshness",
        suffix="beta",
    )

    append_scan_events(findings_path, [alpha, beta], datetime(2026, 3, 8, 12, 0, 0))
    write_json(
        plan_path,
        asdict(build_plan([alpha, beta], "abc123", datetime(2026, 3, 8, 12, 5, 0))),
    )
    before_lines = findings_path.read_text().splitlines()

    event, updated_plan = record_plan_resolution(
        plan_path,
        findings_path,
        alpha.id,
        status="fixed",
        event_at=datetime(2026, 3, 8, 12, 10, 0),
        resolved_by="kirby",
    )

    after_lines = findings_path.read_text().splitlines()
    assert len(after_lines) == len(before_lines) + 1
    assert json.loads(after_lines[-1])["status"] == "fixed"
    assert event["event"] == "status_changed"
    assert updated_plan.current_focus == beta.id


def test_record_plan_resolution_requires_attestation_for_non_trivial_results(
    tmp_path,
) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"
    plan_path = state_dir / "plan.json"

    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )

    append_scan_events(findings_path, [finding], datetime(2026, 3, 8, 12, 0, 0))
    write_json(
        plan_path,
        asdict(build_plan([finding], "abc123", datetime(2026, 3, 8, 12, 5, 0))),
    )

    try:
        record_plan_resolution(
            plan_path,
            findings_path,
            finding.id,
            status="needs_human",
            event_at=datetime(2026, 3, 8, 12, 10, 0),
        )
    except StateError as exc:
        assert str(exc) == "Status needs_human requires a non-empty attestation."
    else:
        raise AssertionError("Expected attestation validation to fail.")


def test_record_plan_resolution_rejects_non_actionable_findings(tmp_path) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"
    plan_path = state_dir / "plan.json"

    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )

    append_scan_events(findings_path, [finding], datetime(2026, 3, 8, 12, 0, 0))
    write_json(
        plan_path,
        asdict(build_plan([finding], "abc123", datetime(2026, 3, 8, 12, 5, 0))),
    )
    record_plan_resolution(
        plan_path,
        findings_path,
        finding.id,
        status="fixed",
        event_at=datetime(2026, 3, 8, 12, 10, 0),
    )

    try:
        record_plan_resolution(
            plan_path,
            findings_path,
            finding.id,
            status="accepted_debt",
            event_at=datetime(2026, 3, 8, 12, 15, 0),
            attestation="This should fail because the finding already left the queue.",
        )
    except StateError as exc:
        assert str(exc) == f"Cannot resolve non-actionable finding: {finding.id}."
    else:
        raise AssertionError("Expected non-actionable resolution validation to fail.")


def test_reopen_plan_finding_reopens_resolved_event_and_refocuses(tmp_path) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"
    plan_path = state_dir / "plan.json"

    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )

    append_scan_events(findings_path, [finding], datetime(2026, 3, 8, 12, 0, 0))
    write_json(
        plan_path,
        asdict(build_plan([finding], "abc123", datetime(2026, 3, 8, 12, 5, 0))),
    )
    record_plan_resolution(
        plan_path,
        findings_path,
        finding.id,
        status="false_positive",
        event_at=datetime(2026, 3, 8, 12, 10, 0),
        attestation="Confirmed locally that this detector fired incorrectly.",
    )

    event, updated_plan = reopen_plan_finding(
        plan_path,
        findings_path,
        finding.id,
        event_at=datetime(2026, 3, 8, 12, 15, 0),
        resolved_by="kirby",
    )

    assert event["status"] == "open"
    assert event["resolved_at"] is None
    assert updated_plan.current_focus == finding.id
    assert latest_events_by_id(load_findings_history(findings_path))[finding.id]["status"] == "open"


def test_state_helpers_preserve_manual_status_metadata_across_scans(tmp_path) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"

    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )

    append_scan_events(findings_path, [finding], datetime(2026, 3, 8, 12, 0, 0))
    append_finding_status_event(
        findings_path,
        finding.id,
        status="accepted_debt",
        event_at=datetime(2026, 3, 8, 13, 0, 0),
        attestation="Known gap accepted until the next planning cycle.",
        resolved_by="kirby",
        resolution_note="Tracked as intentional doc debt for now.",
    )
    latest = append_scan_events(
        findings_path,
        [finding],
        datetime(2026, 3, 8, 14, 0, 0),
    )

    active_findings = active_findings_from_latest_events(latest)

    assert [item.status for item in active_findings] == ["accepted_debt"]
    assert active_findings[0].attestation == (
        "Known gap accepted until the next planning cycle."
    )
    assert active_findings[0].resolved_by == "kirby"
    assert active_findings[0].resolution_note == (
        "Tracked as intentional doc debt for now."
    )
    assert active_findings[0].resolved_at == "2026-03-08T13:00:00"

    scorecard = build_scorecard(
        active_findings,
        {"docs": 1},
        datetime(2026, 3, 8, 14, 0, 0),
    )
    assert scorecard.overall_score == 100
    assert scorecard.strict_score < scorecard.overall_score


def test_accepted_debt_remains_score_tracked_but_leaves_action_queue(tmp_path) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"

    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )

    append_scan_events(findings_path, [finding], datetime(2026, 3, 8, 12, 0, 0))
    append_finding_status_event(
        findings_path,
        finding.id,
        status="accepted_debt",
        event_at=datetime(2026, 3, 8, 13, 0, 0),
        attestation="Known gap accepted until the next planning cycle.",
        resolved_by="kirby",
        resolution_note="Tracked as intentional doc debt for now.",
    )

    latest = latest_events_by_id(load_findings_history(findings_path))
    score_tracked_findings = active_findings_from_latest_events(latest)
    paths = RepoPaths(
        repo_root=tmp_path,
        state_dir=state_dir,
        config=state_dir / "config.yaml",
        findings=findings_path,
        plan=state_dir / "plan.json",
        score=state_dir / "score.json",
        quality=tmp_path / "docs" / "QUALITY_SCORE.md",
    )

    assert [item.status for item in score_tracked_findings] == ["accepted_debt"]
    assert ordered_active_events(paths) == []


def test_scan_auto_resolves_accepted_debt_when_detector_stops_reporting_it(
    tmp_path,
) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"

    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )

    append_scan_events(findings_path, [finding], datetime(2026, 3, 8, 12, 0, 0))
    append_finding_status_event(
        findings_path,
        finding.id,
        status="accepted_debt",
        event_at=datetime(2026, 3, 8, 13, 0, 0),
        attestation="Known gap accepted until the next planning cycle.",
    )

    latest = append_scan_events(findings_path, [], datetime(2026, 3, 8, 14, 0, 0))

    assert latest[finding.id]["status"] == "fixed"
    assert latest[finding.id]["event"] == "resolved"
    assert latest[finding.id]["resolved_at"] == "2026-03-08T14:00:00"


def test_append_finding_status_event_supports_additional_statuses(tmp_path) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"

    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )
    append_scan_events(findings_path, [finding], datetime(2026, 3, 8, 12, 0, 0))

    in_progress = append_finding_status_event(
        findings_path,
        finding.id,
        status="in_progress",
        event_at=datetime(2026, 3, 8, 12, 15, 0),
    )
    needs_human = append_finding_status_event(
        findings_path,
        finding.id,
        status="needs_human",
        event_at=datetime(2026, 3, 8, 12, 30, 0),
        attestation="This mismatch needs a reviewer before we change the doc.",
    )
    false_positive = append_finding_status_event(
        findings_path,
        finding.id,
        status="false_positive",
        event_at=datetime(2026, 3, 8, 12, 45, 0),
        attestation="Scanner reproduced locally and confirmed this is a false alarm.",
    )

    assert in_progress["resolved_at"] is None
    assert needs_human["resolved_at"] is None
    assert false_positive["resolved_at"] == "2026-03-08T12:45:00"


def test_append_finding_status_event_requires_attestation_for_non_trivial_states(
    tmp_path,
) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"

    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )
    append_scan_events(findings_path, [finding], datetime(2026, 3, 8, 12, 0, 0))

    for status in ("accepted_debt", "needs_human", "false_positive"):
        try:
            append_finding_status_event(
                findings_path,
                finding.id,
                status=status,
                event_at=datetime(2026, 3, 8, 12, 30, 0),
            )
        except StateError as exc:
            assert str(exc) == f"Status {status} requires a non-empty attestation."
        else:
            raise AssertionError(f"Expected attestation validation for {status}.")


def test_reobserved_fixed_finding_reopens_with_clean_resolution_metadata(
    tmp_path,
) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"

    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )

    append_scan_events(findings_path, [finding], datetime(2026, 3, 8, 12, 0, 0))
    append_scan_events(findings_path, [], datetime(2026, 3, 8, 13, 0, 0))
    latest = append_scan_events(findings_path, [finding], datetime(2026, 3, 8, 14, 0, 0))

    assert latest[finding.id]["status"] == "open"
    assert latest[finding.id]["event"] == "observed"
    assert latest[finding.id]["resolved_at"] is None
    assert latest[finding.id]["attestation"] is None
    assert latest[finding.id]["resolved_by"] is None
    assert latest[finding.id]["resolution_note"] is None


def test_reobserved_false_positive_finding_reopens(tmp_path) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"

    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )

    append_scan_events(findings_path, [finding], datetime(2026, 3, 8, 12, 0, 0))
    append_finding_status_event(
        findings_path,
        finding.id,
        status="false_positive",
        event_at=datetime(2026, 3, 8, 13, 0, 0),
        attestation="Scanner reproduced locally and confirmed this is a false alarm.",
        resolved_by="kirby",
    )
    latest = append_scan_events(findings_path, [finding], datetime(2026, 3, 8, 14, 0, 0))

    assert latest[finding.id]["status"] == "open"
    assert latest[finding.id]["resolved_at"] is None
    assert latest[finding.id]["attestation"] is None


def test_prepare_review_packet_is_reproducible_and_scope_filtered(tmp_path) -> None:
    repo = tmp_path
    write(repo / "AGENTS.md", "# AGENTS.md\n\n- Overview: docs/index.md\n")
    write(
        repo / "docs" / "index.md",
        """---
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
    write(
        repo / "docs" / "design-docs" / "plan.md",
        """---
doc_id: design-plan
doc_type: reference
domain: design-docs
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
Text.

## Related docs
Text.
""",
    )

    first_path, first_payload = prepare_review_packet(
        repo,
        repo / ".docgarden",
        domains=["docs"],
    )
    second_path, second_payload = prepare_review_packet(
        repo,
        repo / ".docgarden",
        domains=["docs"],
    )

    assert first_path == second_path
    assert first_payload["packet_id"] == second_payload["packet_id"]
    assert first_payload["scope"]["domains"] == ["docs"]
    assert first_payload["scope"]["documents"] == ["docs/index.md"]
    assert [item["rel_path"] for item in first_payload["documents"]] == ["docs/index.md"]


def test_import_review_persists_subjective_findings_and_updates_plan(tmp_path) -> None:
    repo = tmp_path
    state_dir = repo / ".docgarden"
    ensure_state_dirs(state_dir)
    write(
        state_dir / "config.yaml",
        "repo_name: test-docgarden\nstrict_score_fail_threshold: 70\n",
    )
    write(repo / "AGENTS.md", "# AGENTS.md\n\n- Overview: docs/index.md\n")
    write(
        repo / "docs" / "index.md",
        """---
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

    packet_path, packet_payload = prepare_review_packet(repo, state_dir, domains=["docs"])
    import_payload = {
        "format_version": 1,
        "packet_id": packet_payload["packet_id"],
        "review_id": "docs-clarity-pass",
        "provenance": {"runner": "manual", "reviewer": "kirby"},
        "findings": [
            {
                "id": "ambiguous-summary",
                "summary": "The purpose section is too vague for operators.",
                "severity": "medium",
                "files": ["docs/index.md"],
                "evidence": ["The Purpose section only says `Text.`"],
                "recommended_action": "Expand the purpose with the operator-facing contract.",
                "confidence": "high",
            }
        ],
    }
    import_path = repo / "review.json"
    write_json(import_path, import_payload)

    paths = RepoPaths(
        repo_root=repo,
        state_dir=state_dir,
        config=state_dir / "config.yaml",
        findings=state_dir / "findings.jsonl",
        plan=state_dir / "plan.json",
        score=state_dir / "score.json",
        quality=repo / "docs" / "QUALITY_SCORE.md",
    )

    stored_review_path, stored_payload, imported_findings, plan = import_review(
        paths,
        import_path,
        imported_at=datetime(2026, 3, 9, 10, 0, 0),
    )
    latest = latest_events_by_id(load_findings_history(paths.findings))

    assert packet_path.exists()
    assert stored_review_path == state_dir / "reviews" / "review-import-docs-clarity-pass.json"
    assert stored_payload["review_id"] == "docs-clarity-pass"
    assert len(imported_findings) == 1
    assert imported_findings[0].finding_source == "subjective_review"
    assert latest[imported_findings[0].id]["event"] == "review_imported"
    assert latest[imported_findings[0].id]["provenance"]["packet_id"] == packet_payload["packet_id"]
    assert plan.current_focus == imported_findings[0].id
    assert ordered_active_events(paths)[0]["id"] == imported_findings[0].id

    append_scan_events(paths.findings, [], datetime(2026, 3, 9, 11, 0, 0))
    latest_after_scan = latest_events_by_id(load_findings_history(paths.findings))
    assert latest_after_scan[imported_findings[0].id]["status"] == "open"


def test_import_review_fails_closed_when_file_is_outside_packet(tmp_path) -> None:
    repo = tmp_path
    state_dir = repo / ".docgarden"
    ensure_state_dirs(state_dir)
    write(
        state_dir / "config.yaml",
        "repo_name: test-docgarden\nstrict_score_fail_threshold: 70\n",
    )
    write(repo / "AGENTS.md", "# AGENTS.md\n\n- Overview: docs/index.md\n")
    write(
        repo / "docs" / "index.md",
        """---
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
    _, packet_payload = prepare_review_packet(repo, state_dir, domains=["docs"])
    import_path = repo / "review.json"
    write_json(
        import_path,
        {
            "packet_id": packet_payload["packet_id"],
            "provenance": {"runner": "manual"},
            "findings": [
                {
                    "id": "bad-file",
                    "summary": "Bad import.",
                    "severity": "low",
                    "files": ["docs/missing.md"],
                    "evidence": ["File not in packet."],
                    "recommended_action": "Fix the payload.",
                }
            ],
        },
    )
    paths = RepoPaths(
        repo_root=repo,
        state_dir=state_dir,
        config=state_dir / "config.yaml",
        findings=state_dir / "findings.jsonl",
        plan=state_dir / "plan.json",
        score=state_dir / "score.json",
        quality=repo / "docs" / "QUALITY_SCORE.md",
    )

    try:
        import_review(paths, import_path, imported_at=datetime(2026, 3, 9, 10, 0, 0))
    except StateError as exc:
        assert "references files outside packet" in str(exc)
    else:
        raise AssertionError("Expected import_review to reject files outside the packet.")
    assert not paths.findings.exists()


def test_write_quality_score_updates_existing_frontmatter(tmp_path) -> None:
    scorecard = Scorecard(
        updated_at="2026-03-08T15:30:00",
        overall_score=92,
        strict_score=90,
        dimensions={"Structure & metadata": 95},
        domains={"docs": {"score": 90, "status": "high trust", "doc_count": 1, "findings": 0}},
        top_gaps=["Keep active exec plans current."],
        trend={
            "points": [
                {
                    "updated_at": "2026-03-08T15:30:00",
                    "overall_score": 92,
                    "strict_score": 90,
                    "weighted_domain_rollup": 88,
                    "critical_regressions": ["docs"],
                }
            ],
            "summary": {
                "overall_delta": -4,
                "strict_delta": -3,
                "weighted_rollup_delta": -5,
            },
        },
        rollup={
            "weighted_score": 88,
            "raw_average_score": 90,
            "weights": {"docs": 4},
            "critical_regressions": [
                {
                    "domain": "docs",
                    "score": 90,
                    "previous_score": 98,
                    "delta": -8,
                }
            ],
        },
    )
    quality_path = tmp_path / "docs" / "QUALITY_SCORE.md"
    write(
        quality_path,
        """---
doc_id: quality-score
doc_type: canonical
domain: docs
owner: kirby
status: verified
last_reviewed: 2026-01-01
review_cycle_days: 30
---

# Quality Score
""",
    )

    write_quality_score(quality_path, scorecard)
    written = quality_path.read_text()

    assert "last_reviewed: '2026-03-08'" in written
    assert "- Overall: 92" in written
    assert "- Weighted domain rollup: 88" in written
    assert "- docs: 90 (high trust, weight: 4)" in written
    assert "## Critical-Domain Regressions" in written
    assert "- docs: 90 (-8 from 98)" in written
    assert "weighted rollup 88; critical regressions: docs" in written


def test_load_score_supports_legacy_payload_without_rollup(tmp_path) -> None:
    score_path = tmp_path / ".docgarden" / "score.json"
    write_json(
        score_path,
        {
            "updated_at": "2026-03-08T15:30:00",
            "overall_score": 100,
            "strict_score": 98,
            "dimensions": {"Structure & metadata": 100},
            "domains": {
                "docs": {
                    "score": 100,
                    "status": "high trust",
                    "doc_count": 1,
                    "findings": 0,
                }
            },
            "top_gaps": [],
            "trend": {"points": []},
        },
    )

    scorecard = load_score(score_path)

    assert scorecard is not None
    assert scorecard.rollup == {}
    assert scorecard.trend == {"points": []}


def test_build_scorecard_uses_domain_weights_and_tracks_critical_regressions() -> None:
    context = FindingContext(
        rel_path="docs/index.md",
        domain="docs",
        discovered_at="2026-03-08T12:00:00",
    )
    finding = Finding.open_issue(
        context,
        kind="missing-sections",
        severity="medium",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        cluster="structure-gaps",
        suffix="sections",
    )
    previous_score = Scorecard(
        updated_at="2026-03-08T12:00:00",
        overall_score=98,
        strict_score=98,
        dimensions={"Structure & metadata": 100},
        domains={
            "design-docs": {
                "score": 100,
                "status": "high trust",
                "doc_count": 1,
                "findings": 0,
            },
            "docs": {
                "score": 96,
                "status": "high trust",
                "doc_count": 1,
                "findings": 0,
            },
            "exec-plans": {
                "score": 100,
                "status": "high trust",
                "doc_count": 1,
                "findings": 0,
            },
        },
        top_gaps=[],
        trend={
            "points": [
                {
                    "updated_at": "2026-03-08T12:00:00",
                    "overall_score": 98,
                    "strict_score": 98,
                    "weighted_domain_rollup": 98,
                    "critical_regressions": [],
                }
            ]
        },
        rollup={
            "weighted_score": 98,
            "raw_average_score": 99,
            "weights": {"design-docs": 2, "docs": 4, "exec-plans": 3},
            "critical_regressions": [],
        },
    )

    scorecard = build_scorecard(
        [finding],
        {"design-docs": 1, "docs": 1, "exec-plans": 1},
        datetime(2026, 3, 8, 13, 0, 0),
        previous_score=previous_score,
        critical_domains=["docs", "exec-plans"],
        domain_weights={"design-docs": 2, "docs": 4, "exec-plans": 3},
    )

    assert scorecard.rollup["weighted_score"] == 96
    assert scorecard.rollup["raw_average_score"] == 97
    assert scorecard.rollup["weights"] == {
        "design-docs": 2,
        "docs": 4,
        "exec-plans": 3,
    }
    assert scorecard.rollup["critical_regressions"] == [
        {"domain": "docs", "score": 92, "previous_score": 96, "delta": -4}
    ]
    assert scorecard.trend["summary"]["weighted_rollup_delta"] == -2
    assert len(scorecard.trend["points"]) == 2
    assert scorecard.trend["points"][-1]["critical_regressions"] == ["docs"]
