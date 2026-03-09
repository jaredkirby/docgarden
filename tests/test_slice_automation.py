from __future__ import annotations

import json
import subprocess
from pathlib import Path
import time

from docgarden.cli import main
from docgarden.slice_automation import build_slice_paths, load_slice_catalog


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

    monkeypatch.setattr("docgarden.slices.runner.subprocess.Popen", fake_popen)

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
    assert status["phase_started_at"]
    assert status["last_heartbeat_at"]
    assert status["elapsed_seconds"] >= 0
    assert status["agent_pid"] >= 1000


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

    monkeypatch.setattr("docgarden.slices.runner.subprocess.Popen", fake_popen)

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

    monkeypatch.setattr("docgarden.slices.runner.subprocess.Popen", fake_popen)

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
                "files_touched": ["docgarden/scan_alignment.py"],
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

    monkeypatch.setattr("docgarden.slices.runner.subprocess.Popen", fake_popen)

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
    monkeypatch.setattr("docgarden.slices.runner.RUN_STATUS_HEARTBEAT_SECONDS", 0.01)
    timeouts: list[int | None] = []
    responses = iter(
        [
            {
                "status": "blocked",
                "summary": "Need product clarification.",
                "files_touched": ["docgarden/scan_alignment.py"],
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

    monkeypatch.setattr("docgarden.slices.runner.subprocess.Popen", fake_popen)

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

    monkeypatch.setattr("docgarden.slices.runner.os.kill", fake_kill)

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
        "docgarden.slices.runner._git_diff_name_only",
        lambda repo_root: ["docgarden/state.py"],
    )
    monkeypatch.setattr(
        "docgarden.slices.runner._git_untracked_paths",
        lambda repo_root: [".docgarden/slice-loops/"],
    )

    def fake_run(cmd, cwd, text, capture_output, check):
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

    monkeypatch.setattr("docgarden.slices.runner.subprocess.run", fake_run)

    assert main(["slices", "recover"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["recovery_recommendation"] == "partial_repo_changes_need_review"
    assert payload["tracked_changes"] == ["docgarden/state.py"]
    assert payload["verification"]["pytest"]["returncode"] == 0
    assert payload["verification"]["scan"]["returncode"] == 0
