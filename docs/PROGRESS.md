# Progress Tracker

## Current Branch
`main`

## Last Session Summary
**Date**: 2026-03-31

### Completed Work

**Phases 1-6: Core agent**
- Data layer, agent tools, session init, persona system, deployment
- Hedra avatar + ElevenLabs voice cloning with graceful fallback
- GPT-4.1 LLM, ElevenLabs VoiceSettings for speed/stability
- Persona inheritance: base.md (shared) + persona-specific files
- Dog persona (avatar2) created (not yet deployed)
- Deployed to LiveKit Cloud (us-east, agent ID CA_YAj8JF77hrEM)

**Phase 7: Agent-driven browser navigation**
- Tools auto-navigate browser via LiveKit RPC as side effect of data lookups
- Class tab deep-linking via `?class=` query param
- Date validation with fallback for hallucinated dates
- Standalone `show_in_browser` tool for explicit requests

**Phase 8: User profiles and session memory (partially tested)**
- Supabase: user_profiles, session_history, session_messages with cascading deletes
- Onboarding flow: persona-specific scripts, save_user_profile tool
- Incremental message saving via conversation_item_added event
- Session end summary with structured topic/class extraction
- Stable device_id from frontend localStorage UUID

**Code review and refactoring (completed)**
- Code review: 5 sections, 20+ findings (implemented and removed)
- Priority 1 (navigation): Removed nav from aggregate tools (list_classes, get_recent_changes, get_grade_trend). Simplified show_in_browser. Added debug logging.
- Priority 2 (session memory): Context injection switched from role="assistant" to instructions append. Session summary now extracts topics_discussed and classes_mentioned.
- Priority 3 (frontend): DayDetail useEffect for ?class= param changes. NavigationHandler cleanup on unmount. Error state for token fetch failures.
- Priority 4 (tests): 88 non-LLM tests passing across 4 test files:
  - test_analysis.py: 34 tests (data models, snapshot reader, diff, analysis)
  - test_navigation.py: 19 tests (payloads, date validation, tool alignment, format helpers, timestamps)
  - test_user_store.py: 19 tests (profile CRUD, session history, messages, format methods)
  - test_agent.py: 11 tests (agent behavior with mock_tools — requires LLM API)

**Persona restructuring and PII scrub (completed)**
- Persona subdirectories: `<pseudonym>/persona.md` (gitignored) + `example/` (committed template)
- Config split: `config.json` (committed, no secrets) + `config.local.json` (gitignored, real names + service IDs)
- `base.md` templated with `{{STUDENT_NAME}}`, `{{SCHOOL_NAME}}` — replaced at runtime
- `load_persona()` merges configs and templates placeholders
- Global PII scrub across all committed files (docs, tests, plan)
- Celebrity likeness references removed
- `private/` directory for personal media assets (gitignored)

### Planning completed (in PLAN.md)
- Phase 6b: Multi-provider persona support (LemonSlice)
- Phase 9: iOS app via Capacitor + TestFlight
- Phase 10: Public figure persona test case
- Phase 11: Persona management restructuring (completed — merged into PII scrub work)
- Phase 12: Avatar widget UI redesign

## Uncommitted Changes
- None

## Known Issues
- Hedra avatar returns 500 intermittently — gracefully handled
- GPT-4.1 follows persona catchphrases ~70%
- Onboarding may still batch questions 3 & 4
- Prewarm race condition on data repo clone — mitigated with lock directory
- Phase 8 needs end-user validation (device_id, messages, summaries, returning user profile)
- Agent behavior tests (test_agent.py) fail when LLM API is rate-limited (transient, not code issue)

## Architecture

```
sally-schoolwork (this repo) — Agent backend
  src/agent.py             — 15 tools, persona loading, session lifecycle, navigation
  src/data/analysis.py     — Deterministic analysis (tools call these, LLM narrates)
  src/data/snapshot_reader.py — Local filesystem reader for table-mutation-data clone
  src/data/user_store.py   — Supabase client for profiles and session memory
  src/data/models.py       — Dataclasses for snapshot data
  personas/base.md         — Shared context (templated), onboarding script, guardrails
  personas/config.json     — Per-persona: provider choices, temperature (committed)
  personas/config.local.json — Real names, service IDs (gitignored)
  personas/<pseudonym>/persona.md — Per-persona voice style, catchphrases (gitignored)
  personas/example/persona.md — Template for new personas (committed)
  supabase/schema.sql      — Consolidated database schema
  tests/                   — 88 non-LLM tests + 11 LLM-dependent agent tests

table-mutation-tracker (branch feature/livekit-agent-widget)
  frontend/components/AgentWidget.tsx  — Widget, RPC navigation, device_id
  frontend/app/api/livekit-token/      — Server-side JWT token generation
  frontend/app/day/[date]/DayDetail.tsx — ?class= param, useEffect for tab switching
  frontend/app/day/[date]/page.tsx     — Redirect preserves query params

External services:
  LiveKit Cloud, Supabase, Hedra, ElevenLabs, GitHub (table-mutation-data)
```

## Next Steps (Suggested)
1. New persona: cartoon self-portrait + own ElevenLabs voice clone + LemonSlice avatar (achieves Phase 6b multi-provider dispatch)
2. Provider dispatch refactor in agent.py (avatar_provider/tts_provider per persona)
3. Squash commits and push to public repo (Phase 13 — history contains PII)
4. Phase 9: Capacitor iOS build
5. End-user test Phase 8
