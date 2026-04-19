# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start

```bash
uv sync                                      # Install dependencies
uv run python src/agent.py download-files   # Download ML models (first run)
cp .env.example .env.local                  # Add API keys
uv run pytest                               # Run all tests
uv run python src/agent.py console          # Test agent locally
lk agent deploy                             # Deploy to LiveKit Cloud
```

## Key Architecture Concept

**Deterministic/nondeterministic boundary:** The agent has a clear split: `analysis.py` does deterministic Python analysis (unit-tested), and the LLM only narrates results. If data is wrong, look at `analysis.py`. If phrasing is wrong, look at `personas/base.md`. This distinction shapes where bugs live and how to debug.

Tools are @function_tool methods that call deterministic Python and return human-readable strings — the LLM never sees raw JSON. Class-specific tools (get_class_summary, show_class_changes) navigate the browser via RPC as a side effect; aggregate tools (list_classes, get_grade_trend) do not.

## Common Patterns

- **Service calls:** Wrap all external calls (Supabase, git, avatar, TTS) with `ServiceHealth`. Never use bare try/except. See AGENTS.md § "Coding practices for external service calls".
- **Testing:** Unit-test the deterministic layer (`analysis.py`, `date_resolution.py`). Mock the LLM in `test_agent.py` using `judge()`. Always test both happy path and failure path (simulate service outages with `ServiceHealth.mark_failed()`).
- **Personas:** Add a new persona by copying `personas/example/`, adding a config entry, and customizing `persona.md`. No code changes needed — config loads at runtime.
- **Navigation:** If you add a new tool, update the tool list comment in the "Tool design rule" section of AGENTS.md to mark it navigating or non-navigating, and add tests to `test_navigation.py::TestToolNavigationAlignment`.
- **Live testing:** Always run the pre-session checklist in AGENTS.md § "Live session testing protocol". Kill orphaned processes, confirm no cloud agent, verify dispatch routing.

## Full Guidance

**See [AGENTS.md](AGENTS.md)** for complete architecture, environment setup, all commands, testing philosophy, LiveKit documentation, deployment, and detailed coding practices. Start there for questions about system design, implementation decisions, or task context.
