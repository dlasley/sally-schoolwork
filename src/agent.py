import json
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    ChatContext,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    inference,
    room_io,
)
from livekit.plugins import elevenlabs, hedra, noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from data.analysis import (
    diff_snapshots,
    find_assignment,
    get_category_breakdown,
    get_comprehensive_summary,
    get_deleted_assignments,
    get_grade_trend,
    get_modified_assignments,
    list_flagged_assignments,
    summarize_all_classes,
    summarize_changes,
    summarize_class,
)
from data.snapshot_reader import SnapshotReader
from data.user_store import UserStore, get_supabase_client

logger = logging.getLogger("agent")

load_dotenv(".env.local")

DATA_REPO_URL = os.getenv(
    "DATA_REPO_URL", "git@github.com:dlasley/table-mutation-data.git"
)
DATA_REPO_PATH = Path(os.getenv("DATA_REPO_PATH", "./data-repo"))


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
    from datetime import datetime

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

    async def _navigate_browser(self, date: str = "", slug: str = "") -> None:
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

            payload = json.dumps(
                {"view": "day" if date else "calendar", "date": date, "className": slug}
            )
            await room.local_participant.perform_rpc(
                destination_identity=target,
                method="navigateTo",
                payload=payload,
                response_timeout=5.0,
            )
        except Exception:
            logger.debug("Navigation RPC failed", exc_info=True)

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
            return f"Could not find a class matching '{class_name}'. Ask the user to clarify."
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
    ):
        """Get a summary of a specific class including current grade, assignment count, and teacher.

        Use this tool when the user asks about a specific class grade or class details.

        Args:
            class_name: The name of the class to look up. Can be a partial name like "geo" for Geometry.
        """
        reader = context.userdata.reader
        slug = reader.resolve_slug(class_name)
        if not slug:
            return f"Could not find a class matching '{class_name}'. Ask the user to clarify."
        coords = reader.latest_snapshot_coords()
        if coords:
            await self._navigate_browser(date=coords[0], slug=slug)
        return summarize_class(reader, slug)

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
                return f"Could not find a class matching '{class_name}'. Ask the user to clarify."
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
            return f"Could not find a class matching '{class_name}'. Ask the user to clarify."
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
            return f"Could not find a class matching '{class_name}'. Ask the user to clarify."

        # Find the latest snapshot time for each date
        times1 = reader.list_snapshot_times(date1)
        times2 = reader.list_snapshot_times(date2)
        if not times1:
            return f"No snapshot data found for {date1}."
        if not times2:
            return f"No snapshot data found for {date2}."

        await self._navigate_browser(date=date2, slug=slug)
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
                return f"Could not find a class matching '{class_name}'. Ask the user to clarify."
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
            return f"Could not find a class matching '{class_name}'. Ask the user to clarify."
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
            return f"Could not find a class matching '{class_name}'. Ask the user to clarify."
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
                return f"Could not find a class matching '{class_name}'. Ask the user to clarify."
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
                return f"Could not find a class matching '{class_name}'. Ask the user to clarify."
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
            "I can help with:\n"
            "- Current grades and class summaries\n"
            "- Individual assignment scores and details\n"
            "- Recent changes — what's been added, modified, or deleted\n"
            "- Score change history — which assignments had grades updated\n"
            "- Missing, late, or flagged assignments\n"
            "- Grade trends over time\n"
            "- Category breakdowns (quizzes vs homework, etc.)\n"
            "- Overall summaries and patterns across all classes\n"
            "- Comparing assignments between two dates\n"
            "Just ask me anything about grades or assignments!"
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
    async def save_user_profile(
        self,
        context: RunContext[SessionData],
        name: str = "",
        relation_to_student: str = "",
        priorities: str = "",
        communication_preferences: str = "",
    ):
        """Save the user's profile information collected during onboarding.

        Call this tool after you have collected the user's information during
        the onboarding conversation. You may call it multiple times as you
        learn each piece of information.

        Args:
            name: The user's preferred name.
            relation_to_student: Their relation to the student — parent, the student, grandparent, etc.
            priorities: Comma-separated list of what they care about — missing assignments, grade trends, etc.
            communication_preferences: Whether they prefer brief or detailed answers.
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
            communication_preferences=communication_preferences or None,
        )
        context.userdata.needs_onboarding = False
        return "Profile saved."


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


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    # Refresh data repo for latest scrapes
    reader: SnapshotReader = ctx.proc.userdata["reader"]
    reader.refresh()

    # Persona will be loaded after participant connects (to read metadata)

    # Set up user store
    supabase_client = get_supabase_client()
    user_store = UserStore(supabase_client) if supabase_client else None

    # Get device ID and persona from participant (set by frontend via token request)
    await ctx.connect()
    try:
        participant = await ctx.wait_for_participant()
        device_id = participant.identity
        metadata = json.loads(participant.metadata) if participant.metadata else {}
        persona_name = metadata.get("persona") or None
    except Exception:
        device_id = f"unknown-{ctx.room.name}"
        persona_name = None
        logger.warning("Could not get participant identity, using %s", device_id)

    # Load persona (participant choice overrides config default)
    persona = load_persona(persona_name)

    # Check user profile and build context
    needs_onboarding = False
    context_parts = []

    if user_store:
        profile = user_store.get_profile(device_id)
        if profile:
            # Returning user — add profile and session history to instructions
            profile_context = user_store.format_profile_context(profile)
            if profile_context:
                context_parts.append(f"## Current user\n{profile_context}")

            sessions = user_store.get_recent_sessions(device_id, limit=5)
            session_context = user_store.format_session_context(sessions)
            if session_context:
                context_parts.append(f"## Recent sessions\n{session_context}")
        else:
            # New user — flag for onboarding
            needs_onboarding = True
            # Create a minimal profile so session_history FK works
            user_store.save_profile(device_id=device_id)

    # Add class overview
    class_overview = summarize_all_classes(reader)
    if class_overview:
        context_parts.append(f"## Current grades\n{class_overview}")

    # Prepend context to persona instructions (system-level, not conversation history)
    instructions = persona["instructions"]
    if context_parts:
        instructions = instructions + "\n\n" + "\n\n".join(context_parts)

    # Configure TTS based on provider
    tts_provider = persona.get("tts_provider", "cartesia")
    if tts_provider == "elevenlabs" and persona.get("elevenlabs_voice_id"):
        tts = elevenlabs.TTS(
            voice_id=persona["elevenlabs_voice_id"],
            voice_settings=elevenlabs.VoiceSettings(
                stability=float(persona.get("elevenlabs_stability", 0.5)),
                similarity_boost=float(persona.get("elevenlabs_similarity", 0.75)),
                speed=float(persona.get("elevenlabs_speed", 0.85)),
            ),
        )
    else:
        tts = inference.TTS(
            model=persona.get("tts_model", "cartesia/sonic-3"),
            voice=persona.get("tts_voice", "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"),
        )

    session_id = str(uuid.uuid4())
    session_data = SessionData(
        reader=reader,
        user_store=user_store,
        device_id=device_id,
        session_id=session_id,
        needs_onboarding=needs_onboarding,
    )

    session = AgentSession[SessionData](
        userdata=session_data,
        stt=inference.STT(model="deepgram/nova-3", language="multi"),
        llm=inference.LLM(
            model="openai/gpt-4.1",
            extra_kwargs={"temperature": persona.get("llm_temperature", 0.7)},
        ),
        tts=tts,
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    # Start avatar if configured (non-fatal — agent works without it)
    avatar_provider = persona.get("avatar_provider")
    try:
        if avatar_provider == "hedra" and persona.get("hedra_avatar_id"):
            avatar = hedra.AvatarSession(avatar_id=persona["hedra_avatar_id"])
            await avatar.start(session, room=ctx.room)
        elif avatar_provider == "lemonslice" and persona.get("lemonslice_image_url"):
            from livekit.plugins import lemonslice

            avatar = lemonslice.AvatarSession(
                agent_image_url=persona["lemonslice_image_url"],
                agent_prompt=persona.get("lemonslice_agent_prompt", ""),
            )
            await avatar.start(session, room=ctx.room)
    except Exception:
        logger.exception(
            "%s avatar failed to start, continuing without avatar",
            avatar_provider,
        )

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
        if greeting:
            await session.say(greeting)
        await session.generate_reply(
            instructions="The user is new. Mention you have a few quick questions to get to know them. Then ask ONLY their name — nothing else yet."
        )
    else:
        if greeting:
            await session.say(greeting)
        else:
            await session.generate_reply(
                instructions="Greet the user using your catchphrase greeting. Stay in character. If you know their name from the context, use it."
            )

    # Save session summary on disconnect
    async def on_session_end():
        if not user_store:
            return
        try:
            # Try chat context first, fall back to saved messages
            transcript_parts = []
            try:
                chat_ctx = session.chat_ctx
                for item in chat_ctx.items:
                    role = getattr(item, "role", None)
                    content = getattr(item, "content", None)
                    if role in ("user", "assistant") and content:
                        text = content[0] if isinstance(content, list) else content
                        if isinstance(text, str) and text.strip():
                            transcript_parts.append(f"{role}: {text}")
            except Exception:
                pass

            # Fall back to saved messages from Supabase
            if len(transcript_parts) < 2:
                saved = user_store.get_session_messages(session_id)
                transcript_parts = [f"{m['role']}: {m['content']}" for m in saved]

            if len(transcript_parts) < 2:
                logger.info("Too few messages to summarize for %s", device_id)
                return

            transcript = "\n".join(transcript_parts)

            # Summarize via LLM — ask for structured output
            summary_ctx = ChatContext()
            summary_ctx.add_message(
                role="user",
                content=(
                    "Summarize this conversation. Respond in exactly this format:\n"
                    "SUMMARY: (2-3 sentence summary of what was discussed)\n"
                    "TOPICS: (comma-separated list of topics discussed)\n"
                    "CLASSES: (comma-separated list of class names mentioned, or 'none')\n\n"
                    f"{transcript}"
                ),
            )

            response_parts = []
            llm_stream = session.llm.chat(chat_ctx=summary_ctx)
            async for chunk in llm_stream:
                text = None
                if hasattr(chunk, "choices") and chunk.choices:
                    delta = chunk.choices[0].delta
                    text = getattr(delta, "content", None)
                elif hasattr(chunk, "content"):
                    text = chunk.content
                if text:
                    response_parts.append(text)
            await llm_stream.aclose()

            raw = "".join(response_parts).strip()
            if not raw:
                logger.warning("Empty summary generated for %s", device_id)
                return

            # Parse structured response
            summary = raw
            topics = []
            classes = []
            for line in raw.split("\n"):
                line = line.strip()
                if line.upper().startswith("SUMMARY:"):
                    summary = line[8:].strip()
                elif line.upper().startswith("TOPICS:"):
                    topics = [t.strip() for t in line[7:].split(",") if t.strip()]
                elif line.upper().startswith("CLASSES:"):
                    classes = [
                        c.strip()
                        for c in line[8:].split(",")
                        if c.strip() and c.strip().lower() != "none"
                    ]

            user_store.save_session(
                device_id=device_id,
                summary=summary,
                topics_discussed=topics or None,
                classes_mentioned=classes or None,
            )
            logger.info("Session summary saved for %s", device_id)
        except Exception:
            logger.exception("Failed to save session summary")

    ctx.add_shutdown_callback(on_session_end)


if __name__ == "__main__":
    cli.run_app(server)
