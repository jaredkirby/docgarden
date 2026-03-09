from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
import time

import pytest

from docgarden.errors import DocgardenError
from docgarden.cli import main
from docgarden.cli_plan_review import register_plan_parser, register_review_parser
from docgarden.cli_slices import register_slices_parser
from docgarden.cli_slices_commands import command_slices_next
from docgarden.cli_slices_runtime import _resolve_slice_timeout_args
from docgarden.slices.catalog import SliceDefinition, load_slice_catalog
from docgarden.slices.config import SliceRunRequest, build_slice_paths, build_slice_run_config
from docgarden.slices.prompts import build_implementation_prompt, build_review_prompt
from docgarden.slices.run_agent import AgentRunArtifact, _build_codex_subprocess_env
from docgarden.slices.run_execution import execute_slice_request
from docgarden.slices.review_progress import (
    load_review_signature,
    read_review_output,
    review_signature,
)
from docgarden.slices.run_recovery import (
    _partition_run_artifact_untracked_paths,
    _recovery_recommendation,
)
from docgarden.slices.run_status import load_slice_run_status
from docgarden.slices.runner import run_slice_loop


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload) -> None:
    write(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


class FakePopen:
    _next_pid = 1000

    def __init__(
        self,
        cmd,
        *,
        stdout_file,
        stderr_file,
        response,
        timeout_log,
    ) -> None:
        self.cmd = cmd
        self.pid = FakePopen._next_pid
        FakePopen._next_pid += 1
        self.returncode: int | None = None
        self._stdout_file = stdout_file
        self._stderr_file = stderr_file
        self._response = response
        self._timeout_log = timeout_log
        self._timed_out_once = False
        self._emitted_output = False

    def communicate(self, input=None, timeout=None):
        self._timeout_log.append(timeout)
        if input is not None:
            assert isinstance(input, str)
        sleep_seconds = float(self._response.get("sleep_seconds", 0.0))
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
        if not self._emitted_output:
            stdout_text = self._response.get("stdout", "")
            stderr_text = self._response.get("stderr", "")
            if stdout_text:
                self._stdout_file.write(stdout_text)
                self._stdout_file.flush()
            if stderr_text:
                self._stderr_file.write(stderr_text)
                self._stderr_file.flush()

            write_output = self._response.get("write_output")
            if callable(write_output):
                write_output(self.cmd)
            self._emitted_output = True

        if self._response.get("timeout") and not self._timed_out_once:
            self._timed_out_once = True
            raise subprocess.TimeoutExpired(cmd=self.cmd, timeout=timeout)

        self.returncode = int(self._response.get("returncode", 0))
        return ("", "")

    def kill(self) -> None:
        self.returncode = int(self._response.get("killed_returncode", -9))

    def poll(self) -> int | None:
        return self.returncode


def make_slice_repo(tmp_path: Path) -> Path:
    write(tmp_path / ".docgarden" / "config.yaml", "strict_score_fail_threshold: 70\n")
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
| S07 | queued | Workflow drift detector | S06 |
| S08 | queued | Routing quality detector for stale targets | S07 |

## Atomic slices

### S06: Generated-doc contract checks

Status: `completed`

Goal:
- Enforce generated-doc contract rules.

Changes:
- Validate generated-doc provenance metadata.

Files likely touched:
- `docgarden/scan/alignment.py`

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
- `docgarden/scan/alignment.py`
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
- `docgarden/scan/linkage.py`

Acceptance:
- Archived docs routed from indexes are flagged.
""",
    )
    return tmp_path


def make_slice_definition(*, slice_id: str, title: str) -> SliceDefinition:
    return SliceDefinition(
        slice_id=slice_id,
        title=title,
        status="queued",
        goal=f"Deliver {title}.",
        depends_on=["S00"],
        changes=["Implement the change.", "Update the docs."],
        likely_files=["docgarden/slices/runner.py"],
        acceptance=["The change works.", "The docs stay current."],
    )


def test_load_slice_catalog_parses_summary_and_sections(tmp_path) -> None:
    repo = make_slice_repo(tmp_path)

    catalog = load_slice_catalog(repo)

    assert [item.slice_id for item in catalog.ordered_slices] == ["S06", "S07", "S08"]
    assert catalog.next_actionable_slice().slice_id == "S07"
    assert catalog.by_id("S07").changes == [
        "Scan workflow-like docs for local script and path references.",
        "Flag references to missing repo-owned scripts or commands.",
    ]
    assert catalog.dependency_blockers("S07") == []
    assert catalog.dependency_blockers("S08") == ["S07"]
    assert catalog.next_after("S07") is None
    assert (
        catalog.next_after("S07", completed_overrides={"S07"}).slice_id == "S08"
    )


def test_register_review_and_plan_parsers_attach_expected_handlers() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_review_parser(subparsers)
    register_plan_parser(
        subparsers,
        plan_resolve_statuses=("fixed", "accepted_debt", "needs_human"),
    )

    review_args = parser.parse_args(["review", "prepare"])
    plan_args = parser.parse_args(["plan", "focus", "abc"])

    assert review_args.review_command == "prepare"
    assert review_args.func.__name__ == "command_review_prepare"
    assert plan_args.plan_command == "focus"
    assert plan_args.func.__name__ == "command_plan_focus"


def test_register_slices_parser_attaches_slice_subcommands() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_slices_parser(subparsers)

    next_args = parser.parse_args(["slices", "next"])
    run_args = parser.parse_args(["slices", "run"])

    assert next_args.slices_command == "next"
    assert next_args.func.__name__ == "command_slices_next"
    assert run_args.slices_command == "run"
    assert run_args.func.__name__ == "command_slices_run"


def test_command_slices_next_direct_module_call_uses_dependency_aware_schedule(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    monkeypatch.chdir(repo)

    command_slices_next(
        argparse.Namespace(
            catalog_path=None,
            spec_path=None,
            plan_path=None,
            artifacts_dir=None,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["slice_id"] == "S07"
    assert payload["depends_on"] == ["S06"]
    assert payload["next_slice"] == "S08"


def test_slice_runtime_timeout_args_support_agent_override() -> None:
    worker_timeout, reviewer_timeout = _resolve_slice_timeout_args(
        argparse.Namespace(
            agent_timeout_seconds=42,
            worker_timeout_seconds=None,
            reviewer_timeout_seconds=None,
        ),
        command_name="run",
    )

    assert worker_timeout == 42
    assert reviewer_timeout == 42


def test_execute_slice_request_direct_module_path_returns_ready_result(
    tmp_path, monkeypatch
) -> None:
    repo = make_slice_repo(tmp_path)
    paths = build_slice_paths(repo)
    loop_root = repo / ".docgarden" / "slice-loops"
    slice_def = make_slice_definition(slice_id="S07", title="Workflow drift detector")
    request = SliceRunRequest(
        repo_root=repo,
        paths=paths,
        loop_root=loop_root,
        slice_def=slice_def,
        next_slice=None,
        config=build_slice_run_config(max_review_rounds=1),
    )
    monkeypatch.setattr(
        "docgarden.slices.run_execution._capture_repo_baseline",
        lambda repo_root: {
            "baseline_recorded_at": "2026-03-09T00:00:00",
            "baseline_tracked_changes": [],
            "baseline_untracked_paths": [],
        },
    )

    def fake_run_codex_agent(
        repo_root,
        *,
        run_dir,
        schema,
        prefix,
        **kwargs,
    ) -> AgentRunArtifact:
        output_path = run_dir / f"{prefix}.output.json"
        if prefix.startswith("worker"):
            payload = {
                "status": "completed",
                "summary": "Implemented S07.",
                "files_touched": ["docgarden/scan/alignment.py"],
                "tests_run": ["uv run pytest"],
                "docs_updated": [],
                "notes_for_reviewer": [],
                "open_questions": [],
            }
        else:
            payload = {
                "recommendation": "ready_for_next_slice",
                "summary": "S07 is ready.",
                "findings": [],
                "next_step": "Move on.",
            }
        write_json(output_path, payload)
        return AgentRunArtifact(
            prompt_path=run_dir / f"{prefix}.prompt.txt",
            schema_path=run_dir / f"{prefix}.schema.json",
            output_path=output_path,
            stdout_path=run_dir / f"{prefix}.stdout.txt",
            stderr_path=run_dir / f"{prefix}.stderr.txt",
            parsed_output=payload,
            command=["codex", "exec", prefix],
        )

    monkeypatch.setattr(
        "docgarden.slices.run_execution.run_codex_agent",
        fake_run_codex_agent,
    )

    result = execute_slice_request(request)

    assert result.slice_id == "S07"
    assert result.recommendation == "ready_for_next_slice"
    assert len(result.worker_outputs) == 1
    assert len(result.review_outputs) == 1


def test_build_implementation_prompt_includes_revision_context(tmp_path) -> None:
    repo = make_slice_repo(tmp_path)
    paths = build_slice_paths(repo)
    current = make_slice_definition(slice_id="S07", title="Workflow drift detector")
    next_slice = make_slice_definition(
        slice_id="S08",
        title="Routing quality detector for stale targets",
    )
    worker_output = repo / ".docgarden" / "slice-loops" / "worker-round-1.output.json"
    review_output = repo / ".docgarden" / "slice-loops" / "review-round-1.output.json"

    prompt = build_implementation_prompt(
        repo,
        current,
        next_slice=next_slice,
        paths=paths,
        round_number=2,
        review_feedback_path=review_output,
        previous_worker_output_path=worker_output,
    )

    assert "docs/design-docs/docgarden-implementation-slices.md" in prompt
    assert "do not jump ahead into S08 routing quality detector for stale targets" in prompt
    assert f"- prior worker output: {worker_output}" in prompt
    assert f"- latest reviewer feedback: {review_output}" in prompt


def test_build_review_prompt_includes_prior_review_and_rereview_note(tmp_path) -> None:
    repo = make_slice_repo(tmp_path)
    paths = build_slice_paths(repo)
    current = make_slice_definition(slice_id="S07", title="Workflow drift detector")
    worker_output = repo / ".docgarden" / "slice-loops" / "worker-round-2.output.json"
    prior_review = repo / ".docgarden" / "slice-loops" / "review-round-1.output.json"

    prompt = build_review_prompt(
        repo,
        current,
        next_slice=None,
        paths=paths,
        worker_output_path=worker_output,
        round_number=2,
        prior_review_path=prior_review,
    )

    assert f"- latest worker output JSON: {worker_output}" in prompt
    assert f"- prior review output JSON: {prior_review}" in prompt
    assert "Did the implementation stay within S07 without unnecessary sprawl?" in prompt
    assert "this is a follow-up review after revision work" in prompt


def test_run_slice_loop_rejects_explicit_blocked_start_slice(tmp_path) -> None:
    repo = make_slice_repo(tmp_path)

    with pytest.raises(
        DocgardenError,
        match="Cannot start slice S08 until dependencies are completed: S07.",
    ):
        run_slice_loop(repo, start_slice="S08")


def test_load_slice_run_status_normalizes_optional_fields(tmp_path) -> None:
    run_dir = tmp_path / "slice-loops" / "20260309-010101-s07"
    run_dir.mkdir(parents=True)
    write_json(
        run_dir / "run-status.json",
        {
            "slice_id": "S07",
            "status": "running",
            "updated_at": "2026-03-09T01:01:01",
        },
    )

    status = load_slice_run_status(run_dir)

    assert status["slice_id"] == "S07"
    assert status["title"] is None
    assert status["current_phase"] is None
    assert status["elapsed_seconds"] is None
    assert status["retry_of"] is None


def test_partition_run_artifact_untracked_paths_separates_artifacts(tmp_path) -> None:
    repo = tmp_path
    run_dir = repo / ".docgarden" / "slice-loops" / "20260309-010101-s07"

    operator_paths, artifact_paths = _partition_run_artifact_untracked_paths(
        [
            ".docgarden/slice-loops/20260309-010101-s07/review-round-1.output.json",
            ".docgarden/slice-loops/20260309-010101-s07/stdout.txt",
            "docgarden/slices/runner.py",
        ],
        repo_root=repo,
        run_dir=run_dir,
    )

    assert operator_paths == ["docgarden/slices/runner.py"]
    assert artifact_paths == [
        ".docgarden/slice-loops/20260309-010101-s07/review-round-1.output.json",
        ".docgarden/slice-loops/20260309-010101-s07/stdout.txt",
    ]


def test_recovery_recommendation_prefers_review_outputs() -> None:
    payload = {
        "status": {"status": "failed"},
        "new_tracked_changes": ["docgarden/slices/runner.py"],
        "worker_outputs": ["worker-round-1.output.json"],
        "review_outputs": ["review-round-1.output.json"],
    }

    assert _recovery_recommendation(payload) == "review_output_available"


def test_build_codex_subprocess_env_strips_parent_codex_controls(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_CI", "1")
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-123")
    monkeypatch.setenv("KEEP_ME", "still-here")

    env = _build_codex_subprocess_env()

    assert "CODEX_CI" not in env
    assert "CODEX_THREAD_ID" not in env
    assert env["KEEP_ME"] == "still-here"


def test_review_progress_reads_and_signs_review_output(tmp_path) -> None:
    review_output = tmp_path / "review-round-1.output.json"
    payload = {
        "recommendation": "revise_before_next_slice",
        "summary": "Still missing the same workflow filter.",
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
    }
    write_json(review_output, payload)

    parsed = read_review_output(review_output)

    assert parsed == payload
    assert load_review_signature(review_output) == review_signature(payload)


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
    assert "do not run `docgarden slices` commands" in kickoff
    assert "`docgarden-slice-orchestrator` skill" in kickoff
    assert "prioritize the smallest end-to-end change" in kickoff

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
    assert "Review guardrails:" in review_prompt
    assert "do not run `docgarden slices` commands" in review_prompt


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


def test_cli_slices_next_uses_dependency_aware_schedule(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    monkeypatch.chdir(repo)

    assert main(["slices", "next"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["slice_id"] == "S07"
    assert payload["depends_on"] == ["S06"]
    assert payload["next_slice"] == "S08"


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
                "files_touched": ["docgarden/scan/alignment.py"],
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
                "files_touched": ["docgarden/scan/alignment.py", "tests/test_support_modules.py"],
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
                "files_touched": ["docgarden/scan/linkage.py"],
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
    timeouts: list[int | None] = []

    def fake_popen(cmd, cwd, stdin, stdout, stderr, text, env):
        assert cwd == repo
        assert stdin == subprocess.PIPE
        assert text is True
        assert env is not None
        assert "CODEX_CI" not in env
        assert "CODEX_SANDBOX" not in env
        assert "CODEX_SANDBOX_NETWORK_DISABLED" not in env
        assert "CODEX_THREAD_ID" not in env
        assert "--ephemeral" in cmd
        assert "-c" in cmd
        assert "mcp_servers.pencil.enabled=false" in cmd
        assert "mcp_servers.openaiDeveloperDocs.enabled=false" in cmd
        assert "sandbox_workspace_write.network_access=true" in cmd

        payload = next(responses)

        def write_output(command) -> None:
            output_path = Path(command[command.index("--output-last-message") + 1])
            output_path.write_text(json.dumps(payload), encoding="utf-8")

        return FakePopen(
            cmd,
            stdout_file=stdout,
            stderr_file=stderr,
            response={"stdout": "ok\n", "write_output": write_output},
            timeout_log=timeouts,
        )

    monkeypatch.setattr("docgarden.slices.run_agent.subprocess.Popen", fake_popen)

    assert main(["slices", "run", "--max-slices", "2"]) == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)

    assert summary["status"] == "completed"
    assert summary["processed_slices"] == 2
    assert [item["slice_id"] for item in summary["results"]] == ["S07", "S08"]
    assert summary["results"][0]["worker_rounds"] == 2
    assert summary["results"][0]["recommendation"] == "ready_for_next_slice"
    assert summary["results"][1]["worker_rounds"] == 1
    assert summary["next_slice"] is None
    assert timeouts == [900, 300, 900, 300, 900, 300]
    assert "slice S07: artifacts ->" in captured.err
    assert "slice S08: artifacts ->" in captured.err

    loop_root = repo / ".docgarden" / "slice-loops"
    run_dirs = sorted(path for path in loop_root.iterdir() if path.is_dir())
    assert len(run_dirs) == 2
    first_run = run_dirs[0]
    assert (first_run / "worker-round-1.output.json").exists()
    assert (first_run / "review-round-1.output.json").exists()
    assert (first_run / "worker-round-2.output.json").exists()
    assert (first_run / "review-round-2.output.json").exists()
    status = json.loads((first_run / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "ready_for_next_slice"
    assert status["worker_timeout_seconds"] == 900
    assert status["reviewer_timeout_seconds"] == 300
    assert status["baseline_recorded_at"]
    assert status["baseline_tracked_changes"] == []
    assert status["baseline_untracked_paths"] == []
    assert status["phase_started_at"]
    assert status["last_heartbeat_at"]
    assert status["elapsed_seconds"] >= 0
    assert status["agent_pid"] >= 1000


def test_cli_slices_run_stops_after_repeated_review_findings(tmp_path, monkeypatch, capsys) -> None:
    repo = make_slice_repo(tmp_path)
    monkeypatch.chdir(repo)
    responses = iter(
        [
            {
                "status": "completed",
                "summary": "Implemented S07 first pass.",
                "files_touched": ["docgarden/scan/alignment.py"],
                "tests_run": ["uv run pytest"],
                "docs_updated": [],
                "notes_for_reviewer": [],
                "open_questions": [],
            },
            {
                "recommendation": "revise_before_next_slice",
                "summary": "Still missing the same workflow filter.",
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
                "summary": "Attempted a revision.",
                "files_touched": ["docgarden/scan/alignment.py"],
                "tests_run": ["uv run pytest"],
                "docs_updated": [],
                "notes_for_reviewer": [],
                "open_questions": [],
            },
            {
                "recommendation": "revise_before_next_slice",
                "summary": "Still missing the same workflow filter.",
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
        ]
    )

    def fake_popen(cmd, cwd, stdin, stdout, stderr, text, env):
        payload = next(responses)

        def write_output(command) -> None:
            output_path = Path(command[command.index("--output-last-message") + 1])
            output_path.write_text(json.dumps(payload), encoding="utf-8")

        return FakePopen(
            cmd,
            stdout_file=stdout,
            stderr_file=stderr,
            response={"write_output": write_output},
            timeout_log=[],
        )

    monkeypatch.setattr("docgarden.slices.run_agent.subprocess.Popen", fake_popen)

    assert main(["slices", "run", "--max-slices", "1", "--max-review-rounds", "3"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "stopped"
    assert payload["results"][0]["recommendation"] == "stopped_no_progress"

    run_dir = Path(payload["results"][0]["run_dir"])
    status = json.loads((run_dir / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "stopped_no_progress"
    assert status["recommendation"] == "stopped_no_progress"
    assert "no material progress" in status["stop_note"]


def test_cli_slices_run_times_out_and_persists_partial_logs(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    monkeypatch.chdir(repo)
    timeouts: list[int | None] = []

    def fake_popen(cmd, cwd, stdin, stdout, stderr, text, env):
        assert env is not None
        assert "--ephemeral" in cmd
        assert "mcp_servers.pencil.enabled=false" in cmd
        assert "mcp_servers.openaiDeveloperDocs.enabled=false" in cmd
        assert "sandbox_workspace_write.network_access=true" in cmd

        def write_progress(_command) -> None:
            write(repo / "docs" / "progress.md", "# Partial progress\n")

        return FakePopen(
            cmd,
            stdout_file=stdout,
            stderr_file=stderr,
            response={
                "stdout": "partial stdout\n",
                "stderr": "partial stderr\n",
                "write_output": write_progress,
                "timeout": True,
            },
            timeout_log=timeouts,
        )

    monkeypatch.setattr("docgarden.slices.run_agent.subprocess.Popen", fake_popen)

    assert main(["slices", "run", "--agent-timeout-seconds", "12"]) == 1
    captured = capsys.readouterr()
    assert "timed out for worker-round-1 after 12 seconds" in captured.err
    assert "slice S07: artifacts ->" in captured.err
    assert timeouts == [12, None]

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
    status = json.loads((run_dir / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["current_phase"] == "worker"
    assert status["current_prefix"] == "worker-round-1"
    assert "timed out for worker-round-1 after 12 seconds" in status["error"]
    assert status["phase_started_at"]
    assert status["last_heartbeat_at"]
    assert status["elapsed_seconds"] >= 0
    assert (repo / "docs" / "progress.md").exists()


def test_cli_slices_run_nonzero_exit_persists_logs(tmp_path, monkeypatch, capsys) -> None:
    repo = make_slice_repo(tmp_path)
    monkeypatch.chdir(repo)
    timeouts: list[int | None] = []

    def fake_popen(cmd, cwd, stdin, stdout, stderr, text, env):
        assert env is not None
        assert "--ephemeral" in cmd
        assert "mcp_servers.pencil.enabled=false" in cmd
        assert "mcp_servers.openaiDeveloperDocs.enabled=false" in cmd
        assert "sandbox_workspace_write.network_access=true" in cmd
        return FakePopen(
            cmd,
            stdout_file=stdout,
            stderr_file=stderr,
            response={
                "stdout": "agent stdout\n",
                "stderr": "agent stderr\n",
                "returncode": 17,
            },
            timeout_log=timeouts,
        )

    monkeypatch.setattr("docgarden.slices.run_agent.subprocess.Popen", fake_popen)

    assert main(["slices", "run"]) == 1
    captured = capsys.readouterr()
    assert "exit code 17" in captured.err
    assert "worker-round-1.stderr.txt" in captured.err
    assert timeouts == [900]

    run_dirs = sorted((repo / ".docgarden" / "slice-loops").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "worker-round-1.stdout.txt").read_text(encoding="utf-8") == (
        "agent stdout\n"
    )
    assert (run_dir / "worker-round-1.stderr.txt").read_text(encoding="utf-8") == (
        "agent stderr\n"
    )
    status = json.loads((run_dir / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["worker_timeout_seconds"] == 900
    assert status["phase_started_at"]
    assert status["last_heartbeat_at"]
    assert status["elapsed_seconds"] >= 0


def test_cli_slices_run_supports_role_specific_timeouts(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    monkeypatch.chdir(repo)
    timeouts: list[int | None] = []
    responses = iter(
        [
            {
                "status": "completed",
                "summary": "Implemented S07.",
                "files_touched": ["docgarden/scan/alignment.py"],
                "tests_run": ["uv run pytest"],
                "docs_updated": [],
                "notes_for_reviewer": [],
                "open_questions": [],
            },
            {
                "recommendation": "ready_for_next_slice",
                "summary": "S07 is ready.",
                "findings": [],
                "next_step": "Move on.",
            },
        ]
    )

    def fake_popen(cmd, cwd, stdin, stdout, stderr, text, env):
        payload = next(responses)

        def write_output(command) -> None:
            output_path = Path(command[command.index("--output-last-message") + 1])
            output_path.write_text(json.dumps(payload), encoding="utf-8")

        return FakePopen(
            cmd,
            stdout_file=stdout,
            stderr_file=stderr,
            response={"write_output": write_output},
            timeout_log=timeouts,
        )

    monkeypatch.setattr("docgarden.slices.run_agent.subprocess.Popen", fake_popen)

    assert (
        main(
            [
                "slices",
                "run",
                "--max-slices",
                "1",
                "--worker-timeout-seconds",
                "15",
                "--reviewer-timeout-seconds",
                "4",
            ]
        )
        == 0
    )
    _ = capsys.readouterr()
    assert timeouts == [15, 4]


def test_cli_slices_run_updates_run_status_heartbeat_during_long_worker(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    monkeypatch.chdir(repo)
    monkeypatch.setattr("docgarden.slices.run_agent.RUN_STATUS_HEARTBEAT_SECONDS", 0.01)
    timeouts: list[int | None] = []
    responses = iter(
        [
            {
                "status": "blocked",
                "summary": "Need product clarification.",
                "files_touched": ["docgarden/scan/alignment.py"],
                "tests_run": ["uv run pytest"],
                "docs_updated": [],
                "notes_for_reviewer": [],
                "open_questions": ["Clarify product behavior."],
            },
        ]
    )

    def fake_popen(cmd, cwd, stdin, stdout, stderr, text, env):
        payload = next(responses)

        def write_output(command) -> None:
            output_path = Path(command[command.index("--output-last-message") + 1])
            output_path.write_text(json.dumps(payload), encoding="utf-8")

        sleep_seconds = 0.12
        return FakePopen(
            cmd,
            stdout_file=stdout,
            stderr_file=stderr,
            response={
                "write_output": write_output,
                "sleep_seconds": sleep_seconds,
            },
            timeout_log=timeouts,
        )

    monkeypatch.setattr("docgarden.slices.run_agent.subprocess.Popen", fake_popen)

    assert main(["slices", "run", "--max-slices", "1"]) == 1
    _ = capsys.readouterr()
    run_dirs = sorted((repo / ".docgarden" / "slice-loops").iterdir())
    assert len(run_dirs) == 1
    status = json.loads((run_dirs[0] / "run-status.json").read_text(encoding="utf-8"))
    assert status["status"] == "blocked_pending_product_clarification"
    assert status["elapsed_seconds"] > 0
    assert status["last_heartbeat_at"] >= status["phase_started_at"]


def test_cli_slices_run_rejects_mixed_timeout_flags(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    monkeypatch.chdir(repo)

    assert (
        main(
            [
                "slices",
                "run",
                "--agent-timeout-seconds",
                "12",
                "--worker-timeout-seconds",
                "20",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "Use either `--agent-timeout-seconds` or the per-role timeout flags" in captured.err


def test_cli_slices_watch_prints_latest_run_summary(tmp_path, monkeypatch, capsys) -> None:
    repo = make_slice_repo(tmp_path)
    run_dir = repo / ".docgarden" / "slice-loops" / "2026-03-09T101500-s10"
    write_json(
        run_dir / "run-status.json",
        {
            "slice_id": "S10",
            "status": "running",
            "current_phase": "worker",
            "elapsed_seconds": 12.5,
        },
    )
    monkeypatch.chdir(repo)

    assert main(["slices", "watch", "--max-updates", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_dir"] == str(run_dir)
    assert payload["status"]["slice_id"] == "S10"
    assert payload["status"]["elapsed_seconds"] == 12.5


def test_cli_slices_list_reports_runs(tmp_path, monkeypatch, capsys) -> None:
    repo = make_slice_repo(tmp_path)
    first = repo / ".docgarden" / "slice-loops" / "2026-03-09T101500-s09"
    second = repo / ".docgarden" / "slice-loops" / "2026-03-09T101501-s10"
    write_json(first / "run-status.json", {"slice_id": "S09", "status": "ready_for_next_slice"})
    write_json(second / "run-status.json", {"slice_id": "S10", "status": "failed"})
    monkeypatch.chdir(repo)

    assert main(["slices", "list"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifacts_dir"].endswith(".docgarden/slice-loops")
    assert [item["slice_id"] for item in payload["runs"]] == ["S10", "S09"]
    assert payload["runs"][0]["title"] is None
    assert payload["runs"][0]["current_phase"] is None
    assert payload["runs"][0]["elapsed_seconds"] is None
    assert payload["runs"][0]["retry_of"] is None


def test_cli_slices_list_handles_legacy_run_without_status(tmp_path, monkeypatch, capsys) -> None:
    repo = make_slice_repo(tmp_path)
    legacy = repo / ".docgarden" / "slice-loops" / "2026-03-09T092208-s08"
    legacy.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(repo)

    assert main(["slices", "list"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["runs"][0]["slice_id"] == "S08"
    assert payload["runs"][0]["status"] == "legacy_missing_status"
    assert payload["runs"][0]["title"] is None
    assert payload["runs"][0]["current_phase"] is None
    assert payload["runs"][0]["elapsed_seconds"] is None
    assert payload["runs"][0]["retry_of"] is None


def test_cli_slices_stop_marks_run_stopped(tmp_path, monkeypatch, capsys) -> None:
    repo = make_slice_repo(tmp_path)
    run_dir = repo / ".docgarden" / "slice-loops" / "2026-03-09T101501-s10"
    write_json(
        run_dir / "run-status.json",
        {
            "slice_id": "S10",
            "status": "running",
            "current_phase": "worker",
            "agent_pid": 4242,
            "last_heartbeat_at": "2026-03-09T10:15:01",
        },
    )
    monkeypatch.chdir(repo)
    killed: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        killed.append((pid, sig))

    monkeypatch.setattr("docgarden.slices.run_status.os.kill", fake_kill)

    assert main(["slices", "stop"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"]["status"] == "stopped"
    assert payload["status"]["stop_note"] == "Sent SIGTERM to pid 4242."
    assert killed == [(4242, 15)]


def test_cli_slices_recover_runs_verification_and_reports_partial_changes(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    run_dir = repo / ".docgarden" / "slice-loops" / "2026-03-09T101502-s10"
    write_json(
        run_dir / "run-status.json",
        {
            "slice_id": "S10",
            "status": "failed",
            "current_phase": "worker",
            "error": "worker timed out",
        },
    )
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        "docgarden.slices.run_recovery._git_diff_name_only",
        lambda repo_root: ["docgarden/state.py"],
    )
    monkeypatch.setattr(
        "docgarden.slices.run_recovery._git_untracked_paths",
        lambda repo_root: [".docgarden/slice-loops/"],
    )

    def fake_run(cmd, cwd, text, capture_output, check, timeout):
        assert timeout == 300
        if cmd == ["uv", "run", "pytest"]:
            return subprocess.CompletedProcess(cmd, 0, "pytest ok\n", "")
        if cmd == ["uv", "run", "docgarden", "scan"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                json.dumps({"findings": 0, "overall_score": 100}),
                "",
            )
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr("docgarden.slices.run_recovery.subprocess.run", fake_run)

    assert main(["slices", "recover"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["recovery_recommendation"] == "partial_repo_changes_need_review"
    assert payload["tracked_changes"] == ["docgarden/state.py"]
    assert payload["untracked_paths"] == []
    assert payload["current_tracked_changes"] == ["docgarden/state.py"]
    assert payload["new_tracked_changes"] == ["docgarden/state.py"]
    assert payload["run_artifact_untracked_paths"] == [".docgarden/slice-loops/"]
    assert payload["verification"]["pytest"]["returncode"] == 0
    assert payload["verification"]["scan"]["returncode"] == 0


def test_cli_slices_recover_reports_verification_timeout(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    run_dir = repo / ".docgarden" / "slice-loops" / "2026-03-09T101502-s10"
    write_json(
        run_dir / "run-status.json",
        {
            "slice_id": "S10",
            "status": "stopped_no_progress",
            "current_phase": "review",
            "error": "repeated findings",
        },
    )
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        "docgarden.slices.run_recovery._git_diff_name_only",
        lambda repo_root: [],
    )
    monkeypatch.setattr(
        "docgarden.slices.run_recovery._git_untracked_paths",
        lambda repo_root: [],
    )

    def fake_run(cmd, cwd, text, capture_output, check, timeout):
        raise subprocess.TimeoutExpired(
            cmd=cmd,
            timeout=timeout,
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr("docgarden.slices.run_recovery.subprocess.run", fake_run)

    assert main(["slices", "recover"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["recovery_recommendation"] == "safe_to_retry"
    assert payload["verification"]["pytest"]["timed_out"] is True
    assert (
        payload["verification"]["pytest"]["timeout_seconds"]
        == 300
    )
    assert payload["verification"]["scan"]["timed_out"] is True


def test_cli_slices_recover_subtracts_preexisting_repo_state(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    run_dir = repo / ".docgarden" / "slice-loops" / "2026-03-09T101503-s10"
    write_json(
        run_dir / "run-status.json",
        {
            "slice_id": "S10",
            "status": "failed",
            "current_phase": "worker",
            "baseline_recorded_at": "2026-03-09T10:15:02",
            "baseline_tracked_changes": ["README.md"],
            "baseline_untracked_paths": [".docgarden/slice-loops/"],
            "error": "worker timed out",
        },
    )
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        "docgarden.slices.run_recovery._git_diff_name_only",
        lambda repo_root: ["README.md", "docgarden/state.py"],
    )
    monkeypatch.setattr(
        "docgarden.slices.run_recovery._git_untracked_paths",
        lambda repo_root: [".docgarden/slice-loops/", "scratch.txt"],
    )

    assert main(["slices", "recover", "--skip-verification"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["baseline_tracked_changes"] == ["README.md"]
    assert payload["baseline_untracked_paths"] == [".docgarden/slice-loops/"]
    assert payload["current_tracked_changes"] == ["README.md", "docgarden/state.py"]
    assert payload["current_untracked_paths"] == [".docgarden/slice-loops/", "scratch.txt"]
    assert payload["tracked_changes"] == ["docgarden/state.py"]
    assert payload["untracked_paths"] == ["scratch.txt"]
    assert payload["new_tracked_changes"] == ["docgarden/state.py"]
    assert payload["new_untracked_paths"] == ["scratch.txt"]
    assert payload["run_artifact_untracked_paths"] == []
    assert payload["preexisting_tracked_changes"] == ["README.md"]
    assert payload["preexisting_untracked_paths"] == [".docgarden/slice-loops/"]
    assert payload["recovery_recommendation"] == "partial_repo_changes_need_review"


def test_cli_slices_recover_ignores_only_preexisting_repo_state_for_retry(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    run_dir = repo / ".docgarden" / "slice-loops" / "2026-03-09T101504-s10"
    write_json(
        run_dir / "run-status.json",
        {
            "slice_id": "S10",
            "status": "failed",
            "current_phase": "worker",
            "baseline_recorded_at": "2026-03-09T10:15:03",
            "baseline_tracked_changes": ["README.md"],
            "baseline_untracked_paths": [".docgarden/slice-loops/"],
            "error": "worker timed out",
        },
    )
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        "docgarden.slices.run_recovery._git_diff_name_only",
        lambda repo_root: ["README.md"],
    )
    monkeypatch.setattr(
        "docgarden.slices.run_recovery._git_untracked_paths",
        lambda repo_root: [".docgarden/slice-loops/"],
    )

    assert main(["slices", "recover", "--skip-verification"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tracked_changes"] == []
    assert payload["untracked_paths"] == []
    assert payload["new_untracked_paths"] == []
    assert payload["run_artifact_untracked_paths"] == []
    assert payload["preexisting_tracked_changes"] == ["README.md"]
    assert payload["preexisting_untracked_paths"] == [".docgarden/slice-loops/"]
    assert payload["recovery_recommendation"] == "safe_to_retry"


def test_cli_slices_recover_separates_run_artifact_untracked_paths(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    run_dir = repo / ".docgarden" / "slice-loops" / "2026-03-09T101505-s10"
    write_json(
        run_dir / "run-status.json",
        {
            "slice_id": "S10",
            "status": "failed",
            "current_phase": "worker",
            "baseline_recorded_at": "2026-03-09T10:15:04",
            "baseline_tracked_changes": [],
            "baseline_untracked_paths": [],
            "error": "worker timed out",
        },
    )
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        "docgarden.slices.run_recovery._git_diff_name_only",
        lambda repo_root: [],
    )
    monkeypatch.setattr(
        "docgarden.slices.run_recovery._git_untracked_paths",
        lambda repo_root: [
            ".docgarden/slice-loops/",
            ".docgarden/slice-loops/2026-03-09T101505-s10/",
            "scratch.txt",
        ],
    )

    assert main(["slices", "recover", "--skip-verification"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tracked_changes"] == []
    assert payload["untracked_paths"] == ["scratch.txt"]
    assert payload["new_untracked_paths"] == ["scratch.txt"]
    assert payload["run_artifact_untracked_paths"] == [
        ".docgarden/slice-loops/",
        ".docgarden/slice-loops/2026-03-09T101505-s10/",
    ]
    assert payload["recovery_recommendation"] == "safe_to_retry"


def test_cli_slices_prune_dry_run_and_apply(tmp_path, monkeypatch, capsys) -> None:
    repo = make_slice_repo(tmp_path)
    run_root = repo / ".docgarden" / "slice-loops"
    for name, status in [
        ("2026-03-09T101500-s07", "failed"),
        ("2026-03-09T101501-s08", "ready_for_next_slice"),
        ("2026-03-09T101502-s09", "stopped"),
    ]:
        write_json(run_root / name / "run-status.json", {"slice_id": name[-3:].upper(), "status": status})
    monkeypatch.chdir(repo)

    assert main(["slices", "prune", "--keep", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["prune_candidates"]) == 2
    assert len(payload["removed_runs"]) == 0
    assert len(list(run_root.iterdir())) == 3

    assert main(["slices", "prune", "--keep", "1", "--apply"]) == 0
    applied = json.loads(capsys.readouterr().out)
    assert len(applied["removed_runs"]) == 2
    remaining = sorted(path.name for path in run_root.iterdir())
    assert remaining == ["2026-03-09T101502-s09"]


def test_cli_slices_retry_reuses_prior_review_context(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    prior_run_dir = repo / ".docgarden" / "slice-loops" / "2026-03-09T101503-s07"
    prior_worker_output = prior_run_dir / "worker-round-1.output.json"
    prior_review_output = prior_run_dir / "review-round-1.output.json"
    write_json(prior_worker_output, {"status": "completed", "summary": "round 1"})
    write_json(
        prior_review_output,
        {
            "recommendation": "revise_before_next_slice",
            "summary": "needs revision",
            "findings": [],
            "next_step": "Revise.",
        },
    )
    write_json(
        prior_run_dir / "run-status.json",
        {
            "slice_id": "S07",
            "status": "failed",
            "current_phase": "worker",
            "current_round": 2,
            "last_worker_output": str(prior_worker_output),
            "last_review_output": str(prior_review_output),
        },
    )
    monkeypatch.chdir(repo)
    responses = iter(
        [
            {
                "status": "completed",
                "summary": "Implemented revision.",
                "files_touched": ["docgarden/scan/alignment.py"],
                "tests_run": ["uv run pytest"],
                "docs_updated": [],
                "notes_for_reviewer": ["Revision applied."],
                "open_questions": [],
            },
            {
                "recommendation": "ready_for_next_slice",
                "summary": "S07 is ready.",
                "findings": [],
                "next_step": "Move on.",
            },
        ]
    )
    timeouts: list[int | None] = []

    def fake_popen(cmd, cwd, stdin, stdout, stderr, text, env):
        payload = next(responses)

        def write_output(command) -> None:
            output_path = Path(command[command.index("--output-last-message") + 1])
            output_path.write_text(json.dumps(payload), encoding="utf-8")

        return FakePopen(
            cmd,
            stdout_file=stdout,
            stderr_file=stderr,
            response={"write_output": write_output},
            timeout_log=timeouts,
        )

    monkeypatch.setattr("docgarden.slices.run_agent.subprocess.Popen", fake_popen)

    assert main(["slices", "retry", "--run-dir", str(prior_run_dir)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["retried_from"] == str(prior_run_dir)
    assert payload["results"][0]["recommendation"] == "ready_for_next_slice"
    assert timeouts == [900, 300]
    new_run_dir = Path(payload["results"][0]["run_dir"])
    worker_prompt = (new_run_dir / "worker-round-2.prompt.txt").read_text(encoding="utf-8")
    assert str(prior_worker_output) in worker_prompt
    assert str(prior_review_output) in worker_prompt


def test_cli_slices_retry_rejects_successful_run(
    tmp_path, monkeypatch, capsys
) -> None:
    repo = make_slice_repo(tmp_path)
    prior_run_dir = repo / ".docgarden" / "slice-loops" / "2026-03-09T101504-s07"
    write_json(
        prior_run_dir / "run-status.json",
        {
            "slice_id": "S07",
            "status": "ready_for_next_slice",
        },
    )
    monkeypatch.chdir(repo)

    assert main(["slices", "retry", "--run-dir", str(prior_run_dir)]) == 1
    captured = capsys.readouterr()
    assert "Cannot retry successful slice run" in captured.err
