from __future__ import annotations

from pathlib import Path
from typing import Any

from .catalog import SliceDefinition
from .config import SliceAutomationPaths

WORKER_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": ["completed", "blocked"]},
        "summary": {"type": "string"},
        "files_touched": {"type": "array", "items": {"type": "string"}},
        "tests_run": {"type": "array", "items": {"type": "string"}},
        "docs_updated": {"type": "array", "items": {"type": "string"}},
        "notes_for_reviewer": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "status",
        "summary",
        "files_touched",
        "tests_run",
        "docs_updated",
        "notes_for_reviewer",
        "open_questions",
    ],
}

REVIEW_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "recommendation": {
            "type": "string",
            "enum": [
                "ready_for_next_slice",
                "revise_before_next_slice",
                "blocked_pending_product_clarification",
            ],
        },
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "spec_mismatch",
                            "product_ambiguity",
                            "implementation_risk",
                            "testing_documentation_gap",
                        ],
                    },
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "revision_direction": {"type": "string"},
                },
                "required": [
                    "severity",
                    "category",
                    "title",
                    "detail",
                    "revision_direction",
                ],
            },
        },
        "next_step": {"type": "string"},
    },
    "required": ["recommendation", "summary", "findings", "next_step"],
}


def build_implementation_prompt(
    repo_root: Path,
    slice_def: SliceDefinition,
    *,
    next_slice: SliceDefinition | None,
    paths: SliceAutomationPaths,
    round_number: int = 1,
    review_feedback_path: Path | None = None,
    previous_worker_output_path: Path | None = None,
) -> str:
    lines = [
        f"You’re implementing the next slice in {repo_root}.",
        "",
        "Start by reading:",
        f"- {_display_path(repo_root, paths.implementation_slices)}",
        f"- {_display_path(repo_root, paths.spec)}",
        f"- {_display_path(repo_root, paths.spec_slicing_plan)}",
        "",
        f"Your target slice is {slice_def.slice_id}: “{slice_def.title}”.",
        "",
        "Primary goal:",
        f"- {slice_def.goal}",
        "",
        "Required changes:",
    ]
    lines.extend(f"{index}. {item}" for index, item in enumerate(slice_def.changes, start=1))
    if slice_def.likely_files:
        lines.extend(["", "Likely files:"])
        lines.extend(f"- {item}" for item in slice_def.likely_files)
    lines.extend(["", "Acceptance criteria:"])
    lines.extend(f"- {item}" for item in slice_def.acceptance)
    lines.extend(
        [
            "",
            "Working style:",
            (
                f"- keep this slice tight; do not jump ahead into {next_slice.slice_id} {next_slice.title.lower()}"
                if next_slice is not None
                else "- keep this slice tight; do not jump ahead into later queued slices"
            ),
            "- implement the code changes directly; do not run `docgarden slices` commands or use the `docgarden-slice-orchestrator` skill inside this worker",
            "- do not revert unrelated user changes",
            "- if the worktree is dirty, work around unrelated edits and commit only the files you touched",
            "",
            "Verification:",
            "- uv run pytest",
            "- uv run docgarden scan",
            "",
            "Documentation:",
            "- if behavior changed durably, update the relevant exec plan and the README or other routing docs as needed",
        ]
    )
    if round_number > 1:
        lines.extend(
            [
                "",
                "Revision context:",
                f"- prior worker output: {previous_worker_output_path}",
                f"- latest reviewer feedback: {review_feedback_path}",
                "- address the reviewer findings directly and do not leave partial fixes unacknowledged",
            ]
        )
    lines.extend(
        [
            "",
            "Commit:",
            "- make an atomic commit with only the files you touched when the slice is in a reviewable state",
            "",
            "Final response requirement:",
            "- return JSON only matching the provided schema",
        ]
    )
    return "\n".join(lines) + "\n"


def build_review_prompt(
    repo_root: Path,
    slice_def: SliceDefinition,
    *,
    next_slice: SliceDefinition | None,
    paths: SliceAutomationPaths,
    worker_output_path: Path,
    round_number: int = 1,
    prior_review_path: Path | None = None,
) -> str:
    lines = [
        "Act as a PM-style reviewer for the slice implementation in",
        str(repo_root),
        "",
        f"You are reviewing the implementation of {slice_def.slice_id}: “{slice_def.title}”.",
        "",
        "Read first:",
        f"- {_display_path(repo_root, paths.spec)}",
        f"- {_display_path(repo_root, paths.implementation_slices)}",
        f"- {_display_path(repo_root, paths.spec_slicing_plan)}",
        "",
        "Review context:",
        f"- latest worker output JSON: {worker_output_path}",
    ]
    if prior_review_path is not None:
        lines.append(f"- prior review output JSON: {prior_review_path}")
    lines.extend(
        [
            "",
            "Review specifically against this slice definition.",
            "",
            "Goal:",
            f"- {slice_def.goal}",
            "",
            "Planned changes:",
        ]
    )
    lines.extend(f"- {item}" for item in slice_def.changes)
    lines.extend(["", "Acceptance criteria:"])
    lines.extend(f"- {item}" for item in slice_def.acceptance)
    lines.extend(
        [
            "",
            "Questions to answer:",
            "1. Does the implementation satisfy the slice goal?",
            "2. Which planned changes are fully implemented, partially implemented, or missing?",
            "3. Which acceptance criteria are fully met, partially met, or unmet?",
            (
                f"4. Did the implementation stay within {slice_def.slice_id}, or did it sprawl into {next_slice.slice_id}?"
                if next_slice is not None
                else f"4. Did the implementation stay within {slice_def.slice_id} without unnecessary sprawl?"
            ),
            "5. Are the tests, docs, and operator-facing messages sufficient for repeatable use?",
            "6. Are the findings and revision directions specific enough for a worker agent to act on directly?",
            "",
            "Review guardrails:",
            "- review the slice implementation directly; do not run `docgarden slices` commands or use the `docgarden-slice-orchestrator` skill inside this reviewer",
            "",
            "Deliverable:",
            "- findings first, ordered by severity",
            "- recommendation must be one of: ready_for_next_slice, revise_before_next_slice, blocked_pending_product_clarification",
            "- if there are no material issues, say so clearly",
            "- return JSON only matching the provided schema",
        ]
    )
    if round_number > 1:
        lines.extend(
            [
                "",
                "Re-review note:",
                "- this is a follow-up review after revision work; check whether prior findings were actually closed",
            ]
        )
    return "\n".join(lines) + "\n"


def _display_path(repo_root: Path, path: Path) -> str:
    return str(path.relative_to(repo_root)) if path.is_relative_to(repo_root) else str(path)
