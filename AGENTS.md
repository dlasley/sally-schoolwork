# AGENTS.md

A LiveKit voice/text agent ("Sally") that answers questions about a student's grades and assignments. The user is the student's parent. The agent reads snapshot data from a local clone of `dlasley/table-mutation-data` (private repo of daily SIS portal scrapes). The frontend widget lives in a separate repo (`table-mutation-tracker`, branch `feature/livekit-agent-widget`).

## Project structure

This Python project uses the `uv` package manager. Always use `uv` to install dependencies, run the agent, and run tests.

### Architecture

- **Tools do the analysis, LLM narrates.** 15 `@function_tool` methods call deterministic Python in `src/data/analysis.py`. The LLM never sees raw JSON — it receives pre-computed human-readable summaries.
- **Local data, not API.** The `table-mutation-data` repo is cloned at prewarm and git-pulled per session. All snapshot reads are filesystem I/O.
- **Browser navigation.** Class-specific tools auto-navigate the browser via LiveKit RPC as a side effect. Aggregate tools (list_classes, get_recent_changes, get_grade_trend) do not navigate.
- **Persona inheritance.** `personas/base.md` (shared, templated) is concatenated with a persona-specific `persona.md` in a subdirectory at load time. `config.json` (committed) defines provider choices; `config.local.json` (gitignored) holds real names and service IDs. New personas: copy `personas/example/`, customize, add config entry.
- **Avatar and voice are optional.** If avatar/voice IDs are null in `config.local.json`, the agent falls back to Cartesia TTS and no avatar.
- **User profiles.** Stored in Supabase. New users go through a persona-specific onboarding flow. Returning users get profile and session history injected into instructions.

### Key files

- `src/agent.py` — Entrypoint. Persona loading, 15 `@function_tool` methods, `_navigate_browser` RPC helper, `SessionData` with `SnapshotReader` + `UserStore`, prewarm (clones data repo), session init (git pull, profile check, onboarding, Hedra avatar, ElevenLabs or Cartesia TTS), session end summary callback.
- `src/data/analysis.py` — Deterministic analysis: diff, summarize, trends, flags, categories. All return human-readable strings.
- `src/data/snapshot_reader.py` — Reads JSON snapshots from local clone. Fuzzy class name resolution via `resolve_slug()`.
- `src/data/user_store.py` — Supabase client for user profiles, session history, and incremental message saving.
- `src/data/models.py` — Dataclasses: `Assignment`, `ClassMetadata`, `RollingIndex`, etc. with `from_dict()` parsers.
- `personas/base.md` — Shared context (templated with `{{STUDENT_NAME}}` etc.), onboarding script, guardrails.
- `personas/config.json` — Per-persona provider choices, temperature (committed, no secrets).
- `personas/config.local.json` — Real student name, school, service IDs (gitignored).
- `personas/<name>/persona.md` — Per-persona voice style and catchphrases (gitignored).
- `personas/example/persona.md` — Template for creating new personas (committed).
- `supabase/schema.sql` — Consolidated database schema (user_profiles, session_history, session_messages).
- `tests/test_agent.py` — 11 agent behavior tests using `mock_tools` and `judge()` (requires LLM API).
- `tests/test_analysis.py` — 34 data layer unit tests using temp directories with synthetic snapshots.
- `tests/test_navigation.py` — 19 navigation tests: payloads, date validation, tool alignment, format helpers.
- `tests/test_user_store.py` — 19 UserStore tests with mocked Supabase client.

### Environment variables

Set in `.env.local` (local) and as LiveKit Cloud secrets (deployed):

- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` — LiveKit Cloud
- `DATA_REPO_URL` — Git URL for table-mutation-data (include token for private repo)
- `HEDRA_API_KEY` — Hedra avatar
- `ELEVEN_API_KEY` — ElevenLabs TTS/voice cloning
- `SUPABASE_URL`, `SUPABASE_KEY` — Supabase (user profiles and session memory)

### Deployment

`lk agent deploy` builds and deploys to LiveKit Cloud. Persona files are baked into the Docker image — changes to `personas/` require a redeploy. The Dockerfile installs `git` for runtime data repo cloning.

### Formatting

Ruff: 88-char line length, double quotes, space indent. `uv run ruff check` and `uv run ruff format`.

## Commands

```bash
# Install dependencies
uv sync

# Download required models (Silero VAD, turn detector) — run before first use
uv run python src/agent.py download-files

# Run agent in console mode (speak directly in terminal)
uv run python src/agent.py console

# Run agent for frontend/telephony connections
uv run python src/agent.py dev

# Run all tests
uv run pytest

# Run a single test
uv run pytest tests/test_agent.py::test_offers_assistance

# Lint and format
uv run ruff check
uv run ruff format

# Deploy to LiveKit Cloud
lk agent deploy

# Check deployment status
lk agent status

# Tail runtime logs (streams, ctrl+c to stop)
lk agent logs
```

## LiveKit Documentation

LiveKit Agents is a fast-evolving project, and the documentation is updated frequently. You should always refer to the latest documentation when working with this project. For your convenience, LiveKit offers both a CLI and an MCP server that can be used to browse and search its documentation. If the developer has not yet installed the CLI, you should recommend that they install it.

### LiveKit CLI

The [LiveKit CLI](https://docs.livekit.io/intro/basics/cli/) `lk docs` subcommand gives full access to LiveKit documentation from the terminal. Requires CLI version 2.15.0+. Check with `lk --version`.

Install or update the CLI:

- **macOS:** `brew install livekit-cli` (update: `brew update && brew upgrade livekit-cli`)
- **Linux:** `curl -sSL https://get.livekit.io/cli | bash`
- **Windows:** `winget install LiveKit.LiveKitCLI` (update: `winget upgrade LiveKit.LiveKitCLI`)

Run `lk docs --help` to see all available commands. Key commands: `lk docs overview`, `lk docs search`, `lk docs get-page`, `lk docs code-search`, `lk docs changelog`, `lk docs submit-feedback`. Run `lk docs <command> --help` before using a command for the first time, as the help text includes advice on usage and interpreting results. Prefer browsing (`overview`, `get-page`) over search, and prefer `search` over `code-search`, as docs pages are more up-to-date and provide better context than raw code.

### LiveKit Docs MCP Server

For deeper IDE integration, LiveKit also offers an [MCP server](https://docs.livekit.io/reference/developer-tools/docs-mcp/) with the same documentation access. It uses Streamable HTTP transport at `https://docs.livekit.io/mcp`. Refer to your IDE's documentation for how to add it.

### Submit docs feedback to LiveKit

If you use the LiveKit CLI or MCP Server to search or browse documentation, also submit constructive feedback to LiveKit with `lk docs submit-feedback` or the MCP `submit_docs_feedback` tool. Add this to your to-do list when planning work, to ensure you file feedback after completing your other tasks. Useful feedback includes incomplete documentation, broken examples, missing steps or any other documentation gap or issue.

## Handoffs and tasks ("workflows")

Voice AI agents are highly sensitive to excessive latency. For this reason, it's important to design complex agents in a structured manner that minimizes the amount of irrelevant context and unnecessary tools included in requests to the LLM. LiveKit Agents supports handoffs (one agent hands control to another) and tasks (tightly-scoped prompts to achieve a specific outcome) to support building reliable workflows. You should make use of these features, instead of writing long instruction prompts that cover multiple phases of a conversation.  Refer to the [documentation](https://docs.livekit.io/agents/build/workflows/) for more information.

## Testing

When possible, add tests for agent behavior. Read the [documentation](https://docs.livekit.io/agents/start/testing/), and refer to existing tests in the `tests/` directory.  Run tests with `uv run pytest`.

Important: When modifying core agent behavior such as instructions, tool descriptions, and tasks/workflows/handoffs, never just guess what will work. Always use test-driven development (TDD) and begin by writing tests for the desired behavior. For instance, if you're planning to add a new tool, write one or more tests for the tool's behavior, then iterate on the tool until the tests pass correctly. This will ensure you are able to produce a working, reliable agent for the user.

## LiveKit CLI

Beyond documentation access, the LiveKit CLI (`lk`) supports other tasks such as managing SIP trunks for telephony-based agents. Run `lk --help` to explore available commands.

## Related docs

- [PLAN.md](docs/PLAN.md) — Full implementation plan, provider decisions, example use cases
- [AVATAR_PROVIDERS.md](docs/AVATAR_PROVIDERS.md) — Avatar and voice provider research and comparison
- [PROGRESS.md](docs/PROGRESS.md) — Session progress and next steps
