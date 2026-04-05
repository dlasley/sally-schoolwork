# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This project uses `AGENTS.md` as the primary reference. See [AGENTS.md](AGENTS.md) for project conventions, LiveKit documentation access, workflow design, and testing philosophy.

## Critical patterns

**Tools do analysis, LLM narrates.** The 15 `@function_tool` methods in `src/agent.py` call deterministic Python in `src/data/analysis.py` and return human-readable strings. The LLM never processes raw data — it only narrates pre-computed summaries. Do not move analysis logic into instructions or prompts.

**TDD is required for agent behavior.** When modifying instructions, tool descriptions, or adding tools, write failing tests first (`tests/test_agent.py` using `mock_tools`/`judge()`), then iterate until they pass. Never guess what will work.

**Persona config is split across two files.** `personas/config.json` (committed) holds provider choices and temperature. `personas/config.local.json` (gitignored) holds real student/school names and service IDs. Adding a new persona requires only a config entry and a `personas/<name>/persona.md` — no code changes.

**Class-specific tools navigate the browser as a side effect** via LiveKit RPC. Aggregate tools (`list_classes`, `get_recent_changes`, `get_grade_trend`) intentionally do not navigate. Maintain this distinction when adding tools.

**Run tests without API keys** using only the non-LLM test files:
```bash
uv run pytest tests/test_analysis.py tests/test_navigation.py tests/test_user_store.py
```
