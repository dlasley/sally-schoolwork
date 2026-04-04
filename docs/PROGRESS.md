# Progress Tracker

## Current Branch
`main`

## Last Session Summary
**Date**: 2026-04-04

### Completed Work

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

### Planning completed (in docs/PLAN.md)
- Phase 6b: Multi-provider persona support (LemonSlice)
- Phase 6c: Cartoon self-portrait persona (demo-ready)
- Phase 9: iOS app via Capacitor + TestFlight
- Phase 10: Public figure persona test case
- Phase 11: Persona management (completed — merged into PII scrub)
- Phase 12: Avatar widget UI redesign

## Uncommitted Changes
- `personas/base.md` — added `{{CURRENT_DATE}}` template
- `src/agent.py` — env var fallbacks for service IDs, current date injection

## Known Issues
- Hedra avatar returns 500 intermittently — gracefully handled
- GPT-4.1 follows persona catchphrases ~70%
- Onboarding may still batch questions 3 & 4
- Phase 8 needs end-user validation
- `.gitignore` and `lk agent deploy` tension: deploy excludes gitignored files from build context. Workaround: env var fallbacks for service IDs. Needs systematic review.

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
1. Phase 6c: Cartoon self-portrait persona + LemonSlice + provider dispatch refactor
2. Commit and push outstanding changes
3. Phase 9: Capacitor iOS build
4. End-user test Phase 8
