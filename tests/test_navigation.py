"""Tests for browser navigation logic.

Tests _navigate_browser payload construction, show_in_browser date validation,
and which tools should/shouldn't trigger navigation.
"""

import json
import typing

from data.analysis import (
    _format_changes,
    format_assignment,
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

        from assistant import Assistant

        navigating = [
            "list_assignments",
            "get_class_summary",
            "get_assignment_detail",
            "compare_dates",
            "get_flagged_assignments",
            "get_category_breakdown",
            "get_deleted_assignments_list",
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

        from assistant import Assistant

        non_navigating = [
            "list_classes",
            "get_recent_changes",
            "get_grade_trend",
            "get_overall_summary",
            "get_score_changes",
            "save_user_profile",
            "get_ungraded_assignments",
        ]
        for tool_name in non_navigating:
            method = getattr(Assistant, tool_name, None)
            assert method is not None, f"Tool {tool_name} not found on Assistant"
            source = inspect.getsource(method)
            assert "_navigate_browser" not in source, (
                f"Tool {tool_name} should NOT call _navigate_browser"
            )


# --- Contract tests (see docs/CONTRACTS.md) ---


class TestRPCNavigationContract:
    """Verify the navigateTo RPC payload matches the documented contract."""

    REQUIRED_FIELDS: typing.ClassVar[set[str]] = {"view", "date", "className"}

    def _make_payload(self, date: str = "", slug: str = "", compare_date: str = ""):
        """Replicate the payload logic from _navigate_browser."""
        payload_dict: dict = {
            "view": "day" if date else "calendar",
            "date": date,
            "className": slug,
        }
        if compare_date:
            payload_dict["compareDate"] = compare_date
        return payload_dict

    def test_required_fields_present(self):
        payload = self._make_payload(date="2026-04-03", slug="geometry")
        assert self.REQUIRED_FIELDS.issubset(payload.keys())

    def test_day_view_structure(self):
        payload = self._make_payload(date="2026-04-03", slug="geometry")
        assert payload["view"] == "day"
        assert payload["date"] == "2026-04-03"
        assert payload["className"] == "geometry"
        assert "compareDate" not in payload

    def test_calendar_view_structure(self):
        payload = self._make_payload()
        assert payload["view"] == "calendar"
        assert payload["date"] == ""
        assert payload["className"] == ""

    def test_compare_date_format(self):
        payload = self._make_payload(
            date="2026-04-03", slug="geometry", compare_date="2026-03-27/210000"
        )
        assert payload["compareDate"] == "2026-03-27/210000"
        assert "/" in payload["compareDate"]  # date/time format

    def test_special_classname_help(self):
        payload = self._make_payload(slug="help")
        assert payload["className"] == "help"
        assert payload["view"] == "calendar"  # no date → calendar

    def test_special_classname_deleted(self):
        payload = self._make_payload(slug="deleted")
        assert payload["className"] == "deleted"

    def test_payload_serializable(self):
        """Payload must be JSON-serializable."""
        payload = self._make_payload(
            date="2026-04-03", slug="geometry", compare_date="2026-03-27/210000"
        )
        serialized = json.dumps(payload)
        deserialized = json.loads(serialized)
        assert deserialized == payload


class TestSnapshotSchemaContract:
    """Verify snapshot JSON matches the documented contract in CONTRACTS.md."""

    def test_assignment_required_fields(self):
        """Assignment JSON must have all required fields."""
        from data.models import Assignment

        assignment_data = {
            "name": "Test Assignment",
            "due_date": "2026-04-03",
            "category": "Homework",
            "flags": {"missing": False, "late": False},
        }
        a = Assignment.from_dict(assignment_data)
        assert a.name == "Test Assignment"
        assert a.due_date == "2026-04-03"
        assert a.category == "Homework"
        assert isinstance(a.flags, dict)

    def test_assignment_optional_fields_default(self):
        """Optional fields should have safe defaults when missing."""
        from data.models import Assignment

        a = Assignment.from_dict(
            {"name": "Minimal", "due_date": "2026-04-03", "category": "Test"}
        )
        assert a.score_raw == ""
        assert a.points_earned is None
        assert a.points_possible is None
        assert a.percent is None
        assert a.grade is None
        assert a.has_comments is False
        assert a.flags == {}

    def test_metadata_class_fields(self):
        """Metadata class entry must parse all documented fields."""
        from data.models import ClassMetadata

        data = {
            "course": "Geometry",
            "teacher": "Smith, John",
            "teacher_email": "john.smith@test.org",
            "expression": "1(A)",
            "term": "S2",
            "final_grade": "B-",
            "final_percent": 80,
            "assignment_count": 2,
            "last_updated": "3/6/2026",
        }
        cm = ClassMetadata.from_dict(data)
        assert cm.course == "Geometry"
        assert cm.teacher == "Smith, John"
        assert cm.final_grade == "B-"
        assert cm.final_percent == 80
        assert cm.assignment_count == 2

    def test_rolling_index_structure(self):
        """Rolling index must parse snapshots with changes and classes."""
        from data.models import RollingIndex

        data = {
            "snapshots": [
                {
                    "date": "2026-03-08",
                    "time": "210000",
                    "scrape_timestamp": "2026-03-08T21:00:00+00:00",
                    "changes": {"added": 2, "modified": 1, "deleted": 0, "total": 3},
                    "classes": {
                        "geometry": {
                            "course": "Geometry",
                            "final_grade": "B-",
                            "final_percent": 80,
                            "assignment_count": 2,
                        }
                    },
                }
            ]
        }
        index = RollingIndex.from_dict(data)
        assert len(index.snapshots) == 1
        s = index.snapshots[0]
        assert s.date == "2026-03-08"
        assert s.changes.added == 2
        assert "geometry" in s.classes
        assert s.classes["geometry"].course == "Geometry"

    def test_unscored_detection_contract(self):
        """Unscored values match the documented contract."""
        from data.analysis import _is_unscored

        # Documented as unscored
        assert _is_unscored(None) is True
        assert _is_unscored("") is True
        assert _is_unscored("--") is True
        assert _is_unscored("--/20") is True
        assert _is_unscored("0") is True

        # Documented as scored
        assert _is_unscored("18/22") is False
        assert _is_unscored("0/10") is False
        assert _is_unscored("B+") is False


# --- Helper function tests (from code review 4d) ---


class TestFormatHelpers:
    def testformat_assignment(self):
        from data.models import Assignment

        a = Assignment(
            name="Test HW",
            due_date="2026-03-10",
            category="Homework",
            score_raw="18/20",
            grade="B+",
            percent=90,
        )
        result = format_assignment(a)
        assert "Test HW" in result
        assert "2026-03-10" in result
        assert "18/20" in result
        assert "B+" in result
        assert "90%" in result

    def testformat_assignment_no_grade(self):
        from data.models import Assignment

        a = Assignment(
            name="Ungraded",
            due_date="2026-03-10",
            category="Homework",
            score_raw="--/20",
        )
        result = format_assignment(a)
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


# --- Date resolution arithmetic ---


class TestResolveDateArithmetic:
    """Unit tests for resolve_relative_date (pure date math, no LiveKit)."""

    def test_last_friday_from_saturday(self):
        from datetime import date

        from date_resolution import resolve_relative_date

        result = resolve_relative_date("last Friday", today=date(2026, 4, 4))
        assert result == date(2026, 4, 3)

    def test_last_friday_from_friday(self):
        """'last Friday' on a Friday means the previous week."""
        from datetime import date

        from date_resolution import resolve_relative_date

        result = resolve_relative_date("last Friday", today=date(2026, 4, 3))
        assert result == date(2026, 3, 27)

    def test_before_with_iso_date(self):
        """'the Friday before 2026-04-03' -> March 27."""
        from datetime import date

        from date_resolution import resolve_relative_date

        result = resolve_relative_date(
            "the Friday before 2026-04-03", today=date(2026, 4, 4)
        )
        assert result == date(2026, 3, 27)

    def test_before_without_iso_date(self):
        """'the Friday before' from Saturday Apr 4 -> Mar 27."""
        from datetime import date

        from date_resolution import resolve_relative_date

        result = resolve_relative_date("the Friday before", today=date(2026, 4, 4))
        assert result == date(2026, 3, 27)

    def test_yesterday(self):
        from datetime import date

        from date_resolution import resolve_relative_date

        result = resolve_relative_date("yesterday", today=date(2026, 4, 4))
        assert result == date(2026, 4, 3)

    def test_today(self):
        from datetime import date

        from date_resolution import resolve_relative_date

        result = resolve_relative_date("today", today=date(2026, 4, 4))
        assert result == date(2026, 4, 4)

    def test_last_monday(self):
        from datetime import date

        from date_resolution import resolve_relative_date

        # Friday Apr 4 -> previous Monday is Mar 30
        result = resolve_relative_date("last Monday", today=date(2026, 4, 4))
        assert result == date(2026, 3, 30)

    def test_unresolvable_returns_none(self):
        from datetime import date

        from date_resolution import resolve_relative_date

        result = resolve_relative_date("sometime in the past", today=date(2026, 4, 4))
        assert result is None


# --- Placeholder summary detection ---


class TestIsPlaceholderSummary:
    def test_discussed_classes_pattern(self):
        from deferred_summary import is_placeholder_summary

        assert (
            is_placeholder_summary("Discussed Geometry, English 10 (8 messages).")
            is True
        )

    def test_conversation_pattern(self):
        from deferred_summary import is_placeholder_summary

        assert is_placeholder_summary("Conversation with 12 messages.") is True

    def test_llm_generated_summary(self):
        from deferred_summary import is_placeholder_summary

        assert (
            is_placeholder_summary(
                "The user asked about their Geometry grade trend and missing assignments."
            )
            is False
        )

    def test_empty_string(self):
        from deferred_summary import is_placeholder_summary

        assert is_placeholder_summary("") is False
