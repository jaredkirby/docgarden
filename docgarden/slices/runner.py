from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..errors import DocgardenError
from .catalog import load_slice_catalog
from .config import (
    DEFAULT_REVIEWER_TIMEOUT_SECONDS,
    DEFAULT_WORKER_TIMEOUT_SECONDS,
    SliceAutomationPaths,
    SliceRunConfig,
    SliceRunRequest,
    build_slice_run_config,
    build_slice_paths,
)
from .run_execution import SliceRunResult, execute_slice_request
from .run_status import load_slice_run_status, resolve_retry_state


def run_slice_loop(
    repo_root: Path,
    *,
    paths: SliceAutomationPaths | None = None,
    start_slice: str | None = None,
    max_slices: int = 1,
    config: SliceRunConfig | None = None,
) -> dict[str, Any]:
    resolved_paths = paths or build_slice_paths(repo_root)
    resolved_config = config or build_slice_run_config(
        max_review_rounds=3,
        worker_timeout_seconds=DEFAULT_WORKER_TIMEOUT_SECONDS,
        reviewer_timeout_seconds=DEFAULT_REVIEWER_TIMEOUT_SECONDS,
    )
    catalog = load_slice_catalog(repo_root, paths=resolved_paths)
    if start_slice is not None:
        current = catalog.by_id(start_slice)
        blockers = catalog.dependency_blockers(current.slice_id)
        if blockers:
            raise DocgardenError(
                "Cannot start slice "
                f"{current.slice_id} until dependencies are completed: {', '.join(blockers)}."
            )
    else:
        current = catalog.next_actionable_slice()
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
    completed_slice_ids: set[str] = set()
    processed = 0

    while current is not None and (max_slices <= 0 or processed < max_slices):
        next_slice = catalog.next_planned_slice(current.slice_id)
        slice_result = execute_slice_request(
            SliceRunRequest(
                repo_root=repo_root,
                paths=resolved_paths,
                loop_root=loop_root,
                slice_def=current,
                next_slice=next_slice,
                config=resolved_config,
            )
        )
        results.append(slice_result)
        processed += 1
        if slice_result.recommendation != "ready_for_next_slice":
            return {
                "status": "stopped",
                "stopped_at": current.slice_id,
                "results": [asdict(item) for item in results],
            }
        completed_slice_ids.add(current.slice_id)
        next_slice = catalog.next_after(
            current.slice_id,
            completed_overrides=completed_slice_ids,
        )
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
    config: SliceRunConfig | None = None,
) -> dict[str, Any]:
    resolved_paths = paths or build_slice_paths(repo_root)
    resolved_config = config or build_slice_run_config(
        max_review_rounds=3,
        worker_timeout_seconds=DEFAULT_WORKER_TIMEOUT_SECONDS,
        reviewer_timeout_seconds=DEFAULT_REVIEWER_TIMEOUT_SECONDS,
    )
    status = load_slice_run_status(prior_run_dir)
    prior_status = status.status or "unknown"
    if prior_status == "ready_for_next_slice":
        raise DocgardenError(
            f"Cannot retry successful slice run: {prior_run_dir}."
        )

    slice_id = status.slice_id
    if not slice_id:
        raise DocgardenError(
            f"Slice run status is missing `slice_id`: {prior_run_dir / 'run-status.json'}."
        )
    catalog = load_slice_catalog(repo_root, paths=resolved_paths)
    slice_def = catalog.by_id(slice_id)
    next_slice = catalog.next_planned_slice(slice_id)
    result = execute_slice_request(
        SliceRunRequest(
            repo_root=repo_root,
            paths=resolved_paths,
            loop_root=resolved_paths.artifacts_dir,
            slice_def=slice_def,
            next_slice=next_slice,
            config=resolved_config,
        ),
        retry_state=resolve_retry_state(status, prior_run_dir=prior_run_dir),
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
