from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from ..errors import DocgardenError
from ..files import atomic_write_text
from .catalog import SliceDefinition, load_slice_catalog
from .config import SliceAutomationPaths, build_slice_paths
from .prompts import (
    REVIEW_OUTPUT_SCHEMA,
    WORKER_OUTPUT_SCHEMA,
    build_implementation_prompt,
    build_review_prompt,
)


CODEX_ENV_DENYLIST = {
    "CODEX_CI",
    "CODEX_SANDBOX",
    "CODEX_SANDBOX_NETWORK_DISABLED",
    "CODEX_THREAD_ID",
}

DEFAULT_CODEX_EXEC_ARGS = (
    "--ephemeral",
    "-c",
    "mcp_servers.pencil.enabled=false",
    "-c",
    "mcp_servers.openaiDeveloperDocs.enabled=false",
    "-c",
    "sandbox_workspace_write.network_access=true",
)


@dataclass(slots=True)
class AgentRunArtifact:
    prompt_path: Path
    schema_path: Path
    output_path: Path
    stdout_path: Path
    stderr_path: Path
    parsed_output: dict[str, Any]
    command: list[str]


@dataclass(slots=True)
class SliceRunResult:
    slice_id: str
    title: str
    recommendation: str
    worker_rounds: int
    run_dir: str
    worker_outputs: list[str] = field(default_factory=list)
    review_outputs: list[str] = field(default_factory=list)


def run_slice_loop(
    repo_root: Path,
    *,
    paths: SliceAutomationPaths | None = None,
    start_slice: str | None = None,
    max_slices: int = 1,
    max_review_rounds: int = 3,
    agent_timeout_seconds: int | None = 300,
    codex_bin: str = "codex",
    model: str | None = None,
    codex_args: list[str] | None = None,
) -> dict[str, Any]:
    resolved_paths = paths or build_slice_paths(repo_root)
    catalog = load_slice_catalog(repo_root, paths=resolved_paths)
    current = (
        catalog.by_id(start_slice) if start_slice is not None else catalog.next_actionable_slice()
    )
    if current is None:
        return {
            "status": "noop",
            "message": "No queued or active slices remain.",
            "results": [],
        }
    if current.status not in {"queued", "active"}:
        raise DocgardenError(
            f"Cannot start from non-actionable slice {current.slice_id}: {current.status}."
        )

    loop_root = resolved_paths.artifacts_dir
    loop_root.mkdir(parents=True, exist_ok=True)
    results: list[SliceRunResult] = []
    processed = 0

    while current is not None and (max_slices <= 0 or processed < max_slices):
        next_slice = catalog.next_after(current.slice_id)
        slice_result = _run_single_slice(
            repo_root,
            paths=resolved_paths,
            loop_root=loop_root,
            slice_def=current,
            next_slice=next_slice,
            max_review_rounds=max_review_rounds,
            agent_timeout_seconds=agent_timeout_seconds,
            codex_bin=codex_bin,
            model=model,
            codex_args=codex_args or [],
        )
        results.append(slice_result)
        processed += 1
        if slice_result.recommendation != "ready_for_next_slice":
            return {
                "status": "stopped",
                "stopped_at": current.slice_id,
                "results": [asdict(item) for item in results],
            }
        current = next_slice

    return {
        "status": "completed",
        "processed_slices": len(results),
        "results": [asdict(item) for item in results],
        "next_slice": current.slice_id if current is not None else None,
    }


def _run_single_slice(
    repo_root: Path,
    *,
    paths: SliceAutomationPaths,
    loop_root: Path,
    slice_def: SliceDefinition,
    next_slice: SliceDefinition | None,
    max_review_rounds: int,
    agent_timeout_seconds: int | None,
    codex_bin: str,
    model: str | None,
    codex_args: list[str],
) -> SliceRunResult:
    timestamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    run_dir = loop_root / f"{timestamp}-{slice_def.slice_id.lower()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    worker_outputs: list[str] = []
    review_outputs: list[str] = []
    prior_review_path: Path | None = None
    previous_worker_output_path: Path | None = None

    for round_number in range(1, max_review_rounds + 1):
        worker_prompt = build_implementation_prompt(
            repo_root,
            slice_def,
            next_slice=next_slice,
            paths=paths,
            round_number=round_number,
            review_feedback_path=prior_review_path,
            previous_worker_output_path=previous_worker_output_path,
        )
        worker_run = _run_codex_agent(
            repo_root,
            run_dir=run_dir,
            codex_bin=codex_bin,
            codex_args=codex_args,
            model=model,
            prompt=worker_prompt,
            schema=WORKER_OUTPUT_SCHEMA,
            prefix=f"worker-round-{round_number}",
            timeout_seconds=agent_timeout_seconds,
        )
        worker_outputs.append(str(worker_run.output_path))
        previous_worker_output_path = worker_run.output_path
        if worker_run.parsed_output["status"] == "blocked":
            return SliceRunResult(
                slice_id=slice_def.slice_id,
                title=slice_def.title,
                recommendation="blocked_pending_product_clarification",
                worker_rounds=round_number,
                run_dir=str(run_dir),
                worker_outputs=worker_outputs,
                review_outputs=review_outputs,
            )

        review_prompt = build_review_prompt(
            repo_root,
            slice_def,
            next_slice=next_slice,
            paths=paths,
            worker_output_path=worker_run.output_path,
            round_number=round_number,
            prior_review_path=prior_review_path,
        )
        review_run = _run_codex_agent(
            repo_root,
            run_dir=run_dir,
            codex_bin=codex_bin,
            codex_args=codex_args,
            model=model,
            prompt=review_prompt,
            schema=REVIEW_OUTPUT_SCHEMA,
            prefix=f"review-round-{round_number}",
            timeout_seconds=agent_timeout_seconds,
        )
        review_outputs.append(str(review_run.output_path))
        prior_review_path = review_run.output_path
        recommendation = str(review_run.parsed_output["recommendation"])
        if recommendation in {
            "ready_for_next_slice",
            "blocked_pending_product_clarification",
        }:
            return SliceRunResult(
                slice_id=slice_def.slice_id,
                title=slice_def.title,
                recommendation=recommendation,
                worker_rounds=round_number,
                run_dir=str(run_dir),
                worker_outputs=worker_outputs,
                review_outputs=review_outputs,
            )

    raise DocgardenError(
        f"Exceeded max review rounds ({max_review_rounds}) for {slice_def.slice_id}."
    )


def _run_codex_agent(
    repo_root: Path,
    *,
    run_dir: Path,
    codex_bin: str,
    codex_args: list[str],
    model: str | None,
    prompt: str,
    schema: dict[str, Any],
    prefix: str,
    timeout_seconds: int | None,
) -> AgentRunArtifact:
    prompt_path = run_dir / f"{prefix}.prompt.txt"
    schema_path = run_dir / f"{prefix}.schema.json"
    output_path = run_dir / f"{prefix}.output.json"
    stdout_path = run_dir / f"{prefix}.stdout.txt"
    stderr_path = run_dir / f"{prefix}.stderr.txt"

    atomic_write_text(prompt_path, prompt)
    atomic_write_text(schema_path, json.dumps(schema, indent=2, sort_keys=True) + "\n")

    command = [
        codex_bin,
        "exec",
        "--full-auto",
        "-C",
        str(repo_root),
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
    ]
    command.extend(DEFAULT_CODEX_EXEC_ARGS)
    if model:
        command.extend(["--model", model])
    command.extend(codex_args)
    command.append("-")

    try:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            env=_build_codex_subprocess_env(),
        )
    except FileNotFoundError as exc:
        raise DocgardenError(f"Could not find Codex CLI binary: {codex_bin}.") from exc
    except subprocess.TimeoutExpired as exc:
        _write_process_logs(stdout_path, stderr_path, stdout=exc.stdout, stderr=exc.stderr)
        timeout_display = "the configured timeout"
        if timeout_seconds is not None:
            timeout_display = f"{timeout_seconds} seconds"
        raise DocgardenError(
            f"Codex agent run timed out for {prefix} after {timeout_display}. "
            f"Partial logs were written to {stdout_path} and {stderr_path}."
        ) from exc

    _write_process_logs(
        stdout_path,
        stderr_path,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )

    if completed.returncode != 0:
        raise DocgardenError(
            f"Codex agent run failed for {prefix} with exit code {completed.returncode}. "
            f"See {stderr_path}."
        )
    if not output_path.exists():
        raise DocgardenError(
            f"Codex agent run for {prefix} did not write structured output to {output_path}."
        )

    try:
        parsed_output = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DocgardenError(
            f"Structured output for {prefix} was not valid JSON: {output_path}."
        ) from exc
    if not isinstance(parsed_output, dict):
        raise DocgardenError(
            f"Structured output for {prefix} must be a JSON object: {output_path}."
        )

    return AgentRunArtifact(
        prompt_path=prompt_path,
        schema_path=schema_path,
        output_path=output_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        parsed_output=parsed_output,
        command=command,
    )


def _write_process_logs(
    stdout_path: Path,
    stderr_path: Path,
    *,
    stdout: str | bytes | None,
    stderr: str | bytes | None,
) -> None:
    atomic_write_text(stdout_path, _coerce_process_stream(stdout))
    atomic_write_text(stderr_path, _coerce_process_stream(stderr))


def _coerce_process_stream(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _build_codex_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    # Nested `codex exec` runs should not inherit the parent Codex session's
    # sandbox/thread controls, or the child can start in an unusable state.
    for key in CODEX_ENV_DENYLIST:
        env.pop(key, None)
    return env
