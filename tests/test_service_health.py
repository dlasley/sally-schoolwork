"""Tests for the unified service health monitor."""

import asyncio

import pytest

from service_health import ServiceHealth, ServiceStatus, ServiceTier

# --- Registration and status ---


class TestRegistration:
    def test_register_service(self):
        health = ServiceHealth()
        health.register("stt", ServiceTier.CRITICAL)
        state = health.get_state("stt")
        assert state.name == "stt"
        assert state.tier == ServiceTier.CRITICAL
        assert state.status == ServiceStatus.HEALTHY

    def test_register_duplicate_overwrites(self):
        health = ServiceHealth()
        health.register("stt", ServiceTier.CRITICAL)
        health.register("stt", ServiceTier.OPTIONAL)
        assert health.get_state("stt").tier == ServiceTier.OPTIONAL

    def test_get_state_unknown_returns_none(self):
        health = ServiceHealth()
        assert health.get_state("nonexistent") is None


class TestMarkStatus:
    def test_mark_healthy(self):
        health = ServiceHealth()
        health.register("stt", ServiceTier.CRITICAL)
        health.mark_failed("stt", "connection refused")
        health.mark_healthy("stt")
        state = health.get_state("stt")
        assert state.status == ServiceStatus.HEALTHY
        assert state.failure_count == 0

    def test_mark_failed(self):
        health = ServiceHealth()
        health.register("stt", ServiceTier.CRITICAL)
        health.mark_failed("stt", "429 Too Many Requests")
        state = health.get_state("stt")
        assert state.status == ServiceStatus.DOWN
        assert state.last_error == "429 Too Many Requests"
        assert state.failure_count == 1

    def test_mark_failed_increments_count(self):
        health = ServiceHealth()
        health.register("stt", ServiceTier.CRITICAL)
        health.mark_failed("stt", "error 1")
        health.mark_failed("stt", "error 2")
        assert health.get_state("stt").failure_count == 2
        assert health.get_state("stt").last_error == "error 2"

    def test_mark_degraded(self):
        health = ServiceHealth()
        health.register("git", ServiceTier.IMPORTANT)
        health.mark_degraded("git", "using stale data")
        state = health.get_state("git")
        assert state.status == ServiceStatus.DEGRADED
        assert state.last_error == "using stale data"


# --- Session start gating ---


class TestCanStartSession:
    def test_all_healthy(self):
        health = ServiceHealth()
        health.register("stt", ServiceTier.CRITICAL)
        health.register("llm", ServiceTier.CRITICAL)
        health.register("avatar", ServiceTier.OPTIONAL)
        ok, reasons = health.can_start_session()
        assert ok is True
        assert reasons == []

    def test_critical_down_blocks(self):
        health = ServiceHealth()
        health.register("stt", ServiceTier.CRITICAL)
        health.register("llm", ServiceTier.CRITICAL)
        health.mark_failed("stt", "429 rate limit")
        ok, reasons = health.can_start_session()
        assert ok is False
        assert len(reasons) == 1
        assert "stt" in reasons[0]

    def test_multiple_critical_down(self):
        health = ServiceHealth()
        health.register("stt", ServiceTier.CRITICAL)
        health.register("llm", ServiceTier.CRITICAL)
        health.mark_failed("stt", "429")
        health.mark_failed("llm", "timeout")
        ok, reasons = health.can_start_session()
        assert ok is False
        assert len(reasons) == 2

    def test_important_down_does_not_block(self):
        health = ServiceHealth()
        health.register("stt", ServiceTier.CRITICAL)
        health.register("supabase", ServiceTier.IMPORTANT)
        health.mark_failed("supabase", "connection refused")
        ok, _reasons = health.can_start_session()
        assert ok is True

    def test_optional_down_does_not_block(self):
        health = ServiceHealth()
        health.register("stt", ServiceTier.CRITICAL)
        health.register("avatar", ServiceTier.OPTIONAL)
        health.mark_failed("avatar", "credits exhausted")
        ok, _reasons = health.can_start_session()
        assert ok is True


# --- Session warnings ---


class TestSessionWarnings:
    def test_no_warnings_when_healthy(self):
        health = ServiceHealth()
        health.register("stt", ServiceTier.CRITICAL)
        health.register("supabase", ServiceTier.IMPORTANT)
        assert health.session_warnings() == []

    def test_important_down_produces_warning(self):
        health = ServiceHealth()
        health.register("supabase", ServiceTier.IMPORTANT)
        health.mark_failed("supabase", "connection refused")
        warnings = health.session_warnings()
        assert len(warnings) == 1
        assert "supabase" in warnings[0].lower()

    def test_optional_down_produces_warning(self):
        health = ServiceHealth()
        health.register("avatar", ServiceTier.OPTIONAL)
        health.mark_failed("avatar", "credits exhausted")
        warnings = health.session_warnings()
        assert len(warnings) == 1
        assert "avatar" in warnings[0].lower()

    def test_degraded_produces_warning(self):
        health = ServiceHealth()
        health.register("git", ServiceTier.IMPORTANT)
        health.mark_degraded("git", "using stale data")
        warnings = health.session_warnings()
        assert len(warnings) == 1

    def test_critical_down_not_in_warnings(self):
        """Critical failures block the session, so they're not warnings."""
        health = ServiceHealth()
        health.register("stt", ServiceTier.CRITICAL)
        health.mark_failed("stt", "429")
        warnings = health.session_warnings()
        assert len(warnings) == 0


# --- Sync wrapper ---


class TestCheckServiceSync:
    def test_successful_call(self):
        health = ServiceHealth()
        health.register("supabase", ServiceTier.IMPORTANT)
        result = health.check_service_sync("supabase", lambda: {"name": "Dave"})
        assert result == {"name": "Dave"}
        assert health.get_state("supabase").status == ServiceStatus.HEALTHY

    def test_failed_call(self):
        health = ServiceHealth()
        health.register("supabase", ServiceTier.IMPORTANT)

        def failing():
            raise ConnectionError("refused")

        result = health.check_service_sync("supabase", failing)
        assert result is None
        assert health.get_state("supabase").status == ServiceStatus.DOWN
        assert "refused" in health.get_state("supabase").last_error

    def test_passes_args(self):
        health = ServiceHealth()
        health.register("supabase", ServiceTier.IMPORTANT)
        result = health.check_service_sync("supabase", lambda x, y: x + y, 3, 4)
        assert result == 7


# --- Async wrapper ---


class TestCheckServiceAsync:
    @pytest.mark.asyncio
    async def test_successful_async_call(self):
        health = ServiceHealth()
        health.register("avatar", ServiceTier.OPTIONAL)

        async def start_avatar():
            return "avatar_started"

        result = await health.check_service("avatar", start_avatar())
        assert result == "avatar_started"
        assert health.get_state("avatar").status == ServiceStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_failed_async_call(self):
        health = ServiceHealth()
        health.register("avatar", ServiceTier.OPTIONAL)

        async def failing_avatar():
            raise RuntimeError("credits exhausted")

        result = await health.check_service("avatar", failing_avatar())
        assert result is None
        assert health.get_state("avatar").status == ServiceStatus.DOWN
        assert "credits exhausted" in health.get_state("avatar").last_error

    @pytest.mark.asyncio
    async def test_timeout(self):
        health = ServiceHealth()
        health.register("slow", ServiceTier.OPTIONAL)

        async def slow_service():
            await asyncio.sleep(10)
            return "done"

        result = await health.check_service("slow", slow_service(), timeout=0.1)
        assert result is None
        assert health.get_state("slow").status == ServiceStatus.DOWN
        assert "timeout" in health.get_state("slow").last_error.lower()


# --- Summary ---


class TestSummary:
    def test_summary_all_healthy(self):
        health = ServiceHealth()
        health.register("stt", ServiceTier.CRITICAL)
        health.register("avatar", ServiceTier.OPTIONAL)
        summary = health.summary()
        assert "stt" in summary
        assert "healthy" in summary.lower()

    def test_summary_includes_failures(self):
        health = ServiceHealth()
        health.register("stt", ServiceTier.CRITICAL)
        health.mark_failed("stt", "429")
        summary = health.summary()
        assert "429" in summary
        assert "down" in summary.lower()
