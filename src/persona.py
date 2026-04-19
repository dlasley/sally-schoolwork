"""Persona config loading and template merging."""

import json
import os
from datetime import datetime
from pathlib import Path


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
        "simli_face_id": os.getenv("SIMLI_FACE_ID"),
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
