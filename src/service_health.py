"""Unified service health monitor for external dependencies.

Tracks the status of all remote services (STT, LLM, TTS, avatar, Supabase,
git, RPC) with consistent logging, tier-based degradation, and session start
gating. New providers register with a tier and the monitor handles the rest.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger("service_health")


class ServiceStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


class ServiceTier(Enum):
    CRITICAL = "critical"  # STT, LLM, TTS — session cannot function
    IMPORTANT = "important"  # Supabase, git — session degraded
    OPTIONAL = "optional"  # Avatar, RPC, background tasks — unaffected


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
        """Register a service to monitor."""
        self._services[name] = ServiceState(name=name, tier=tier)

    def get_state(self, name: str) -> ServiceState | None:
        """Get current state of a service, or None if not registered."""
        return self._services.get(name)

    def mark_healthy(self, name: str) -> None:
        """Mark a service as healthy, resetting failure state."""
        state = self._services.get(name)
        if not state:
            return
        state.status = ServiceStatus.HEALTHY
        state.last_error = None
        state.failure_count = 0
        state.last_check = datetime.now(timezone.utc)

    def mark_failed(self, name: str, error: str) -> None:
        """Mark a service as down due to an error."""
        state = self._services.get(name)
        if not state:
            return
        state.status = ServiceStatus.DOWN
        state.last_error = error
        state.failure_count += 1
        state.last_check = datetime.now(timezone.utc)
        logger.error(
            "%s/%s: %s (failure #%d)",
            state.name,
            state.tier.value,
            error,
            state.failure_count,
        )

    def mark_degraded(self, name: str, reason: str) -> None:
        """Mark a service as degraded (functioning but impaired)."""
        state = self._services.get(name)
        if not state:
            return
        state.status = ServiceStatus.DEGRADED
        state.last_error = reason
        state.last_check = datetime.now(timezone.utc)
        logger.warning("%s/%s degraded: %s", state.name, state.tier.value, reason)

    def can_start_session(self) -> tuple[bool, list[str]]:
        """Check if all critical services are healthy.

        Returns (ok, reasons) where reasons lists the critical failures.
        """
        reasons = []
        for state in self._services.values():
            if (
                state.tier == ServiceTier.CRITICAL
                and state.status == ServiceStatus.DOWN
            ):
                reasons.append(f"{state.name}: {state.last_error}")
        return (len(reasons) == 0, reasons)

    def session_warnings(self) -> list[str]:
        """Warnings for non-critical services that are degraded or down.

        These get injected into the LLM's context so it can inform the user.
        Critical failures block the session entirely, so they're not warnings.
        """
        warnings = []
        for state in self._services.values():
            if state.tier == ServiceTier.CRITICAL:
                continue
            if state.status == ServiceStatus.DOWN:
                warnings.append(
                    f"{state.name} is unavailable ({state.last_error}). "
                    f"Related features are disabled."
                )
            elif state.status == ServiceStatus.DEGRADED:
                warnings.append(f"{state.name} is degraded: {state.last_error}")
        return warnings

    def check_service_sync(self, name: str, fn, *args, **kwargs):
        """Run a sync call, update health status, return result or None."""
        try:
            result = fn(*args, **kwargs)
            self.mark_healthy(name)
            return result
        except Exception as exc:
            self.mark_failed(name, str(exc))
            return None

    async def check_service(self, name: str, coro, timeout: float = 30.0):
        """Run an async call with timeout, update health status, return result or None."""
        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
            self.mark_healthy(name)
            return result
        except asyncio.TimeoutError:
            self.mark_failed(name, f"Timeout after {timeout}s")
            return None
        except Exception as exc:
            self.mark_failed(name, str(exc))
            return None

    def summary(self) -> str:
        """Human-readable summary of all service states for logging."""
        lines = []
        for state in self._services.values():
            status = state.status.value
            detail = f" ({state.last_error})" if state.last_error else ""
            lines.append(f"  {state.name}/{state.tier.value}: {status}{detail}")
        return "Service health:\n" + "\n".join(lines)
