"""Test avatar personas for configuration and API key validity."""

import json
import logging
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

logger = logging.getLogger("test_avatars")

# Load .env.local if it exists
env_path = Path(__file__).parent.parent / ".env.local"
if env_path.exists():
    load_dotenv(env_path)


class TestAvatarPersonas:
    """Test that all avatar personas are properly configured."""

    @pytest.fixture
    def config_data(self):
        """Load personas config."""
        config_path = Path(__file__).parent.parent / "personas" / "config.json"
        with open(config_path) as f:
            return json.load(f)

    @pytest.fixture
    def local_config_data(self):
        """Load local config (may not exist, return empty dict if missing)."""
        local_path = (
            Path(__file__).parent.parent / "personas" / "config.local.json"
        )
        if local_path.exists():
            with open(local_path) as f:
                return json.load(f)
        return {}

    def test_all_personas_defined(self, config_data):
        """Test that at least avatar1, avatar2, avatar3 are defined."""
        personas = config_data.get("personas", {})
        assert "avatar1" in personas, "avatar1 persona not defined"
        assert "avatar2" in personas, "avatar2 persona not defined"
        assert "avatar3" in personas, "avatar3 persona not defined"

    @pytest.mark.parametrize("persona_name", ["avatar1", "avatar2", "avatar3"])
    def test_persona_structure(self, persona_name, config_data):
        """Test that each persona has required fields."""
        persona = config_data["personas"][persona_name]
        assert "instructions" in persona, f"{persona_name}: missing 'instructions'"
        assert "greeting" in persona, f"{persona_name}: missing 'greeting'"
        assert "avatar_provider" in persona, f"{persona_name}: missing 'avatar_provider'"
        assert "tts_provider" in persona, f"{persona_name}: missing 'tts_provider'"
        assert (
            "llm_temperature" in persona
        ), f"{persona_name}: missing 'llm_temperature'"

    @pytest.mark.parametrize("persona_name", ["avatar1", "avatar2", "avatar3"])
    def test_persona_instructions_exist(self, persona_name, config_data):
        """Test that persona instruction files exist."""
        persona = config_data["personas"][persona_name]
        instructions_path = Path(__file__).parent.parent / persona["instructions"]
        assert (
            instructions_path.exists()
        ), f"{persona_name}: instructions file not found at {instructions_path}"
        assert (
            instructions_path.stat().st_size > 0
        ), f"{persona_name}: instructions file is empty"

    def test_avatar1_simli_config(self, config_data, local_config_data):
        """Test avatar1 (Simli) configuration and API key."""
        persona = config_data["personas"]["avatar1"]
        assert persona["avatar_provider"] == "simli"
        assert persona["tts_provider"] == "elevenlabs"

        # Check local config or env var for face ID
        face_id = local_config_data.get("personas", {}).get("avatar1", {}).get("simli_face_id") or os.getenv(
            "SIMLI_FACE_ID"
        )
        if face_id:
            logger.info(f"avatar1: Simli face ID found: {face_id[:10]}...")
        else:
            logger.warning("avatar1: No Simli face ID in config.local.json or SIMLI_FACE_ID env var")

        # Check for Simli API key
        simli_key = os.getenv("SIMLI_API_KEY")
        if simli_key:
            logger.info("avatar1: SIMLI_API_KEY found")
        else:
            logger.warning("avatar1: SIMLI_API_KEY not set")

        # Check for ElevenLabs API key
        eleven_key = os.getenv("ELEVEN_API_KEY")
        if eleven_key:
            logger.info("avatar1: ELEVEN_API_KEY found")
        else:
            logger.warning("avatar1: ELEVEN_API_KEY not set")

        # Check for voice ID
        voice_id = local_config_data.get("personas", {}).get("avatar1", {}).get("elevenlabs_voice_id") or os.getenv(
            "ELEVENLABS_VOICE_ID"
        )
        if voice_id:
            logger.info(f"avatar1: ElevenLabs voice ID found: {voice_id[:10]}...")
        else:
            logger.warning("avatar1: No ElevenLabs voice ID in config")

    def test_avatar2_lemonslice_config(self, config_data, local_config_data):
        """Test avatar2 (LemonSlice) configuration and API key."""
        persona = config_data["personas"]["avatar2"]
        assert persona["avatar_provider"] == "lemonslice"
        assert persona["tts_provider"] == "elevenlabs"

        # Check for image URL
        image_url = local_config_data.get("avatar2", {}).get("lemonslice_image_url") or os.getenv(
            "LEMONSLICE_IMAGE_URL"
        )
        if image_url:
            logger.info(f"avatar2: LemonSlice image URL found: {image_url[:50]}...")
        else:
            logger.warning("avatar2: No LemonSlice image URL in config")

        # Check for LemonSlice API key
        lemonslice_key = os.getenv("LEMONSLICE_API_KEY")
        if lemonslice_key:
            logger.info("avatar2: LEMONSLICE_API_KEY found")
        else:
            logger.warning("avatar2: LEMONSLICE_API_KEY not set (credits may be exhausted)")

        # Check for ElevenLabs
        eleven_key = os.getenv("ELEVEN_API_KEY")
        voice_id = local_config_data.get("avatar2", {}).get("elevenlabs_voice_id") or os.getenv(
            "ELEVENLABS_VOICE_ID_AVATAR2"
        )
        if eleven_key and voice_id:
            logger.info(f"avatar2: ElevenLabs configured")
        else:
            logger.warning("avatar2: ElevenLabs not fully configured")

    def test_avatar3_lemonslice_config(self, config_data, local_config_data):
        """Test avatar3 (LemonSlice) configuration and API key."""
        persona = config_data["personas"]["avatar3"]
        assert persona["avatar_provider"] == "lemonslice"
        assert persona["tts_provider"] == "elevenlabs"

        # Check for image URL
        image_url = local_config_data.get("avatar3", {}).get("lemonslice_image_url") or os.getenv(
            "LEMONSLICE_IMAGE_URL_AVATAR3"
        )
        if image_url:
            logger.info(f"avatar3: LemonSlice image URL found: {image_url[:50]}...")
        else:
            logger.warning("avatar3: No LemonSlice image URL in config")

        # Check for LemonSlice API key
        lemonslice_key = os.getenv("LEMONSLICE_API_KEY")
        if lemonslice_key:
            logger.info("avatar3: LEMONSLICE_API_KEY found")
        else:
            logger.warning("avatar3: LEMONSLICE_API_KEY not set (credits may be exhausted)")

        # Check for ElevenLabs
        eleven_key = os.getenv("ELEVEN_API_KEY")
        voice_id = local_config_data.get("avatar3", {}).get("elevenlabs_voice_id") or os.getenv(
            "ELEVENLABS_VOICE_ID_AVATAR3"
        )
        if eleven_key and voice_id:
            logger.info(f"avatar3: ElevenLabs configured")
        else:
            logger.warning("avatar3: ElevenLabs not fully configured")

    def test_required_api_keys_present(self):
        """Test that critical API keys are present."""
        # These are always required
        assert os.getenv("DEEPGRAM_API_KEY"), "DEEPGRAM_API_KEY not set (STT provider)"
        assert os.getenv("ANTHROPIC_API_KEY"), "ANTHROPIC_API_KEY not set (LLM provider)"
        assert os.getenv("ELEVEN_API_KEY"), "ELEVEN_API_KEY not set (TTS for avatars)"

        logger.info("✓ All critical API keys present")

    def test_avatar_providers_available(self):
        """Test that avatar provider libraries can be imported."""
        try:
            from livekit.plugins import simli
            logger.info("✓ simli plugin available")
        except ImportError:
            logger.error("✗ simli plugin not available")
            pytest.skip("simli plugin not installed")

        try:
            from livekit.plugins import lemonslice
            logger.info("✓ lemonslice plugin available")
        except ImportError:
            logger.error("✗ lemonslice plugin not available (non-critical)")

    def test_persona_files_are_not_empty(self, config_data):
        """Test that all persona markdown files have content."""
        for persona_name, persona in config_data["personas"].items():
            instructions_path = Path(__file__).parent.parent / persona["instructions"]
            if instructions_path.exists():
                with open(instructions_path) as f:
                    content = f.read().strip()
                    assert (
                        len(content) > 100
                    ), f"{persona_name}: instructions file suspiciously short ({len(content)} chars)"
                    logger.info(f"✓ {persona_name}: {len(content)} chars of instructions")
            else:
                logger.warning(f"⚠ {persona_name}: instructions file not found")

    def test_avatar_provider_consistency(self, config_data):
        """Test that avatar providers are consistent with expected values."""
        valid_providers = {"lemonslice", "simli", None}
        for persona_name, persona in config_data["personas"].items():
            provider = persona.get("avatar_provider")
            assert provider in valid_providers, (
                f"{persona_name}: unknown avatar provider '{provider}'"
            )
