# docgarden

`docgarden` is a repo-local maintenance harness for agent-facing documentation.
It scans for stale or malformed docs, writes an honest quality score, persists
findings, and offers a narrow safe-fix path for mechanical hygiene issues.

## Commands

```bash
docgarden scan
docgarden status
docgarden next
docgarden plan
docgarden show FINDING_ID
docgarden quality write
docgarden fix safe --apply
docgarden config show
docgarden doctor
```

## MVP scope

Phase 1 focuses on:

- frontmatter validation
- required section checks
- stale review detection
- duplicate `doc_id` detection
- broken route and internal markdown link checks
- quality scoring and score publication
- append-only findings history and a prioritized plan view

Alignment reviews, domain-specific contradiction detection, and PR automation are
intentionally deferred until later phases.
