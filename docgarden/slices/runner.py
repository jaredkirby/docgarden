from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import os
import signal
import shutil
import subprocess
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable

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

DEFAULT_WORKER_TIMEOUT_SECONDS = 900
DEFAULT_REVIEWER_TIMEOUT_SECONDS = 300
RUN_STATUS_HEARTBEAT_SECONDS = 5.0
RUN_ACTIVE_STATUSES = frozenset({"running"})
NATIVE_POPEN = subprocess.Popen
DEFAULT_PRUNABLE_RUN_STATUSES = frozenset(
    {
        "ready_for_next_slice",
        "failed",
        "stopped",
        "blocked_pending_product_clarification",
    }
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
    worker_timeout_seconds: int | None = DEFAULT_WORKER_TIMEOUT_SECONDS,
    reviewer_timeout_seconds: int | None = DEFAULT_REVIEWER_TIMEOUT_SECONDS,
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
            worker_timeout_seconds=worker_timeout_seconds,
            reviewer_timeout_seconds=reviewer_timeout_seconds,
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


def retry_slice_run(
    repo_root: Path,
    prior_run_dir: Path,
    *,
    paths: SliceAutomationPaths | None = None,
    max_review_rounds: int = 3,
    worker_timeout_seconds: int | None = DEFAULT_WORKER_TIMEOUT_SECONDS,
    reviewer_timeout_seconds: int | None = DEFAULT_REVIEWER_TIMEOUT_SECONDS,
    codex_bin: str = "codex",
    model: str | None = None,
    codex_args: list[str] | None = None,
) -> dict[str, Any]:
    resolved_paths = paths or build_slice_paths(repo_root)
    status = load_slice_run_status(prior_run_dir)
    prior_status = str(status.get("status", "unknown"))
    if prior_status == "ready_for_next_slice":
        raise DocgardenError(
            f"Cannot retry successful slice run: {prior_run_dir}."
        )

    slice_id = status.get("slice_id")
    if not isinstance(slice_id, str) or not slice_id:
        raise DocgardenError(
            f"Slice run status is missing `slice_id`: {prior_run_dir / 'run-status.json'}."
        )
    catalog = load_slice_catalog(repo_root, paths=resolved_paths)
    slice_def = catalog.by_id(slice_id)
    next_slice = catalog.next_after(slice_id)

    last_worker_output = status.get("last_worker_output")
    if not isinstance(last_worker_output, str) or not last_worker_output:
        worker_outputs = sorted(prior_run_dir.glob("worker-round-*.output.json"))
        if worker_outputs:
            last_worker_output = str(worker_outputs[-1])
    last_review_output = status.get("last_review_output")
    if not isinstance(last_review_output, str) or not last_review_output:
        review_outputs = sorted(prior_run_dir.glob("review-round-*.output.json"))
        if review_outputs:
            last_review_output = str(review_outputs[-1])

    current_round = status.get("current_round")
    if not isinstance(current_round, int) or current_round < 1:
        current_round = 1

    retry_options: dict[str, Any] = {
        "initial_round_number": current_round,
        "previous_worker_output_path": Path(last_worker_output)
        if isinstance(last_worker_output, str) and last_worker_output
        else None,
        "prior_review_path": Path(last_review_output)
        if isinstance(last_review_output, str) and last_review_output
        else None,
        "start_with_review": False,
        "retry_of": str(prior_run_dir),
    }

    if retry_options["prior_review_path"] is not None:
        if status.get("current_phase") == "review" and retry_options["previous_worker_output_path"] is not None:
            retry_options["start_with_review"] = True
        else:
            retry_options["initial_round_number"] = current_round
    elif retry_options["previous_worker_output_path"] is not None:
        retry_options["start_with_review"] = True
    else:
        retry_options["initial_round_number"] = current_round

    result = _run_single_slice(
        repo_root,
        paths=resolved_paths,
        loop_root=resolved_paths.artifacts_dir,
        slice_def=slice_def,
        next_slice=next_slice,
        max_review_rounds=max_review_rounds,
        worker_timeout_seconds=worker_timeout_seconds,
        reviewer_timeout_seconds=reviewer_timeout_seconds,
        codex_bin=codex_bin,
        model=model,
        codex_args=codex_args or [],
        **retry_options,
    )
    return {
        "status": (
            "completed"
            if result.recommendation == "ready_for_next_slice"
            else "stopped"
        ),
        "retried_from": str(prior_run_dir),
        "results": [asdict(result)],
    }


def _run_single_slice(
    repo_root: Path,
    *,
    paths: SliceAutomationPaths,
    loop_root: Path,
    slice_def: SliceDefinition,
    next_slice: SliceDefinition | None,
    max_review_rounds: int,
    worker_timeout_seconds: int | None,
    reviewer_timeout_seconds: int | None,
    codex_bin: str,
    model: str | None,
    codex_args: list[str],
    initial_round_number: int = 1,
    prior_review_path: Path | None = None,
    previous_worker_output_path: Path | None = None,
    start_with_review: bool = False,
    retry_of: str | None = None,
) -> SliceRunResult:
    timestamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    run_dir = loop_root / f"{timestamp}-{slice_def.slice_id.lower()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"[docgarden] slice {slice_def.slice_id}: artifacts -> {run_dir}",
        file=sys.stderr,
    )

    worker_outputs: list[str] = []
    review_outputs: list[str] = []
    repo_baseline = _capture_repo_baseline(repo_root)
    status_payload = {
        "slice_id": slice_def.slice_id,
        "title": slice_def.title,
        "artifacts_dir": str(run_dir),
        "max_review_rounds": max_review_rounds,
        "worker_timeout_seconds": worker_timeout_seconds,
        "reviewer_timeout_seconds": reviewer_timeout_seconds,
        "worker_outputs": worker_outputs,
        "review_outputs": review_outputs,
        **repo_baseline,
    }
    if retry_of is not None:
        status_payload["retry_of"] = retry_of
    _write_run_status(run_dir, **status_payload, status="running")

    if start_with_review:
        if previous_worker_output_path is None:
            raise DocgardenError("Cannot retry from review without a prior worker output.")
        review_prefix = f"review-round-{initial_round_number}"
        review_status = {
            "current_phase": "review",
            "current_round": initial_round_number,
            "current_prefix": review_prefix,
        }
        _write_run_status(
            run_dir,
            **status_payload,
            status="running",
            **review_status,
            last_worker_output=str(previous_worker_output_path),
        )
        try:
            review_run = _run_codex_agent(
                repo_root,
                run_dir=run_dir,
                codex_bin=codex_bin,
                codex_args=codex_args,
                model=model,
                prompt=build_review_prompt(
                    repo_root,
                    slice_def,
                    next_slice=next_slice,
                    paths=paths,
                    worker_output_path=previous_worker_output_path,
                    round_number=initial_round_number,
                    prior_review_path=prior_review_path,
                ),
                schema=REVIEW_OUTPUT_SCHEMA,
                prefix=review_prefix,
                timeout_seconds=reviewer_timeout_seconds,
                status_callback=_make_status_callback(
                    run_dir,
                    status_payload,
                    review_status,
                    last_worker_output=str(previous_worker_output_path),
                ),
            )
        except DocgardenError as exc:
            _write_run_status(
                run_dir,
                **status_payload,
                **review_status,
                status="failed",
                last_worker_output=str(previous_worker_output_path),
                error=str(exc),
            )
            raise
        review_outputs.append(str(review_run.output_path))
        prior_review_path = review_run.output_path
        recommendation = str(review_run.parsed_output["recommendation"])
        if recommendation in {
            "ready_for_next_slice",
            "blocked_pending_product_clarification",
        }:
            _write_run_status(
                run_dir,
                **status_payload,
                status=recommendation,
                **review_status,
                last_worker_output=str(previous_worker_output_path),
                last_review_output=str(review_run.output_path),
                recommendation=recommendation,
            )
            return SliceRunResult(
                slice_id=slice_def.slice_id,
                title=slice_def.title,
                recommendation=recommendation,
                worker_rounds=initial_round_number,
                run_dir=str(run_dir),
                worker_outputs=worker_outputs,
                review_outputs=review_outputs,
            )
        initial_round_number += 1

    for round_number in range(initial_round_number, max_review_rounds + 1):
        worker_prompt = build_implementation_prompt(
            repo_root,
            slice_def,
            next_slice=next_slice,
            paths=paths,
            round_number=round_number,
            review_feedback_path=prior_review_path,
            previous_worker_output_path=previous_worker_output_path,
        )
        worker_prefix = f"worker-round-{round_number}"
        worker_status = {
            "current_phase": "worker",
            "current_round": round_number,
            "current_prefix": worker_prefix,
        }
        _write_run_status(
            run_dir,
            **status_payload,
            status="running",
            **worker_status,
        )
        try:
            worker_run = _run_codex_agent(
                repo_root,
                run_dir=run_dir,
                codex_bin=codex_bin,
                codex_args=codex_args,
                model=model,
                prompt=worker_prompt,
                schema=WORKER_OUTPUT_SCHEMA,
                prefix=worker_prefix,
                timeout_seconds=worker_timeout_seconds,
                status_callback=_make_status_callback(
                    run_dir,
                    status_payload,
                    worker_status,
                ),
            )
        except DocgardenError as exc:
            _write_run_status(
                run_dir,
                **status_payload,
                **worker_status,
                status="failed",
                error=str(exc),
            )
            raise
        worker_outputs.append(str(worker_run.output_path))
        previous_worker_output_path = worker_run.output_path
        if worker_run.parsed_output["status"] == "blocked":
            _write_run_status(
                run_dir,
                **status_payload,
                status="blocked_pending_product_clarification",
                current_phase="worker",
                current_round=round_number,
                current_prefix=worker_prefix,
                last_worker_output=str(worker_run.output_path),
            )
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
        review_prefix = f"review-round-{round_number}"
        review_status = {
            "current_phase": "review",
            "current_round": round_number,
            "current_prefix": review_prefix,
        }
        _write_run_status(
            run_dir,
            **status_payload,
            status="running",
            **review_status,
            last_worker_output=str(worker_run.output_path),
        )
        try:
            review_run = _run_codex_agent(
                repo_root,
                run_dir=run_dir,
                codex_bin=codex_bin,
                codex_args=codex_args,
                model=model,
                prompt=review_prompt,
                schema=REVIEW_OUTPUT_SCHEMA,
                prefix=review_prefix,
                timeout_seconds=reviewer_timeout_seconds,
                status_callback=_make_status_callback(
                    run_dir,
                    status_payload,
                    review_status,
                    last_worker_output=str(worker_run.output_path),
                ),
            )
        except DocgardenError as exc:
            _write_run_status(
                run_dir,
                **status_payload,
                **review_status,
                status="failed",
                last_worker_output=str(worker_run.output_path),
                error=str(exc),
            )
            raise
        review_outputs.append(str(review_run.output_path))
        prior_review_path = review_run.output_path
        recommendation = str(review_run.parsed_output["recommendation"])
        if recommendation in {
            "ready_for_next_slice",
            "blocked_pending_product_clarification",
        }:
            _write_run_status(
                run_dir,
                **status_payload,
                status=recommendation,
                current_phase="review",
                current_round=round_number,
                current_prefix=review_prefix,
                last_worker_output=str(worker_run.output_path),
                last_review_output=str(review_run.output_path),
                recommendation=recommendation,
            )
            return SliceRunResult(
                slice_id=slice_def.slice_id,
                title=slice_def.title,
                recommendation=recommendation,
                worker_rounds=round_number,
                run_dir=str(run_dir),
                worker_outputs=worker_outputs,
                review_outputs=review_outputs,
            )

    _write_run_status(
        run_dir,
        **status_payload,
        status="failed",
        current_phase="review",
        current_round=max_review_rounds,
        current_prefix=f"review-round-{max_review_rounds}",
        error=f"Exceeded max review rounds ({max_review_rounds}) for {slice_def.slice_id}.",
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
    status_callback: Callable[..., None] | None = None,
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

    atomic_write_text(stdout_path, "")
    atomic_write_text(stderr_path, "")

    try:
        with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr_file:
            process = subprocess.Popen(
                command,
                cwd=repo_root,
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                env=_build_codex_subprocess_env(),
            )
            started_at = _iso_now()
            started_monotonic = time.monotonic()
            if status_callback is not None:
                status_callback(
                    agent_pid=process.pid,
                    phase_started_at=started_at,
                    last_heartbeat_at=started_at,
                    elapsed_seconds=0.0,
                )
            stop_event = threading.Event()
            heartbeat_thread: threading.Thread | None = None
            if status_callback is not None:
                heartbeat_thread = threading.Thread(
                    target=_heartbeat_run_status,
                    args=(process, stop_event, status_callback, started_monotonic),
                    daemon=True,
                )
                heartbeat_thread.start()
            try:
                process.communicate(input=prompt, timeout=timeout_seconds)
                if status_callback is not None:
                    status_callback(
                        agent_pid=process.pid,
                        last_heartbeat_at=_iso_now(),
                        elapsed_seconds=_elapsed_seconds(started_monotonic),
                    )
            except subprocess.TimeoutExpired as exc:
                if status_callback is not None:
                    status_callback(
                        agent_pid=process.pid,
                        last_heartbeat_at=_iso_now(),
                        elapsed_seconds=_elapsed_seconds(started_monotonic),
                    )
                stop_event.set()
                process.kill()
                process.communicate()
                timeout_display = "the configured timeout"
                if timeout_seconds is not None:
                    timeout_display = f"{timeout_seconds} seconds"
                raise DocgardenError(
                    f"Codex agent run timed out for {prefix} after {timeout_display}. "
                    f"Partial logs were written to {stdout_path} and {stderr_path}."
                ) from exc
            finally:
                stop_event.set()
                if heartbeat_thread is not None:
                    heartbeat_thread.join(timeout=1)
    except FileNotFoundError as exc:
        raise DocgardenError(f"Could not find Codex CLI binary: {codex_bin}.") from exc

    if process.returncode != 0:
        raise DocgardenError(
            f"Codex agent run failed for {prefix} with exit code {process.returncode}. "
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


def _make_status_callback(
    run_dir: Path,
    base_payload: dict[str, Any],
    phase_payload: dict[str, Any],
    **extra_payload: Any,
) -> Callable[..., None]:
    def emit(**heartbeat_payload: Any) -> None:
        _write_run_status(
            run_dir,
            **base_payload,
            **phase_payload,
            **extra_payload,
            **heartbeat_payload,
        )

    return emit


def _heartbeat_run_status(
    process: subprocess.Popen[str],
    stop_event: threading.Event,
    status_callback: Callable[..., None],
    started_monotonic: float,
) -> None:
    while not stop_event.wait(RUN_STATUS_HEARTBEAT_SECONDS):
        if process.poll() is not None:
            return
        status_callback(
            agent_pid=process.pid,
            last_heartbeat_at=_iso_now(),
            elapsed_seconds=_elapsed_seconds(started_monotonic),
        )


def _write_run_status(run_dir: Path, **payload: Any) -> None:
    existing: dict[str, Any] = {}
    status_path = run_dir / "run-status.json"
    if status_path.exists():
        try:
            loaded = json.loads(status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            existing = loaded
    enriched = {**existing, **payload, "updated_at": _iso_now()}
    atomic_write_text(
        status_path,
        json.dumps(enriched, indent=2, sort_keys=True) + "\n",
    )


def _iso_now() -> str:
    return datetime.now().isoformat()


def _iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).isoformat()


def _elapsed_seconds(started_monotonic: float) -> float:
    return round(time.monotonic() - started_monotonic, 1)


def _slice_id_from_run_dir(run_dir: Path) -> str | None:
    suffix = run_dir.name.rsplit("-", 1)[-1]
    if suffix.startswith("s") and suffix[1:].isdigit():
        return f"S{suffix[1:]}"
    return None


def resolve_slice_run_dir(
    artifacts_dir: Path,
    *,
    run_dir: str | Path | None = None,
) -> Path:
    if run_dir is not None:
        candidate = Path(run_dir)
        if not candidate.is_absolute():
            candidate = candidate if candidate.exists() else artifacts_dir / candidate
        if not candidate.exists() or not candidate.is_dir():
            raise DocgardenError(f"Slice run directory not found: {candidate}")
        return candidate

    run_dirs = sorted(path for path in artifacts_dir.iterdir() if path.is_dir())
    if not run_dirs:
        raise DocgardenError(f"No slice runs found in {artifacts_dir}.")
    return run_dirs[-1]


def load_slice_run_status(run_dir: Path) -> dict[str, Any]:
    status_path = run_dir / "run-status.json"
    if not status_path.exists():
        raise DocgardenError(f"Slice run status not found: {status_path}")
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DocgardenError(f"Slice run status is not valid JSON: {status_path}") from exc
    if not isinstance(payload, dict):
        raise DocgardenError(f"Slice run status must be a JSON object: {status_path}")
    return payload


def summarize_slice_run(run_dir: Path) -> dict[str, Any]:
    status = load_slice_run_status(run_dir)
    worker_outputs = sorted(str(path) for path in run_dir.glob("worker-round-*.output.json"))
    review_outputs = sorted(str(path) for path in run_dir.glob("review-round-*.output.json"))
    return {
        "run_dir": str(run_dir),
        "status": status,
        "worker_outputs": worker_outputs,
        "review_outputs": review_outputs,
        "stdout_logs": sorted(str(path) for path in run_dir.glob("*.stdout.txt")),
        "stderr_logs": sorted(str(path) for path in run_dir.glob("*.stderr.txt")),
    }


def list_slice_runs(artifacts_dir: Path) -> list[dict[str, Any]]:
    if not artifacts_dir.exists():
        return []
    summaries: list[dict[str, Any]] = []
    for run_dir in sorted(
        (path for path in artifacts_dir.iterdir() if path.is_dir()),
        reverse=True,
    ):
        status_path = run_dir / "run-status.json"
        if status_path.exists():
            status = load_slice_run_status(run_dir)
        else:
            status = {
                "slice_id": _slice_id_from_run_dir(run_dir),
                "status": "legacy_missing_status",
                "updated_at": _iso_from_timestamp(run_dir.stat().st_mtime),
            }
        summaries.append(
            {
                "run_dir": str(run_dir),
                "name": run_dir.name,
                "slice_id": status.get("slice_id"),
                "title": status.get("title"),
                "status": status.get("status"),
                "current_phase": status.get("current_phase"),
                "updated_at": status.get("updated_at"),
                "elapsed_seconds": status.get("elapsed_seconds"),
                "retry_of": status.get("retry_of"),
            }
        )
    return summaries


def stop_slice_run(run_dir: Path) -> dict[str, Any]:
    status = load_slice_run_status(run_dir)
    base_status = {
        key: value
        for key, value in status.items()
        if key not in {"status", "last_heartbeat_at", "stopped_at", "stop_note"}
    }
    pid = status.get("agent_pid")
    stop_note = "Run was not active."
    if status.get("status") in RUN_ACTIVE_STATUSES and isinstance(pid, int):
        try:
            os.kill(pid, signal.SIGTERM)
            stop_note = f"Sent SIGTERM to pid {pid}."
        except ProcessLookupError:
            stop_note = f"Process {pid} was no longer running."
        except PermissionError as exc:
            raise DocgardenError(
                f"Could not stop slice run pid {pid}: {exc}."
            ) from exc
    elif status.get("status") in RUN_ACTIVE_STATUSES:
        stop_note = "Run was active but no agent_pid was recorded."

    _write_run_status(
        run_dir,
        **base_status,
        status="stopped",
        stopped_at=_iso_now(),
        stop_note=stop_note,
        last_heartbeat_at=_iso_now(),
    )
    return summarize_slice_run(run_dir)


def prune_slice_runs(
    artifacts_dir: Path,
    *,
    keep: int = 3,
    apply: bool = False,
    prunable_statuses: set[str] | None = None,
) -> dict[str, Any]:
    if keep < 0:
        raise DocgardenError("`keep` must be 0 or greater.")
    summaries = list_slice_runs(artifacts_dir)
    statuses = prunable_statuses or set(DEFAULT_PRUNABLE_RUN_STATUSES)
    prunable = [item for item in summaries if item.get("status") in statuses]
    preserved = prunable[:keep]
    candidates = prunable[keep:]
    removed: list[str] = []
    if apply:
        for item in candidates:
            shutil.rmtree(item["run_dir"])
            removed.append(item["run_dir"])
    return {
        "artifacts_dir": str(artifacts_dir),
        "apply": apply,
        "keep": keep,
        "prunable_statuses": sorted(statuses),
        "preserved_runs": [item["run_dir"] for item in preserved],
        "prune_candidates": [item["run_dir"] for item in candidates],
        "removed_runs": removed,
    }


def recover_slice_run(
    repo_root: Path,
    run_dir: Path,
    *,
    verify: bool = True,
) -> dict[str, Any]:
    summary = summarize_slice_run(run_dir)
    status = summary["status"]
    baseline_tracked = _coerce_path_list(status.get("baseline_tracked_changes"))
    baseline_untracked = _coerce_path_list(status.get("baseline_untracked_paths"))
    current_tracked = _git_diff_name_only(repo_root)
    current_untracked = _git_untracked_paths(repo_root)
    new_tracked = _diff_repo_paths(current_tracked, baseline_tracked)
    new_untracked = _diff_repo_paths(current_untracked, baseline_untracked)
    recovery: dict[str, Any] = {
        "run_dir": str(run_dir),
        "status": status,
        "baseline_recorded_at": status.get("baseline_recorded_at"),
        "baseline_tracked_changes": baseline_tracked,
        "baseline_untracked_paths": baseline_untracked,
        "current_tracked_changes": current_tracked,
        "current_untracked_paths": current_untracked,
        "tracked_changes": new_tracked,
        "untracked_paths": new_untracked,
        "new_tracked_changes": new_tracked,
        "new_untracked_paths": new_untracked,
        "preexisting_tracked_changes": _overlap_repo_paths(current_tracked, baseline_tracked),
        "preexisting_untracked_paths": _overlap_repo_paths(current_untracked, baseline_untracked),
        "worker_outputs": summary["worker_outputs"],
        "review_outputs": summary["review_outputs"],
    }
    recovery["recovery_recommendation"] = _recovery_recommendation(recovery)
    if verify:
        recovery["verification"] = {
            "pytest": _run_command_capture(["uv", "run", "pytest"], cwd=repo_root),
            "scan": _run_command_capture(["uv", "run", "docgarden", "scan"], cwd=repo_root),
        }
    return recovery


def _run_command_capture(command: list[str], *, cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _capture_repo_baseline(repo_root: Path) -> dict[str, Any]:
    return {
        "baseline_recorded_at": _iso_now(),
        "baseline_tracked_changes": _git_diff_name_only(repo_root),
        "baseline_untracked_paths": _git_untracked_paths(repo_root),
    }


def _run_native_capture(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    process = NATIVE_POPEN(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate()
    return subprocess.CompletedProcess(command, process.returncode or 0, stdout, stderr)


def _git_diff_name_only(repo_root: Path) -> list[str]:
    completed = _run_native_capture(["git", "diff", "--name-only"], cwd=repo_root)
    if completed.returncode != 0:
        return []
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _git_untracked_paths(repo_root: Path) -> list[str]:
    completed = _run_native_capture(["git", "status", "--short"], cwd=repo_root)
    if completed.returncode != 0:
        return []
    paths: list[str] = []
    for line in completed.stdout.splitlines():
        if line.startswith("?? "):
            paths.append(line[3:])
    return paths


def _coerce_path_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(str(item) for item in value if isinstance(item, str) and item.strip())


def _diff_repo_paths(current: list[str], baseline: list[str]) -> list[str]:
    baseline_set = set(baseline)
    return sorted(path for path in current if path not in baseline_set)


def _overlap_repo_paths(current: list[str], baseline: list[str]) -> list[str]:
    baseline_set = set(baseline)
    return sorted(path for path in current if path in baseline_set)


def _recovery_recommendation(payload: dict[str, Any]) -> str:
    status = payload.get("status")
    tracked = payload.get("new_tracked_changes", payload.get("tracked_changes", []))
    worker_outputs = payload.get("worker_outputs", [])
    review_outputs = payload.get("review_outputs", [])
    run_status = status.get("status") if isinstance(status, dict) else None
    if review_outputs:
        return "review_output_available"
    if worker_outputs:
        return "worker_output_available"
    if tracked and run_status in {"failed", "stopped"}:
        return "partial_repo_changes_need_review"
    if run_status in {"failed", "stopped"}:
        return "safe_to_retry"
    return "inspect_run_status"


def _build_codex_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    # Nested `codex exec` runs should not inherit the parent Codex session's
    # sandbox/thread controls, or the child can start in an unusable state.
    for key in CODEX_ENV_DENYLIST:
        env.pop(key, None)
    return env
