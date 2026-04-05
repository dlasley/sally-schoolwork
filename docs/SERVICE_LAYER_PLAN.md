# Unified Service Error Detection Layer

## Problem

Remote service calls in `agent.py` have inconsistent error handling. Some are in try/except blocks, some crash the session silently, some fail in background tasks with no visibility. During the 2026-04-04/05 testing sessions, LemonSlice credit exhaustion, Deepgram 429s, and OpenAI STT incompatibility all manifested identically (greeting plays, agent goes silent) with no distinguishing signal. Debugging required hours of CSV analysis instead of reading a log.

## Current state: 30+ remote calls, 6 error handling patterns

| Pattern | Example | Count | Problem |
|---------|---------|-------|---------|
| No handling | `inference.STT(...)`, `user_store.get_profile()` | ~12 | Crashes session with no useful error |
| try/except + logger.exception | Avatar init, save_session | ~6 | Logged but user/operator has no visibility |
| try/except + continue | git pull timeout | ~2 | Silently uses stale data |
| Background task + try/except | Deferred summarization | ~2 | Fails invisibly in fire-and-forget task |
| Event handler + try/except | save_message | ~1 | Individual data loss goes unnoticed |
| Timeout specified | git clone (60s), git pull (30s), RPC (5s) | 3 | Only 3 of 30+ calls have timeouts |

## Design: `ServiceHealth` monitor

A single module (`src/service_health.py`) that:

1. **Wraps** every external call with consistent logging, timeout, and error classification
2. **Tracks** service status (healthy/degraded/down) per provider
3. **Reports** aggregate health at session start and on status change
4. **Degrades gracefully** with defined fallback behavior per service tier

### Service tiers

| Tier | Services | On failure |
|------|----------|------------|
| **Critical** (session cannot function) | STT, LLM, TTS | Log error, refuse to start session, report to user: "I'm having trouble connecting right now" |
| **Important** (session degraded) | Supabase (profile, sessions), git pull | Log warning, continue with reduced functionality, note what's missing |
| **Optional** (session unaffected) | Avatar (Hedra, LemonSlice), RPC navigation, deferred summarization | Log info, continue normally |

### Core API

```python
# src/service_health.py

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger("service_health")

class ServiceStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"

class ServiceTier(Enum):
    CRITICAL = "critical"    # STT, LLM, TTS
    IMPORTANT = "important"  # Supabase, git
    OPTIONAL = "optional"    # Avatar, RPC, background tasks

@dataclass
class ServiceState:
    name: str
    tier: ServiceTier
    status: ServiceStatus = ServiceStatus.HEALTHY
    last_error: str | None = None
    last_check: datetime | None = None
    failure_count: int = 0

class ServiceHealth:
    """Tracks health of all external services for one agent session."""

    def __init__(self):
        self._services: dict[str, ServiceState] = {}

    def register(self, name: str, tier: ServiceTier) -> None:
        self._services[name] = ServiceState(name=name, tier=tier)

    def mark_healthy(self, name: str) -> None: ...
    def mark_failed(self, name: str, error: Exception) -> None: ...

    def can_start_session(self) -> tuple[bool, list[str]]:
        """Check if all critical services are healthy. Returns (ok, reasons)."""
        ...

    def session_warnings(self) -> list[str]:
        """List of degraded/down important services for context injection."""
        ...

    async def check_service(self, name: str, coro, timeout: float = 10.0):
        """Run an async call with timeout, update health status, return result or None."""
        ...

    def check_service_sync(self, name: str, fn, *args, timeout: float = 10.0):
        """Run a sync call with timeout, update health status, return result or None."""
        ...
```

### Usage in agent.py

```python
# Session initialization
health = ServiceHealth()
health.register("stt", ServiceTier.CRITICAL)
health.register("llm", ServiceTier.CRITICAL)
health.register("tts", ServiceTier.CRITICAL)
health.register("supabase", ServiceTier.IMPORTANT)
health.register("git", ServiceTier.IMPORTANT)
health.register("avatar", ServiceTier.OPTIONAL)
health.register("rpc", ServiceTier.OPTIONAL)
health.register("summarizer", ServiceTier.OPTIONAL)

# Before session start — check critical services
user_store = health.check_service_sync("supabase", get_supabase_client)
profile = health.check_service_sync("supabase", user_store.get_profile, device_id)

# Avatar — optional, failures don't block
await health.check_service("avatar", avatar.start(session, room=ctx.room))

# Before session.start() — gate on critical services
ok, reasons = health.can_start_session()
if not ok:
    await session.say("I'm having trouble connecting right now. Please try again in a moment.")
    logger.error("Session blocked: %s", reasons)
    return

# Inject health warnings into instructions
warnings = health.session_warnings()
if warnings:
    context_parts.append("## Service status\n" + "\n".join(warnings))
```

### Provider registry (future-proof)

New providers (avatar, voice, STT, TTS) register with a tier and the health monitor handles the rest. No per-provider error handling code scattered through agent.py.

```python
# Adding a new avatar provider requires zero error handling code:
health.register("new_avatar_provider", ServiceTier.OPTIONAL)
await health.check_service("new_avatar_provider", new_provider.start(...))
# Health monitor logs, tracks, and degrades automatically
```

### What this catches that current code doesn't

| Scenario | Current behavior | With ServiceHealth |
|----------|-----------------|-------------------|
| LemonSlice credits exhausted | Avatar fails silently, session may break | Logged as OPTIONAL/DOWN, session continues, operator alerted |
| Deepgram 429 | STT init fails, session crashes with no useful log | Logged as CRITICAL/DOWN, session refuses to start with user-facing message |
| Supabase unreachable | Session crashes during profile fetch | Logged as IMPORTANT/DOWN, session continues without profile/history |
| OpenAI API key missing | Deferred summarization silently fails | Logged as OPTIONAL/DOWN, no summarization attempted |
| Git pull timeout | Session uses stale data, user unaware | Logged as IMPORTANT/DEGRADED, "data may not include today's changes" injected into context |
| RPC navigation fails | Browser doesn't navigate, user confused | Already handled OK, but now tracked in unified health dashboard |

## Implementation sequence (COMPLETED 2026-04-05)

1. ~~Create `src/service_health.py`~~ — Done. ServiceHealth, ServiceState, tiers, check_service/check_service_sync wrappers.
2. ~~Add tests in `tests/test_service_health.py`~~ — Done. 25 tests covering all functionality.
3. ~~Integrate into `my_agent()`~~ — Done. git, Supabase, avatar, summarizer calls wrapped.
4. ~~Add session start gate~~ — Done. `can_start_session()` checks critical services. (Note: STT/LLM/TTS are initialized by the LiveKit framework, so health registration for those is declarative — actual failure detection comes from LiveKit's own error handling, not our wrappers.)
5. ~~Add context injection~~ — Done. `session_warnings()` injected into LLM instructions.
6. ~~Add health summary to session close log~~ — Done. `health.summary()` logged on close.

## Files

| File | Purpose |
|------|---------|
| `src/service_health.py` | New — ServiceHealth class and types |
| `tests/test_service_health.py` | New — unit tests for health tracking |
| `src/agent.py` | Modify — wrap all service calls, add session gate |

## Not in scope

- External monitoring/alerting (Grafana, PagerDuty) — this is local observability only
- Automatic retry with backoff — keep it simple, just detect and report
- Circuit breaker pattern — overkill for 4 users
- Health check HTTP endpoint — could add later if needed for deployment monitoring
