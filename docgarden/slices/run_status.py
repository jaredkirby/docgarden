from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
import shutil
import signal
from pathlib import Path
from typing import Any

from ..errors import DocgardenError
from ..files import atomic_write_text


RUN_ACTIVE_STATUSES = frozenset({"running"})
DEFAULT_PRUNABLE_RUN_STATUSES = frozenset(
    {
        "ready_for_next_slice",
        "failed",
        "stopped",
        "stopped_no_progress",
        "blocked_pending_product_clarification",
    }
)


@dataclass(frozen=True, slots=True)
class SliceRunStatusRecord:
    slice_id: str | None = None
    title: str | None = None
    artifacts_dir: str | None = None
    max_review_rounds: int | None = None
    worker_timeout_seconds: int | None = None
    reviewer_timeout_seconds: int | None = None
    worker_outputs: tuple[str, ...] = ()
    review_outputs: tuple[str, ...] = ()
    baseline_recorded_at: str | None = None
    baseline_tracked_changes: tuple[str, ...] = ()
    baseline_untracked_paths: tuple[str, ...] = ()
    retry_of: str | None = None
    status: str | None = None
    current_phase: str | None = None
    current_round: int | None = None
    current_prefix: str | None = None
    last_worker_output: str | None = None
    last_review_output: str | None = None
    recommendation: str | None = None
    error: str | None = None
    updated_at: str | None = None
    agent_pid: int | None = None
    phase_started_at: str | None = None
    last_heartbeat_at: str | None = None
    elapsed_seconds: float | None = None
    stopped_at: str | None = None
    stop_note: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SliceRunStatusRecord":
        return cls(
            slice_id=_coerce_optional_str(payload.get("slice_id")),
            title=_coerce_optional_str(payload.get("title")),
            artifacts_dir=_coerce_optional_str(payload.get("artifacts_dir")),
            max_review_rounds=_coerce_optional_int(payload.get("max_review_rounds")),
            worker_timeout_seconds=_coerce_optional_int(
                payload.get("worker_timeout_seconds")
            ),
            reviewer_timeout_seconds=_coerce_optional_int(
                payload.get("reviewer_timeout_seconds")
            ),
            worker_outputs=tuple(_coerce_path_list(payload.get("worker_outputs"))),
            review_outputs=tuple(_coerce_path_list(payload.get("review_outputs"))),
            baseline_recorded_at=_coerce_optional_str(
                payload.get("baseline_recorded_at")
            ),
            baseline_tracked_changes=tuple(
                _coerce_path_list(payload.get("baseline_tracked_changes"))
            ),
            baseline_untracked_paths=tuple(
                _coerce_path_list(payload.get("baseline_untracked_paths"))
            ),
            retry_of=_coerce_optional_str(payload.get("retry_of")),
            status=_coerce_optional_str(payload.get("status")),
            current_phase=_coerce_optional_str(payload.get("current_phase")),
            current_round=_coerce_optional_int(payload.get("current_round")),
            current_prefix=_coerce_optional_str(payload.get("current_prefix")),
            last_worker_output=_coerce_optional_str(payload.get("last_worker_output")),
            last_review_output=_coerce_optional_str(payload.get("last_review_output")),
            recommendation=_coerce_optional_str(payload.get("recommendation")),
            error=_coerce_optional_str(payload.get("error")),
            updated_at=_coerce_optional_str(payload.get("updated_at")),
            agent_pid=_coerce_optional_int(payload.get("agent_pid")),
            phase_started_at=_coerce_optional_str(payload.get("phase_started_at")),
            last_heartbeat_at=_coerce_optional_str(payload.get("last_heartbeat_at")),
            elapsed_seconds=_coerce_optional_float(payload.get("elapsed_seconds")),
            stopped_at=_coerce_optional_str(payload.get("stopped_at")),
            stop_note=_coerce_optional_str(payload.get("stop_note")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for field_name in (
            "slice_id",
            "title",
            "artifacts_dir",
            "max_review_rounds",
            "worker_timeout_seconds",
            "reviewer_timeout_seconds",
            "baseline_recorded_at",
            "retry_of",
            "status",
            "current_phase",
            "current_round",
            "current_prefix",
            "last_worker_output",
            "last_review_output",
            "recommendation",
            "error",
            "updated_at",
            "agent_pid",
            "phase_started_at",
            "last_heartbeat_at",
            "elapsed_seconds",
            "stopped_at",
            "stop_note",
        ):
            value = getattr(self, field_name)
            if value is not None:
                payload[field_name] = value
        payload["worker_outputs"] = list(self.worker_outputs)
        payload["review_outputs"] = list(self.review_outputs)
        payload["baseline_tracked_changes"] = list(self.baseline_tracked_changes)
        payload["baseline_untracked_paths"] = list(self.baseline_untracked_paths)
        return payload

    def __getitem__(self, key: str) -> Any:
        if key in self.__dataclass_fields__:
            return getattr(self, key)
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        if key in self.__dataclass_fields__:
            return getattr(self, key)
        return self.to_dict().get(key, default)

    def merged(self, **updates: Any) -> "SliceRunStatusRecord":
        payload = self.to_dict()
        payload.update(updates)
        payload["updated_at"] = _iso_now()
        return SliceRunStatusRecord.from_dict(payload)

    def for_phase(
        self,
        *,
        phase: str,
        round_number: int,
        prefix: str,
        **updates: Any,
    ) -> "SliceRunStatusRecord":
        return self.merged(
            current_phase=phase,
            current_round=round_number,
            current_prefix=prefix,
            **updates,
        )

    def with_status(self, status: str, **updates: Any) -> "SliceRunStatusRecord":
        return self.merged(status=status, **updates)

    def is_active(self) -> bool:
        return self.status in RUN_ACTIVE_STATUSES

    def summary_row(self, *, run_dir: Path) -> dict[str, Any]:
        return {
            "run_dir": str(run_dir),
            "name": run_dir.name,
            "slice_id": self.slice_id,
            "title": self.title,
            "status": self.status,
            "current_phase": self.current_phase,
            "updated_at": self.updated_at,
            "elapsed_seconds": self.elapsed_seconds,
            "retry_of": self.retry_of,
        }


@dataclass(frozen=True, slots=True)
class SliceRetryState:
    initial_round_number: int = 1
    prior_review_path: Path | None = None
    previous_worker_output_path: Path | None = None
    start_with_review: bool = False
    retry_of: str | None = None


def _write_run_status(run_dir: Path, status: SliceRunStatusRecord) -> None:
    atomic_write_text(
        run_dir / "run-status.json",
        json.dumps(status.to_dict(), indent=2, sort_keys=True) + "\n",
    )


def _iso_now() -> str:
    return datetime.now().isoformat()


def _iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).isoformat()


def _elapsed_seconds(started_monotonic: float) -> float:
    import time

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


def load_slice_run_status(run_dir: Path) -> SliceRunStatusRecord:
    status_path = run_dir / "run-status.json"
    if not status_path.exists():
        raise DocgardenError(f"Slice run status not found: {status_path}")
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DocgardenError(f"Slice run status is not valid JSON: {status_path}") from exc
    if not isinstance(payload, dict):
        raise DocgardenError(f"Slice run status must be a JSON object: {status_path}")
    return SliceRunStatusRecord.from_dict(payload)


def load_slice_run_status_or(
    run_dir: Path,
    *,
    fallback: SliceRunStatusRecord,
) -> SliceRunStatusRecord:
    try:
        return load_slice_run_status(run_dir)
    except DocgardenError:
        return fallback


def summarize_slice_run(run_dir: Path) -> dict[str, Any]:
    status = load_slice_run_status(run_dir)
    worker_outputs = sorted(str(path) for path in run_dir.glob("worker-round-*.output.json"))
    review_outputs = sorted(str(path) for path in run_dir.glob("review-round-*.output.json"))
    return {
        "run_dir": str(run_dir),
        "status": status.to_dict(),
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
            status = SliceRunStatusRecord(
                slice_id=_slice_id_from_run_dir(run_dir),
                status="legacy_missing_status",
                updated_at=_iso_from_timestamp(run_dir.stat().st_mtime),
            )
        summaries.append(status.summary_row(run_dir=run_dir))
    return summaries


def stop_slice_run(run_dir: Path) -> dict[str, Any]:
    status = load_slice_run_status(run_dir)
    pid = status.agent_pid
    stop_note = "Run was not active."
    if status.is_active() and isinstance(pid, int):
        try:
            os.kill(pid, signal.SIGTERM)
            stop_note = f"Sent SIGTERM to pid {pid}."
        except ProcessLookupError:
            stop_note = f"Process {pid} was no longer running."
        except PermissionError as exc:
            raise DocgardenError(
                f"Could not stop slice run pid {pid}: {exc}."
            ) from exc
    elif status.is_active():
        stop_note = "Run was active but no agent_pid was recorded."

    _write_run_status(
        run_dir,
        status.with_status(
            "stopped",
            stopped_at=_iso_now(),
            stop_note=stop_note,
            last_heartbeat_at=_iso_now(),
        ),
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


def resolve_retry_state(
    status: SliceRunStatusRecord,
    *,
    prior_run_dir: Path,
) -> SliceRetryState:
    last_worker_output = status.last_worker_output
    if last_worker_output is None:
        worker_outputs = sorted(prior_run_dir.glob("worker-round-*.output.json"))
        if worker_outputs:
            last_worker_output = str(worker_outputs[-1])
    last_review_output = status.last_review_output
    if last_review_output is None:
        review_outputs = sorted(prior_run_dir.glob("review-round-*.output.json"))
        if review_outputs:
            last_review_output = str(review_outputs[-1])

    current_round = status.current_round or 1
    previous_worker_output_path = (
        Path(last_worker_output) if last_worker_output is not None else None
    )
    prior_review_path = (
        Path(last_review_output) if last_review_output is not None else None
    )
    start_with_review = False
    if prior_review_path is not None:
        if status.current_phase == "review" and previous_worker_output_path is not None:
            start_with_review = True
    elif previous_worker_output_path is not None:
        start_with_review = True

    return SliceRetryState(
        initial_round_number=current_round,
        prior_review_path=prior_review_path,
        previous_worker_output_path=previous_worker_output_path,
        start_with_review=start_with_review,
        retry_of=str(prior_run_dir),
    )


def build_initial_slice_run_status(
    *,
    slice_id: str,
    title: str,
    artifacts_dir: Path,
    max_review_rounds: int,
    worker_timeout_seconds: int | None,
    reviewer_timeout_seconds: int | None,
    baseline: dict[str, Any],
    retry_of: str | None,
) -> SliceRunStatusRecord:
    return SliceRunStatusRecord(
        slice_id=slice_id,
        title=title,
        artifacts_dir=str(artifacts_dir),
        max_review_rounds=max_review_rounds,
        worker_timeout_seconds=worker_timeout_seconds,
        reviewer_timeout_seconds=reviewer_timeout_seconds,
        baseline_recorded_at=str(baseline["baseline_recorded_at"]),
        baseline_tracked_changes=tuple(baseline["baseline_tracked_changes"]),
        baseline_untracked_paths=tuple(baseline["baseline_untracked_paths"]),
        retry_of=retry_of,
    ).with_status("running")


def _coerce_optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _coerce_optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _coerce_optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _coerce_path_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]
