from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import DocgardenError


def read_review_output(review_output_path: Path) -> dict[str, Any]:
    if not review_output_path.exists():
        raise DocgardenError(f"Review output not found: {review_output_path}.")
    try:
        payload = json.loads(review_output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DocgardenError(
            f"Review output was not valid JSON: {review_output_path}."
        ) from exc
    if not isinstance(payload, dict):
        raise DocgardenError(
            f"Review output must be a JSON object: {review_output_path}."
        )
    return payload


def load_review_signature(review_output_path: Path | None) -> tuple[Any, ...] | None:
    if review_output_path is None:
        return None
    try:
        return review_signature(read_review_output(review_output_path))
    except DocgardenError:
        return None


def review_signature(parsed_output: dict[str, Any]) -> tuple[Any, ...]:
    findings: tuple[tuple[str, str, str, str, str], ...] = tuple(
        (
            str(item.get("severity", "")),
            str(item.get("category", "")),
            str(item.get("title", "")),
            str(item.get("detail", "")),
            str(item.get("revision_direction", "")),
        )
        for item in parsed_output.get("findings", [])
        if isinstance(item, dict)
    )
    return (
        str(parsed_output.get("recommendation", "")),
        str(parsed_output.get("summary", "")),
        findings,
        str(parsed_output.get("next_step", "")),
    )
