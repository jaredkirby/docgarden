# docgarden

A repo-local maintenance harness for agent-facing documentation. Scans your
`docs/` tree and `AGENTS.md` for stale, broken, or malformed docs, scores
quality honestly across six dimensions, and gives you a prioritized queue of
what to fix — with safe autofix for the mechanical stuff.

## Install

Requires Python 3.11+.

```bash
pip install git+https://github.com/jaredkirby/docgarden.git
```

For development:

```bash
git clone https://github.com/jaredkirby/docgarden.git
cd docgarden
pip install -e .
```

## Quick start

```bash
docgarden scan                  # scan all docs, persist findings and scores
docgarden status                # see active finding count and current score
docgarden next                  # get the highest-priority finding to fix
docgarden fix safe --apply      # auto-fix safe mechanical issues
```

After fixing findings manually:

```bash
docgarden plan resolve FINDING_ID --result fixed
docgarden scan                  # verify and refresh scores
```

## Core workflow

```
scan  ->  plan  ->  fix  ->  rescan
```

`docgarden scan` evaluates every markdown file under `docs/` plus `AGENTS.md`,
persists findings to `.docgarden/findings.jsonl`, computes quality scores, and
builds a prioritized plan. `docgarden next` tells you what to fix. After fixing,
`docgarden plan resolve` records the outcome and `docgarden scan` confirms the
fix landed.

For partial feedback while editing, use `docgarden scan --scope changed` to scan
only files with local git changes. Return to a full scan before treating scores
as authoritative.

## What it checks

- **Frontmatter** — required fields, valid statuses, metadata completeness
- **Structure** — required sections per document type (canonical, exec-plan, etc.)
- **Freshness** — stale reviews on verified docs past their review cycle
- **Links** — broken internal markdown links with replacement suggestions
- **Routing** — broken or stale routes in AGENTS.md and index docs
- **Alignment** — source-of-truth artifacts that don't exist on disk
- **Duplication** — duplicate `doc_id` values across docs
- **Orphans** — docs with no inbound links from routers or other docs
- **Promotion** — repeated rules across transient docs that should be canonical

## Documentation

- [Getting started](docs/getting-started.md) — first-time setup walkthrough
- [Concepts](docs/concepts.md) — findings, scores, plans, domains, document types
- [Command reference](docs/commands.md) — every command with options and examples
- [Configuration](docs/configuration.md) — `.docgarden/config.yaml` reference
- [CI setup](docs/ci-setup.md) — GitHub Actions integration
- [Architecture](docs/architecture.md) — codebase guide for contributors
- [Full spec](docs/design-docs/docgarden-spec.md) — design target (ahead of implementation)
