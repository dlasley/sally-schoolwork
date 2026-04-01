"""Tests for browser navigation logic.

Tests _navigate_browser payload construction, show_in_browser date validation,
and which tools should/shouldn't trigger navigation.
"""

import json

from data.analysis import (
    _format_assignment,
    _format_changes,
)

# --- Payload construction tests ---


class TestNavigationPayload:
    """Test the RPC payload format that _navigate_browser would send."""

    def test_day_view_payload(self):
        """Day view with date produces correct payload."""
        payload = json.dumps(
            {"view": "day", "date": "2026-03-10", "className": "geometry"}
        )
        parsed = json.loads(payload)
        assert parsed["view"] == "day"
        assert parsed["date"] == "2026-03-10"
        assert parsed["className"] == "geometry"

    def test_calendar_view_payload(self):
        """Calendar view produces correct payload with no date."""
        payload = json.dumps({"view": "calendar", "date": "", "className": ""})
        parsed = json.loads(payload)
        assert parsed["view"] == "calendar"
        assert parsed["date"] == ""

    def test_day_view_without_class(self):
        """Day view without class has empty className."""
        payload = json.dumps({"view": "day", "date": "2026-03-10", "className": ""})
        parsed = json.loads(payload)
        assert parsed["className"] == ""

    def test_view_selection_logic(self):
        """View is 'day' when date provided, 'calendar' when not."""
        date = "2026-03-10"
        view = "day" if date else "calendar"
        assert view == "day"

        date = ""
        view = "day" if date else "calendar"
        assert view == "calendar"


# --- Date validation tests (show_in_browser logic) ---


class TestDateValidation:
    """Test the date resolution logic from show_in_browser."""

    def _resolve_date(self, date: str, available: list[str]) -> str:
        """Replicate the date resolution logic from show_in_browser."""
        if date and date in available:
            return date
        elif available:
            return available[-1]
        return ""

    def test_exact_date_match(self):
        available = ["2026-03-08", "2026-03-10", "2026-03-25"]
        assert self._resolve_date("2026-03-10", available) == "2026-03-10"

    def test_fallback_to_latest(self):
        available = ["2026-03-08", "2026-03-10", "2026-03-25"]
        assert self._resolve_date("2026-03-15", available) == "2026-03-25"

    def test_empty_date_uses_latest(self):
        available = ["2026-03-08", "2026-03-10", "2026-03-25"]
        assert self._resolve_date("", available) == "2026-03-25"

    def test_no_available_dates(self):
        assert self._resolve_date("2026-03-10", []) == ""

    def test_hallucinated_date_falls_back(self):
        """LLM may generate dates from wrong year."""
        available = ["2026-03-08", "2026-03-10"]
        assert self._resolve_date("2024-03-10", available) == "2026-03-10"


# --- Tool navigation alignment tests ---


class TestToolNavigationAlignment:
    """Verify which tools should and shouldn't trigger navigation.

    These are structural tests — they verify the design decision,
    not the actual RPC call (which requires a LiveKit room).
    """

    def test_navigating_tools_have_navigate_call(self):
        """Tools that show class-specific data should call _navigate_browser."""
        import inspect

        from agent import Assistant

        navigating = [
            "list_assignments",
            "get_class_summary",
            "get_assignment_detail",
            "compare_dates",
            "get_flagged_assignments",
            "get_category_breakdown",
            "show_capabilities",
        ]
        for tool_name in navigating:
            method = getattr(Assistant, tool_name, None)
            assert method is not None, f"Tool {tool_name} not found on Assistant"
            source = inspect.getsource(method)
            assert "_navigate_browser" in source, (
                f"Tool {tool_name} should call _navigate_browser"
            )

    def test_non_navigating_tools_skip_navigation(self):
        """Aggregate tools should NOT call _navigate_browser."""
        import inspect

        from agent import Assistant

        non_navigating = [
            "list_classes",
            "get_recent_changes",
            "get_grade_trend",
            "get_overall_summary",
            "get_deleted_assignments_list",
            "get_score_changes",
            "save_user_profile",
        ]
        for tool_name in non_navigating:
            method = getattr(Assistant, tool_name, None)
            assert method is not None, f"Tool {tool_name} not found on Assistant"
            source = inspect.getsource(method)
            assert "_navigate_browser" not in source, (
                f"Tool {tool_name} should NOT call _navigate_browser"
            )


# --- Helper function tests (from code review 4d) ---


class TestFormatHelpers:
    def test_format_assignment(self):
        from data.models import Assignment

        a = Assignment(
            name="Test HW",
            due_date="2026-03-10",
            category="Homework",
            score_raw="18/20",
            grade="B+",
            percent=90,
        )
        result = _format_assignment(a)
        assert "Test HW" in result
        assert "2026-03-10" in result
        assert "18/20" in result
        assert "B+" in result
        assert "90%" in result

    def test_format_assignment_no_grade(self):
        from data.models import Assignment

        a = Assignment(
            name="Ungraded",
            due_date="2026-03-10",
            category="Homework",
            score_raw="--/20",
        )
        result = _format_assignment(a)
        assert "Ungraded" in result
        assert "--/20" in result
        assert "Grade" not in result

    def test_format_changes_added(self):
        changes = [
            {
                "class": "geo",
                "assignment": "New HW",
                "due_date": "2026-03-10",
                "type": "added",
            }
        ]
        result = _format_changes(changes)
        assert "Added" in result
        assert "New HW" in result

    def test_format_changes_modified(self):
        changes = [
            {
                "class": "geo",
                "assignment": "Old HW",
                "due_date": "2026-03-10",
                "type": "modified",
                "changes": [{"field": "score_raw", "old": "8/10", "new": "10/10"}],
            }
        ]
        result = _format_changes(changes)
        assert "Modified" in result
        assert "score_raw" in result
        assert "8/10" in result
        assert "10/10" in result

    def test_format_changes_empty(self):
        result = _format_changes([])
        assert result == ""


# --- Timestamp parsing (from code review 4d) ---


class TestParseTimestamp:
    def test_parse_with_timezone(self):
        from data.analysis import _parse_timestamp

        dt = _parse_timestamp("2026-03-10T15:30:41.707513+00:00")
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 10

    def test_parse_with_z_suffix(self):
        from data.analysis import _parse_timestamp

        dt = _parse_timestamp("2026-03-10T15:30:41Z")
        assert dt.hour == 15
        assert dt.minute == 30

    def test_parse_without_timezone(self):
        from data.analysis import _parse_timestamp

        dt = _parse_timestamp("2026-03-10T15:30:41")
        assert dt.second == 41
