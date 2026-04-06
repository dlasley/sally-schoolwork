# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See [AGENTS.md](AGENTS.md) for full project conventions, LiveKit documentation access, workflow design, and testing philosophy.

## Commands

```bash
uv sync                                          # Install dependencies
uv run python src/agent.py download-files         # Download VAD/turn-detector models (first use)
uv run python src/agent.py dev                    # Run agent for frontend connections
uv run python src/agent.py console                # Run agent in terminal console mode
uv run pytest tests/test_analysis.py tests/test_navigation.py tests/test_user_store.py tests/test_service_health.py  # Non-LLM tests (no API keys needed)
uv run pytest tests/test_agent.py                 # LLM-dependent agent behavior tests (needs API keys)
uv run pytest tests/test_analysis.py::TestAnalysis::test_grade_trend  # Single test
uv run ruff check && uv run ruff format           # Lint and format (88-char, double quotes, space indent)
lk agent deploy                                   # Deploy to LiveKit Cloud
lk agent status                                   # Check deployment
lk agent logs                                     # Tail runtime logs
```

## Critical patterns

**Tools do analysis, LLM narrates.** The `@function_tool` methods in [agent.py](src/agent.py) call deterministic Python in [analysis.py](src/data/analysis.py) and return human-readable strings. The LLM never processes raw data — it only narrates pre-computed summaries. Do not move analysis logic into instructions or prompts.

**TDD is required for agent behavior.** When modifying instructions, tool descriptions, or adding tools, write failing tests first (`tests/test_agent.py` using `mock_tools`/`judge()`), then iterate until they pass. Never guess what will work.

**Persona config is split across two files.** `personas/config.json` (committed) holds provider choices and temperature. `personas/config.local.json` (gitignored) holds real student/school names and service IDs. Adding a new persona requires only a config entry and a `personas/<name>/persona.md` — no code changes.

**Class-specific tools navigate the browser as a side effect** via LiveKit RPC. Aggregate tools (`list_classes`, `get_recent_changes`, `get_grade_trend`) intentionally do not navigate. Maintain this distinction when adding tools.

**Session close handler is synchronous.** `_save_session_history()` uses blocking Supabase calls (no async) because it fires from `session.once("close")` where the event loop may be shutting down. LLM-powered summary upgrade happens later via `_upgrade_session_summary()` at the next session start.

**Date resolution uses a reference date.** `resolve_relative_date()` is a standalone function (not embedded in a tool method) that extracts ISO dates from descriptions (e.g. "the Friday before 2026-04-03") and computes relative days from that anchor, not just today. The "before" keyword adds an extra week offset.

**All remote service calls go through `ServiceHealth`.** The `ServiceHealth` class in `src/service_health.py` wraps every external call (Supabase, git, avatar, summarizer) with consistent error logging, tier-based degradation, and session start gating. When adding a new external dependency, register it with a tier and use `health.check_service()` or `health.check_service_sync()` — never bare try/except.

**Use `start` not `dev` for debugging.** `uv run python src/agent.py start` produces full JSON logs in the terminal. The `dev` command uses a file watcher that spawns child processes whose logs may not appear. Always kill orphaned multiprocessing workers before restarting: `ps aux | grep "agent.py\|multiprocessing" | grep -v grep | awk '{print $2}' | xargs kill 2>/dev/null`.

**Follow the live testing protocol and coding practices in AGENTS.md.** The "Testing" section contains a mandatory pre-session checklist and coding rules for external service calls. These exist because silent failures in remote calls and orphaned processes have caused repeated multi-hour debugging sessions.

**Class list is dynamic, not hardcoded.** The class list in the LLM's context comes from the rolling index at session start (via `_build_data_context()`). There is no static class list in `base.md` — it was removed to avoid conflicting with the dynamic source. If classes change, the agent picks them up automatically from snapshot data. Teacher names are also dynamic via tools.

## Progress and planning

**`docs/PROGRESS.md` is the single living document** for both progress tracking and forward-looking plans. Update it before commits and during long sessions per the global CLAUDE.md directive. When completing or modifying a planned feature, update the relevant section in PROGRESS.md.

**`docs/PLAN.md` is a historical planning document** from initial development. Do not update it with new plans — use PROGRESS.md instead. PLAN.md is kept for reference on original design intent and provider research.
