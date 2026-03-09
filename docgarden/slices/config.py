from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SliceAutomationPaths:
    implementation_slices: Path
    spec: Path
    spec_slicing_plan: Path
    artifacts_dir: Path


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
