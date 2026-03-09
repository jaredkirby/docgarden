from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from .cli_slices_commands import _slice_paths_from_args
from .errors import DocgardenError
from .slices.config import (
    DEFAULT_REVIEWER_TIMEOUT_SECONDS,
    DEFAULT_WORKER_TIMEOUT_SECONDS,
    build_slice_run_config,
)
from .slices.run_recovery import recover_slice_run
from .slices.run_status import (
    prune_slice_runs,
    resolve_slice_run_dir,
    stop_slice_run,
    summarize_slice_run,
)
from .slices.runner import retry_slice_run, run_slice_loop


def command_slices_watch(args: argparse.Namespace) -> None:
    repo_root = Path.cwd()
    paths = _slice_paths_from_args(repo_root, args)
    if args.max_updates < 0:
        raise DocgardenError("`docgarden slices watch --max-updates` must be 0 or greater.")
    if args.interval_seconds <= 0:
        raise DocgardenError(
            "`docgarden slices watch --interval-seconds` must be greater than 0."
        )
    run_dir = resolve_slice_run_dir(paths.artifacts_dir, run_dir=args.run_dir)
    updates = 0
    while True:
        summary = summarize_slice_run(run_dir)
        print(json.dumps(summary, indent=2, sort_keys=True))
        updates += 1
        status = summary["status"].get("status")
        if status != "running":
            return
        if args.max_updates and updates >= args.max_updates:
            return
        time.sleep(args.interval_seconds)


def command_slices_stop(args: argparse.Namespace) -> int:
    repo_root = Path.cwd()
    paths = _slice_paths_from_args(repo_root, args)
    run_dir = resolve_slice_run_dir(paths.artifacts_dir, run_dir=args.run_dir)
    summary = stop_slice_run(run_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def command_slices_recover(args: argparse.Namespace) -> int:
    repo_root = Path.cwd()
    paths = _slice_paths_from_args(repo_root, args)
    run_dir = resolve_slice_run_dir(paths.artifacts_dir, run_dir=args.run_dir)
    recovery = recover_slice_run(
        repo_root,
        run_dir,
        verify=not args.skip_verification,
    )
    print(json.dumps(recovery, indent=2, sort_keys=True))
    if args.skip_verification:
        return 0
    verification = recovery.get("verification", {})
    pytest_result = verification.get("pytest", {})
    scan_result = verification.get("scan", {})
    if pytest_result.get("returncode", 0) != 0 or scan_result.get("returncode", 0) != 0:
        return 1
    return 0


def command_slices_retry(args: argparse.Namespace) -> int:
    if args.max_review_rounds < 1:
        raise DocgardenError(
            "`docgarden slices retry --max-review-rounds` must be at least 1."
        )
    repo_root = Path.cwd()
    paths = _slice_paths_from_args(repo_root, args)
    run_dir = resolve_slice_run_dir(paths.artifacts_dir, run_dir=args.run_dir)
    summary = retry_slice_run(
        repo_root,
        run_dir,
        paths=paths,
        config=_slice_run_config_from_args(args, command_name="retry"),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("status") == "completed" else 1


def command_slices_prune(args: argparse.Namespace) -> int:
    if args.keep < 0:
        raise DocgardenError("`docgarden slices prune --keep` must be 0 or greater.")
    repo_root = Path.cwd()
    paths = _slice_paths_from_args(repo_root, args)
    payload = prune_slice_runs(
        paths.artifacts_dir,
        keep=args.keep,
        apply=args.apply,
        prunable_statuses=set(args.statuses) if args.statuses else None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def command_slices_run(args: argparse.Namespace) -> int:
    if args.max_slices < 0:
        raise DocgardenError("`docgarden slices run --max-slices` must be 0 or greater.")
    if args.max_review_rounds < 1:
        raise DocgardenError(
            "`docgarden slices run --max-review-rounds` must be at least 1."
        )
    summary = run_slice_loop(
        Path.cwd(),
        paths=_slice_paths_from_args(Path.cwd(), args),
        start_slice=args.from_slice,
        max_slices=args.max_slices,
        config=_slice_run_config_from_args(args, command_name="run"),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("status") in {"completed", "noop"} else 1


def _slice_run_config_from_args(args: argparse.Namespace, *, command_name: str):
    worker_timeout_seconds, reviewer_timeout_seconds = _resolve_slice_timeout_args(
        args,
        command_name=command_name,
    )
    return build_slice_run_config(
        max_review_rounds=args.max_review_rounds,
        worker_timeout_seconds=(
            None if worker_timeout_seconds == 0 else worker_timeout_seconds
        ),
        reviewer_timeout_seconds=(
            None if reviewer_timeout_seconds == 0 else reviewer_timeout_seconds
        ),
        codex_bin=args.codex_bin,
        model=args.model,
        codex_args=args.codex_arg or [],
    )


def _resolve_slice_timeout_args(
    args: argparse.Namespace,
    *,
    command_name: str,
) -> tuple[int, int]:
    prefix = f"`docgarden slices {command_name}"
    if (
        args.agent_timeout_seconds is not None
        and (args.worker_timeout_seconds is not None or args.reviewer_timeout_seconds is not None)
    ):
        raise DocgardenError(
            "Use either `--agent-timeout-seconds` or the per-role timeout flags, not both."
        )
    _require_non_negative_timeout(
        args.agent_timeout_seconds,
        flag_name="agent-timeout-seconds",
        prefix=prefix,
    )
    _require_non_negative_timeout(
        args.worker_timeout_seconds,
        flag_name="worker-timeout-seconds",
        prefix=prefix,
    )
    _require_non_negative_timeout(
        args.reviewer_timeout_seconds,
        flag_name="reviewer-timeout-seconds",
        prefix=prefix,
    )

    worker_timeout_seconds = DEFAULT_WORKER_TIMEOUT_SECONDS
    reviewer_timeout_seconds = DEFAULT_REVIEWER_TIMEOUT_SECONDS
    if args.agent_timeout_seconds is not None:
        worker_timeout_seconds = args.agent_timeout_seconds
        reviewer_timeout_seconds = args.agent_timeout_seconds
    if args.worker_timeout_seconds is not None:
        worker_timeout_seconds = args.worker_timeout_seconds
    if args.reviewer_timeout_seconds is not None:
        reviewer_timeout_seconds = args.reviewer_timeout_seconds
    return worker_timeout_seconds, reviewer_timeout_seconds


def _require_non_negative_timeout(
    value: int | None,
    *,
    flag_name: str,
    prefix: str,
) -> None:
    if value is not None and value < 0:
        raise DocgardenError(f"{prefix} --{flag_name}` must be 0 or greater.")
