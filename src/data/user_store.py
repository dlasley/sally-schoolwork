"""User profile and session history persistence via Supabase."""

from __future__ import annotations

import logging
import os

from supabase import Client, create_client

logger = logging.getLogger("user_store")


def get_supabase_client() -> Client | None:
    """Create a Supabase client from environment variables."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        logger.warning("SUPABASE_URL or SUPABASE_KEY not set, user profiles disabled")
        return None
    return create_client(url, key)


class UserStore:
    """Read and write user profiles and session history."""

    def __init__(self, client: Client) -> None:
        self.client = client

    def get_profile(self, device_id: str) -> dict | None:
        """Fetch user profile by device ID. Returns None if not found."""
        result = (
            self.client.table("user_profiles")
            .select("*")
            .eq("device_id", device_id)
            .execute()
        )
        if result.data:
            return result.data[0]
        return None

    def save_profile(
        self,
        device_id: str,
        name: str | None = None,
        relation_to_student: str | None = None,
        priorities: list[str] | None = None,
        communication_preferences: str | None = None,
    ) -> dict:
        """Create or update a user profile."""
        data: dict = {"device_id": device_id}
        if name is not None:
            data["name"] = name
        if relation_to_student is not None:
            data["relation_to_student"] = relation_to_student
        if priorities is not None:
            data["priorities"] = priorities
        if communication_preferences is not None:
            data["communication_preferences"] = communication_preferences

        result = (
            self.client.table("user_profiles")
            .upsert(data, on_conflict="device_id")
            .execute()
        )
        return result.data[0] if result.data else data

    def get_recent_sessions(self, device_id: str, limit: int = 5) -> list[dict]:
        """Fetch the most recent session summaries for a device."""
        result = (
            self.client.table("session_history")
            .select("*")
            .eq("device_id", device_id)
            .order("session_date", desc=True)
            .limit(limit)
            .execute()
        )
        return list(reversed(result.data)) if result.data else []

    def save_session(
        self,
        device_id: str,
        summary: str,
        topics_discussed: list[str] | None = None,
        classes_mentioned: list[str] | None = None,
    ) -> None:
        """Save a session summary."""
        data: dict = {
            "device_id": device_id,
            "summary": summary,
        }
        if topics_discussed:
            data["topics_discussed"] = topics_discussed
        if classes_mentioned:
            data["classes_mentioned"] = classes_mentioned

        self.client.table("session_history").insert(data).execute()

    def save_message(
        self,
        device_id: str,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        """Save a single conversation message (incremental, per-turn)."""
        self.client.table("session_messages").insert(
            {
                "device_id": device_id,
                "session_id": session_id,
                "role": role,
                "content": content,
            }
        ).execute()

    def get_session_messages(self, session_id: str) -> list[dict]:
        """Fetch all messages for a session."""
        result = (
            self.client.table("session_messages")
            .select("*")
            .eq("session_id", session_id)
            .order("created_at")
            .execute()
        )
        return result.data if result.data else []

    def format_profile_context(self, profile: dict) -> str:
        """Format a user profile as context for the LLM."""
        parts = []
        if profile.get("name"):
            parts.append(f"The user's name is {profile['name']}.")
        if profile.get("relation_to_student"):
            parts.append(f"They are the student's {profile['relation_to_student']}.")
        if profile.get("communication_preferences"):
            parts.append(f"They prefer {profile['communication_preferences']} answers.")
        if profile.get("priorities"):
            parts.append(f"They care most about: {', '.join(profile['priorities'])}.")
        return " ".join(parts)

    def format_session_context(self, sessions: list[dict]) -> str:
        """Format recent session summaries as context for the LLM."""
        if not sessions:
            return ""
        lines = ["Previous conversations:"]
        for s in sessions:
            date = s.get("session_date", "")[:10]
            lines.append(f"- {date}: {s['summary']}")
        return "\n".join(lines)
