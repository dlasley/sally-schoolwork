import asyncio
import contextlib
import json
import logging
import os
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    inference,
    room_io,
)
from livekit.plugins import (
    anthropic,
    deepgram,
    elevenlabs,
    hedra,
    noise_cancellation,
    silero,
)
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from data.analysis import (
    diff_snapshots,
    find_assignment,
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
from data.user_store import UserStore, get_supabase_client
from service_health import ServiceHealth, ServiceTier

logger = logging.getLogger("agent")

# Suppress noisy HTTP/2 debug loggers that drown out agent logs
for _noisy in ("hpack", "httpcore", "httpx", "h2"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

load_dotenv(".env.local")

DATA_REPO_URL = os.getenv(
    "DATA_REPO_URL", "git@github.com:dlasley/table-mutation-data.git"
)
DATA_REPO_PATH = Path(os.getenv("DATA_REPO_PATH", "./data-repo"))


# --- Date resolution ---


def resolve_relative_date(description: str, today: date) -> date | None:
    """Resolve a natural language date description to a date object.

    Pure date arithmetic — no LiveKit or data dependencies.
    Returns None if the description cannot be resolved.
    """
    desc = description.lower().strip()
    day_map = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }

    # If description contains an ISO date, use it as the reference point
    # e.g. "the Friday before 2026-04-03" -> compute Friday relative to April 3rd
    reference_date = today
    iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", description)
    if iso_match:
        with contextlib.suppress(ValueError):
            reference_date = date.fromisoformat(iso_match.group(1))

    # "before" means go one additional week back past the nearest occurrence
    extra_weeks = 1 if "before" in desc else 0

    if desc in ("today",):
        return today
    elif desc in ("yesterday",):
        return today - timedelta(days=1)
    else:
        for day_name, weekday in day_map.items():
            if day_name in desc:
                days_back = (reference_date.weekday() - weekday) % 7
                if days_back == 0 and extra_weeks == 0:
                    days_back = 7  # "last X" when today is X means previous week
                days_back += extra_weeks * 7
                return reference_date - timedelta(days=days_back)

    return None


# --- Persona loading ---


def load_persona(name: str | None = None) -> dict:
    """Load persona config and instructions from personas/ directory.

    Merges config.json (committed) with config.local.json (gitignored),
    concatenates base.md with persona-specific markdown, and templates
    {{STUDENT_NAME}}, {{STUDENT_NICKNAME}}, {{SCHOOL_NAME}} placeholders.
    """
    config_path = Path("personas/config.json")
    config = json.loads(config_path.read_text())
    persona_name = name or config["default"]
    persona_cfg = dict(config["personas"][persona_name])

    # Merge local config (real names, service IDs) if present
    local_config_path = Path("personas/config.local.json")
    local_vars = {}
    if local_config_path.exists():
        local_config = json.loads(local_config_path.read_text())
        local_vars = {
            "STUDENT_NAME": local_config.get("student_name", "the student"),
            "STUDENT_NICKNAME": local_config.get("student_nickname", ""),
            "SCHOOL_NAME": local_config.get("school_name", "the school"),
        }
        # Merge persona-specific local config (service IDs, voice settings)
        local_personas = local_config.get("personas", {})
        if persona_name in local_personas:
            persona_cfg.update(local_personas[persona_name])
    else:
        local_vars = {
            "STUDENT_NAME": "the student",
            "STUDENT_NICKNAME": "",
            "SCHOOL_NAME": "the school",
        }

    # Fall back to env vars for values not in local config
    # These are set as LiveKit Cloud secrets for deployment
    env_fallbacks = {
        "elevenlabs_voice_id": os.getenv("ELEVENLABS_VOICE_ID"),
        "hedra_avatar_id": os.getenv("HEDRA_AVATAR_ID"),
        "lemonslice_image_url": os.getenv("LEMONSLICE_IMAGE_URL"),
        "elevenlabs_speed": os.getenv("ELEVENLABS_SPEED"),
        "elevenlabs_stability": os.getenv("ELEVENLABS_STABILITY"),
        "elevenlabs_similarity": os.getenv("ELEVENLABS_SIMILARITY"),
    }
    for key, env_val in env_fallbacks.items():
        if env_val and key not in persona_cfg:
            persona_cfg[key] = (
                float(env_val) if key.startswith("elevenlabs_s") else env_val
            )

    # Template vars also fall back to env vars
    if (
        not local_vars.get("STUDENT_NAME")
        or local_vars["STUDENT_NAME"] == "the student"
    ):
        local_vars["STUDENT_NAME"] = os.getenv("STUDENT_NAME", "the student")
    if not local_vars.get("STUDENT_NICKNAME"):
        local_vars["STUDENT_NICKNAME"] = os.getenv("STUDENT_NICKNAME", "")
    if not local_vars.get("SCHOOL_NAME") or local_vars["SCHOOL_NAME"] == "the school":
        local_vars["SCHOOL_NAME"] = os.getenv("SCHOOL_NAME", "the school")

    # Load and concatenate instructions
    parts = []
    if "base" in config:
        parts.append(Path(config["base"]).read_text())
    parts.append(Path(persona_cfg["instructions"]).read_text())
    instructions = "\n\n".join(parts)

    # Template placeholders
    local_vars["CURRENT_DATE"] = datetime.now().strftime("%Y-%m-%d")
    for key, value in local_vars.items():
        instructions = instructions.replace("{{" + key + "}}", value)

    return {"instructions": instructions, **persona_cfg}


# --- Session state ---


@dataclass
class SessionData:
    reader: SnapshotReader = field(
        default_factory=lambda: SnapshotReader(DATA_REPO_PATH)
    )
    user_store: UserStore | None = None
    device_id: str = ""
    session_id: str = ""
    needs_onboarding: bool = False


# --- Agent ---


class Assistant(Agent):
    def __init__(self, instructions: str) -> None:
        super().__init__(instructions=instructions)

    @staticmethod
    def _class_not_found(name: str) -> str:
        return f"Could not find a class matching '{name}'. Ask the user to clarify."

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
        slug = reader.resolve_slug(class_name)
        if not slug:
            return self._class_not_found(class_name)
        coords = reader.latest_snapshot_coords()
        if not coords:
            return "No snapshot data available."
        assignments = reader.read_assignments(*coords, slug)
        if not assignments:
            return f"No assignments found for '{slug}'."
        from data.analysis import _format_assignment

        await self._navigate_browser(date=coords[0], slug=slug)
        lines = [_format_assignment(a) for a in assignments]
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
        slug = reader.resolve_slug(class_name)
        if not slug:
            return self._class_not_found(class_name)
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
            slug = reader.resolve_slug(class_name)
            if not slug:
                return self._class_not_found(class_name)
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
        slug = reader.resolve_slug(class_name)
        if not slug:
            return self._class_not_found(class_name)
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
        slug = reader.resolve_slug(class_name)
        if not slug:
            return self._class_not_found(class_name)

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
            slug = reader.resolve_slug(class_name)
            if not slug:
                return self._class_not_found(class_name)
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
        slug = reader.resolve_slug(class_name)
        if not slug:
            return self._class_not_found(class_name)
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
        slug = reader.resolve_slug(class_name)
        if not slug:
            return self._class_not_found(class_name)
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
            slug = reader.resolve_slug(class_name)
            if not slug:
                return self._class_not_found(class_name)
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
            slug = reader.resolve_slug(class_name)
            if not slug:
                return self._class_not_found(class_name)
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
            slug = reader.resolve_slug(class_name)
            if not slug:
                return self._class_not_found(class_name)
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


# --- Deferred summarization ---


def _is_placeholder_summary(summary: str) -> bool:
    return bool(
        re.match(
            r"^(Discussed .+\(\d+ messages\)\.|Conversation with \d+ messages\.)",
            summary.strip(),
        )
    )


async def _upgrade_session_summary(last_session: dict, user_store) -> None:
    """Upgrade a placeholder summary with an LLM-generated one.

    Runs as a background task at session start. All blocking Supabase calls
    are wrapped in asyncio.to_thread() to avoid blocking the event loop.
    """
    import anthropic as anthropic_sdk

    prev_session_id = last_session.get("session_id")
    if not prev_session_id:
        return
    if not _is_placeholder_summary(last_session.get("summary", "")):
        return

    try:
        messages = await asyncio.to_thread(
            user_store.get_session_messages, prev_session_id
        )
        if len(messages) < 2:
            return

        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        client = anthropic_sdk.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        completion = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Summarize this grade-tracking conversation in 2-3 sentences. "
                        "Focus on what classes were discussed, what the user was concerned "
                        "about, and any notable findings (grade changes, missing work, trends).\n\n"
                        f"{transcript}"
                    ),
                }
            ],
        )
        new_summary = (completion.content[0].text or "").strip()
        if new_summary:
            await asyncio.to_thread(
                user_store.update_session_summary, prev_session_id, new_summary
            )
            logger.info("Upgraded session summary for %s", prev_session_id)
    except Exception:
        logger.exception("Failed to upgrade session summary for %s", prev_session_id)


# --- Server setup ---


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

    # Clone data repo if not present (check .git to avoid race between prewarm processes)
    if (DATA_REPO_PATH / ".git").exists():
        logger.info("Data repo already present at %s", DATA_REPO_PATH)
    else:
        lock = Path(str(DATA_REPO_PATH) + ".cloning")
        try:
            lock.mkdir(parents=True, exist_ok=False)
            logger.info("Cloning data repo to %s", DATA_REPO_PATH)
            subprocess.run(
                ["git", "clone", DATA_REPO_URL, str(DATA_REPO_PATH)],
                check=True,
                timeout=60,
            )
        except FileExistsError:
            logger.info("Another process is cloning data repo, waiting...")
            for _ in range(30):
                if (DATA_REPO_PATH / ".git").exists():
                    break
                import time

                time.sleep(1)
        finally:
            lock.rmdir() if lock.exists() else None

    # Initialize reader and cache rolling index
    reader = SnapshotReader(DATA_REPO_PATH)
    reader.get_rolling_index()
    proc.userdata["reader"] = reader


server.setup_fnc = prewarm


def _build_user_context(
    health: ServiceHealth,
    user_store: UserStore | None,
    device_id: str,
    ip_address: str | None,
) -> tuple[bool, list[str], str | None]:
    """Check user profile and build context parts for LLM instructions.

    Returns (needs_onboarding, context_parts, user_name).
    """
    needs_onboarding = False
    context_parts: list[str] = []
    user_name = None

    if not user_store or device_id.startswith("unknown-"):
        return needs_onboarding, context_parts, user_name

    profile = health.check_service_sync("supabase", user_store.get_profile, device_id)
    if profile:
        user_name = profile.get("name")
        profile_context = user_store.format_profile_context(profile)
        if profile_context:
            context_parts.append(f"## Current user\n{profile_context}")

        sessions = (
            health.check_service_sync(
                "supabase", user_store.get_recent_sessions, device_id, 5
            )
            or []
        )
        session_context = user_store.format_session_context(sessions)
        if session_context:
            context_parts.append(
                f"## Recent sessions\n{session_context}\n"
                "When the user asks about previous conversations, reference "
                "these summaries. Never say you don't have access to prior "
                "conversations."
            )

        # Background: upgrade last session's placeholder summary with LLM
        if sessions:
            _upgrade_task = asyncio.create_task(  # noqa: RUF006
                health.check_service(
                    "summarizer",
                    _upgrade_session_summary(sessions[-1], user_store),
                ),
                name="upgrade_session_summary",
            )
    elif health.get_state("supabase").status.value == "healthy":
        # Profile query succeeded but returned None — new user
        needs_onboarding = True
        health.check_service_sync(
            "supabase",
            user_store.save_profile,
            device_id=device_id,
            ip_address=ip_address,
        )
        context_parts.append(
            "## New user\n"
            "This user has never spoken to you before. You MUST complete onboarding "
            "before answering any other questions. Follow the onboarding script in your "
            "instructions exactly — one question at a time. Do not skip onboarding even "
            "if the user asks you something else first."
        )

    return needs_onboarding, context_parts, user_name


def _build_data_context(reader: SnapshotReader) -> list[str]:
    """Build context parts from snapshot data (grades overview, available dates)."""
    context_parts: list[str] = []

    class_overview = summarize_all_classes(reader)
    if class_overview:
        context_parts.append(f"## Current grades\n{class_overview}")

    available_dates = reader.list_snapshot_dates()
    if available_dates:
        day_names = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        annotated = []
        for d in available_dates:
            try:
                parsed = date.fromisoformat(d)
                annotated.append(f"{d} ({day_names[parsed.weekday()]})")
            except ValueError:
                annotated.append(d)
        dates_str = ", ".join(annotated)
        context_parts.append(
            f"## Available snapshot dates\n"
            f"Data exists for these dates only: {dates_str}\n"
            f"Use the day names to resolve relative date references like 'last Friday'. "
            f"Never claim data is unavailable for a date in this list."
        )

    return context_parts


def _configure_tts(persona: dict):
    """Create TTS instance based on persona provider config."""
    tts_provider = persona.get("tts_provider", "cartesia")
    if tts_provider == "elevenlabs" and persona.get("elevenlabs_voice_id"):
        return elevenlabs.TTS(
            voice_id=persona["elevenlabs_voice_id"],
            voice_settings=elevenlabs.VoiceSettings(
                stability=float(persona.get("elevenlabs_stability", 0.5)),
                similarity_boost=float(persona.get("elevenlabs_similarity", 0.75)),
                speed=float(persona.get("elevenlabs_speed", 0.85)),
            ),
        )
    return inference.TTS(
        model=persona.get("tts_model", "cartesia/sonic-3"),
        voice=persona.get("tts_voice", "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"),
    )


async def _start_avatar(health: ServiceHealth, persona: dict, session, room) -> None:
    """Start avatar session if configured (optional, non-fatal)."""
    avatar_provider = persona.get("avatar_provider")
    if avatar_provider == "hedra" and persona.get("hedra_avatar_id"):
        avatar = hedra.AvatarSession(avatar_id=persona["hedra_avatar_id"])
        await health.check_service("avatar", avatar.start(session, room=room))
    elif avatar_provider == "lemonslice" and persona.get("lemonslice_image_url"):
        from livekit.plugins import lemonslice

        avatar = lemonslice.AvatarSession(
            agent_image_url=persona["lemonslice_image_url"],
            agent_prompt=persona.get("lemonslice_agent_prompt", ""),
        )
        await health.check_service("avatar", avatar.start(session, room=room))


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    # Initialize service health monitor
    health = ServiceHealth()
    health.register("stt", ServiceTier.CRITICAL)
    health.register("llm", ServiceTier.CRITICAL)
    health.register("tts", ServiceTier.CRITICAL)
    health.register("supabase", ServiceTier.IMPORTANT)
    health.register("git", ServiceTier.IMPORTANT)
    health.register("avatar", ServiceTier.OPTIONAL)
    health.register("summarizer", ServiceTier.OPTIONAL)

    # Refresh data repo for latest scrapes
    reader: SnapshotReader = ctx.proc.userdata["reader"]
    health.check_service_sync("git", reader.refresh)

    # Persona will be loaded after participant connects (to read metadata)

    # Set up user store
    supabase_client = health.check_service_sync("supabase", get_supabase_client)
    user_store = UserStore(supabase_client) if supabase_client else None

    # Get device ID and persona from participant (set by frontend via token request)
    await ctx.connect()
    try:
        participant = await ctx.wait_for_participant()
        device_id = participant.identity
        metadata = json.loads(participant.metadata) if participant.metadata else {}
        persona_name = metadata.get("persona") or None
        ip_address = participant.attributes.get("ip_address")
    except Exception:
        device_id = f"unknown-{ctx.room.name}"
        persona_name = None
        ip_address = None
        logger.warning("Could not get participant identity, using %s", device_id)

    # Load persona (participant choice overrides config default)
    persona = load_persona(persona_name)

    # Build user and data context
    needs_onboarding, context_parts, user_name = _build_user_context(
        health, user_store, device_id, ip_address
    )
    context_parts.extend(_build_data_context(reader))

    # Inject service health warnings into context
    health_warnings = health.session_warnings()
    if health_warnings:
        context_parts.append(
            "## Service status\n"
            + "\n".join(health_warnings)
            + "\nInform the user if they ask about affected features."
        )

    # Prepend context to persona instructions (system-level, not conversation history)
    instructions = persona["instructions"]
    if context_parts:
        instructions = instructions + "\n\n" + "\n\n".join(context_parts)

    tts = _configure_tts(persona)

    session_id = str(uuid.uuid4())
    session_data = SessionData(
        reader=reader,
        user_store=user_store,
        device_id=device_id,
        session_id=session_id,
        needs_onboarding=needs_onboarding,
    )

    # Validate API keys before creating session
    if not os.getenv("DEEPGRAM_API_KEY"):
        health.mark_failed("stt", "DEEPGRAM_API_KEY not set")
    else:
        health.mark_healthy("stt")

    if not os.getenv("ANTHROPIC_API_KEY"):
        health.mark_failed("llm", "ANTHROPIC_API_KEY not set")
    else:
        health.mark_healthy("llm")

    # Check if critical services are available before session start
    ok, reasons = health.can_start_session()
    if not ok:
        logger.error("Cannot start session: %s", reasons)
        return

    session = AgentSession[SessionData](
        userdata=session_data,
        stt=deepgram.STT(model="nova-3", language="multi"),
        llm=anthropic.LLM(
            model="claude-sonnet-4-6",
            temperature=persona.get("llm_temperature", 0.7),
        ),
        tts=tts,
        turn_handling={"turn_detection": MultilingualModel()},
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    # TODO: Re-enable avatar once Hedra blocking issue is resolved.
    # Hedra avatar blocks audio output pipeline if video track never publishes.
    # await _start_avatar(health, persona, session, ctx.room)

    await session.start(
        agent=Assistant(instructions=instructions),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind
                    == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC()
                ),
            ),
        ),
    )

    # Save messages incrementally as they happen
    if user_store:

        @session.on("conversation_item_added")
        def _on_conversation_item(event):
            try:
                item = event.item
                role = getattr(item, "role", None)
                text = getattr(item, "text_content", None)
                if role in ("user", "assistant") and text and text.strip():
                    user_store.save_message(device_id, session_id, role, text)
            except Exception:
                logger.exception("Failed to save conversation item")

    # Greet or onboard
    greeting = persona.get("greeting")
    if needs_onboarding:
        onboarding_greeting = (
            f"{greeting} Before we get started, what's your name?"
            if greeting
            else "Hey hey! I'm Sally Schoolwork! Before we get started, what's your name?"
        )
        await session.say(onboarding_greeting)
    else:
        if greeting:
            personalized = f"Hey {user_name}! {greeting}" if user_name else greeting
            await session.say(personalized)
        else:
            await session.generate_reply(
                instructions="Greet the user using your catchphrase greeting. Stay in character. If you know their name from the context, use it."
            )

    # Build class keyword map dynamically from snapshot data (not hardcoded)
    _class_keywords: dict[str, str] = {}
    index = reader.get_rolling_index()
    latest = index.latest_snapshot()
    if latest:
        for slug, cls in latest.classes.items():
            _class_keywords[slug] = cls.course
            for word in cls.course.lower().split():
                if len(word) > 2 and word not in _class_keywords:
                    _class_keywords[word] = cls.course

    # Save session summary on disconnect.
    # Synchronous — no asyncio involvement, safe to call from close event handler.
    # session.once("close") fires per-session on participant disconnect.
    # ctx.add_shutdown_callback is a last-resort fallback for process exit.
    _session_saved = False

    def _save_session_history():
        nonlocal _session_saved
        if _session_saved:
            return
        _session_saved = True
        if not user_store:
            return
        try:
            saved = user_store.get_session_messages(session_id)
            if not saved:
                logger.info("No messages for session %s", session_id)
                return

            msg_count = len(saved)
            user_text = " ".join(
                m["content"] for m in saved if m.get("role") == "user"
            ).lower()

            seen: set[str] = set()
            classes_mentioned = []
            for kw, name in _class_keywords.items():
                if kw in user_text and name not in seen:
                    classes_mentioned.append(name)
                    seen.add(name)

            summary = (
                f"Discussed {', '.join(classes_mentioned)} ({msg_count} messages)."
                if classes_mentioned
                else f"Conversation with {msg_count} messages."
            )
            user_store.save_session(
                device_id=device_id,
                session_id=session_id,
                summary=summary,
                classes_mentioned=classes_mentioned or None,
            )
            logger.info("Session saved for %s: %s", device_id, summary)
        except Exception:
            logger.exception("Failed to save session history")

    def _on_close(_event):
        _save_session_history()
        logger.info(health.summary())

    session.once("close", _on_close)

    async def _shutdown_fallback():
        _save_session_history()

    ctx.add_shutdown_callback(_shutdown_fallback)


if __name__ == "__main__":
    cli.run_app(server)
