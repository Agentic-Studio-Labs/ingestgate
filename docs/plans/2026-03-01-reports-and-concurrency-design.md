# Auto Markdown Reports & LLM Concurrency

**Date:** 2026-03-01
**Status:** Approved

## Problem

1. The CLI only outputs to console by default. The `analyze` command has an opt-in `--report` flag, but users must remember to use it. No other command generates reports.
2. All LLM calls (analyzer and fixer) run sequentially. Processing 73 documents takes 3-6+ minutes for analysis alone, with fixer adding hundreds more serial API calls.

## Design

### Feature 1: Auto Markdown Report (all commands)

**Filename format:** `kb-prep-{command}-{YYYYMMDD-HHMMSS}.md`

**CLI changes:**
- All 4 commands (`score`, `analyze`, `fix`, `upload`) auto-generate a timestamped markdown report in the current working directory.
- Add `--no-report` flag to suppress report generation.
- Remove the existing `--report` flag from `analyze` (replaced by default behavior).
- Print the report file path to console after generation.

**Report content by command:**

| Command | Sections |
|---------|----------|
| score | Score table, issue details (if --detail), summary stats |
| analyze | Scores, content analysis per file, knowledge graph summary, folder recommendation |
| fix | Scores, fix actions per file with descriptions, output paths |
| upload | Full pipeline: scores, fixes, folder structure, upload results with IDs/errors |

**Implementation:**
- Refactor `_write_report` into composable section writers: `_report_scores()`, `_report_analyses()`, `_report_graph()`, `_report_fixes()`, `_report_uploads()`, `_report_recommendations()`.
- Each command assembles the sections it needs.
- All sections return `list[str]` (lines of markdown).

### Feature 2: LLM Call Concurrency

**Concurrency model:** `asyncio` with `AsyncAnthropic` client and `Semaphore(N)`.

**Default concurrency:** 5 (configurable via `--concurrency` flag and `Config.concurrency` field).

**Analyzer changes:**
- Replace `Anthropic` with `AsyncAnthropic` client.
- `analyze()` becomes `async`.
- `_call_with_retry()` becomes `async`, using `await client.messages.create()`.
- `analyze_and_build_graph()` becomes `async`:
  1. Launch all `analyze(doc)` calls via `asyncio.gather()` with semaphore.
  2. After all complete, build graph sequentially (fast, needs shared state).

**Fixer changes:**
- Replace `Anthropic` with `AsyncAnthropic` client.
- `_call_llm()` becomes `async`.
- Individual fix methods (`_fix_dangling_reference`, `_fix_generic_heading`, etc.) become `async`.
- `fix()` becomes `async`. Within a single document, the three phases stay ordered (in-place edits, splits, filename), but individual fix calls within a phase can overlap.
- Cross-document parallelism: CLI calls `asyncio.gather()` over docs with semaphore.

**Config changes:**
- Add `concurrency: int = 5` to `Config` dataclass.
- Add `--concurrency` flag to `analyze`, `fix`, `upload` commands.

**CLI entry points:**
- `score` stays synchronous (no LLM calls).
- `analyze`, `fix`, `upload` use `asyncio.run()` to run their async implementation.

**Rate limiting:**
- Keep existing exponential backoff retry logic in `_call_with_retry` / `_call_llm`.
- The semaphore caps concurrent requests; backoff handles transient 429s.
- On rate limit, only the affected coroutine sleeps; others continue.

## Files Changed

| File | Changes |
|------|---------|
| `config.py` | Add `concurrency: int = 5` field |
| `analyzer.py` | Async rewrite: `AsyncAnthropic`, async methods, semaphore |
| `fixer.py` | Async rewrite: `AsyncAnthropic`, async methods |
| `cli.py` | Auto-report on all commands, `--no-report`/`--concurrency` flags, `asyncio.run()`, refactored report sections |

## Not in Scope

- Concurrent file parsing (fast enough as-is).
- Concurrent uploads (separate enhancement).
- Async for `score` command (no LLM calls).
