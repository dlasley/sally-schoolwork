"""Sally Schoolwork agent — entrypoint and session orchestrator."""

import json
import logging
import os
import subprocess
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    cli,
    room_io,
)
from livekit.plugins import anthropic, deepgram, noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from assistant import Assistant, SessionData
from data.snapshot_reader import SnapshotReader
from data.user_store import UserStore, get_supabase_client
from persona import load_persona
from service_health import ServiceHealth, ServiceTier
from session_lifecycle import (
    build_class_keywords,
    build_data_context,
    build_user_context,
    configure_tts,
    deliver_greeting,
    save_session_history,
    start_avatar,
    validate_api_keys,
)

logger = logging.getLogger("agent")

# Suppress noisy HTTP/2 debug loggers that drown out agent logs
for _noisy in ("hpack", "httpcore", "httpx", "h2"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

load_dotenv(".env.local")

DATA_REPO_URL = os.getenv(
    "DATA_REPO_URL", "git@github.com:dlasley/table-mutation-data.git"
)
DATA_REPO_PATH = Path(os.getenv("DATA_REPO_PATH", "./data-repo"))


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
                time.sleep(1)
        finally:
            lock.rmdir() if lock.exists() else None

    # Initialize reader and cache rolling index
    reader = SnapshotReader(DATA_REPO_PATH)
    reader.get_rolling_index()
    proc.userdata["reader"] = reader


server.setup_fnc = prewarm


# --- Session orchestrator ---


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

    # Set up user store
    supabase_client = health.check_service_sync("supabase", get_supabase_client)
    user_store = UserStore(supabase_client) if supabase_client else None

    # Get device ID and persona from participant
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

    # Load persona and build context
    persona = load_persona(persona_name)
    needs_onboarding, context_parts, user_name = build_user_context(
        health, user_store, device_id, ip_address
    )
    context_parts.extend(build_data_context(reader))

    # Inject service health warnings
    health_warnings = health.session_warnings()
    if health_warnings:
        context_parts.append(
            "## Service status\n"
            + "\n".join(health_warnings)
            + "\nInform the user if they ask about affected features."
        )

    # Assemble instructions
    instructions = persona["instructions"]
    if context_parts:
        instructions = instructions + "\n\n" + "\n\n".join(context_parts)

    tts = configure_tts(persona)

    # Validate API keys
    validate_api_keys(health, persona)
    ok, reasons = health.can_start_session()
    if not ok:
        logger.error("Cannot start session: %s", reasons)
        return

    # Create session
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
    await start_avatar(health, persona, session, ctx.room)

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

    # Save messages incrementally
    if user_store:

        @session.on("conversation_item_added")
        def _on_conversation_item(event):
            item = event.item
            role = getattr(item, "role", None)
            text = getattr(item, "text_content", None)
            if role in ("user", "assistant") and text and text.strip():
                health.check_service_sync(
                    "supabase",
                    user_store.save_message,
                    device_id,
                    session_id,
                    role,
                    text,
                )

    # Greet or onboard
    await deliver_greeting(session, persona, needs_onboarding, user_name)

    # Register session close handler
    class_keywords = build_class_keywords(reader)
    _session_saved = False

    def _on_close(_event):
        nonlocal _session_saved
        if _session_saved:
            return
        _session_saved = True
        if user_store:
            save_session_history(user_store, device_id, session_id, class_keywords)
        logger.info(health.summary())

    session.once("close", _on_close)

    async def _shutdown_fallback():
        _on_close(None)

    ctx.add_shutdown_callback(_shutdown_fallback)


if __name__ == "__main__":
    cli.run_app(server)
