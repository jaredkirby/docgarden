from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


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
        data = yaml.safe_load(path.read_text()) or {}
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_name": self.repo_name,
            "strict_score_fail_threshold": self.strict_score_fail_threshold,
            "critical_domains": self.critical_domains,
            "review_defaults": self.review_defaults,
            "safe_autofix": self.safe_autofix,
            "block_on": self.block_on,
        }
