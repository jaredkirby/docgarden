from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from docgarden.errors import ConfigError, DocgardenError, StateError
from docgarden.files import atomic_write_text
from docgarden.markdown import parse_document, replace_frontmatter, resolve_link_target
from docgarden.models import Finding, PlanState, Scorecard
from docgarden.quality import write_quality_score
from docgarden.scan_document_rules import missing_frontmatter_finding
from docgarden.scan_linkage import collect_domain_doc_counts, repo_relative_path
from docgarden.state import (
    append_scan_events,
    build_plan,
    ensure_state_dirs,
    latest_events_by_id,
    load_findings_history,
    write_json,
)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_finding_open_issue_builds_stable_identifier() -> None:
    finding = Finding.open_issue(
        rel_path="docs/exec-plans/active/plan.md",
        kind="missing-sections",
        severity="medium",
        domain="exec-plans",
        summary="Missing headings.",
        evidence=["Missing headings: Validation"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        discovered_at="2026-03-08T12:00:00",
        cluster="structure-gaps",
        confidence="high",
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


def test_state_helpers_persist_findings_and_plan(tmp_path) -> None:
    state_dir = tmp_path / ".docgarden"
    ensure_state_dirs(state_dir)
    findings_path = state_dir / "findings.jsonl"

    finding = Finding.open_issue(
        rel_path="docs/index.md",
        kind="missing-sections",
        severity="medium",
        domain="docs",
        summary="Missing headings.",
        evidence=["Missing headings: Scope"],
        recommended_action="Add the missing section.",
        safe_to_autofix=True,
        discovered_at="2026-03-08T12:00:00",
        cluster="structure-gaps",
        confidence="high",
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

    output_path = state_dir / "score.json"
    write_json(output_path, {"strict_score": 91})
    assert json.loads(output_path.read_text())["strict_score"] == 91


def test_write_quality_score_updates_existing_frontmatter(tmp_path) -> None:
    scorecard = Scorecard(
        updated_at="2026-03-08T15:30:00",
        overall_score=92,
        strict_score=90,
        dimensions={"Structure & metadata": 95},
        domains={"docs": {"score": 90, "status": "high trust", "doc_count": 1, "findings": 0}},
        top_gaps=["Keep active exec plans current."],
        trend={"points": []},
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
    assert "- docs: 90 (high trust)" in written
