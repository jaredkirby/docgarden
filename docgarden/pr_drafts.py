from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Config
from .errors import DocgardenError
from .models import Finding

TRANSIENT_CHANGED_PATHS = {
    ".docgarden/findings.jsonl",
    ".docgarden/plan.json",
    ".docgarden/score.json",
}
TRANSIENT_CHANGED_PREFIXES = (
    ".docgarden/baselines/",
    ".docgarden/cache/",
    ".docgarden/locks/",
    ".docgarden/reviews/",
    ".docgarden/runs/",
    ".docgarden/slice-loops/",
    ".docgarden/slice-loops-baseline-eval/",
    ".docgarden/slice-loops-eval/",
)


@dataclass(frozen=True, slots=True)
class DraftPublishTarget:
    enabled: bool
    provider: str | None
    repository: str | None
    base_branch: str | None
    token_env_var: str
    api_base_url: str

    @classmethod
    def from_config(cls, config: Config) -> "DraftPublishTarget":
        raw = config.pr_drafts if isinstance(config.pr_drafts, dict) else {}
        provider = _optional_string(raw.get("provider"))
        repository = _optional_string(raw.get("repository"))
        base_branch = _optional_string(raw.get("base_branch"))
        token_env_var = _optional_string(raw.get("token_env_var")) or "DOCGARDEN_GITHUB_TOKEN"
        api_base_url = _optional_string(raw.get("api_base_url")) or "https://api.github.com"
        return cls(
            enabled=bool(raw.get("enabled", False)),
            provider=provider,
            repository=repository,
            base_branch=base_branch,
            token_env_var=token_env_var,
            api_base_url=api_base_url,
        )

    def publish_blockers(self) -> list[str]:
        blockers: list[str] = []
        if not self.enabled:
            blockers.append(
                "Remote PR and issue automation is disabled. Set "
                "`pr_drafts.enabled: true` in `.docgarden/config.yaml` to allow `--publish`."
            )
        if self.provider != "github":
            blockers.append(
                "Only `pr_drafts.provider: github` is supported for `docgarden pr draft --publish`."
            )
        if not self.repository:
            blockers.append(
                "Configure `pr_drafts.repository` as `owner/repo` before using `--publish`."
            )
        if not self.base_branch:
            blockers.append(
                "Configure `pr_drafts.base_branch` before using `--publish`."
            )
        if not os.environ.get(self.token_env_var):
            blockers.append(
                f"Set the `{self.token_env_var}` environment variable before using `--publish`."
            )
        return blockers

    def as_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "repository": self.repository,
            "base_branch": self.base_branch,
            "token_env_var": self.token_env_var,
            "api_base_url": self.api_base_url,
        }


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _run_git_path_query(repo_root: Path, args: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise DocgardenError(
            "Unable to derive changed files from git state. "
            f"Git said: {result.stderr.strip() or 'unknown git error'}"
        )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _should_include_changed_path(rel_path: str) -> bool:
    if rel_path in TRANSIENT_CHANGED_PATHS:
        return False
    return not any(rel_path.startswith(prefix) for prefix in TRANSIENT_CHANGED_PREFIXES)


def collect_changed_files(repo_root: Path) -> tuple[list[str], list[str], list[str]]:
    tracked_existing = _run_git_path_query(
        repo_root,
        ["diff", "--name-only", "--diff-filter=ACMR", "--relative"],
    )
    staged_existing = _run_git_path_query(
        repo_root,
        ["diff", "--cached", "--name-only", "--diff-filter=ACMR", "--relative"],
    )
    untracked = _run_git_path_query(
        repo_root,
        ["ls-files", "--others", "--exclude-standard"],
    )
    tracked_deleted = _run_git_path_query(
        repo_root,
        ["diff", "--name-only", "--diff-filter=D", "--relative"],
    )
    staged_deleted = _run_git_path_query(
        repo_root,
        ["diff", "--cached", "--name-only", "--diff-filter=D", "--relative"],
    )

    changed_files = _dedupe_preserving_order(
        [
            str(Path(path))
            for path in [*tracked_existing, *staged_existing, *untracked]
            if _should_include_changed_path(str(Path(path)))
        ]
    )
    deleted_files = _dedupe_preserving_order(
        [
            str(Path(path))
            for path in [*tracked_deleted, *staged_deleted]
            if _should_include_changed_path(str(Path(path)))
        ]
    )
    notes: list[str] = []
    if not changed_files and not deleted_files:
        notes.append("No non-transient changed files were detected from local git state.")
    return changed_files, deleted_files, notes


def current_branch_name(repo_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def build_pr_draft_payload(
    repo_root: Path,
    config: Config,
    actionable_findings: list[Finding],
    *,
    unsafe_as_issue: bool,
) -> dict[str, Any]:
    target = DraftPublishTarget.from_config(config)
    changed_files, deleted_files, notes = collect_changed_files(repo_root)
    branch_name = current_branch_name(repo_root)
    unsafe_findings = [
        finding for finding in actionable_findings if not finding.safe_to_autofix
    ]
    selected_findings = unsafe_findings if unsafe_as_issue else actionable_findings
    if unsafe_as_issue and not selected_findings:
        raise DocgardenError(
            "No unsafe actionable findings are available for "
            "`docgarden pr draft --unsafe-as-issue`."
        )

    mode = "issue" if unsafe_as_issue else "pr"
    title = _draft_title(mode=mode, findings=selected_findings)
    body = _draft_body(
        mode=mode,
        findings=selected_findings,
        changed_files=changed_files,
        deleted_files=deleted_files,
        branch_name=branch_name,
        base_branch=target.base_branch,
        unsafe_finding_count=len(unsafe_findings),
    )
    summary = _draft_summary(
        mode=mode,
        finding_count=len(selected_findings),
        changed_file_count=len(changed_files),
        deleted_file_count=len(deleted_files),
    )
    publish_blockers = _draft_publish_blockers(
        target=target,
        mode=mode,
        finding_count=len(selected_findings),
    )

    return {
        "mode": mode,
        "summary": summary,
        "title": title,
        "body": body,
        "total_actionable_findings": len(actionable_findings),
        "total_active_findings": len(actionable_findings),
        "finding_count": len(selected_findings),
        "finding_ids": [finding.id for finding in selected_findings],
        "findings": [_finding_payload(finding) for finding in selected_findings],
        "safe_finding_ids": [
            finding.id for finding in actionable_findings if finding.safe_to_autofix
        ],
        "unsafe_finding_ids": [finding.id for finding in unsafe_findings],
        "changed_files": changed_files,
        "deleted_files": deleted_files,
        "branch": branch_name,
        "publish_target": target.as_payload(),
        "publish_ready": not publish_blockers,
        "publish_blockers": publish_blockers,
        "published": False,
        "remote": None,
        "notes": notes,
    }


def publish_pr_draft(repo_root: Path, config: Config, payload: dict[str, Any]) -> dict[str, Any]:
    target = DraftPublishTarget.from_config(config)
    mode = str(payload.get("mode", "pr"))
    blockers = _draft_publish_blockers(
        target=target,
        mode=mode,
        finding_count=int(payload.get("finding_count", 0)),
    )
    if blockers:
        raise DocgardenError("Cannot publish draft: " + " ".join(blockers))

    token = os.environ.get(target.token_env_var)
    if not token:
        raise DocgardenError(
            f"Cannot publish draft without `{target.token_env_var}` in the environment."
        )

    if mode == "pr":
        head_branch = current_branch_name(repo_root)
        if not head_branch or head_branch == "HEAD":
            raise DocgardenError(
                "Cannot publish a draft PR from a detached or unknown git HEAD."
            )
        response = _github_api_request(
            target=target,
            token=token,
            endpoint="/pulls",
            payload={
                "title": payload["title"],
                "body": payload["body"],
                "head": head_branch,
                "base": target.base_branch,
                "draft": True,
            },
        )
        return {
            "kind": "pull_request",
            "number": response.get("number"),
            "url": response.get("html_url"),
            "head_branch": head_branch,
            "base_branch": target.base_branch,
        }

    response = _github_api_request(
        target=target,
        token=token,
        endpoint="/issues",
        payload={
            "title": payload["title"],
            "body": payload["body"],
        },
    )
    return {
        "kind": "issue",
        "number": response.get("number"),
        "url": response.get("html_url"),
    }


def _draft_title(*, mode: str, findings: list[Finding]) -> str:
    count = len(findings)
    if mode == "issue":
        return f"docgarden: follow up on {count} unsafe finding(s)"
    return f"docgarden: draft fixes for {count} finding(s)"


def _draft_publish_blockers(
    *,
    target: DraftPublishTarget,
    mode: str,
    finding_count: int,
) -> list[str]:
    blockers = list(target.publish_blockers())
    if mode == "pr" and finding_count == 0:
        blockers.append(
            "Draft PR publish requires at least one actionable finding in scope. "
            "Run `docgarden pr draft` without `--publish` for a local preview, "
            "or wait until the next scan reports actionable findings."
        )
    return blockers


def _draft_summary(
    *,
    mode: str,
    finding_count: int,
    changed_file_count: int,
    deleted_file_count: int,
) -> str:
    noun = "unsafe actionable finding" if mode == "issue" else "actionable finding"
    draft_kind = "issue" if mode == "issue" else "PR"
    deleted_fragment = (
        f" and {deleted_file_count} deleted file(s)"
        if deleted_file_count
        else ""
    )
    return (
        f"Prepared a draft {draft_kind} summary from {finding_count} {noun}(s), "
        f"{changed_file_count} changed file(s){deleted_fragment}."
    )


def _draft_body(
    *,
    mode: str,
    findings: list[Finding],
    changed_files: list[str],
    deleted_files: list[str],
    branch_name: str | None,
    base_branch: str | None,
    unsafe_finding_count: int,
) -> str:
    lines = [
        "## Summary",
        _draft_summary(
            mode=mode,
            finding_count=len(findings),
            changed_file_count=len(changed_files),
            deleted_file_count=len(deleted_files),
        ),
    ]
    if branch_name:
        lines.append(f"Current branch: `{branch_name}`.")
    if mode == "pr" and base_branch:
        lines.append(f"Configured base branch: `{base_branch}`.")

    lines.extend(["", "## Findings in scope"])
    if findings:
        lines.extend(_finding_markdown_line(finding) for finding in findings)
    else:
        lines.append("- No actionable findings are currently recorded.")

    lines.extend(["", "## Changed files"])
    if changed_files:
        lines.extend(f"- `{path}`" for path in changed_files)
    else:
        lines.append("- No non-transient changed files were detected.")

    if deleted_files:
        lines.extend(["", "## Deleted files"])
        lines.extend(f"- `{path}`" for path in deleted_files)

    if mode == "pr" and unsafe_finding_count:
        lines.extend(
            [
                "",
                "## Unsafe follow-up",
                (
                    f"- {unsafe_finding_count} actionable finding(s) are not marked "
                    "safe to autofix. Run `docgarden pr draft --unsafe-as-issue` to "
                    "prepare a follow-up issue instead of a PR."
                ),
            ]
        )

    return "\n".join(lines)


def _finding_markdown_line(finding: Finding) -> str:
    files_display = ", ".join(f"`{path}`" for path in finding.files) or "`(no files)`"
    return (
        f"- `{finding.id}` (`{finding.kind}`, status `{finding.status}`, "
        f"severity `{finding.severity}`) on {files_display}: {finding.summary} "
        f"Recommended action: {finding.recommended_action}"
    )


def _finding_payload(finding: Finding) -> dict[str, Any]:
    return {
        "id": finding.id,
        "kind": finding.kind,
        "status": finding.status,
        "severity": finding.severity,
        "summary": finding.summary,
        "files": list(finding.files),
        "recommended_action": finding.recommended_action,
        "safe_to_autofix": finding.safe_to_autofix,
    }


def _github_api_request(
    *,
    target: DraftPublishTarget,
    token: str,
    endpoint: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not target.repository:
        raise DocgardenError("Cannot call GitHub without a configured repository.")

    request = Request(
        url=(
            f"{target.api_base_url.rstrip('/')}/repos/"
            f"{target.repository}{endpoint}"
        ),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise DocgardenError(
            f"GitHub draft publish failed with HTTP {exc.code}: {error_body}"
        ) from exc
    except URLError as exc:
        raise DocgardenError(f"GitHub draft publish failed: {exc.reason}") from exc
