#!/usr/bin/env python
"""Check avatar persona status and configuration."""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load env vars
env_path = Path(__file__).parent / ".env.local"
if env_path.exists():
    load_dotenv(env_path)

# Load config
config_path = Path(__file__).parent / "personas" / "config.json"
with open(config_path) as f:
    config = json.load(f)

# Load local config if exists
local_path = Path(__file__).parent / "personas" / "config.local.json"
local_config = {}
if local_path.exists():
    with open(local_path) as f:
        local_config = json.load(f)

print("\n" + "=" * 70)
print("AVATAR PERSONA STATUS REPORT")
print("=" * 70)

# Check critical API keys
print("\n📋 CRITICAL API KEYS:")
critical = {
    "DEEPGRAM_API_KEY": "Speech-to-text",
    "ANTHROPIC_API_KEY": "LLM (Claude)",
    "ELEVEN_API_KEY": "ElevenLabs TTS",
}
for key, desc in critical.items():
    val = os.getenv(key)
    status = "✓" if val else "✗"
    print(f"  {status} {key:25} ({desc})")
    if val:
        print(f"       → {val[:20]}...")

print("\n" + "-" * 70)
print("PERSONA CONFIGURATIONS:")
print("-" * 70)

for persona_name in ["avatar1", "avatar2", "avatar3", "demo"]:
    persona = config["personas"].get(persona_name)
    if not persona:
        continue

    print(f"\n🎭 {persona_name.upper()}")
    print(f"   Provider: {persona.get('avatar_provider', 'none')}")
    print(f"   TTS: {persona.get('tts_provider', 'cartesia')}")
    print(f"   Temperature: {persona.get('llm_temperature', 'default')}")

    # Get persona-specific local config
    persona_local = local_config.get("personas", {}).get(persona_name, {})

    # Avatar-specific config
    if persona.get("avatar_provider") == "hedra":
        avatar_id = persona_local.get("hedra_avatar_id") or os.getenv("HEDRA_AVATAR_ID")
        hedra_key = os.getenv("HEDRA_API_KEY")
        status = "✓" if (avatar_id and hedra_key) else "⚠"
        print(f"   {status} Hedra Avatar ID: {avatar_id[:15] + '...' if avatar_id else 'NOT CONFIGURED'}")
        print(f"   {status} HEDRA_API_KEY: {'SET' if hedra_key else 'NOT SET'}")

    elif persona.get("avatar_provider") == "lemonslice":
        image_url = persona_local.get("lemonslice_image_url") or os.getenv("LEMONSLICE_IMAGE_URL")
        lemonslice_key = os.getenv("LEMONSLICE_API_KEY")
        status = "✓" if (image_url and lemonslice_key) else "⚠"
        print(f"   {status} LemonSlice Image: {image_url[:30] + '...' if image_url else 'NOT CONFIGURED'}")
        print(f"   {status} LEMONSLICE_API_KEY: {'SET' if lemonslice_key else 'NOT SET (CREDITS MAY BE EXHAUSTED)'}")

    elif persona.get("avatar_provider") == "simli":
        face_id = persona_local.get("simli_face_id") or os.getenv("SIMLI_FACE_ID")
        simli_key = os.getenv("SIMLI_API_KEY")
        status = "✓" if (face_id and simli_key) else "⚠"
        print(f"   {status} Simli Face ID: {face_id[:15] + '...' if face_id else 'NOT CONFIGURED'}")
        print(f"   {status} SIMLI_API_KEY: {'SET' if simli_key else 'NOT SET'}")

    # TTS config
    if persona.get("tts_provider") == "elevenlabs":
        voice_id = persona_local.get("elevenlabs_voice_id") or os.getenv("ELEVENLABS_VOICE_ID")
        eleven_key = os.getenv("ELEVEN_API_KEY")
        status = "✓" if (voice_id and eleven_key) else "⚠"
        print(f"   {status} ElevenLabs Voice: {voice_id[:15] + '...' if voice_id else 'NOT CONFIGURED'}")
        print(f"   {status} ELEVEN_API_KEY: {'SET' if eleven_key else 'NOT SET'}")

print("\n" + "=" * 70)
print("SUMMARY:")
print("=" * 70)

avatar1_local = local_config.get("personas", {}).get("avatar1", {})
avatar2_local = local_config.get("personas", {}).get("avatar2", {})
avatar3_local = local_config.get("personas", {}).get("avatar3", {})
demo_local = local_config.get("personas", {}).get("demo", {})

avatar1_ready = (
    os.getenv("SIMLI_API_KEY")
    and (avatar1_local.get("simli_face_id") or os.getenv("SIMLI_FACE_ID"))
    and os.getenv("ELEVEN_API_KEY")
    and (avatar1_local.get("elevenlabs_voice_id") or os.getenv("ELEVENLABS_VOICE_ID"))
)

lemonslice_ready = (
    os.getenv("LEMONSLICE_API_KEY")
    and (avatar2_local.get("lemonslice_image_url") or os.getenv("LEMONSLICE_IMAGE_URL"))
    and os.getenv("ELEVEN_API_KEY")
)

simli_ready = (
    os.getenv("SIMLI_API_KEY")
    and (demo_local.get("simli_face_id") or os.getenv("SIMLI_FACE_ID"))
    and os.getenv("ELEVEN_API_KEY")
)

print(f"\n🎬 avatar1 (Simli):      {'✓ READY' if avatar1_ready else '⚠ MISSING CONFIG'}")
print(f"🎬 avatar2 (LemonSlice): {'✓ READY' if lemonslice_ready else '⚠ MISSING CONFIG'}")
print(f"🎬 avatar3 (LemonSlice): {'✓ READY' if lemonslice_ready else '⚠ MISSING CONFIG'}")
print(f"🎬 demo (Simli):         {'✓ READY' if simli_ready else '⚠ MISSING CONFIG'}")

print("\n" + "=" * 70 + "\n")
