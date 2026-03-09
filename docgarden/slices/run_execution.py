from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

from ..errors import DocgardenError
from .config import SliceRunRequest
from .prompts import (
    REVIEW_OUTPUT_SCHEMA,
    WORKER_OUTPUT_SCHEMA,
    build_implementation_prompt,
    build_review_prompt,
)
from .run_agent import AgentRunArtifact, make_status_callback, run_codex_agent
from .review_progress import (
    load_review_signature,
    read_review_output,
    review_signature,
)
from .run_recovery import _capture_repo_baseline
from .run_status import (
    SliceRetryState,
    SliceRunStatusRecord,
    _iso_now,
    _write_run_status,
    build_initial_slice_run_status,
    load_slice_run_status_or,
)


@dataclass(slots=True)
class SliceRunResult:
    slice_id: str
    title: str
    recommendation: str
    worker_rounds: int
    run_dir: str
    worker_outputs: list[str] = field(default_factory=list)
    review_outputs: list[str] = field(default_factory=list)


def execute_slice_request(
    request: SliceRunRequest,
    *,
    retry_state: SliceRetryState | None = None,
) -> SliceRunResult:
    timestamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    run_dir = request.loop_root / f"{timestamp}-{request.slice_def.slice_id.lower()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"[docgarden] slice {request.slice_def.slice_id}: artifacts -> {run_dir}",
        file=sys.stderr,
    )

    retry = retry_state or SliceRetryState()
    worker_outputs: list[str] = []
    review_outputs: list[str] = []
    status = build_initial_slice_run_status(
        slice_id=request.slice_def.slice_id,
        title=request.slice_def.title,
        artifacts_dir=run_dir,
        max_review_rounds=request.config.max_review_rounds,
        worker_timeout_seconds=request.config.worker_timeout_seconds,
        reviewer_timeout_seconds=request.config.reviewer_timeout_seconds,
        baseline=_capture_repo_baseline(request.repo_root),
        retry_of=retry.retry_of,
    )
    _write_run_status(run_dir, status)

    current_round = retry.initial_round_number
    prior_review_path = retry.prior_review_path
    previous_worker_output_path = retry.previous_worker_output_path
    previous_review_signature = load_review_signature(prior_review_path)

    if retry.start_with_review:
        if previous_worker_output_path is None:
            raise DocgardenError("Cannot retry from review without a prior worker output.")
        review_run, status = _run_review_phase(
            request,
            run_dir=run_dir,
            status=status,
            round_number=current_round,
            worker_output_path=previous_worker_output_path,
            prior_review_path=prior_review_path,
        )
        review_outputs.append(str(review_run.output_path))
        terminal_result, previous_review_signature = _finalize_review_outcome(
            request,
            run_dir=run_dir,
            status=status,
            round_number=current_round,
            worker_outputs=worker_outputs,
            review_outputs=review_outputs,
            prior_signature=previous_review_signature,
        )
        if terminal_result is not None:
            return terminal_result
        prior_review_path = review_run.output_path
        current_round += 1

    for round_number in range(current_round, request.config.max_review_rounds + 1):
        worker_run, status = _run_worker_phase(
            request,
            run_dir=run_dir,
            status=status,
            round_number=round_number,
            prior_review_path=prior_review_path,
            previous_worker_output_path=previous_worker_output_path,
        )
        worker_outputs.append(str(worker_run.output_path))
        previous_worker_output_path = worker_run.output_path
        if worker_run.parsed_output["status"] == "blocked":
            blocked_status = status.with_status(
                "blocked_pending_product_clarification",
                recommendation="blocked_pending_product_clarification",
            )
            _write_run_status(run_dir, blocked_status)
            return SliceRunResult(
                slice_id=request.slice_def.slice_id,
                title=request.slice_def.title,
                recommendation="blocked_pending_product_clarification",
                worker_rounds=round_number,
                run_dir=str(run_dir),
                worker_outputs=worker_outputs,
                review_outputs=review_outputs,
            )

        review_run, status = _run_review_phase(
            request,
            run_dir=run_dir,
            status=status,
            round_number=round_number,
            worker_output_path=worker_run.output_path,
            prior_review_path=prior_review_path,
        )
        review_outputs.append(str(review_run.output_path))
        terminal_result, previous_review_signature = _finalize_review_outcome(
            request,
            run_dir=run_dir,
            status=status,
            round_number=round_number,
            worker_outputs=worker_outputs,
            review_outputs=review_outputs,
            prior_signature=previous_review_signature,
        )
        if terminal_result is not None:
            return terminal_result
        prior_review_path = review_run.output_path

    failure_message = (
        "Exceeded max review rounds "
        f"({request.config.max_review_rounds}) for {request.slice_def.slice_id}."
    )
    _write_run_status(
        run_dir,
        status.for_phase(
            phase="review",
            round_number=request.config.max_review_rounds,
            prefix=f"review-round-{request.config.max_review_rounds}",
        ).with_status("failed", error=failure_message),
    )
    raise DocgardenError(failure_message)


def _run_worker_phase(
    request: SliceRunRequest,
    *,
    run_dir: Path,
    status: SliceRunStatusRecord,
    round_number: int,
    prior_review_path: Path | None,
    previous_worker_output_path: Path | None,
) -> tuple[AgentRunArtifact, SliceRunStatusRecord]:
    prefix = f"worker-round-{round_number}"
    started_at = _iso_now()
    phase_status = status.for_phase(
        phase="worker",
        round_number=round_number,
        prefix=prefix,
        phase_started_at=started_at,
        last_heartbeat_at=started_at,
        elapsed_seconds=0.0,
    )
    _write_run_status(run_dir, phase_status)
    try:
        worker_run = run_codex_agent(
            request.repo_root,
            run_dir=run_dir,
            codex_bin=request.config.codex_bin,
            codex_args=list(request.config.codex_args),
            model=request.config.model,
            prompt=build_implementation_prompt(
                request.repo_root,
                request.slice_def,
                next_slice=request.next_slice,
                paths=request.paths,
                round_number=round_number,
                review_feedback_path=prior_review_path,
                previous_worker_output_path=previous_worker_output_path,
            ),
            schema=WORKER_OUTPUT_SCHEMA,
            prefix=prefix,
            timeout_seconds=request.config.worker_timeout_seconds,
            status_callback=make_status_callback(run_dir, phase_status),
        )
    except DocgardenError as exc:
        _write_run_status(
            run_dir,
            _latest_run_status(run_dir, fallback=phase_status).with_status(
                "failed",
                error=str(exc),
            ),
        )
        raise
    latest_status = _latest_run_status(run_dir, fallback=phase_status)
    return worker_run, latest_status.merged(
        worker_outputs=[*status.worker_outputs, str(worker_run.output_path)],
        last_worker_output=str(worker_run.output_path),
    )


def _run_review_phase(
    request: SliceRunRequest,
    *,
    run_dir: Path,
    status: SliceRunStatusRecord,
    round_number: int,
    worker_output_path: Path,
    prior_review_path: Path | None,
) -> tuple[AgentRunArtifact, SliceRunStatusRecord]:
    prefix = f"review-round-{round_number}"
    started_at = _iso_now()
    phase_status = status.for_phase(
        phase="review",
        round_number=round_number,
        prefix=prefix,
        last_worker_output=str(worker_output_path),
        phase_started_at=started_at,
        last_heartbeat_at=started_at,
        elapsed_seconds=0.0,
    )
    _write_run_status(run_dir, phase_status)
    try:
        review_run = run_codex_agent(
            request.repo_root,
            run_dir=run_dir,
            codex_bin=request.config.codex_bin,
            codex_args=list(request.config.codex_args),
            model=request.config.model,
            prompt=build_review_prompt(
                request.repo_root,
                request.slice_def,
                next_slice=request.next_slice,
                paths=request.paths,
                worker_output_path=worker_output_path,
                round_number=round_number,
                prior_review_path=prior_review_path,
            ),
            schema=REVIEW_OUTPUT_SCHEMA,
            prefix=prefix,
            timeout_seconds=request.config.reviewer_timeout_seconds,
            status_callback=make_status_callback(run_dir, phase_status),
        )
    except DocgardenError as exc:
        _write_run_status(
            run_dir,
            _latest_run_status(run_dir, fallback=phase_status).with_status(
                "failed",
                error=str(exc),
            ),
        )
        raise
    latest_status = _latest_run_status(run_dir, fallback=phase_status)
    return review_run, latest_status.merged(
        review_outputs=[*status.review_outputs, str(review_run.output_path)],
        last_review_output=str(review_run.output_path),
    )


def _finalize_review_outcome(
    request: SliceRunRequest,
    *,
    run_dir: Path,
    status: SliceRunStatusRecord,
    round_number: int,
    worker_outputs: list[str],
    review_outputs: list[str],
    prior_signature: tuple[Any, ...] | None,
) -> tuple[SliceRunResult | None, tuple[Any, ...] | None]:
    parsed_output = read_review_output(Path(status.last_review_output or ""))
    recommendation = str(parsed_output["recommendation"])
    current_signature = review_signature(parsed_output)
    if recommendation in {
        "ready_for_next_slice",
        "blocked_pending_product_clarification",
    }:
        terminal_status = status.with_status(
            recommendation,
            recommendation=recommendation,
        )
        _write_run_status(run_dir, terminal_status)
        return (
            _build_run_result(
                slice_id=request.slice_def.slice_id,
                title=request.slice_def.title,
                recommendation=recommendation,
                round_number=round_number,
                run_dir=run_dir,
                worker_outputs=worker_outputs,
                review_outputs=review_outputs,
            ),
            current_signature,
        )
    if prior_signature is not None and current_signature == prior_signature:
        stop_note = (
            "Stopped after repeated reviewer findings showed no material progress "
            f"for {request.slice_def.slice_id} at round {round_number}."
        )
        stalled_status = status.with_status(
            "stopped_no_progress",
            recommendation="stopped_no_progress",
            error=stop_note,
            stopped_at=_iso_now(),
            stop_note=stop_note,
        )
        _write_run_status(run_dir, stalled_status)
        return (
            _build_run_result(
                slice_id=request.slice_def.slice_id,
                title=request.slice_def.title,
                recommendation="stopped_no_progress",
                round_number=round_number,
                run_dir=run_dir,
                worker_outputs=worker_outputs,
                review_outputs=review_outputs,
            ),
            current_signature,
        )
    return None, current_signature


def _build_run_result(
    *,
    slice_id: str,
    title: str,
    recommendation: str,
    round_number: int,
    run_dir: Path,
    worker_outputs: list[str],
    review_outputs: list[str],
) -> SliceRunResult:
    return SliceRunResult(
        slice_id=slice_id,
        title=title,
        recommendation=recommendation,
        worker_rounds=round_number,
        run_dir=str(run_dir),
        worker_outputs=list(worker_outputs),
        review_outputs=list(review_outputs),
    )


def _latest_run_status(
    run_dir: Path,
    *,
    fallback: SliceRunStatusRecord,
) -> SliceRunStatusRecord:
    return load_slice_run_status_or(run_dir, fallback=fallback)
