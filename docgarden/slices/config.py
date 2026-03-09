from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SliceAutomationPaths:
    implementation_slices: Path
    spec: Path
    spec_slicing_plan: Path
    artifacts_dir: Path


@dataclass(frozen=True, slots=True)
class SliceRunConfig:
    max_review_rounds: int
    worker_timeout_seconds: int | None
    reviewer_timeout_seconds: int | None
    codex_bin: str
    model: str | None
    codex_args: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SliceRunRequest:
    repo_root: Path
    paths: SliceAutomationPaths
    loop_root: Path
    slice_def: "SliceDefinition"
    next_slice: "SliceDefinition | None"
    config: SliceRunConfig


DEFAULT_WORKER_TIMEOUT_SECONDS = 900
DEFAULT_REVIEWER_TIMEOUT_SECONDS = 300


def build_slice_paths(
    repo_root: Path,
    *,
    implementation_slices: str | Path | None = None,
    spec: str | Path | None = None,
    spec_slicing_plan: str | Path | None = None,
    artifacts_dir: str | Path | None = None,
) -> SliceAutomationPaths:
    return SliceAutomationPaths(
        implementation_slices=_resolve_repo_path(
            repo_root,
            implementation_slices,
            default=Path("docs/design-docs/docgarden-implementation-slices.md"),
        ),
        spec=_resolve_repo_path(
            repo_root,
            spec,
            default=Path("docs/design-docs/docgarden-spec.md"),
        ),
        spec_slicing_plan=_resolve_repo_path(
            repo_root,
            spec_slicing_plan,
            default=Path("docs/exec-plans/active/2026-03-09-docgarden-spec-slicing.md"),
        ),
        artifacts_dir=_resolve_repo_path(
            repo_root,
            artifacts_dir,
            default=Path(".docgarden/slice-loops"),
        ),
    )


def _resolve_repo_path(repo_root: Path, value: str | Path | None, *, default: Path) -> Path:
    candidate = Path(value) if value is not None else default
    return candidate if candidate.is_absolute() else repo_root / candidate


def build_slice_run_config(
    *,
    max_review_rounds: int,
    worker_timeout_seconds: int | None = DEFAULT_WORKER_TIMEOUT_SECONDS,
    reviewer_timeout_seconds: int | None = DEFAULT_REVIEWER_TIMEOUT_SECONDS,
    codex_bin: str = "codex",
    model: str | None = None,
    codex_args: list[str] | tuple[str, ...] | None = None,
) -> SliceRunConfig:
    return SliceRunConfig(
        max_review_rounds=max_review_rounds,
        worker_timeout_seconds=worker_timeout_seconds,
        reviewer_timeout_seconds=reviewer_timeout_seconds,
        codex_bin=codex_bin,
        model=model,
        codex_args=tuple(codex_args or ()),
    )
