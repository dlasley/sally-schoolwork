"""Background session summary upgrade via LLM."""

import asyncio
import logging
import os
import re

logger = logging.getLogger("deferred_summary")


def is_placeholder_summary(summary: str) -> bool:
    """Check if a summary matches the placeholder pattern from session close."""
    return bool(
        re.match(
            r"^(Discussed .+\(\d+ messages\)\.|Conversation with \d+ messages\.)",
            summary.strip(),
        )
    )


async def upgrade_session_summary(last_session: dict, user_store) -> None:
    """Upgrade a placeholder summary with an LLM-generated one.

    Runs as a background task at session start. All blocking Supabase calls
    are wrapped in asyncio.to_thread() to avoid blocking the event loop.
    """
    import anthropic as anthropic_sdk

    prev_session_id = last_session.get("session_id")
    if not prev_session_id:
        return
    if not is_placeholder_summary(last_session.get("summary", "")):
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
