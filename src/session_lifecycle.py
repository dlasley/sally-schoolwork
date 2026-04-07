"""Session setup and teardown helpers for the agent."""

import asyncio
import logging
import os
from datetime import date

from livekit.agents import inference
from livekit.plugins import elevenlabs, hedra

from data.analysis import summarize_all_classes
from data.snapshot_reader import SnapshotReader
from data.user_store import UserStore
from deferred_summary import upgrade_session_summary
from service_health import ServiceHealth

logger = logging.getLogger("agent")


def build_user_context(
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
                    upgrade_session_summary(sessions[-1], user_store),
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


def build_data_context(reader: SnapshotReader) -> list[str]:
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


def configure_tts(persona: dict):
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


async def start_avatar(health: ServiceHealth, persona: dict, session, room) -> None:
    """Start avatar session if configured (optional, non-fatal).

    For Hedra, validates the avatar asset exists before starting to prevent
    silent audio pipeline blocking (Hedra's plugin doesn't fail on 404 assets,
    it silently waits for a video track that never comes).
    """
    avatar_provider = persona.get("avatar_provider")
    if avatar_provider == "hedra" and persona.get("hedra_avatar_id"):
        avatar_id = persona["hedra_avatar_id"]
        avatar = hedra.AvatarSession(avatar_id=avatar_id)
        await health.check_service("avatar", avatar.start(session, room=room))
    elif avatar_provider == "simli" and persona.get("simli_face_id"):
        from livekit.plugins import simli

        avatar = simli.AvatarSession(
            simli_config=simli.SimliConfig(
                api_key=os.getenv("SIMLI_API_KEY", ""),
                face_id=persona["simli_face_id"],
            ),
        )
        await health.check_service("avatar", avatar.start(session, room=room))
    elif avatar_provider == "lemonslice" and persona.get("lemonslice_image_url"):
        from livekit.plugins import lemonslice

        avatar = lemonslice.AvatarSession(
            agent_image_url=persona["lemonslice_image_url"],
            agent_prompt=persona.get("lemonslice_agent_prompt", ""),
        )
        await health.check_service("avatar", avatar.start(session, room=room))


async def deliver_greeting(
    session, persona: dict, needs_onboarding: bool, user_name: str | None
) -> None:
    """Deliver the appropriate greeting or start onboarding."""
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


def build_class_keywords(reader: SnapshotReader) -> dict[str, str]:
    """Build class keyword map dynamically from snapshot data."""
    keywords: dict[str, str] = {}
    index = reader.get_rolling_index()
    latest = index.latest_snapshot()
    if latest:
        for slug, cls in latest.classes.items():
            keywords[slug] = cls.course
            for word in cls.course.lower().split():
                if len(word) > 2 and word not in keywords:
                    keywords[word] = cls.course
    return keywords


def save_session_history(
    user_store: UserStore,
    device_id: str,
    session_id: str,
    class_keywords: dict[str, str],
) -> None:
    """Save session summary on disconnect. Synchronous — safe for close handler."""
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
        for kw, name in class_keywords.items():
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


def validate_api_keys(health: ServiceHealth, persona: dict) -> None:
    """Validate required API keys and update health status."""
    if not os.getenv("DEEPGRAM_API_KEY"):
        health.mark_failed("stt", "DEEPGRAM_API_KEY not set")
    else:
        health.mark_healthy("stt")

    if not os.getenv("ANTHROPIC_API_KEY"):
        health.mark_failed("llm", "ANTHROPIC_API_KEY not set")
    else:
        health.mark_healthy("llm")

    tts_provider = persona.get("tts_provider", "cartesia")
    if tts_provider == "elevenlabs" and not os.getenv("ELEVEN_API_KEY"):
        health.mark_failed("tts", "ELEVEN_API_KEY not set")
    else:
        health.mark_healthy("tts")

    avatar_provider = persona.get("avatar_provider")
    if avatar_provider == "simli" and not os.getenv("SIMLI_API_KEY"):
        health.mark_failed("avatar", "SIMLI_API_KEY not set")
