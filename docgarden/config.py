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
    domain_weights: dict[str, int | float] = field(default_factory=dict)
    review_defaults: dict[str, int] = field(default_factory=dict)
    safe_autofix: dict[str, Any] = field(default_factory=dict)
    block_on: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.critical_domains, list) or not all(
            isinstance(item, str) for item in self.critical_domains
        ):
            raise TypeError("critical_domains must be a list of strings")
        if not isinstance(self.domain_weights, dict):
            raise TypeError("domain_weights must be a mapping of domain names to weights")
        normalized_weights: dict[str, int | float] = {}
        for domain, weight in self.domain_weights.items():
            if not isinstance(domain, str):
                raise TypeError("domain_weights keys must be strings")
            if not isinstance(weight, (int, float)) or weight < 0:
                raise TypeError(
                    "domain_weights values must be non-negative numbers"
                )
            normalized_weights[domain] = weight
        self.domain_weights = normalized_weights
        if not isinstance(self.block_on, list) or not all(
            isinstance(item, str) for item in self.block_on
        ):
            raise TypeError("block_on must be a list of strings")

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
            "domain_weights": self.domain_weights,
            "review_defaults": self.review_defaults,
            "safe_autofix": self.safe_autofix,
            "block_on": self.block_on,
        }
