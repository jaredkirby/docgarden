---
doc_id: architecture
doc_type: reference
domain: docs
owner: kirby
status: draft
last_reviewed: 2026-03-10
review_cycle_days: 30
applies_to:
  - repo
source_of_truth:
  - docgarden/
verification:
  method: doc-reviewed
  confidence: medium
supersedes: []
superseded_by: null
tags:
  - architecture
  - contributing
---

# Architecture & Contributor Guide

## Module map

The codebase is organized into five layers. Each module has a single responsibility.

### CLI layer

| Module | Responsibility |
|--------|---------------|
| `docgarden/cli.py` | Builds the argparse parser tree and wires subcommands to handler functions. Entry point via `main()`. |
| `docgarden/cli_commands.py` | Handler functions for `scan`, `status`, `ci check`, `next`, `show`, `quality write`, `fix safe`, `pr draft`, `config show`, and `doctor`. Each handler constructs `RepoPaths`, delegates to lower layers, and prints JSON. |
| `docgarden/cli_plan_review.py` | Handler functions for `plan`, `plan triage`, `plan focus`, `plan resolve`, `plan reopen`, `review prepare`, and `review import`. Registers the `plan` and `review` sub-parser trees. |

### Scan engine layer (`docgarden/scan/`)

| Module | Responsibility |
|--------|---------------|
| `scan/__init__.py` | Package marker. |
| `scan/scanner.py` | Core scan orchestration. Discovers markdown files, runs document rules per file and repo rules across all files. Exports `scan_repo()`, `scan_changed_files()`, `determine_changed_docs()`, and the `DOCUMENT_RULES` / `REPO_RULES` tuples. Defines `DocumentScanContext` and `RepoScanContext`. |
| `scan/document_rules.py` | Per-document finding constructors: `missing_frontmatter_finding`, `missing_metadata_finding`, `invalid_status_finding`, `missing_sections_finding`, `stale_review_finding`, `verified_without_sources_finding`, `broken_link_finding`, `generated_doc_contract_finding`, `generated_doc_stale_finding`. Also defines `REQUIRED_METADATA`, `ALLOWED_STATUS`, and `REQUIRED_SECTIONS`. |
| `scan/alignment.py` | Artifact-alignment detectors: `missing_source_of_truth_findings`, `invalid_validation_command_findings`, `generated_doc_findings`, `workflow_asset_findings`, and `promotion_suggestion_findings`. Contains command validation logic and the transient-knowledge promotion heuristic. |
| `scan/linkage.py` | Cross-file relationship detectors: `duplicate_doc_id_findings`, `broken_route_findings`, `route_quality_findings`, `orphan_doc_findings`. Tracks inbound links and routed targets across the repo. |
| `scan/findings.py` | `FindingSpec` dataclass and `build_finding` / `build_document_finding` helper functions that construct `Finding` objects from a spec and a document or path context. |
| `scan/workflow.py` | High-level scan orchestration: `run_scan()` performs a full scan and persists state (findings, score, plan, run artifacts). `run_changed_scan()` does a lightweight scan of only changed files without persisting durable state. |

### State & persistence layer

| Module | Responsibility |
|--------|---------------|
| `docgarden/state.py` | All durable state operations: loading and appending to `findings.jsonl`, deduplication via `latest_events_by_id()`, plan construction via `build_plan()`, resolution and reopening of findings, review packet preparation and import, triage stage transitions. |
| `docgarden/files.py` | `atomic_write_text()` -- crash-safe file writes using temp file + `os.replace`. |

### Scoring & fixing layer

| Module | Responsibility |
|--------|---------------|
| `docgarden/quality.py` | `build_scorecard()` computes dimension scores, domain scores, weighted rollup, trend tracking, and critical-domain regressions. `render_quality_markdown()` formats the scorecard as a human-readable doc. `write_quality_score()` persists it. |
| `docgarden/fixers.py` | `preview_safe_fixes()` and `apply_safe_fixes()` apply mechanical fixes for findings marked `safe_to_autofix`. Supported fix kinds: `stale-review` (set status to needs-review), `missing-sections` (append stub headings), `missing-metadata` (add skeleton fields), `broken-link` (replace target), `broken-route` / `stale-route` (replace route references). |
| `docgarden/automation.py` | `build_ci_check_payload()` evaluates the configured `block_on` rules and strict-score threshold to produce a pass/fail JSON payload for CI integration. Defines `BLOCKING_RULES` that match findings against configurable policy. |
| `docgarden/pr_drafts.py` | `build_pr_draft_payload()` collects changed files from git, formats a PR or issue body from actionable findings, and checks publish readiness. `publish_pr_draft()` pushes to GitHub's API. |

### Shared foundation

| Module | Responsibility |
|--------|---------------|
| `docgarden/models.py` | All data classes: `Finding`, `FindingRecord`, `FindingContext`, `Scorecard`, `DomainScore`, `PlanState`, `RepoPaths`, `ScanRunResult`, and status constant sets (`FINDING_STATUSES`, `ACTIONABLE_FINDING_STATUSES`, etc.). |
| `docgarden/config.py` | `Config` dataclass loaded from `.docgarden/config.yaml`. Fields: `strict_score_fail_threshold`, `critical_domains`, `domain_weights`, `block_on`, `pr_drafts`. |
| `docgarden/errors.py` | Exception hierarchy: `DocgardenError` (base), `ConfigError`, `StateError`, `MarkdownError`. Each carries an `exit_code`. |
| `docgarden/markdown.py` | Markdown parsing utilities: `parse_document()` reads a file and returns a `Document` with frontmatter, body, headings, links, and routed paths. Also: `split_frontmatter`, `dump_frontmatter`, `replace_frontmatter`, `extract_markdown_links`, `extract_sections`, `resolve_link_target`. |


## Data flow

Trace of `docgarden scan` (full scope):

```
CLI (cli.py main)
  -> command_scan (cli_commands.py)
       -> repo_paths() builds RepoPaths, ensures .docgarden/ dirs exist
       -> run_scan (scan/workflow.py)
            -> Config.load() reads .docgarden/config.yaml
            -> load_score() reads previous .docgarden/score.json
            -> scan_repo (scan/scanner.py)
                 -> discover_markdown_files() finds AGENTS.md + docs/**/*.md
                 -> parse_document() for each file -> Document objects
                 -> per-document: _scan_document() runs DOCUMENT_RULES
                 -> repo-wide: _scan_repo_rules() runs REPO_RULES
                 -> returns (findings, domain_doc_counts, documents)
            -> append_scan_events (state.py)
                 -> loads findings.jsonl history
                 -> for each current finding: appends "observed" event
                 -> for previously-open findings no longer observed: appends "resolved" event
                 -> returns latest_events map
            -> build_scorecard (quality.py)
                 -> computes dimension scores, domain scores, rollup, trend
            -> write_score() persists .docgarden/score.json
            -> build_plan (state.py)
                 -> orders actionable findings by severity, preserves previous focus
            -> write_json() persists .docgarden/plan.json
            -> writes run artifacts to .docgarden/runs/<timestamp>/
            -> returns ScanRunResult
       -> prints JSON summary to stdout
```


## Key abstractions

**`Document`** (`markdown.py`) -- A parsed markdown file. Contains `path`, `rel_path`, `frontmatter` (dict from YAML), `body`, `headings`, `links`, `routed_paths`, and `raw_text`. Produced by `parse_document()`.

**`Finding`** (`models.py`) -- A single detected issue. Fields: `id` (deterministic, e.g. `missing-metadata::docs::index.md::metadata`), `kind`, `severity` (high/medium/low), `domain`, `status`, `files`, `summary`, `evidence`, `recommended_action`, `safe_to_autofix`, `cluster`, `confidence`. Constructed via `Finding.open_issue()` from a `FindingContext`.

**`FindingRecord`** (`models.py`) -- A `Finding` plus event metadata (`event`, `event_at`). This is what gets persisted to `findings.jsonl`. Each line in the file is a serialized `FindingRecord`. A `FindingRecord` can be converted back to a `Finding` via `.to_finding()`.

**`FindingContext`** (`models.py`) -- Lightweight context for constructing findings. Holds `rel_path`, `domain`, `discovered_at`, `confidence`, and optional `files`. Provides `finding_id()` to build deterministic IDs from `kind + path parts + suffix`.

**`FindingSpec`** (`scan/findings.py`) -- Declarative specification for a finding: `kind`, `severity`, `summary`, `evidence`, `recommended_action`, `cluster`, `suffix`, `safe_to_autofix`, and optional `details`. Passed to `build_finding()` or `build_document_finding()` to produce a `Finding`.

**`Scorecard`** (`models.py`) -- Aggregate quality score. Contains `overall_score`, `strict_score`, per-`dimensions` scores, per-`domains` `DomainScore` entries, `top_gaps`, `trend` (historical score points), and `rollup` (weighted domain aggregation with critical regressions).

**`PlanState`** (`models.py`) -- Persisted triage/action plan. Contains `lifecycle_stage` (observe/reflect/organize/complete), `current_focus` (finding ID), `ordered_findings`, `clusters` (finding IDs grouped by cluster name), `deferred_items`, `stage_notes`, and `strategy_text`.

**`Config`** (`config.py`) -- Repo-level configuration from `.docgarden/config.yaml`. Controls `strict_score_fail_threshold`, `critical_domains`, `domain_weights`, `block_on` rules, and `pr_drafts` settings.

**`RepoPaths`** (`models.py`) -- Named path bundle: `repo_root`, `state_dir` (`.docgarden/`), `config`, `findings`, `plan`, `score`, `quality`. Every command constructs one via `repo_paths()` in `cli_commands.py`.


## Scan architecture

The scanner uses a two-pass design.

### Pass 1: Document rules (per-file)

Each markdown file is parsed into a `Document`. If the file lacks frontmatter, it gets a `missing-frontmatter` finding and no further rules run. Otherwise, a `DocumentScanContext` is built and each rule in `DOCUMENT_RULES` runs against it.

`DocumentScanContext` carries the parsed `Document`, the current timestamp, `repo_root`, and shared mutable state: `doc_id_counter` (tracks ID uniqueness), `inbound_links` (accumulates which files link to what), and `routed_targets` (accumulates doc-path references from body text).

The document rules tuple, in order:

1. `_metadata_rule` -- checks for missing required metadata fields (`doc_id`, `doc_type`, `domain`, `owner`, `status`, `last_reviewed`, `review_cycle_days`) and invalid status values.
2. `_section_rule` -- checks for required headings based on `doc_type` (canonical, exec-plan, generated, archive each have their own required section list).
3. `_freshness_rule` -- checks if verified docs have exceeded their `review_cycle_days`.
4. `_trust_rule` -- checks if verified canonical docs have `source_of_truth` and `verification` metadata.
5. `_alignment_rule` -- checks source-of-truth artifact existence, validation command validity, generated-doc contract and staleness, and workflow asset references.
6. `_link_rule` -- checks for broken markdown links. Also populates `inbound_links` and `routed_targets` as a side effect for pass 2.

### Pass 2: Repo rules (cross-file)

After all documents have been scanned individually, `REPO_RULES` run against a `RepoScanContext` that has access to all documents and the accumulated link/route maps.

`RepoScanContext` carries `repo_root`, the full `documents` list, `documents_by_rel_path` dict, and the same shared counters/maps from pass 1.

The repo rules tuple, in order:

1. `_duplicate_doc_id_rule` -- flags documents sharing the same `doc_id`.
2. `_broken_route_rule` -- flags route references (inline doc-path mentions) pointing to nonexistent files.
3. `_route_quality_rule` -- flags current-truth routers (AGENTS.md, index.md files) that link to archived, deprecated, or stale docs.
4. `_promotion_rule` -- detects rule-like statements repeated across multiple transient-knowledge docs and suggests promoting them to canonical docs.
5. `_orphan_rule` -- flags docs under `docs/` that receive no inbound links from any scanned document.


## How to add a new detector

### Step 1: Write the finding constructor

Add a function to `docgarden/scan/document_rules.py` (for per-file checks) or create one in `docgarden/scan/alignment.py` or `docgarden/scan/linkage.py` (for cross-file checks). The function constructs a `Finding` using `build_document_finding()`:

```python
# In scan/document_rules.py
from .findings import FindingSpec, build_document_finding

def my_new_finding(document: Document, *, discovered_at: str) -> Finding:
    return build_document_finding(
        document,
        FindingSpec(
            kind="my-new-kind",              # unique kind string
            severity="medium",               # high, medium, or low
            summary=f"{document.rel_path} has a problem.",
            evidence=["Explanation of what was detected."],
            recommended_action="Do this to fix it.",
            safe_to_autofix=False,           # set True if fixers.py can fix it
            cluster="my-cluster",            # groups related findings in the plan
            suffix="my-suffix",              # makes the finding ID unique per file
            details={},                      # optional structured data for fixers
        ),
        domain=document_domain(document),
        discovered_at=discovered_at,
    )
```

### Step 2: Write the rule function

Add a rule function in `scan/scanner.py`. For a document rule it takes `DocumentScanContext` and returns `list[Finding]`:

```python
def _my_new_rule(context: DocumentScanContext) -> list[Finding]:
    if not some_condition(context.document):
        return []
    return [my_new_finding(context.document, discovered_at=context.discovered_at)]
```

For a repo rule it takes `RepoScanContext` instead.

### Step 3: Register the rule

Add it to the appropriate tuple in `scan/scanner.py`:

```python
DOCUMENT_RULES: tuple[DocumentRule, ...] = (
    _metadata_rule,
    _section_rule,
    # ...existing rules...
    _my_new_rule,       # <-- add here
)
```

Or for repo-wide rules:

```python
REPO_RULES: tuple[RepoRule, ...] = (
    _duplicate_doc_id_rule,
    # ...existing rules...
    _my_new_repo_rule,  # <-- add here
)
```

### Step 4: Map the kind to a scoring dimension

In `docgarden/quality.py`, add the kind to `dimension_map` inside `build_scorecard()`:

```python
dimension_map = {
    # ...existing mappings...
    "my-new-kind": "Structure & metadata",  # pick the right dimension
}
```

### Step 5: (Optional) Add autofix support

If `safe_to_autofix=True`, add a handler in `docgarden/fixers.py` inside `apply_safe_fixes()` with a new `elif finding.kind == "my-new-kind":` branch that reads the file, applies the fix, and writes it back with `atomic_write_text()`. Also add a description in `describe_safe_fix()`.

### Step 6: Write tests

Add test cases in `tests/test_docgarden.py`. Create a temp directory with the problematic file structure, call `scan_repo()`, and assert the expected finding kind appears.


## State persistence

### findings.jsonl -- append-only event log

Located at `.docgarden/findings.jsonl`. Each line is a JSON-serialized `FindingRecord` -- a finding snapshot plus `event` (e.g. `"observed"`, `"resolved"`, `"status_changed"`, `"review_imported"`) and `event_at` timestamp.

On each full scan, `append_scan_events()` in `state.py`:
1. Loads the full history.
2. Computes `latest_events_by_id()` -- a dict mapping each finding ID to its most recent `FindingRecord`, using last-write-wins deduplication.
3. For each currently-observed finding: appends an `"observed"` event. If the prior status was `"fixed"` or `"false_positive"`, the finding is reopened. Otherwise the prior status is preserved (so human resolutions like `"accepted_debt"` survive re-observation).
4. For each previously-open mechanical finding no longer observed: appends a `"resolved"` event with status `"fixed"` (auto-resolution).

Manual status changes (`plan resolve`, `plan reopen`) append `"status_changed"` events via `append_finding_status_event()`.

The file only grows. Deduplication happens in memory via `latest_events_by_id()` on every read.

### plan.json -- rebuilt on each full scan

Located at `.docgarden/plan.json`. Rebuilt from scratch by `build_plan()` after each full scan. Contains ordered findings (sorted by severity, with previous ordering preserved), cluster groupings, deferred items, current focus, lifecycle stage, and triage notes.

The previous plan's `current_focus` is sticky -- it survives rebuilds as long as the focused finding is still actionable and at least as severe as the next candidate.

### score.json -- rebuilt on each full scan

Located at `.docgarden/score.json`. Contains the full `Scorecard` -- dimension scores, domain scores, weighted rollup, trend history (last 20 data points), and critical regressions. Rebuilt by `build_scorecard()` and written by `write_score()`.

### Run artifacts

Each full scan writes a snapshot to `.docgarden/runs/<timestamp>/` with `summary.json`, `changed_files.txt`, and `findings.delta.json`.


## Testing

### File locations

- `tests/conftest.py` -- adds the repo root to `sys.path` so test imports resolve.
- `tests/test_docgarden.py` -- core tests for the scan engine, fixers, and finding detection. Uses `tempfile.TemporaryDirectory` to create isolated repo structures with `AGENTS.md`, `docs/`, and frontmatter fixtures.
- `tests/test_cli.py` -- CLI integration tests. Exercises commands via `main(argv)` against temp repos, checks JSON output, and verifies state persistence.
- `tests/test_support_modules.py` -- tests for utility modules (markdown parsing, state operations, etc.).

### Test repo setup pattern

Tests create a temp directory and write markdown files with helper functions:

```python
def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
```

A minimal test repo needs:
- `AGENTS.md` with a route to `docs/index.md`
- `docs/index.md` with full canonical frontmatter and required sections
- Optionally `.docgarden/config.yaml`

Then call `scan_repo(repo_root)` and assert on the returned findings list.

### Running tests

```bash
# from repo root
uv run pytest
uv run pytest tests/test_docgarden.py -v      # specific file
uv run pytest -k "test_name_pattern"           # filter by name
```


## Dependencies

- **Python 3.11+** (uses `from __future__ import annotations`, `match` is not used but `|` union types in annotations require 3.11).
- **PyYAML >= 6.0** -- the only runtime dependency. Used for frontmatter parsing and config loading.
- **No other runtime dependencies.** HTTP calls to GitHub use stdlib `urllib.request`.
- **Build system:** setuptools >= 68 with wheel. Defined in `pyproject.toml`.
- **Test runner:** pytest (configured in `pyproject.toml` under `[tool.pytest.ini_options]`).
- The CLI is installed as the `docgarden` console script via `[project.scripts]` in `pyproject.toml`, pointing at `docgarden.cli:main`.
