from __future__ import annotations

import json
import subprocess
from pathlib import Path

from docgarden.cli import main
from docgarden.slice_automation import build_slice_paths, load_slice_catalog


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_slice_repo(tmp_path: Path) -> Path:
    write(tmp_path / ".docgarden" / "config.yaml", "repo_name: test-docgarden\n")
    write(tmp_path / "AGENTS.md", "# AGENTS.md\n\n- Overview: docs/index.md\n")
    write(
        tmp_path / "docs" / "index.md",
        """---
doc_id: docs-index
doc_type: canonical
domain: docs
owner: kirby
status: verified
last_reviewed: 2026-03-09
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
        tmp_path / "docs" / "design-docs" / "docgarden-spec.md",
        "# Spec\n\nText.\n",
    )
    write(
        tmp_path
        / "docs"
        / "exec-plans"
        / "active"
        / "2026-03-09-docgarden-spec-slicing.md",
        "# Exec Plan\n\nText.\n",
    )
    write(
        tmp_path / "docs" / "design-docs" / "docgarden-implementation-slices.md",
        """---
doc_id: docgarden-implementation-slices
doc_type: reference
domain: design-docs
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

# Docgarden Implementation Slices

## Slice summary

| Slice | Status | Goal | Depends on |
| --- | --- | --- | --- |
| S06 | completed | Generated-doc contract checks | S00 |
| S07 | queued | Workflow drift detector | S01 |
| S08 | queued | Routing quality detector for stale targets | S01 |

## Atomic slices

### S06: Generated-doc contract checks

Status: `completed`

Goal:
- Enforce generated-doc contract rules.

Changes:
- Validate generated-doc provenance metadata.

Files likely touched:
- `docgarden/scan_alignment.py`

Acceptance:
- Generated docs missing provenance metadata receive findings.

### S07: Workflow drift detector

Status: `queued`

Goal:
- Catch docs that instruct contributors to use scripts, commands, or paths that no longer exist.

Changes:
- Scan workflow-like docs for local script and path references.
- Flag references to missing repo-owned scripts or commands.

Files likely touched:
- `docgarden/scan_alignment.py`
- `docgarden/markdown.py`
- `tests/test_support_modules.py`

Acceptance:
- Missing workflow assets produce actionable findings with evidence.
- External commands and URLs are ignored.

### S08: Routing quality detector for stale targets

Status: `queued`

Goal:
- Move beyond route exists toward route quality.

Changes:
- Detect routed archive docs when a better canonical route exists.

Files likely touched:
- `docgarden/scan_linkage.py`

Acceptance:
- Archived docs routed from indexes are flagged.
""",
    )
    return tmp_path


def test_load_slice_catalog_parses_summary_and_sections(tmp_path) -> None:
    repo = make_slice_repo(tmp_path)

    catalog = load_slice_catalog(repo)

    assert [item.slice_id for item in catalog.ordered_slices] == ["S06", "S07", "S08"]
    assert catalog.next_actionable_slice().slice_id == "S07"
    assert catalog.by_id("S07").changes == [
        "Scan workflow-like docs for local script and path references.",
        "Flag references to missing repo-owned scripts or commands.",
    ]


def test_load_slice_catalog_supports_custom_doc_paths(tmp_path) -> None:
    repo = make_slice_repo(tmp_path)
    custom_root = repo / "automation"
    custom_root.mkdir()
    custom_catalog = custom_root / "slices.md"
    custom_catalog.write_text(
        (repo / "docs" / "design-docs" / "docgarden-implementation-slices.md").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )

    catalog = load_slice_catalog(
        repo,
        paths=build_slice_paths(
            repo,
            implementation_slices=custom_catalog,
            spec=repo / "docs" / "design-docs" / "docgarden-spec.md",
            spec_slicing_plan=repo
            / "docs"
            / "exec-plans"
            / "active"
            / "2026-03-09-docgarden-spec-slicing.md",
        ),
    )

    assert catalog.next_actionable_slice().slice_id == "S07"


def test_cli_slices_prompt_commands_render_current_slice_context(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    worker_output = repo / "worker.json"
    worker_output.write_text('{"status": "completed"}', encoding="utf-8")
    review_output = repo / "review.json"
    review_output.write_text('{"recommendation": "revise_before_next_slice"}', encoding="utf-8")
    monkeypatch.chdir(repo)

    assert main(["slices", "kickoff-prompt"]) == 0
    kickoff = capsys.readouterr().out
    assert "Your target slice is S07" in kickoff
    assert "do not jump ahead into S08" in kickoff

    assert (
        main(
            [
                "slices",
                "review-prompt",
                "--slice",
                "S07",
                "--worker-output",
                str(worker_output),
                "--prior-review-output",
                str(review_output),
                "--round",
                "2",
            ]
        )
        == 0
    )
    review_prompt = capsys.readouterr().out
    assert "latest worker output JSON" in review_prompt
    assert str(worker_output) in review_prompt
    assert str(review_output) in review_prompt
    assert "this is a follow-up review after revision work" in review_prompt


def test_cli_slices_kickoff_prompt_supports_custom_paths(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    custom_catalog = repo / "custom" / "slice-backlog.md"
    write(
        custom_catalog,
        (repo / "docs" / "design-docs" / "docgarden-implementation-slices.md").read_text(
            encoding="utf-8"
        ),
    )
    monkeypatch.chdir(repo)

    assert (
        main(
            [
                "slices",
                "kickoff-prompt",
                "--catalog-path",
                str(custom_catalog),
                "--spec-path",
                "docs/design-docs/docgarden-spec.md",
                "--plan-path",
                "docs/exec-plans/active/2026-03-09-docgarden-spec-slicing.md",
            ]
        )
        == 0
    )
    kickoff = capsys.readouterr().out
    assert "custom/slice-backlog.md" in kickoff
    assert "Your target slice is S07" in kickoff


def test_cli_slices_run_revises_then_advances_to_next_slice(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    monkeypatch.chdir(repo)

    responses = iter(
        [
            {
                "status": "completed",
                "summary": "Implemented S07 first pass.",
                "files_touched": ["docgarden/scan_alignment.py"],
                "tests_run": ["uv run pytest"],
                "docs_updated": ["README.md"],
                "notes_for_reviewer": ["First pass complete."],
                "open_questions": [],
            },
            {
                "recommendation": "revise_before_next_slice",
                "summary": "One gap remains.",
                "findings": [
                    {
                        "severity": "medium",
                        "category": "implementation_risk",
                        "title": "Missing command filtering",
                        "detail": "Repo-owned commands are not filtered tightly enough.",
                        "revision_direction": "Tighten the workflow command classifier.",
                    }
                ],
                "next_step": "Revise the worker output and resubmit for review.",
            },
            {
                "status": "completed",
                "summary": "Implemented S07 revision.",
                "files_touched": ["docgarden/scan_alignment.py", "tests/test_support_modules.py"],
                "tests_run": ["uv run pytest", "uv run docgarden scan"],
                "docs_updated": ["README.md"],
                "notes_for_reviewer": ["Revision applied."],
                "open_questions": [],
            },
            {
                "recommendation": "ready_for_next_slice",
                "summary": "S07 is ready.",
                "findings": [],
                "next_step": "Move on to S08.",
            },
            {
                "status": "completed",
                "summary": "Implemented S08.",
                "files_touched": ["docgarden/scan_linkage.py"],
                "tests_run": ["uv run pytest"],
                "docs_updated": [],
                "notes_for_reviewer": ["S08 complete."],
                "open_questions": [],
            },
            {
                "recommendation": "ready_for_next_slice",
                "summary": "S08 is ready.",
                "findings": [],
                "next_step": "No more queued slices.",
            },
        ]
    )

    def fake_run(cmd, cwd, input, text, capture_output, check, timeout, env):
        assert timeout == 300
        assert env is not None
        assert "CODEX_CI" not in env
        assert "CODEX_SANDBOX" not in env
        assert "CODEX_SANDBOX_NETWORK_DISABLED" not in env
        assert "CODEX_THREAD_ID" not in env
        output_path = Path(cmd[cmd.index("--output-last-message") + 1])
        payload = next(responses)
        output_path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "ok\n", "")

    monkeypatch.setattr("docgarden.slices.runner.subprocess.run", fake_run)

    assert main(["slices", "run", "--max-slices", "2"]) == 0
    summary = json.loads(capsys.readouterr().out)

    assert summary["status"] == "completed"
    assert summary["processed_slices"] == 2
    assert [item["slice_id"] for item in summary["results"]] == ["S07", "S08"]
    assert summary["results"][0]["worker_rounds"] == 2
    assert summary["results"][0]["recommendation"] == "ready_for_next_slice"
    assert summary["results"][1]["worker_rounds"] == 1
    assert summary["next_slice"] is None

    loop_root = repo / ".docgarden" / "slice-loops"
    run_dirs = sorted(path for path in loop_root.iterdir() if path.is_dir())
    assert len(run_dirs) == 2
    first_run = run_dirs[0]
    assert (first_run / "worker-round-1.output.json").exists()
    assert (first_run / "review-round-1.output.json").exists()
    assert (first_run / "worker-round-2.output.json").exists()
    assert (first_run / "review-round-2.output.json").exists()


def test_cli_slices_run_times_out_and_persists_partial_logs(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    monkeypatch.chdir(repo)

    def fake_run(cmd, cwd, input, text, capture_output, check, timeout, env):
        assert env is not None
        raise subprocess.TimeoutExpired(
            cmd=cmd,
            timeout=timeout,
            output="partial stdout\n",
            stderr="partial stderr\n",
        )

    monkeypatch.setattr("docgarden.slices.runner.subprocess.run", fake_run)

    assert main(["slices", "run", "--agent-timeout-seconds", "12"]) == 1
    captured = capsys.readouterr()
    assert "timed out for worker-round-1 after 12 seconds" in captured.err

    run_dirs = sorted((repo / ".docgarden" / "slice-loops").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "worker-round-1.stdout.txt").read_text(encoding="utf-8") == (
        "partial stdout\n"
    )
    assert (run_dir / "worker-round-1.stderr.txt").read_text(encoding="utf-8") == (
        "partial stderr\n"
    )
    assert not (run_dir / "worker-round-1.output.json").exists()


def test_cli_slices_run_nonzero_exit_persists_logs(tmp_path, monkeypatch, capsys) -> None:
    repo = make_slice_repo(tmp_path)
    monkeypatch.chdir(repo)

    def fake_run(cmd, cwd, input, text, capture_output, check, timeout, env):
        assert timeout == 300
        assert env is not None
        return subprocess.CompletedProcess(cmd, 17, "agent stdout\n", "agent stderr\n")

    monkeypatch.setattr("docgarden.slices.runner.subprocess.run", fake_run)

    assert main(["slices", "run"]) == 1
    captured = capsys.readouterr()
    assert "exit code 17" in captured.err
    assert "worker-round-1.stderr.txt" in captured.err

    run_dirs = sorted((repo / ".docgarden" / "slice-loops").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "worker-round-1.stdout.txt").read_text(encoding="utf-8") == (
        "agent stdout\n"
    )
    assert (run_dir / "worker-round-1.stderr.txt").read_text(encoding="utf-8") == (
        "agent stderr\n"
    )
