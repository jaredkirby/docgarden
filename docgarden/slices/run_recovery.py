from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from .run_status import summarize_slice_run

NATIVE_POPEN = subprocess.Popen
DEFAULT_RECOVERY_VERIFY_TIMEOUT_SECONDS = 300


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
    operator_untracked, run_artifact_untracked = _partition_run_artifact_untracked_paths(
        new_untracked,
        repo_root=repo_root,
        run_dir=run_dir,
    )
    recovery: dict[str, Any] = {
        "run_dir": str(run_dir),
        "status": status,
        "baseline_recorded_at": status.get("baseline_recorded_at"),
        "baseline_tracked_changes": baseline_tracked,
        "baseline_untracked_paths": baseline_untracked,
        "current_tracked_changes": current_tracked,
        "current_untracked_paths": current_untracked,
        "tracked_changes": new_tracked,
        "untracked_paths": operator_untracked,
        "new_tracked_changes": new_tracked,
        "new_untracked_paths": operator_untracked,
        "run_artifact_untracked_paths": run_artifact_untracked,
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
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=DEFAULT_RECOVERY_VERIFY_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timed_out": True,
            "timeout_seconds": DEFAULT_RECOVERY_VERIFY_TIMEOUT_SECONDS,
        }
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


def _iso_now() -> str:
    from .run_status import _iso_now as current_iso_now

    return current_iso_now()


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


def _partition_run_artifact_untracked_paths(
    paths: list[str],
    *,
    repo_root: Path,
    run_dir: Path,
) -> tuple[list[str], list[str]]:
    run_relative = _repo_relative_path(repo_root, run_dir)
    if run_relative is None:
        return sorted(paths), []
    operator_paths: list[str] = []
    artifact_paths: list[str] = []
    for raw_path in paths:
        candidate = Path(raw_path.rstrip("/"))
        if _paths_overlap(candidate, run_relative):
            artifact_paths.append(raw_path)
        else:
            operator_paths.append(raw_path)
    return sorted(operator_paths), sorted(artifact_paths)


def _overlap_repo_paths(current: list[str], baseline: list[str]) -> list[str]:
    baseline_set = set(baseline)
    return sorted(path for path in current if path in baseline_set)


def _repo_relative_path(repo_root: Path, path: Path) -> Path | None:
    try:
        return path.relative_to(repo_root)
    except ValueError:
        return None


def _paths_overlap(candidate: Path, target: Path) -> bool:
    return _path_starts_with(candidate, target) or _path_starts_with(target, candidate)


def _path_starts_with(path: Path, prefix: Path) -> bool:
    prefix_parts = prefix.parts
    if len(prefix_parts) > len(path.parts):
        return False
    return path.parts[: len(prefix_parts)] == prefix_parts


def _recovery_recommendation(payload: dict[str, Any]) -> str:
    status = payload.get("status")
    tracked = payload.get("new_tracked_changes", payload.get("tracked_changes", []))
    worker_outputs = payload.get("worker_outputs", [])
    review_outputs = payload.get("review_outputs", [])
    run_status = status.get("status") if isinstance(status, dict) else None
    stopped_like_statuses = {"failed", "stopped", "stopped_no_progress"}
    if review_outputs:
        return "review_output_available"
    if worker_outputs:
        return "worker_output_available"
    if tracked and run_status in stopped_like_statuses:
        return "partial_repo_changes_need_review"
    if run_status in stopped_like_statuses:
        return "safe_to_retry"
    return "inspect_run_status"
