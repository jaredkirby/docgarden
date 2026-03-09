from __future__ import annotations


class DocgardenError(Exception):
    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class ConfigError(DocgardenError):
    """Raised when repo configuration cannot be loaded safely."""


class StateError(DocgardenError):
    """Raised when persisted .docgarden state is missing or malformed."""
