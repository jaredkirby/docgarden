from __future__ import annotations

import argparse
import json
from pathlib import Path

from .errors import DocgardenError
from .slices.catalog import load_slice_catalog
from .slices.config import build_slice_paths
from .slices.prompts import build_implementation_prompt, build_review_prompt
from .slices.run_status import list_slice_runs


def command_slices_next(args: argparse.Namespace) -> None:
    repo_root = Path.cwd()
    paths = _slice_paths_from_args(repo_root, args)
    catalog = load_slice_catalog(repo_root, paths=paths)
    next_slice = catalog.next_actionable_slice()
    if next_slice is None:
        print("No queued or active slices remain.")
        return
    upcoming = catalog.next_planned_slice(next_slice.slice_id)
    print(
        json.dumps(
            {
                "slice_id": next_slice.slice_id,
                "title": next_slice.title,
                "status": next_slice.status,
                "goal": next_slice.goal,
                "depends_on": next_slice.depends_on,
                "changes": next_slice.changes,
                "acceptance": next_slice.acceptance,
                "next_slice": upcoming.slice_id if upcoming is not None else None,
            },
            indent=2,
            sort_keys=True,
        )
    )


def command_slices_list(args: argparse.Namespace) -> int:
    repo_root = Path.cwd()
    paths = _slice_paths_from_args(repo_root, args)
    payload = {
        "artifacts_dir": str(paths.artifacts_dir),
        "runs": list_slice_runs(paths.artifacts_dir),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def command_slices_kickoff_prompt(args: argparse.Namespace) -> None:
    repo_root = Path.cwd()
    paths = _slice_paths_from_args(repo_root, args)
    catalog = load_slice_catalog(repo_root, paths=paths)
    slice_def = (
        catalog.by_id(args.slice_id)
        if args.slice_id is not None
        else catalog.next_actionable_slice()
    )
    if slice_def is None:
        raise DocgardenError("No queued or active slices remain.")
    next_slice = catalog.next_planned_slice(slice_def.slice_id)
    print(
        build_implementation_prompt(
            repo_root,
            slice_def,
            next_slice=next_slice,
            paths=paths,
            round_number=args.round,
            review_feedback_path=Path(args.review_feedback)
            if args.review_feedback
            else None,
            previous_worker_output_path=Path(args.previous_worker_output)
            if args.previous_worker_output
            else None,
        ),
        end="",
    )


def command_slices_review_prompt(args: argparse.Namespace) -> None:
    repo_root = Path.cwd()
    paths = _slice_paths_from_args(repo_root, args)
    catalog = load_slice_catalog(repo_root, paths=paths)
    slice_def = (
        catalog.by_id(args.slice_id)
        if args.slice_id is not None
        else catalog.next_actionable_slice()
    )
    if slice_def is None:
        raise DocgardenError("No queued or active slices remain.")
    next_slice = catalog.next_planned_slice(slice_def.slice_id)
    print(
        build_review_prompt(
            repo_root,
            slice_def,
            next_slice=next_slice,
            paths=paths,
            worker_output_path=Path(args.worker_output),
            round_number=args.round,
            prior_review_path=Path(args.prior_review_output)
            if args.prior_review_output
            else None,
        ),
        end="",
    )


def _slice_paths_from_args(repo_root: Path, args: argparse.Namespace):
    return build_slice_paths(
        repo_root,
        implementation_slices=getattr(args, "catalog_path", None),
        spec=getattr(args, "spec_path", None),
        spec_slicing_plan=getattr(args, "plan_path", None),
        artifacts_dir=getattr(args, "artifacts_dir", None),
    )
