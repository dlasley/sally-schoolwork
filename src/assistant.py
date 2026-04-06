"""Assistant agent class with all @function_tool methods."""

import json
import logging
from dataclasses import dataclass, field
from datetime import date

from livekit import rtc
from livekit.agents import Agent, RunContext, function_tool

from data.analysis import (
    diff_snapshots,
    find_assignment,
    format_assignment,
    get_category_breakdown,
    get_comprehensive_summary,
    get_deleted_assignments,
    get_grade_trend,
    get_modified_assignments,
    get_ungraded_assignments,
    list_flagged_assignments,
    summarize_all_classes,
    summarize_changes,
    summarize_class,
)
from data.snapshot_reader import SnapshotReader
from data.user_store import UserStore
from date_resolution import resolve_relative_date

logger = logging.getLogger("agent")


@dataclass
class SessionData:
    reader: SnapshotReader = field(default_factory=SnapshotReader)
    user_store: UserStore | None = None
    device_id: str = ""
    session_id: str = ""
    needs_onboarding: bool = False


class Assistant(Agent):
    def __init__(self, instructions: str) -> None:
        super().__init__(instructions=instructions)

    @staticmethod
    def _class_not_found(name: str) -> str:
        return f"Could not find a class matching '{name}'. Ask the user to clarify."

    def _resolve_class(
        self, context: RunContext[SessionData], class_name: str
    ) -> tuple[str | None, str | None]:
        """Resolve class name to slug. Returns (slug, None) or (None, error_string)."""
        slug = context.userdata.reader.resolve_slug(class_name)
        if not slug:
            return None, self._class_not_found(class_name)
        return slug, None

    async def _navigate_browser(
        self, date: str = "", slug: str = "", compare_date: str = ""
    ) -> None:
        """Navigate the user's browser as a side effect. Non-blocking, fire-and-forget."""
        try:
            from livekit.agents import get_job_context

            room = get_job_context().room
            target = None
            for p in room.remote_participants.values():
                if p.kind != rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
                    target = p.identity
                    break
            if not target:
                return

            payload_dict: dict = {
                "view": "day" if date else "calendar",
                "date": date,
                "className": slug,
            }
            if compare_date:
                reader = get_job_context().proc.userdata["reader"]
                times = reader.list_snapshot_times(compare_date)
                if times:
                    payload_dict["compareDate"] = f"{compare_date}/{times[-1]}"
            payload = json.dumps(payload_dict)
            await room.local_participant.perform_rpc(
                destination_identity=target,
                method="navigateTo",
                payload=payload,
                response_timeout=5.0,
            )
        except Exception:
            logger.debug("Navigation RPC failed", exc_info=True)

    @function_tool()
    async def resolve_date(
        self,
        context: RunContext[SessionData],
        description: str,
    ):
        """Resolve a relative date description to an exact YYYY-MM-DD date.

        ALWAYS call this tool before passing a date to any other tool.
        Use it for any relative reference: 'last Friday', 'yesterday',
        'two weeks ago', 'March 15th', etc.

        Args:
            description: Natural language date description, e.g. 'last Friday'.
        """
        resolved = resolve_relative_date(description, date.today())

        reader = context.userdata.reader
        available = reader.list_snapshot_dates()

        if resolved:
            resolved_str = resolved.isoformat()
            in_data = resolved_str in available
            return (
                f"Resolved '{description}' to {resolved_str}. "
                f"{'Data exists for this date.' if in_data else 'No snapshot for this date — nearest available: ' + (next((d for d in reversed(available) if d <= resolved_str), available[-1] if available else 'none'))}"
            )

        # Fallback: return available dates so LLM can pick
        return f"Could not resolve '{description}'. Available dates: {', '.join(available)}"

    @function_tool()
    async def list_classes(
        self,
        context: RunContext[SessionData],
    ):
        """List all classes with their current grades.

        Use this tool when the user asks about their classes, grades overview,
        or wants to know what classes they have.
        """
        reader = context.userdata.reader
        return summarize_all_classes(reader)

    @function_tool()
    async def list_assignments(
        self,
        context: RunContext[SessionData],
        class_name: str,
    ):
        """List all assignments for a class with their scores, grades, and due dates.

        Use this tool when the user asks to see all assignments, all scores, all homework,
        or a full list of work for a class.

        Args:
            class_name: The name of the class. Can be a partial name like "geo" for Geometry.
        """
        reader = context.userdata.reader
        slug, err = self._resolve_class(context, class_name)
        if err:
            return err
        coords = reader.latest_snapshot_coords()
        if not coords:
            return "No snapshot data available."
        assignments = reader.read_assignments(*coords, slug)
        if not assignments:
            return f"No assignments found for '{slug}'."

        await self._navigate_browser(date=coords[0], slug=slug)
        lines = [format_assignment(a) for a in assignments]
        return "\n\n".join(lines)

    @function_tool()
    async def get_class_summary(
        self,
        context: RunContext[SessionData],
        class_name: str,
        date: str = "",
    ):
        """Get a summary of a specific class including current grade, assignment count, and teacher.

        Use this tool when the user asks about a specific class grade or class details.
        For historical queries ("last Friday", "on March 15th"), pass the resolved date.

        Args:
            class_name: The name of the class to look up. Can be a partial name like "geo" for Geometry.
            date: Optional date in YYYY-MM-DD format. Defaults to the latest snapshot.
        """
        reader = context.userdata.reader
        slug, err = self._resolve_class(context, class_name)
        if err:
            return err
        available = reader.list_snapshot_dates()
        resolved_date = date if (date and date in available) else None
        if resolved_date:
            nav_date = resolved_date
        else:
            coords = reader.latest_snapshot_coords()
            nav_date = coords[0] if coords else ""
        await self._navigate_browser(date=nav_date, slug=slug)
        return summarize_class(reader, slug, date=resolved_date)

    @function_tool()
    async def get_recent_changes(
        self,
        context: RunContext[SessionData],
        class_name: str = "",
        days: int = 7,
    ):
        """Get recent assignment and grade changes.

        Use this tool when the user asks what changed recently, if any grades were updated,
        or if any assignments were added or removed.

        Args:
            class_name: Optional class name to filter changes. Leave empty for all classes.
            days: Number of days to look back. Defaults to 7.
        """
        reader = context.userdata.reader
        slug = None
        if class_name:
            slug, err = self._resolve_class(context, class_name)
            if err:
                return err
        return summarize_changes(reader, slug=slug, days=days)

    @function_tool()
    async def get_assignment_detail(
        self,
        context: RunContext[SessionData],
        class_name: str,
        assignment_name: str,
    ):
        """Look up details for a specific assignment including score, grade, and due date.

        Use this tool when the user asks about a specific assignment, quiz, or homework.

        Args:
            class_name: The name of the class the assignment belongs to.
            assignment_name: The name or partial name of the assignment to look up.
        """
        reader = context.userdata.reader
        slug, err = self._resolve_class(context, class_name)
        if err:
            return err
        coords = reader.latest_snapshot_coords()
        if coords:
            await self._navigate_browser(date=coords[0], slug=slug)
        return find_assignment(reader, slug, assignment_name)

    @function_tool()
    async def compare_dates(
        self,
        context: RunContext[SessionData],
        class_name: str,
        date1: str,
        date2: str,
    ):
        """Compare assignments between two dates to see what changed.

        Use this tool when the user asks to compare grades or assignments between
        specific dates, or asks what changed between two points in time.

        Args:
            class_name: The name of the class to compare.
            date1: The earlier date in YYYY-MM-DD format.
            date2: The later date in YYYY-MM-DD format.
        """
        reader = context.userdata.reader
        slug, err = self._resolve_class(context, class_name)
        if err:
            return err

        # Find the latest snapshot time for each date
        times1 = reader.list_snapshot_times(date1)
        times2 = reader.list_snapshot_times(date2)
        if not times1:
            return f"No snapshot data found for {date1}."
        if not times2:
            return f"No snapshot data found for {date2}."

        await self._navigate_browser(date=date2, slug=slug, compare_date=date1)
        return diff_snapshots(reader, slug, date1, times1[-1], date2, times2[-1])

    @function_tool()
    async def get_flagged_assignments(
        self,
        context: RunContext[SessionData],
        class_name: str = "",
        flag: str = "",
    ):
        """List assignments with specific flags like missing, late, incomplete, exempt, or absent.

        Use this tool when the user asks about missing work, late assignments,
        or anything related to assignment status flags.

        Args:
            class_name: Optional class name to filter. Leave empty for all classes.
            flag: Optional specific flag to filter by: missing, late, incomplete, exempt, absent. Leave empty for all flags.
        """
        reader = context.userdata.reader
        slug = None
        if class_name:
            slug, err = self._resolve_class(context, class_name)
            if err:
                return err
        coords = reader.latest_snapshot_coords()
        if coords:
            await self._navigate_browser(date=coords[0], slug=slug or "")
        return list_flagged_assignments(reader, slug=slug, flag=flag or None)

    @function_tool()
    async def get_category_breakdown(
        self,
        context: RunContext[SessionData],
        class_name: str,
    ):
        """Break down performance by assignment category for a class.

        Use this tool when the user asks how they're doing on quizzes vs homework,
        or wants to see performance by category like Homework, Quizzes, Tests, etc.

        Args:
            class_name: The name of the class to analyze.
        """
        reader = context.userdata.reader
        slug, err = self._resolve_class(context, class_name)
        if err:
            return err
        coords = reader.latest_snapshot_coords()
        if coords:
            await self._navigate_browser(date=coords[0], slug=slug)
        return get_category_breakdown(reader, slug)

    @function_tool()
    async def get_grade_trend(
        self,
        context: RunContext[SessionData],
        class_name: str,
        days: int = 30,
    ):
        """Track how a class grade has changed over time.

        Use this tool when the user asks about grade trends, whether grades are
        improving or declining, or how grades have changed over a period.

        Args:
            class_name: The name of the class to track.
            days: Number of days to look back. Defaults to 30.
        """
        reader = context.userdata.reader
        slug, err = self._resolve_class(context, class_name)
        if err:
            return err
        return get_grade_trend(reader, slug, days=days)

    @function_tool()
    async def get_overall_summary(
        self,
        context: RunContext[SessionData],
        days: int = 14,
    ):
        """Get a comprehensive summary across all classes — grades, changes, flags, deletions, and trends.

        Use this tool for broad or abstract questions like:
        - "What should I be worried about?"
        - "Give me an overall picture"
        - "Are there any patterns?"
        - "What's changed recently across everything?"
        - "Summarize how things are going"

        Args:
            days: Number of days to look back for changes and trends. Defaults to 14.
        """
        reader = context.userdata.reader
        return get_comprehensive_summary(reader, days=days)

    @function_tool()
    async def get_deleted_assignments_list(
        self,
        context: RunContext[SessionData],
        class_name: str = "",
        days: int = 14,
    ):
        """List assignments that were deleted or removed over a date range.

        Use this tool when the user asks about deleted, removed, or disappeared assignments.

        Args:
            class_name: Optional class name to filter. Leave empty for all classes.
            days: Number of days to look back. Defaults to 14.
        """
        reader = context.userdata.reader
        slug = None
        if class_name:
            slug, err = self._resolve_class(context, class_name)
            if err:
                return err
        await self._navigate_browser(date="", slug="deleted")
        return get_deleted_assignments(reader, slug=slug, days=days)

    @function_tool()
    async def get_score_changes(
        self,
        context: RunContext[SessionData],
        class_name: str = "",
        days: int = 14,
    ):
        """List assignments that had score or grade modifications over a date range.

        Use this tool when the user asks about score changes, grade updates,
        retroactive modifications, or which assignments had their scores changed.

        Args:
            class_name: Optional class name to filter. Leave empty for all classes.
            days: Number of days to look back. Defaults to 14.
        """
        reader = context.userdata.reader
        slug = None
        if class_name:
            slug, err = self._resolve_class(context, class_name)
            if err:
                return err
        return get_modified_assignments(reader, slug=slug, days=days)

    @function_tool()
    async def show_capabilities(
        self,
        context: RunContext[SessionData],
    ):
        """Show the user what kinds of questions they can ask.

        Use this tool when the user asks for help, asks what you can do,
        or says they don't know what to ask. Also use it at the end of onboarding.
        """
        await self._navigate_browser(date="", slug="help")
        return (
            "Narrate this naturally in one or two spoken sentences — no lists or bullets: "
            "You can look up current grades and class summaries, individual assignment scores, "
            "recent changes like new or modified assignments, grade trends over time, "
            "missing or late work, and comparisons between two dates. "
            "The help page is now open in the browser for more examples."
        )

    @function_tool()
    async def show_in_browser(
        self,
        context: RunContext[SessionData],
        view: str = "day",
        date: str = "",
        class_name: str = "",
    ):
        """Navigate the user's browser to show relevant data.

        Use this tool when the user explicitly asks to see something in the browser,
        or to go back to the calendar. Most data tools already navigate automatically.

        Args:
            view: "calendar" to go back to the main calendar, or "day" to show a specific date.
            date: Date in YYYY-MM-DD format. If empty or not found, uses the latest available date.
            class_name: Class name to select that class tab.
        """
        reader = context.userdata.reader

        if view == "calendar":
            await self._navigate_browser()
            return "Showing the calendar."

        # Validate date against actual snapshot data
        available_dates = reader.list_snapshot_dates()
        if date and date in available_dates:
            resolved_date = date
        elif available_dates:
            resolved_date = available_dates[-1]
        else:
            return "No snapshot data available to show."

        slug = ""
        if class_name:
            slug = reader.resolve_slug(class_name) or ""

        await self._navigate_browser(date=resolved_date, slug=slug)
        return "Showing it in the browser now."

    @function_tool()
    async def get_ungraded_assignments(
        self,
        context: RunContext[SessionData],
        class_name: str = "",
    ):
        """List assignments that have no score entered yet, sorted by point value descending.

        Use this tool when the user asks about ungraded work, assignments with no score,
        pending grades, or the highest-value work not yet scored.

        Args:
            class_name: Optional class name to filter. Leave empty for all classes.
        """
        reader = context.userdata.reader
        slug = None
        if class_name:
            slug, err = self._resolve_class(context, class_name)
            if err:
                return err
        return get_ungraded_assignments(reader, slug=slug)

    @function_tool()
    async def save_user_profile(
        self,
        context: RunContext[SessionData],
        name: str = "",
        relation_to_student: str = "",
        priorities: str = "",
    ):
        """Save the user's profile information collected during onboarding.

        Call this tool after you have collected the user's information during
        the onboarding conversation. You may call it multiple times as you
        learn each piece of information.

        Args:
            name: The user's preferred name.
            relation_to_student: Their relation to the student — parent, the student, grandparent, etc.
            priorities: Comma-separated list of what they care about — missing assignments, grade trends, etc.
        """
        store = context.userdata.user_store
        if not store:
            return "Profile storage is not available."

        priority_list = (
            [p.strip() for p in priorities.split(",") if p.strip()]
            if priorities
            else None
        )

        store.save_profile(
            device_id=context.userdata.device_id,
            name=name or None,
            relation_to_student=relation_to_student or None,
            priorities=priority_list,
        )
        context.userdata.needs_onboarding = False
        return "Profile saved."
