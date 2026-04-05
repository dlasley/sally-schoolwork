# Progress Tracker

## Current Branch
`main`

## Last Session Summary
**Date**: 2026-04-05

### Regression fix session (2026-04-05)

**Test coverage added (19 new tests, 107 total non-LLM):**
- `TestResolveDateArithmetic` (8 tests): "last Friday" from Saturday/Friday, "before" with/without ISO date, yesterday, today, last Monday, unresolvable
- `TestAnalysis::test_get_ungraded_*` (4 tests): finds unscored, excludes scored, all classes, none found
- `TestToolNavigationAlignment`: added `get_ungraded_assignments` to non-navigating tools list
- `TestSaveSessionWithSessionId` (2 tests): session_id included/omitted in save_session
- `TestUpdateSessionSummary` (1 test): update called with correct args
- `TestIsPlaceholderSummary` (4 tests): placeholder patterns match, LLM summaries don't, empty string

**Code fixes:**
- Extracted `resolve_relative_date()` as standalone module-level function (was embedded in tool method, untestable)
- Fixed 3 ruff violations: `contextlib.suppress`, unused `times` variable, `asyncio.create_task` reference
- Returning-user greeting now includes name via string interpolation (`f"Hey {user_name}! {greeting}"`)
- Session history context injection strengthened with explicit instruction to reference summaries
- Documented `openai` extra in pyproject.toml (needed for deferred summarization, not reverted STT)
- Suppressed hpack/httpcore/httpx/h2 DEBUG noise in agent.py logging config

**Unified service error detection layer (new):**
- Created `src/service_health.py`: ServiceHealth class with tier-based degradation (CRITICAL/IMPORTANT/OPTIONAL), sync/async call wrappers with timeout, session start gating, context injection for LLM warnings
- 25 tests in `tests/test_service_health.py` covering registration, status tracking, gating logic, sync/async wrappers, timeout behavior, summary output
- Integrated into `agent.py`: git refresh, Supabase client init, profile/session queries, avatar start, deferred summarization all wrapped with health monitor. Session close logs health summary. Service warnings injected into LLM context.
- 132 total non-LLM tests, all passing

**agent.py refactoring:**
- Removed orphaned imports: inline `import re`, `from datetime import date as date_type`, `from datetime import datetime` replaced with module-level imports
- Extracted `_class_not_found()` static method on Assistant, replacing 11 copies of the same error string
- Removed dead `communication_preferences` parameter from `user_store.save_profile()` and `format_profile_context()`, updated tests
- Replaced hardcoded class keyword map in `_save_session_history` with dynamic map built from `SnapshotReader` rolling index
- Decomposed `my_agent()` (was 310+ lines) into 4 extracted helpers: `_build_user_context()`, `_build_data_context()`, `_configure_tts()`, `_start_avatar()`
- Fixed `turn_detection` deprecation: replaced with `turn_handling={"turn_detection": MultilingualModel()}`
- 132 total non-LLM tests, all passing

**Instruction-level fixes (already in uncommitted base.md, need live retest):**
- Onboarding CRITICAL RULE, WRONG/RIGHT Q2 example, show_capabilities instruction
- Bullet point prohibition WRONG/RIGHT examples
- Guardrail redirect for school-system questions
- communication_preferences removed from save_user_profile tool

**Dispatch routing and session crash root cause found (2026-04-05 late night)**

Two compounding issues were masking each other:

1. **Orphaned multiprocessing workers stealing dispatches**: `kill` on the parent `agent.py` process does NOT kill its pre-warmed child workers (they show as `Python -c from multiprocessing.spawn...`, not `agent.py`). These orphans stayed registered with LiveKit Cloud and intercepted all dispatches, making the new agent's terminal show zero logs. Fix: `ps aux | grep multiprocessing | grep -v grep | awk '{print $2}' | xargs kill` before restart.

2. **Deepgram 429 rate limit killing sessions**: The real crash. All those orphaned STT connections burned through Deepgram's rate limit. Each new session: TTS starts the greeting (works), STT tries to connect to Deepgram, gets 429'd, retries 3 times over ~4 seconds, then `AgentSession is closing due to unrecoverable error`. Greeting truncated mid-sentence, session dead.

The `dev` command's log formatting hid the error entirely. Switching to `start` (JSON logs) revealed it immediately once orphans were cleared.

Also suppressed hpack/httpcore/httpx/h2 DEBUG noise that was drowning out agent logs (added to agent.py module-level logging config).

**Deprecation warning noted**: `turn_detection is deprecated and will be removed in v2.0. Use turn_handling=TurnHandlingOptions(...) instead`

**LemonSlice credits exhausted** (email 2026-04-04 10:57 PM) — avatar2/avatar3 have no video. Testing with avatar1 (Hedra) only until credits topped off.

**Next step**: wait for Deepgram rate limit to reset (hours), then run one clean avatar1 test session to verify all code fixes.

### Completed Work (prior sessions)

**Phases 1-6: Core agent**
- Data layer, agent tools, session init, persona system, deployment
- Hedra avatar + ElevenLabs voice cloning with graceful fallback
- GPT-4.1 LLM, ElevenLabs VoiceSettings for speed/stability
- Deployed to LiveKit Cloud (us-east, agent ID CA_YAj8JF77hrEM)

**Phase 7: Agent-driven browser navigation**
- Tools auto-navigate browser via LiveKit RPC as side effect
- Class tab deep-linking via `?class=` query param
- Help page at `/help` with example questions, navigated via `show_capabilities` tool

**Phase 8: User profiles and session memory (partially tested)**
- Supabase: user_profiles, session_history, session_messages with cascading deletes
- Onboarding flow, incremental message saving, session end summary with topic extraction
- Stable device_id from frontend localStorage UUID
- Env var fallbacks for service IDs (voice ID, avatar ID, student name) for deployment

**Phase 13: PII scrub and public repo (completed)**
- Persona restructuring: `base.md` templated with `{{STUDENT_NAME}}`, `{{SCHOOL_NAME}}`, `{{CURRENT_DATE}}`
- Config split: `config.json` (committed) + `config.local.json` (gitignored)
- Persona subdirectories: `persona.md` tracked, media gitignored by extension
- Global PII scrub, gender field removed, gender-neutral pronoun instruction added
- Public repo pushed to GitHub with squashed history

**Code review and refactoring (completed)**
- Code review: 5 sections, 20+ findings (implemented and removed)
- Navigation alignment: removed nav from aggregate tools
- Session memory: context injection via instructions, structured topic extraction
- Frontend: DayDetail useEffect, NavigationHandler cleanup, error state
- 88 non-LLM tests across 4 test files + 11 LLM-dependent agent tests

**New tools added:**
- `get_overall_summary`: meta-tool aggregating all analysis for holistic questions
- `get_deleted_assignments_list`: finds removed assignments across snapshots
- `get_score_changes`: retroactive score modifications (filters initial grading)
- `show_capabilities`: navigates to help page + narrates capabilities

**End-user testing sessions (2026-04-04, 9+ iterations)**

Testing was conducted across two browser devices (device `a4b54517` and `ab0b4d51`) over ~3 hours. Code changes to agent.py and base.md were iterated between sessions, but the local dev agent may not have been restarted between all code changes, meaning some test sessions may have been running stale code. This makes it difficult to determine which iteration of the code produced which behavior. The regression observations below are accurate to what the end user experienced, but the root cause attribution to specific code states should be treated as approximate.

*Session `af9beedf` (device 1, ~03:00 UTC)*: First connection. Onboarding did not trigger at all. User had to ask "Shouldn't there have been some onboarding?" Sally responded with bullet-point lists (violating output rules), used emojis ("Have a great day! :blush:"), and navigated to April 4th (Saturday) when asked for "last Friday." Required multiple user corrections to show the right date. Sally offered a Q4-style communication preferences question when the user asked about onboarding.

*Session `6ed793c3` (device 1, ~03:17 UTC)*: Onboarding triggered but capabilities shown as bullet list before onboarding started. Q2 asked name + relation in one response. Still asked Q4 (brief vs. detailed). "Last Friday" navigated to March 27th instead of April 3rd. User had to correct: "That's not last Friday. Last Friday was April third."

*Session `d2030c64` (device 1, ~03:27 UTC)*: Onboarding still showing capabilities as bullets before questions. STT transcribed "Dave" as "Dev" (STT accuracy issue, not agent logic). Q2+Q3 still not cleanly separated. "Last Friday" again resolved to March 27th instead of April 3rd. "Compare to Friday before" also broken. User gave up on comparison: "No. Never mind."

*Session `78950ee3` (device 1, ~03:42 UTC)*: Onboarding improved: Q1/Q2/Q3 asked individually. Still asked Q4 (brief vs. detailed). "Last Friday" still navigated to March 27th. User again corrected: "You're showing me March twenty seventh. I asked for last Friday. It's April third." After explicit date correction, comparison between April 3rd and March 27th worked correctly.

*Session `6498e922` (device 1, ~04:12 UTC)*: Onboarding Q1/Q2/Q3 individual. Q4 still asked. show_capabilities called (help page opened). "Last Friday" resolved correctly to April 3rd. "Compare to the Friday before" broken: both dates resolved to April 3rd. User had to manually specify "March twenty seventh."

*Session `903c8c97` (device 2, ~04:37 UTC)*: The comprehensive regression session. Q2+Q3 batched ("Are you the student, a parent, or someone else? And is there anything in particular you care most about?"). "How do they detect grades?" got a long lecture about how school grading systems work instead of a redirect. Deleted assignments listed with bullet dashes. "Highest value assignments not yet graded" returned false negative ("no incomplete assignments"). User pushed back repeatedly ("So there is at least one ungraded assignment." / "In fact, Arthur, multiple ungraded assignments currently in English.") before agent acknowledged the data. show_capabilities not called after onboarding.

*Sessions `82810dd9`, `f3bc1abc`, `f0846a47`, `142ba50c` (~05:06-05:23 UTC)*: STT provider migration attempts. These are 1-message sessions where the greeting played but the agent never responded to voice input. These correspond to the OpenAI STT experiment.

*Session `2648f374` (device 2, ~05:57 UTC)*: Post-revert to Deepgram. Voice working again. Deferred summarization confirmed: this session later received an LLM-generated summary.

*Session `a514363f` (device 2, ~04:46 UTC)*: Returning user test. "What did we talk about last time?" returned "I don't have access to your previous conversations" despite session_history rows existing. Session history context injection not working for this session.

*Session `eabe204a` (device 2, ~05:57 UTC)*: Short returning-user test. Agent did not use the user's name in greeting despite profile existing.

**Testing methodology corrected**
- Root cause of many previously unexplained test failures identified: deployed LiveKit Cloud agent (CA_YAj8JF77hrEM) was intercepting all dispatches instead of local dev worker
- Cloud agent has been deleted; local dev worker now receives all dispatches
- Protocol going forward: run `lk agent list` before any local dev test session to confirm no conflicting deployed agent
- **Critical**: always restart the local dev agent (`uv run python src/agent.py dev`) after making code changes before testing. The dev server does not hot-reload.

**STT provider migration attempt (reverted)**
- Switched to `openai_plugins.STT(model="gpt-4o-transcribe")` to avoid Deepgram inference rate limits
- OPENAI_API_KEY was missing from .env.local, causing silent session failures (entrypoint exception, no greeting)
- After adding key: greeting worked but agent never responded to subsequent user voice -- STT transcribed but MultilingualModel turn detection did not trigger
- Reverted to `inference.STT(model="deepgram/nova-3", language="multi")`
- Deepgram 429s were caused by rapid-fire test sessions, not regular usage; acceptable for now

**Phase 8 partially confirmed (2026-04-05)**
- session_history writes confirmed: close handler fires correctly per-session
- Deferred summarization confirmed: session 2648f374 received LLM-generated summary
- Session history context injection for returning users: NOT confirmed working (session a514363f returned "I don't have access to your previous conversations")
- OPENAI_API_KEY added to .env.local (required by _upgrade_session_summary)

### Planning completed (in docs/PLAN.md)
- Phase 6b: Multi-provider persona support (LemonSlice)
- Phase 6c: Cartoon self-portrait persona (demo-ready)
- Phase 9: iOS app via Capacitor + TestFlight
- Phase 10: Public figure persona test case
- Phase 11: Persona management (completed — merged into PII scrub)
- Phase 12: Avatar widget UI redesign

## Uncommitted Changes (safe to commit)
- `src/agent.py` — major refactor: extracted `resolve_relative_date()`, `_build_user_context()`, `_build_data_context()`, `_configure_tts()`, `_start_avatar()`, `_class_not_found()` helper. ServiceHealth integration. Dynamic class keywords from rolling index. `turn_handling` deprecation fix. Greeting name interpolation. Session history context strengthening. Suppressed hpack/httpcore debug noise. Deferred summarization, get_ungraded_assignments tool, synchronous close handler.
- `src/service_health.py` — new: unified service health monitor (CRITICAL/IMPORTANT/OPTIONAL tiers)
- `src/data/analysis.py` — `get_ungraded_assignments(reader, slug)`: finds assignments with no score entered, sorted by point value
- `src/data/user_store.py` — `save_session` optional `session_id` param; `update_session_summary` method; removed dead `communication_preferences` parameter and formatting
- `supabase/schema.sql` — `session_id text unique` column added to `session_history`
- `supabase/migrations/001_session_history_session_id.sql` — migration (already run on live DB)
- `personas/base.md` — onboarding CRITICAL RULE, Q2 example, show_capabilities instruction, bullet point rule, guardrail redirect
- `pyproject.toml` — added openai extra with comment (needed for AsyncOpenAI in deferred summarization)
- `tests/test_navigation.py` — 12 new tests (resolve_date arithmetic, placeholder summary, alignment update)
- `tests/test_analysis.py` — 4 new tests (get_ungraded_assignments)
- `tests/test_user_store.py` — 3 new tests (session_id, update_session_summary); removed communication_preferences from test data
- `tests/test_service_health.py` — new: 25 tests for service health
- `.env.local` — OPENAI_API_KEY added (required for deferred summarization)

## Known Issues

### CONFIRMED RESOLVED
- **session_history not writing**: `session.once("close", ...)` synchronous close handler confirmed working -- rows written per-session on disconnect
- **Deferred summarization**: `asyncio.to_thread()` wrapping confirmed working -- session 2648f374 received LLM-generated summary
- **Cloud agent blocking local dev**: CA_YAj8JF77hrEM deleted. Local dev worker receives dispatches correctly.

### OpenAI STT incompatible with MultilingualModel (attempted, reverted)
**Symptom**: Greeting delivered successfully; user speech transcribed (session_messages written) but agent never responded. MultilingualModel turn detection did not trigger.
**Root cause hypothesis**: `openai_plugins.STT(model="gpt-4o-transcribe")` does not provide the streaming ASR tokens or confidence metadata that MultilingualModel expects for end-of-turn detection.
**Also observed**: One session (82810dd9) produced no greeting and no session_history row -- silent exception during entrypoint, likely from a transient STT init failure.
**Status**: Reverted to `inference.STT(model="deepgram/nova-3", language="multi")`. If direct OpenAI STT is needed in future, use a VAD-only turn detector (`silero.VAD` without MultilingualModel) or investigate whether `gpt-4o-transcribe` supports the expected streaming format.
**Deepgram 429s**: Were caused by rapid-fire test sessions, not regular usage. Not a concern for normal use. Alternative: `inference.STT(model="assemblyai/u3-rt-pro")` if rate limits recur.

### Onboarding issues (fixes in code, testing status uncertain)
Note: because the local dev agent may not have been restarted between code changes during the 2026-04-04 testing session, it is unclear which sessions tested the pre-fix or post-fix code. All items below need clean retesting with a confirmed fresh agent restart.
- **Q2+Q3 batching**: Observed in sessions 903c8c97 (Q2+Q3 in one response), 6ed793c3, d2030c64. Fix in current base.md: CRITICAL RULE + WRONG/RIGHT Q2 example. Status: needs clean retest.
- **Q4 still asked**: Observed in sessions 6ed793c3, 78950ee3, 6498e922 (asked "brief or detailed?" after Q3). Fix: removed `communication_preferences` from `save_user_profile` tool params. Status: needs clean retest.
- **show_capabilities not called after onboarding**: Observed in session 903c8c97. Worked in session 6498e922 (help page opened). Fix in current base.md explains tool opens browser. Status: partially working, needs clean retest.
- **Capabilities shown as bullet list**: Observed in sessions 6ed793c3, d2030c64 -- Sally listed capabilities as bullets before/during onboarding instead of speaking naturally.

### Date resolution issues (fixes in code, testing status uncertain)
- **"Last Friday" resolved to wrong date**: Observed in sessions af9beedf (navigated to April 4th Saturday), 6ed793c3/d2030c64/78950ee3 (resolved to March 27th instead of April 3rd). Worked correctly in session 6498e922. Fix: reference date extraction in resolve_date. Status: worked in at least one session, needs clean retest.
- **"The Friday before" broken**: Observed in session 6498e922 (both dates resolved to April 3rd). Fix: "before" keyword adds extra_weeks offset. Status: needs clean retest.

### Tool behavior issues (fixes in code, testing status uncertain)
- **Ungraded assignments false negative**: Observed in session 903c8c97 -- agent said "no incomplete assignments" when English had multiple ungraded items. User had to push back three times before agent acknowledged. Fix: `get_ungraded_assignments` tool added in current agent.py. Status: needs clean retest.
- **Bullet points from tool output**: Observed in sessions af9beedf, 6ed793c3, 903c8c97. Fix: WRONG/RIGHT rule in current base.md. Status: needs clean retest.
- **Out-of-scope school questions**: Observed in session 903c8c97 ("How do they detect grades?" got a long lecture). Fix: guardrail redirect in current base.md. Status: needs clean retest.

### Session history / returning user issues
- **Session history not injected for returning users**: Observed in session a514363f -- "What did we talk about last time?" returned "I don't have access to your previous conversations" despite session_history rows existing in Supabase. Root cause unknown. Needs investigation.
- **Returning user greeting doesn't use name**: Observed in session eabe204a. `session.say(greeting)` hardcoded. Attempted fix via `generate_reply` caused regression. Alternative: string interpolation into greeting.

### Minor
- **Hedra avatar returns 500 intermittently**: Gracefully handled.
- **Session memory race condition**: If new session starts within ~10 seconds of previous session ending, close handler write may not complete before new session queries recent sessions. Low priority -- only affects back-to-back sessions.
- **GPT-4.1 follows persona catchphrases ~70%**: Known.
- **`.gitignore` and `lk agent deploy` tension**: Gitignored files excluded from deploy build context. Workaround: env var fallbacks. Needs systematic review.
- **STT transcription accuracy**: "Dave" transcribed as "Dev" in session d2030c64. User had to spell it out. STT-level issue, not agent logic.

## Architecture

```
sally-schoolwork (this repo) — Agent backend
  src/agent.py             — 15 tools, persona loading, session lifecycle, navigation
  src/data/analysis.py     — Deterministic analysis (tools call these, LLM narrates)
  src/data/snapshot_reader.py — Local filesystem reader for table-mutation-data clone
  src/data/user_store.py   — Supabase client for profiles and session memory
  src/data/models.py       — Dataclasses for snapshot data
  personas/base.md         — Shared context (templated), onboarding script, guardrails
  personas/config.json     — Per-persona provider choices, temperature (committed)
  personas/config.local.json — Real names, service IDs (gitignored)
  personas/<pseudonym>/persona.md — Per-persona voice style, catchphrases (tracked)
  personas/example/persona.md — Template for new personas (committed)
  supabase/schema.sql      — Consolidated database schema
  tests/                   — 88 non-LLM tests + 11 LLM-dependent agent tests

table-mutation-tracker (branch feature/livekit-agent-widget)
  frontend/components/AgentWidget.tsx  — Widget, RPC navigation, device_id
  frontend/app/api/livekit-token/      — Server-side JWT token generation
  frontend/app/day/[date]/DayDetail.tsx — ?class= param, useEffect for tab switching
  frontend/app/day/[date]/page.tsx     — Redirect preserves query params
  frontend/app/help/page.tsx           — Capabilities/help page

External services:
  LiveKit Cloud, Supabase, Hedra, ElevenLabs, GitHub (table-mutation-data)
```

## Next Steps
1. **Resolve dispatch routing issue** — kill all agent processes, wait 30s, restart, test avatar1 (Hedra) only. If dispatches still don't reach the terminal process, investigate LiveKit Cloud worker registration state.
2. **Test behavior fixes** (onboarding, guardrails, bullets, ungraded tool) — all code fixes in place, need clean live test with confirmed-working dispatch routing.
3. **Commit outstanding changes** — agent.py, base.md, analysis.py, user_store.py, supabase files, new tests
4. **Unified service error layer** — see [SERVICE_LAYER_PLAN.md](SERVICE_LAYER_PLAN.md). Wrap all remote calls (STT, LLM, TTS, avatar, Supabase, git, RPC) with consistent health tracking, tier-based degradation, and session start gating. Priority: before next deploy.
5. **Re-deploy to LiveKit Cloud** — deleted CA_YAj8JF77hrEM; redeploy with new code + service layer for persistent non-dev usage
6. **Top off LemonSlice credits** — then test avatar2/avatar3 personas
7. Phase 6c: Cartoon self-portrait persona + LemonSlice + provider dispatch refactor
8. Phase 9: Capacitor iOS build

### Testing checklist (clean retest required)
**Protocol**: restart `uv run python src/agent.py dev` before each test. Run `lk agent list` to confirm no cloud agent. Use a fresh device_id (clear localStorage) for onboarding tests.

Onboarding (new user):
- [ ] Q1 asks name only (no relation, no priorities in same response)
- [ ] Q2 asks relation only (no priorities in same response)
- [ ] Q3 asks priorities only (no Q4 about communication preferences)
- [ ] No Q4 asked at all (communication_preferences removed from save_user_profile)
- [ ] show_capabilities tool called after Q3 answered (help page opens in browser)
- [ ] Capabilities described as natural sentences, not bullet lists

Returning user:
- [ ] Greeting uses the user's name from profile
- [ ] Session history context injected ("What did we talk about last time?" returns prior session info)
- [ ] Deferred summary upgrade: placeholder summary replaced by LLM-generated one on next session

Date resolution:
- [ ] "Last Friday" resolves to April 3rd (not March 27th, not April 4th Saturday)
- [ ] "The Friday before" (relative to April 3rd) resolves to March 27th
- [ ] "Compare April 3rd to the Friday before" produces correct two-date comparison
- [ ] Browser navigates to correct date (URL matches spoken date)

Tool behavior:
- [ ] "What's not graded?" / "ungraded assignments" returns actual ungraded items (not false negative)
- [ ] Deleted assignments narrated as natural sentences, not bullet-dash lists
- [ ] "How do grades work?" / out-of-scope school questions get redirect, not lecture
- [ ] Tool output in general narrated conversationally (no markdown, no lists, no emojis)
