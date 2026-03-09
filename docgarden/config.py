from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError


@dataclass(slots=True)
class Config:
    repo_name: str = "docgarden"
    strict_score_fail_threshold: int = 70
    critical_domains: list[str] = field(default_factory=list)
    review_defaults: dict[str, int] = field(default_factory=dict)
    safe_autofix: dict[str, Any] = field(default_factory=dict)
    block_on: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Config":
        if not path.exists():
            return cls()
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid config at {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(
                f"Invalid config at {path}: expected a mapping at the top level."
            )
        try:
            return cls(**data)
        except TypeError as exc:
            raise ConfigError(f"Invalid config at {path}: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_name": self.repo_name,
            "strict_score_fail_threshold": self.strict_score_fail_threshold,
            "critical_domains": self.critical_domains,
            "review_defaults": self.review_defaults,
            "safe_autofix": self.safe_autofix,
            "block_on": self.block_on,
        }
