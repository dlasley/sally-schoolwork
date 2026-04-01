# Voice Cloning Recording Guide

Reference for creating ElevenLabs voice clones for Sally Schoolwork personas.

## Quick start (Instant Clone — 1-2 minutes)

1. Record 1-2 minutes of clean audio (do NOT exceed 3 minutes)
2. Upload to ElevenLabs → Voices → Add Voice → Instant Voice Clone
3. Get the voice ID from voice settings
4. Add to `personas/config.local.json` as `elevenlabs_voice_id`

## Recording tips (from ElevenLabs)

- **Match the intended style** — record conversationally if you want a conversational clone. Don't read like a newscaster.
- **Vary sentence length and emotion slightly** — monotone input = monotone output
- **Stay consistent in overall style** — either animated throughout OR calm throughout. Don't mix.
- **1-1.5 second pauses** between paragraphs, shorter between sentences
- **No filler words** (um, uh, ahm) unless you want them replicated
- **No vocal fry or throat clearing**
- **Single speaker only**

## Equipment

- Pop filter required
- ~20cm (two fists) from the microphone
- Quiet room, no reverb
- Levels: -23dB to -18dB RMS, true peak of -3dB
- Recommended: XLR mic + audio interface (e.g., Audio Technica AT2020 + Focusrite)
- Acceptable: quality USB mic in a quiet room

## Scripts for recording

### Option 1: Phonetically balanced (recommended for coverage)

**Tailored Swift** — open-source, phonetically balanced sentences covering all English phonemes:
- https://github.com/jaedmunt/Tailored_Swift
- 4 categories: vowels (10), diphthongs (6), consonants (19), combinations (5)
- 2 minutes from a subset produced effective clones in testing

### Option 2: Classic phonetic corpus

**Harvard Sentences** — IEEE standard for telecom testing, 72 lists:
- https://parakeet-salmon-bzz9.squarespace.com/free-resources/phrases-to-speak-for-accurate-voice-cloning-harvard-sentences
- Examples: "The birch canoe slid on the smooth planks." / "Glue the sheet to the dark blue background."

### Option 3: Natural conversation (best for persona voice)

Read content that matches the persona's style:
- Read the persona's catchphrases aloud as if speaking to someone
- Ad-lib a 2-minute monologue in the character's voice
- Read a passage from something you wrote yourself — natural intonation comes through

### Option 4: Long-form (Professional Clone — 1-3 hours)

**Tweed Jefferson's Four-Script Suite:**
- https://www.tweedjefferson.com/voice-cloning-script/
- Voice Calibration, Emotional Without Theatrics, Articulation Stress-Test, Dialogue-Driven Cadence
- Designed for 2+ hours of recording

## ElevenLabs built-in scripts

The Professional Voice Cloning dashboard has built-in scripts in three categories:
- **Narrative** (audiobook style)
- **Conversational** (dialogue, casual)
- **Advertising** (commercial voiceover)

Access via: ElevenLabs dashboard → Voices → Add Voice → Professional Clone → Record yourself

## Duration requirements

| Clone type | Duration | Processing | Quality |
|---|---|---|---|
| Instant | 1-2 min (max 3 min) | Seconds | Good — approximates the voice |
| Professional | 30 min - 3 hours | 3-6 hours | High — dedicated model trained on your audio |

## File formats accepted

Audio: MP3, WAV, M4A, FLAC, OGA, OGG
Video: MP4, MOV (audio extracted automatically)
Recommended: MP3 at 192kbps or above
