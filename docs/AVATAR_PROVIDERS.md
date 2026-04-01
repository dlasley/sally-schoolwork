# Virtual Avatar Providers for LiveKit Agents

Research as of 2026-03-26. Pricing is approximate and sourced from provider websites and public sources.

## Comparison Table

| Provider | Description | Create from photo? | Differentiators | Cost Model | Approx. Cost | Free Tier | SDK Support | Docs |
|---|---|---|---|---|---|---|---|---|
| **Hedra** | Generate avatars from a single image, photorealistic to animated styles | **Yes** — via API upload or PIL Image at runtime. Auto-centers/crops around face to 512x512. Might be great. It wants me to upload pics to create one for myself. | Sub-100ms latency with LiveKit; photorealistic to animated styles | Per-minute | **$0.05/min** | Yes (300 credits) | Python, Node.js | [LK docs](https://docs.livekit.io/agents/models/avatar/plugins/hedra/), [API](https://api.hedra.com/web-app/redoc) |
| **Tavus** | Hyper-realistic replicas trained from video of a real person | **No** — requires video recording, not a photo. Trains a "replica" for highest fidelity. | Custom replica training; 30+ languages; requires Persona + Replica setup; echo pipeline mode for LK | Subscription + per-min overages | **$0.32-$0.37/min** overage; plans from $59/mo | Yes (25 min/mo) | Python only | [LK docs](https://docs.livekit.io/agents/models/avatar/plugins/tavus/), [Tavus docs](https://docs.tavus.io/) |
| **Simli** | Low-latency realtime video avatars | **Yes** — upload face via [dashboard](https://app.simli.com/faces) or [API](https://docs.simli.com/), reference by `face_id`. Demo is not very good: https://www.simli.com/gs-demo| Configurable emotions; Trinity-1 model at ultra-low cost | Pay-as-you-go | **$0.01-$0.05/min** (Trinity vs Legacy) | Yes ($10 credit + 50 min/mo) | Python only | [LK docs](https://docs.livekit.io/agents/models/avatar/plugins/simli/), [Simli docs](https://docs.simli.com/) |
| **Anam** | Lifelike conversational avatars with stock gallery | **Yes** — create custom avatar from photo via [Anam Lab](https://lab.anam.ai/avatars), reference by `avatarId`. Demo looks good: https://anam.ai/| Stock avatar gallery; per-second billing | Subscription + per-min overages | **$0.12-$0.16/min** overage; plans from free | Yes (30 min/mo, 1 avatar) | Python, Node.js | [LK docs](https://docs.livekit.io/agents/models/avatar/plugins/anam/), [Anam docs](https://docs.anam.ai/) |
| **Keyframe Labs** | Hyper-realistic, emotionally expressive avatars | **No** — stock persona library only. Custom personas available on Enterprise (24-hour turnaround). | Dynamic emotion control via `set_emotion()` (happy/sad/angry/neutral) — LLM can drive expressions via function tool; 720-1080p facial resolution; persona slugs | Per-minute | **$0.06/min** | Yes (limited) | Python only | [LK docs](https://docs.livekit.io/agents/models/avatar/plugins/keyframe/), [Keyframe docs](https://docs.keyframelabs.com/) |
| **LemonSlice** | Any-style avatars — humans, cartoon mascots, animals | **Yes** — via image URL or [agent dashboard](https://lemonslice.com/agents/create). Auto center-crops to 368x560. Works with human faces, cartoon characters, animals. Demo looks -- ok, not great: https://lemonslice.com/agents | Widest style range (any anthropomorphic image); movement prompt (`agent_prompt`); voice cloning (own TTS stack) | Subscription (credit-based) | Plans from **$8/mo** (1,000 credits) | Not listed | Python, Node.js | [LK docs](https://docs.livekit.io/agents/models/avatar/plugins/lemonslice/), [LemonSlice docs](https://lemonslice.com/docs/api-reference/overview) |
| **LiveAvatar (HeyGen)** | Dynamic realtime avatars from HeyGen's platform | **Yes** — create custom avatars via [dashboard](https://app.liveavatar.com/home). Demo is pretty good. Especially the foreign language learning one: https://lemonslice.com/agents| Backed by HeyGen (large established player) | Credit packs | **$0.10-$0.20/min** ($100/1,000 credits) | No | Python only | [LK docs](https://docs.livekit.io/agents/models/avatar/plugins/liveavatar/), [LiveAvatar docs](https://docs.liveavatar.com/) |
| **Beyond Presence** | Hyper-realistic interactive avatars | **No** — stock avatar IDs only. Default avatar included. | Default avatar included (no setup needed); speech-to-video mode uses half the credits of managed agents | Subscription + credit overages | **$0.09-$0.35/min** depending on tier; plans from $49/mo | Yes (20 min/mo) | Python, Node.js | [LK docs](https://docs.livekit.io/agents/models/avatar/plugins/bey/), [Bey docs](https://docs.bey.dev/) |
| **TruGen** | Realtime AI video with bidirectional interaction | **No** — ~20 stock avatars only. | Gaussian Avatar rendering; precision lip-sync | Subscription | From **$28/mo** | Yes (free plan) | Python, Node.js | [LK docs](https://docs.livekit.io/agents/models/avatar/plugins/trugen/), [TruGen docs](https://docs.trugen.ai/) |
| **AvatarTalk** | Realtime conversational avatars | **No** — [dashboard](https://avatartalk.ai/dashboard/)-managed avatars only. | Configurable emotions (`expressive` default); no rate limits; supports on-premise and embedded hardware deployment | Pay-as-you-go (no subscription) | **$0.05-$0.10/min** (volume discounts) | Yes (10 min) | Python only | [LK docs](https://docs.livekit.io/agents/models/avatar/plugins/avatartalk/), [API docs](https://github.com/avatartalk-ai/avatartalk-examples/blob/main/API.md) |
| **Avatario** | Realtime conversational avatars | **Unknown** — [dashboard](https://avatario.ai/dashboard/)-managed avatars. | Dashboard-based avatar selection | Unknown (not published) | Contact sales | Unknown | Python only | [LK docs](https://docs.livekit.io/agents/models/avatar/plugins/avatario/), [Avatario docs](https://avatario.ai/docs) |
| **bitHuman** | Local or cloud avatars, CPU-based rendering | **Yes** — via API, PIL Image, local file path, or URL. Also supports pre-built `.imx` model files. Laggy and bad: https://www.bithuman.ai/#explore | Only provider that runs on CPU (no GPU needed) — works on Chromebooks, Raspberry Pi; `expression` vs `essence` model modes | Credit-based | Not published (claimed 10x cheaper due to CPU) | Yes (99 credits/mo) | Python only | [LK docs](https://docs.livekit.io/agents/models/avatar/plugins/bithuman/), [bitHuman docs](https://docs.bithuman.ai/) |

## Photo-to-avatar summary

Providers that support creating an avatar from a photo (headshot):

| Provider | Creation method | Best for |
|---|---|---|
| **Hedra** | API upload or PIL Image at runtime | Photorealistic from a single headshot — primary use case. $0.05/min. |
| **Simli** | Dashboard or API upload | Low-cost photorealistic. $0.01-$0.05/min. |
| **Anam** | Anam Lab web tool | Stock gallery + custom creation. Per-second billing. |
| **LemonSlice** | Image URL or agent dashboard | Creative/stylized characters (humans, mascots, animals). |
| **LiveAvatar (HeyGen)** | Dashboard | Backed by HeyGen. $0.10-$0.20/min. |
| **bitHuman** | API, PIL Image, file path, or URL | Self-hosted on CPU — no cloud costs. |

**Tavus** requires video, not a photo. **Keyframe Labs** offers custom personas on Enterprise tier (24-hour turnaround). **Beyond Presence**, **TruGen**, **AvatarTalk**, and **Avatario** are stock-library only with no documented custom photo workflow.

## Voice cloning from a recording

LiveKit doesn't have built-in voice cloning — it's handled by the TTS provider. The workflow is: upload audio sample(s) to the provider, get a cloned voice ID, use that ID in your LiveKit agent. Cloned voices require using the provider's plugin directly (not LiveKit Inference, which doesn't support custom voices yet).

### TTS providers with voice cloning

| Provider | Cloning method | Quality tiers | LK plugin | Notes |
|---|---|---|---|---|
| **ElevenLabs** | Upload audio samples via [ElevenLabs platform](https://elevenlabs.io/) | Instant (short sample, seconds) or Professional (longer samples, higher fidelity) | `livekit-agents[elevenlabs]` | Most mature cloning product. 30+ languages. |
| **Cartesia** | Clone via [Cartesia platform](https://play.cartesia.ai/) from audio samples | Single tier | `livekit-agents[cartesia]` | Currently configured as this project's TTS — would just need to switch from Inference to plugin. |
| **Google Cloud TTS** | `voice_clone_key` parameter — text string representing voice data | Single tier | `livekit-agents[google]` | Integrated into plugin params directly. |
| **Resemble AI** | Purpose-built voice cloning platform. Upload recordings via [Resemble dashboard](https://app.resemble.ai/). | Rapid (few seconds) or Professional | `livekit-agents[resemble]` | Specializes in cloning — also offers emotion control and per-word pronunciation. |
| **LemonSlice** | Voice cloning bundled with avatar platform (own TTS stack, not ElevenLabs) | Single tier, limited docs | `livekit-agents[lemonslice]` | Pairs cloned voice with custom avatar in one package. Cloning specs not publicly documented. |

### Usage example (ElevenLabs)

```python
from livekit.agents import AgentSession
from livekit.plugins import elevenlabs

session = AgentSession(
    tts=elevenlabs.TTS(voice="<your-cloned-voice-id>"),
    # ... llm, stt, etc.
)
```

### Voice + avatar pairing

For a fully custom persona (cloned voice + photo-based avatar), the most practical combinations:

| Avatar provider | TTS provider | Notes |
|---|---|---|
| **Hedra** | **ElevenLabs** or **Cartesia** | Photo-to-avatar + cloned voice. Cheapest avatar ($0.05/min) + best cloning (ElevenLabs). |
| **LemonSlice** | **LemonSlice** (own TTS) | Single provider for both — voice cloning and avatar from one image. Simplest setup, but cloning quality undocumented. |
| **bitHuman** | **ElevenLabs** or **Resemble** | Self-hosted avatar + cloned voice. No avatar cloud costs. |
| **Simli** | **ElevenLabs** or **Cartesia** | Low-cost avatar ($0.01-$0.05/min) + cloned voice. |

## Standouts for school assistant use case

- **Hedra** or **Simli** — cheapest per-minute, simple setup (just an image), good for a utility-focused agent
- **LemonSlice** — only provider that explicitly supports non-human styles (cartoon mascots, animals) if a character/mascot is desired
- **Keyframe Labs** — best emotion control API with direct `@function_tool` integration (e.g., look concerned when reporting a bad grade)
- **bitHuman** — avoids cloud costs entirely, runs locally on CPU
