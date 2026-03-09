from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import Config
from .markdown import Document, parse_document
from .models import SCORE_RELEVANT_FINDING_STATUSES
from .scan_workflow import run_scan
from .state import latest_events_by_id, load_findings_history, load_score

BlockingRuleMatcher = Callable[
    [dict[str, Any], Path, dict[str, Document | None]],
    bool,
]


def _score_relevant_events(
    latest_events: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    return sorted(
        (
            event
            for event in latest_events.values()
            if event.get("status") in SCORE_RELEVANT_FINDING_STATUSES
        ),
        key=lambda event: str(event.get("id", "")),
    )


def _primary_document(
    event: dict[str, Any],
    repo_root: Path,
    cache: dict[str, Document | None],
) -> Document | None:
    raw_files = event.get("files")
    files = raw_files if isinstance(raw_files, list) else []
    for rel_path in files:
        if not isinstance(rel_path, str) or not rel_path:
            continue
        cached = cache.get(rel_path)
        if rel_path in cache:
            return cached

        path = repo_root / rel_path
        if not path.exists():
            cache[rel_path] = None
            continue

        cache[rel_path] = parse_document(path, repo_root)
        return cache[rel_path]
    return None


def _rule_broken_agents_routes(
    event: dict[str, Any],
    repo_root: Path,
    cache: dict[str, Document | None],
) -> bool:
    del repo_root, cache
    if event.get("kind") not in {"broken-route", "stale-route"}:
        return False
    raw_files = event.get("files")
    files = raw_files if isinstance(raw_files, list) else []
    return any(path == "AGENTS.md" for path in files)


def _rule_missing_frontmatter_on_canonical(
    event: dict[str, Any],
    repo_root: Path,
    cache: dict[str, Document | None],
) -> bool:
    del repo_root, cache
    if event.get("kind") != "missing-frontmatter":
        return False
    raw_files = event.get("files")
    files = raw_files if isinstance(raw_files, list) else []
    return any(
        isinstance(path, str) and path.startswith("docs/")
        for path in files
    )


def _is_verified_canonical_document(
    event: dict[str, Any],
    repo_root: Path,
    cache: dict[str, Document | None],
) -> bool:
    document = _primary_document(event, repo_root, cache)
    if document is None:
        return False
    return (
        document.frontmatter.get("doc_type") == "canonical"
        and document.frontmatter.get("status") == "verified"
    )


def _rule_stale_verified_canonical_docs(
    event: dict[str, Any],
    repo_root: Path,
    cache: dict[str, Document | None],
) -> bool:
    if event.get("kind") not in {"stale-review", "verified-without-sources"}:
        return False
    return _is_verified_canonical_document(event, repo_root, cache)


def _rule_active_exec_plan_missing_progress(
    event: dict[str, Any],
    repo_root: Path,
    cache: dict[str, Document | None],
) -> bool:
    if event.get("kind") != "missing-sections":
        return False

    details = event.get("details")
    missing_sections = (
        details.get("missing_sections")
        if isinstance(details, dict)
        else None
    )
    if not isinstance(missing_sections, list) or "Progress" not in missing_sections:
        return False

    document = _primary_document(event, repo_root, cache)
    if document is None:
        return False
    return (
        document.rel_path.startswith("docs/exec-plans/active/")
        and document.frontmatter.get("doc_type") == "exec-plan"
    )


BLOCKING_RULES: dict[str, tuple[str, BlockingRuleMatcher]] = {
    "broken_agents_routes": (
        "Broken or stale routes in `AGENTS.md`.",
        _rule_broken_agents_routes,
    ),
    "missing_frontmatter_on_canonical": (
        "Docs under `docs/` that are missing frontmatter and therefore cannot prove canonical metadata.",
        _rule_missing_frontmatter_on_canonical,
    ),
    "stale_verified_canonical_docs": (
        "Verified canonical docs that are stale or missing trust metadata.",
        _rule_stale_verified_canonical_docs,
    ),
    "active_exec_plan_missing_progress": (
        "Active exec plans that are missing the required `Progress` section.",
        _rule_active_exec_plan_missing_progress,
    ),
}


def _summarize_event(event: dict[str, Any]) -> dict[str, Any]:
    raw_files = event.get("files")
    files = [item for item in raw_files if isinstance(item, str)] if isinstance(raw_files, list) else []
    return {
        "id": event.get("id"),
        "kind": event.get("kind"),
        "status": event.get("status"),
        "severity": event.get("severity"),
        "summary": event.get("summary"),
        "files": files,
        "recommended_action": event.get("recommended_action"),
    }


def build_ci_check_payload(paths) -> dict[str, Any]:
    if not paths.score.exists():
        run_scan(paths)

    config = Config.load(paths.config)
    score = load_score(paths.score)
    latest = latest_events_by_id(load_findings_history(paths.findings))
    active_events = _score_relevant_events(latest)
    document_cache: dict[str, Document | None] = {}

    failures: list[dict[str, Any]] = []
    threshold = config.strict_score_fail_threshold
    strict_score = score.strict_score if score else None
    if strict_score is not None and strict_score < threshold:
        failures.append(
            {
                "type": "strict_score_fail_threshold",
                "summary": (
                    f"Strict score {strict_score} is below the configured "
                    f"threshold of {threshold}."
                ),
                "strict_score": strict_score,
                "threshold": threshold,
            }
        )

    for rule_name in config.block_on:
        rule = BLOCKING_RULES.get(rule_name)
        if rule is None:
            failures.append(
                {
                    "type": "unknown_blocking_rule",
                    "rule": rule_name,
                    "summary": (
                        f"`block_on` references unknown rule `{rule_name}`."
                    ),
                }
            )
            continue

        description, matcher = rule
        matches = [
            _summarize_event(event)
            for event in active_events
            if matcher(event, paths.repo_root, document_cache)
        ]
        if not matches:
            continue
        failures.append(
            {
                "type": "blocking_rule",
                "rule": rule_name,
                "summary": (
                    f"Configured blocking rule `{rule_name}` matched "
                    f"{len(matches)} finding(s)."
                ),
                "description": description,
                "finding_count": len(matches),
                "findings": matches,
            }
        )

    return {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "passed": not failures,
        "strict_score": strict_score,
        "strict_score_fail_threshold": threshold,
        "block_on": list(config.block_on),
        "active_score_relevant_findings": len(active_events),
        "failures": failures,
    }
