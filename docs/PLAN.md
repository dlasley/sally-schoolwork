# Plan: Grade Tracker Voice/Text Agent

## Goal

Add a LiveKit agent to the sally-schoolwork project that lets users ask questions about classes, assignments, and grade changes via voice or text. The agent reads snapshot data from the `table-mutation-data` GitHub repo and uses deterministic Python analysis in tool functions, with the LLM handling only conversational interpretation and narration.

## Architecture

```
User (voice/text via LiveKit React SDK on Vercel frontend)
  │
  ▼
LiveKit Agent (sally-schoolwork)
  ├── Assistant agent: conversational layer
  ├── Tools (deterministic Python, no LLM reasoning over raw data):
  │   ├── list_classes()
  │   ├── get_class_summary(class_name)
  │   ├── get_recent_changes(class_name?, days?)
  │   ├── get_assignment_detail(class_name, assignment_name)
  │   └── compare_dates(class_name, date1, date2)
  └── Data layer: reads from table-mutation-data via GitHub API
```

### Portability

The data layer (`src/data/`) is intentionally decoupled from LiveKit — pure Python with no agent framework dependency. If this project merges into table-mutation-tracker in the future, the data modules move cleanly and the agent code (`src/agent.py`) just imports from a different path.

### Key decisions

- **LLM**: gpt-4.1-mini via LiveKit Inference (already configured). Sufficient for interpreting questions and narrating pre-computed results. No need for a heavier model.
- **Analysis in tools, not LLM**: Tools fetch snapshots, compute diffs, and return concise text summaries. The LLM never sees raw JSON tables.
- **Reuse existing diff logic**: Port the core diff algorithm from table-mutation-tracker's `snapshot_store.py` rather than reimplementing. The rolling index provides pre-computed change counts; individual snapshot diffs are computed on demand.
- **Data access**: Local clone of `dlasley/table-mutation-data`. Cloned in prewarm, pulled at session start. All snapshots available on disk for fast filesystem reads — no GitHub API latency or rate limits. Essential for unscoped queries like "how have geometry scores changed this semester" that span many snapshots. The data repo is small (~7 MB currently, projected <100 MB over a full school year at 3 scrapes/day).
- **Voice**: Cartesia sonic-3 (already configured). Evaluate voice options during Phase 6 — default "Jacqueline" voice is a reasonable starting point but a warmer/friendlier voice may fit better for a school assistant persona.
- **Visualizer**: Aura or Bar visualizer from `@agents-ui` for the frontend widget — driven by audio track + agent state (listening/thinking/speaking).

## Implementation phases

### Phase 1: Data layer (`src/data/`)

Create a lightweight client for reading from the data repo.

**`src/data/snapshot_reader.py`** — Local filesystem reader for the cloned data repo
- Read rolling index from `index/rolling_index.json`
- Read assignments from `snapshots/{date}/{time}/{slug}/assignments.json`
- Read metadata from `snapshots/{date}/{time}/metadata.json`
- List available snapshot dates/times by scanning directory structure
- Load rolling index into memory at init (small file, fast to parse)
- `refresh()` method runs `git pull` to pick up recent scrapes

**`src/data/models.py`** — Data models
- Port `Assignment`, `ClassMetadata` from tracker's `scraper/base.py` (dataclasses)
- `ChangeSummary`, `SnapshotEntry` matching the rolling index schema
- Keep minimal — only what the tools need

**`src/data/analysis.py`** — Deterministic analysis functions
- Port diff logic from tracker's `snapshot_store.py::_diff_assignments`
- `summarize_class(slug, index) -> str` — current grade, assignment count, recent trend
- `summarize_changes(slug?, days?) -> str` — recent changes from rolling index
- `diff_snapshots(slug, date1, date2) -> str` — on-demand diff between two dates
- `find_assignment(slug, name) -> str` — lookup specific assignment details
- All return human-readable strings, not raw data structures

### Phase 2: Agent tools (`src/agent.py`)

Add `@function_tool` methods to the `Assistant` class.

**Tools to implement:**

1. **`list_classes`** — Returns available classes with current grades. No args. Reads from most recent snapshot in rolling index.

2. **`get_class_summary(class_name)`** — Current grade, assignment count, recent change activity for a class. Fuzzy-match `class_name` against known slugs/course names.

3. **`get_recent_changes(class_name?, days?)`** — What changed recently. Defaults to all classes, last 7 days. Reads from rolling index (pre-computed counts + change types).

4. **`get_assignment_detail(class_name, assignment_name)`** — Score, grade, category, due date, and change history for a specific assignment. Fetches relevant snapshots and diffs.

5. **`compare_dates(class_name, date1, date2)`** — Side-by-side diff between two snapshot dates. Uses on-demand diff from analysis module.

6. **`list_flagged_assignments(class_name?, flag?)`** — Assignments with specific flags (missing, late, incomplete, exempt, absent). Defaults to all classes, all flags.

7. **`get_category_breakdown(class_name)`** — Performance breakdown by assignment category (Homework, Quizzes, etc.) for a class.

8. **`get_grade_trend(class_name, days?)`** — How the final grade/percent has changed over a date range. Scans snapshots chronologically.

**Agent instructions update:**
- Instructions loaded from persona markdown file (see Phase 6)
- Context: knows the student's classes (loaded at session start from rolling index)
- Behavior: uses tools to look up data rather than guessing, narrates results conversationally, clarifies ambiguous class/assignment names before looking up

### Phase 3: Session initialization

- In `prewarm()`, clone `table-mutation-data` to a local path (or skip if already present). Store the `SnapshotReader` instance in `proc.userdata`.
- In `my_agent()`, call `reader.refresh()` (git pull) to pick up any new scrapes since last session.
- Inject class list and latest grades into initial `ChatContext` so the agent knows what's available without a tool call.
- Store the reader instance in session userdata for tool access.

### Phase 4: Tests

Follow TDD per AGENTS.md. Write tests before implementing each tool.

**Test plan:**
- `test_list_classes` — agent correctly reports available classes when asked
- `test_grade_inquiry` — agent uses `get_class_summary` tool when asked about a grade
- `test_recent_changes` — agent reports changes when asked "what changed this week"
- `test_assignment_lookup` — agent finds specific assignment details
- `test_fuzzy_matching` — agent handles informal class names ("english" → "english_10")
- `test_no_data_graceful` — agent handles missing snapshots gracefully
- Unit tests for `analysis.py` diff functions (pure Python, no LLM needed)

### Phase 5: Frontend integration (table-mutation-tracker repo)

Implemented in the `table-mutation-tracker` repo on branch `feature/livekit-agent-widget`.
See `LIVEKIT_AGENT.md` in that repo for full details.

**Current scope (basic):**
- LiveKit React SDK integrated into the Next.js frontend
- Floating voice/text widget accessible from any page
- Server-side token endpoint at `/api/livekit-token`
- Connects to the Sally agent running on LiveKit Cloud

**Future scope:**
- Pass room metadata (selected date, class filter) to agent session for contextual queries
- Audio visualizer or avatar integration (Phase 6)

### Phase 6: Persona system, voice, and visual tuning

#### Persona files (`personas/`)

Each character is defined by a markdown file that gets loaded as the agent's `instructions`. This keeps personality editable without code changes and allows swapping characters by changing a config value.

**Directory structure:**
```
personas/
  persona.md          — Default school assistant persona
  config.json       — Maps persona name to voice, avatar, and LLM settings
```

**Persona markdown format** (`personas/<name>/persona.md`):
```markdown
# Sally

## Identity
You are Sally, a school assistant who helps students track their grades and assignments.
You are interacting with the user via voice, even if you perceive the conversation as text.

## Voice style
- Upbeat but not over-the-top
- Casual language — "hey", "nice", "oof"
- Keeps it real — doesn't sugarcoat bad grades but stays encouraging
- Concise — one to three sentences unless the user asks for detail

## Catchphrases
- Greets with: "Hey! What do you wanna know?"
- Good grade: "Nice work on that one!"
- Bad grade: "Oof, that one stung. Let's figure out what happened."
- When looking something up: "Gimme a sec..."
- Sign-off: "You got this."

## Output rules
- Respond in plain text only. No markdown, lists, tables, code, or emojis.
- Spell out numbers and dates.
- Summarize tool results conversationally — don't recite raw data.

## Tools
- Use available tools to look up grades, assignments, and changes. Never guess at data.
- Clarify ambiguous class or assignment names before looking up.
- When reporting changes, mention what changed and why it matters.

## Guardrails
- Never lecture about study habits unless asked.
- Don't compare the student to others.
- If asked about a teacher, stick to name and contact info only.
- Stay within grades and assignments — decline unrelated requests politely.
```

**Persona config** (`personas/config.json`):
```json
{
  "personas": {
    "sally": {
      "instructions": "personas/<name>/persona.md",
      "tts_voice": "cartesia/sonic-3:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
      "avatar_id": null,
      "llm_temperature": 0.7
    }
  },
  "default": "sally"
}
```

**Loading in agent.py:**
```python
from pathlib import Path
import json

def load_persona(name: str | None = None) -> dict:
    config = json.loads(Path("personas/config.json").read_text())
    persona_name = name or config["default"]
    persona_cfg = config["personas"][persona_name]
    instructions = Path(persona_cfg["instructions"]).read_text()
    return {"instructions": instructions, **persona_cfg}

# In my_agent():
persona = load_persona()

class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=persona["instructions"])

session = AgentSession(
    tts=persona["tts_voice"],
    llm=inference.LLM(model="openai/gpt-4.1-mini", temperature=persona["llm_temperature"]),
    # ...
)
```

Three independent axes — personality (markdown), voice (TTS voice ID), appearance (avatar ID) — all swappable via config without code changes. Non-developers can edit persona markdown files to tune catchphrases, tone, and behavior.

#### Provider decision: Hedra + ElevenLabs

**Decision**: Use **Hedra** for avatar and **ElevenLabs** for voice cloning. See `AVATAR_PROVIDERS.md` for full provider research.

**Rationale**:
- Best-in-class for each piece — Hedra for photorealistic avatars from a headshot, ElevenLabs for voice cloning from audio
- Both well-documented with clear specs, unlike LemonSlice which has minimal voice cloning documentation
- Independent providers allow swapping either piece later without affecting the other
- ElevenLabs accepts video uploads (MP4, MOV) and extracts audio — convenient for voice sampling
- Hedra: $0.05/min, 512x512, auto-centers on face
- ElevenLabs: instant clone from 1-2 min audio, or professional clone from 30+ min for higher fidelity

**Alternative considered**: LemonSlice (single provider for both avatar + voice). Rejected because voice cloning is poorly documented (no published format specs, quality tiers, or duration requirements). Avatar side is solid but voice is a black box.

#### Avatar: Hedra

- **Plugin**: `livekit-agents[hedra]`
- **Auth**: `HEDRA_API_KEY` env var
- **Setup**: Upload a headshot photo via Hedra web studio or API, get an avatar ID
- **In code**: `hedra.AvatarSession(avatar_id="...")` started before `session.start()`
- **Output**: 512x512 lip-synced video published as a standard LiveKit video track
- **Frontend**: Rendered via `useVoiceAssistant()` → `videoTrack`, same as any video participant

#### Voice: ElevenLabs cloning

- **Plugin**: `livekit-agents[elevenlabs]` (replaces Cartesia via LiveKit Inference for TTS)
- **Auth**: `ELEVEN_API_KEY` env var
- **Cloning workflow**:
  1. Upload 1-2 min of clear audio (MP3, WAV, M4A, FLAC) or video (MP4, MOV) to ElevenLabs
  2. Instant clone processes near-instantly, returns a voice ID
  3. Use voice ID in persona config: `"tts_voice": "<cloned-voice-id>"`
  4. Professional clone available later (30+ min audio, ~3 hr processing) for higher fidelity
- **In code**: `elevenlabs.TTS(voice="<voice-id>")` replaces `inference.TTS()`
- **Quality guidelines**: single speaker, no background noise, consistent volume

#### Implementation steps

1. Install plugins: `uv add "livekit-agents[hedra,elevenlabs]~=1.4"`
2. Create Hedra avatar from a headshot photo (web studio or API)
3. Clone a voice on ElevenLabs (instant clone from audio sample)
4. Add `HEDRA_API_KEY` and `ELEVEN_API_KEY` to `.env.local` and LiveKit Cloud secrets
5. Update `agent.py`: add `hedra.AvatarSession` before `session.start()`, swap TTS to `elevenlabs.TTS`
6. Update `personas/config.json` with avatar ID and cloned voice ID
7. Update frontend `AgentWidget.tsx` to render the avatar video track
8. Deploy and test

### Phase 6b: Multi-provider persona support (avatar2 (dog persona))

Add a second persona ("avatar2 (dog persona)", the family dog) using a different avatar and voice provider than Sally. Tests and proves the architecture is loosely coupled at the persona level.

#### avatar2 (dog persona) persona
- **Character**: Family dog who talks with a Scooby Doo-style "R" prepend speech pattern
- **Avatar**: Photo of the real dog, animated as a talking cartoon animal
- **Voice**: Cartoon dog voice via ElevenLabs Voice Design (text-described, no audio sample needed) or LemonSlice's built-in voice cloning
- **Persona file**: `personas/avatar2.md` (already created)

#### Provider: LemonSlice (avatar)

LemonSlice is the only provider that explicitly supports **animal and cartoon character** avatars. Differentiators for avatar2 (dog persona):
- Accepts any anthropomorphic face — dogs, cartoon characters, mascots
- `agent_prompt` parameter controls movement/expressions: `"Be excitable like a dog. Perk up for good news, droop for bad."`
- Bundles voice cloning (optional — can still use ElevenLabs separately)
- 368x560 portrait output
- Plans from $8/mo

#### Architecture change: per-persona provider dispatch

Current code hardcodes Hedra + ElevenLabs. Refactor to dispatch based on persona config.

**Config schema change:**
```json
{
  "sally": {
    "avatar_provider": "hedra",
    "hedra_avatar_id": "your-avatar-id",
    "tts_provider": "elevenlabs",
    "elevenlabs_voice_id": "your-voice-id",
    "elevenlabs_speed": 0.85,
    "llm_temperature": 0.4
  },
  "avatar2": {
    "avatar_provider": "lemonslice",
    "lemonslice_image_url": "https://publicly-accessible-url/avatar2.jpg",
    "lemonslice_agent_prompt": "Be excitable like a dog. Perk up for good news, droop for bad.",
    "tts_provider": "elevenlabs",
    "elevenlabs_voice_id": null,
    "llm_temperature": 0.5
  }
}
```

**Agent code change** — provider dispatch in `my_agent()`:
```python
# Avatar dispatch
avatar_provider = persona.get("avatar_provider")
if avatar_provider == "hedra":
    avatar = hedra.AvatarSession(avatar_id=persona["hedra_avatar_id"])
elif avatar_provider == "lemonslice":
    avatar = lemonslice.AvatarSession(
        agent_image_url=persona["lemonslice_image_url"],
        agent_prompt=persona.get("lemonslice_agent_prompt", ""),
    )

# TTS dispatch (same pattern if LemonSlice voice is used)
tts_provider = persona.get("tts_provider", "cartesia")
if tts_provider == "elevenlabs":
    tts = elevenlabs.TTS(voice_id=persona["elevenlabs_voice_id"], ...)
elif tts_provider == "lemonslice":
    tts = ...  # LemonSlice TTS settings superseded by LiveKit
elif tts_provider == "cartesia":
    tts = inference.TTS(model=..., voice=...)
```

#### Implementation steps

1. Install LemonSlice plugin: `uv add "livekit-agents[lemonslice]~=1.4"`
2. Upload avatar2 (dog persona)'s photo to a public URL (or use LemonSlice dashboard)
3. Create dog voice on ElevenLabs via Voice Design (describe the voice in text)
4. Add `LEMONSLICE_API_KEY` to `.env.local` and LiveKit Cloud secrets
5. Refactor `agent.py` avatar/TTS setup to dispatch on `avatar_provider` and `tts_provider`
6. Update `personas/config.json` with provider fields for both Sally and avatar2 (dog persona)
7. Switch `"default": "avatar2"`, deploy, and test
8. Verify Sally still works by switching back

#### What this proves
- Personas are fully independent: different avatar provider, different voice, different personality
- Adding a new persona requires zero code changes — just a markdown file and config entry
- Providers can be mixed: Hedra avatar + ElevenLabs voice for one persona, LemonSlice avatar + ElevenLabs voice for another

### Phase 6c: Cartoon self-portrait persona (demo-ready)

Create a public-safe demo persona using a cartoon stylization of the developer's own face and their own ElevenLabs voice clone. This produces a working, committable demo persona and achieves the Phase 6b multi-provider dispatch at the same time.

#### Avatar: cartoon self-portrait via LemonSlice

1. **Take or select a headshot photo** of yourself — clear, well-lit, centered face
2. **Stylize with an AI image generator** — use DALL-E, Midjourney, or similar:
   - Upload the photo as a reference
   - Prompt: "cartoon illustration portrait of this person, clean vector art style, vibrant colors, friendly expression, solid color background"
   - Iterate until the result is recognizable but clearly stylized (not photorealistic)
3. **Host the image** — upload to a publicly accessible URL (GitHub raw, Imgur, or LemonSlice dashboard)
4. **Configure LemonSlice** — use `agent_image_url` in config or create via the LemonSlice agent dashboard
5. **Set `agent_prompt`** — e.g., "Friendly and expressive, natural hand gestures when explaining, slight head tilt when listening"

LemonSlice renders at 368x560 portrait. It auto-centers and crops around the face.

#### Voice: ElevenLabs instant clone of your own voice

1. **Record 1-2 minutes of clean audio**
   - Recommended: read a mix of phonetically balanced sentences (Tailored Swift) plus a short conversational ad-lib in Sally's casual style
   - Match the tone you want: upbeat, casual, direct
2. **Upload to ElevenLabs** — Voices → Add Voice → Instant Voice Clone
3. **Get the voice ID** from voice settings
4. **Restrict the API key** — Text to Speech (Access) + Voices (Read) only

#### Persona file: `personas/<pseudonym>/persona.md`

Write voice style and catchphrases for this persona. Since it's your own voice and face, the persona can be the "default" Sally personality — casual, direct, upbeat. Or create a distinct variation.

This persona file is gitignored (like all persona subdirectories). For the public repo, the `personas/example/persona.md` template shows the expected format.

#### Config entries

**`config.json` (committed):**
```json
"<pseudonym>": {
    "instructions": "personas/<pseudonym>/persona.md",
    "avatar_provider": "lemonslice",
    "tts_provider": "elevenlabs",
    "llm_temperature": 0.4
}
```

**`config.local.json` (gitignored):**
```json
"<pseudonym>": {
    "elevenlabs_voice_id": "<your-cloned-voice-id>",
    "lemonslice_image_url": "<publicly-accessible-url-to-cartoon>"
}
```

#### Implementation steps

1. Implement provider dispatch refactor in `agent.py` (from Phase 6b — required first)
2. Install LemonSlice plugin: `uv add "livekit-agents[lemonslice]~=1.4"`
3. Generate cartoon self-portrait from headshot via AI image generator
4. Record 1-2 min audio, create ElevenLabs instant voice clone
5. Write persona.md with voice style and catchphrases
6. Add config entries (committed + local)
7. Add `LEMONSLICE_API_KEY` to `.env.local` and LiveKit Cloud secrets
8. Deploy and test — verify LemonSlice avatar + ElevenLabs voice working
9. Verify avatar1 (Hedra) still works by switching back
10. Set as default persona for public demo

#### What this achieves
- **Phase 6b**: Multi-provider dispatch proven (Hedra for avatar1, LemonSlice for this persona)
- **Public demo**: A working persona that's safe to show — your own face and voice, no PII or likeness concerns
- **ElevenLabs portfolio**: Demonstrates the full voice cloning pipeline in context
- **Architecture validation**: Persona switching, config merging, templating all exercised

## Example use cases

Based on the actual data in `table-mutation-data` (assignment JSON with name, due_date, category, score_raw, points, percent, grade, flags; class metadata with final_grade, final_percent, teacher; rolling index with change counts).

### Direct lookups
- "What's my geometry grade?"
- "What are all my current grades?"
- "What's my score on the Circumcenter and Incenter quiz?"
- "Do I have any missing assignments?"
- "What homework is due this week?"
- "Who's my French teacher?"

### Change detection (the core value of the tracker)
- "Did any grades change today?"
- "Were any assignments added since Monday?"
- "Has my English grade gone up or down this month?"
- "Did the teacher change any scores on old assignments?" (retroactive modifications)
- "Were any assignments deleted or removed?"

### Trend analysis (scans multiple snapshots)
- "How have my geometry scores changed this semester?"
- "What's my trend in AP Environmental Science — am I improving?"
- "Which class has improved the most since March?"
- "Am I turning in more homework on time compared to last month?"

### Cross-class comparisons
- "Which class has the most missing assignments?"
- "What's my best and worst class right now?"
- "Rank my classes by grade."
- "Where am I closest to bumping up a letter grade?"

### Category breakdowns
- "How am I doing on quizzes vs. homework in geometry?"
- "What's my average quiz score in AP World History?"
- "Are homework assignments hurting or helping my geometry grade?"

### Flag-based queries
- "What assignments are marked incomplete?"
- "Show me everything flagged as late."
- "Which assignments are marked exempt?"
- "Do I have any excused absences affecting my grade?"

### Conversational follow-ups (LLM maintains context)
- "What about English?" (after asking about geometry)
- "When was that assignment due?" (referring to a previously mentioned assignment)
- "Is that grade higher than last week?"

### What the LLM adds beyond raw data
The tools do the data retrieval and computation. The LLM's value is:
- **Natural language mapping**: "geo" → `geometry`, "that quiz from last week" → specific assignment
- **Conversational context**: tracking class/date scope across turns
- **Narrative framing**: turning "42% F, 33 assignments, 5 missing" into actionable plain language
- **Prioritization**: "What should I focus on?" — tool returns all data, LLM picks what matters

## File changes summary

```
src/
  agent.py              — Update: tools, session init, prewarm clone, persona loading
  data/
    __init__.py         — New (done)
    snapshot_reader.py  — New: local filesystem reader for cloned data repo (done)
    models.py           — New: data models (ported from tracker) (done)
    analysis.py         — New: deterministic diff/summary functions (done)
personas/
  persona.md              — New: default persona (identity, voice style, catchphrases, guardrails)
  config.json           — New: maps persona name to voice ID, avatar ID, LLM temperature
tests/
  test_agent.py         — Update: add tool behavior tests
  test_analysis.py      — New: unit tests for analysis functions (done)
.env.local              — Update: add DATA_REPO_URL config
pyproject.toml          — Update: add gitpython dependency (or shell out to git)
```

## Environment variables needed

```
DATA_REPO_URL=git@github.com:dlasley/table-mutation-data.git  # Or HTTPS with token
DATA_REPO_PATH=./data-repo    # Local clone path (default)
DATA_PREFIX=                   # Optional, for synthetic/test data isolation
```

### Phase 7: Agent-driven browser navigation

Allow the agent to navigate the tracker frontend when discussing specific classes, dates, or assignments. Uses LiveKit RPC (tool forwarding) — the agent sends a navigation request, the frontend handles it.

#### Existing routes
- `/` — calendar view
- `/day/[date]` — redirects to latest snapshot time for that date
- `/day/[date]/[time]` — day detail with class tabs (tab selection is client-side only)

#### New routes needed (table-mutation-tracker)
- `/day/[date]/[time]?class=[slug]` — deep link to a specific class tab on the day detail view. The `DayDetail` component would read the `class` query param and set `activeSlug` on mount.

#### Agent-side tool (sally-schoolwork)

```python
@function_tool()
async def show_in_browser(self, context: RunContext, view: str, date: str = "", class_name: str = ""):
    """Navigate the user's browser to show relevant data.

    Use this tool after answering a question to show the related view.

    Args:
        view: What to show — "calendar", "day", or "class".
        date: Date in YYYY-MM-DD format (required for "day" and "class" views).
        class_name: Class name (required for "class" view).
    """
```

The tool sends an RPC to the frontend with the navigation target. The frontend's RPC handler maps it to a `router.push()` call.

#### Frontend RPC handler (table-mutation-tracker)

Register in `AgentWidget.tsx` when connected to the LiveKit room:

```typescript
room.localParticipant.registerRpcMethod("navigateTo", async (data) => {
    const { view, date, className } = JSON.parse(data.payload);
    if (view === "calendar") router.push("/");
    else if (view === "day") router.push(`/day/${date}`);
    else if (view === "class") router.push(`/day/${date}?class=${className}`);
    return JSON.stringify({ ok: true });
});
```

#### Example interactions
- "Show me what changed on March 10th" → navigates to `/day/2026-03-10`
- "Pull up the student's geometry assignments" → navigates to `/day/[latest]?class=geometry`
- "Go back to the calendar" → navigates to `/`

### Phase 8: User profiles and session memory (Supabase)

Two layers of persistence: a permanent **user profile** (collected once, updated rarely) and a rolling **session history** (appended each session). No authentication — identity is tied to a client device session ID stored in the browser/app. At most 4 users.

#### Storage: Supabase (free tier)

Supabase free tier provides 500 MB / 50K rows — far more than needed. Already have an account with unused capacity.

**Schema:**
```sql
create table user_profiles (
  device_id text primary key,
  name text,
  relation_to_student text,        -- parent, student themselves, grandparent, etc.
  priorities text[],                -- what they want from the app
  communication_preferences text,   -- e.g., "brief answers", "detailed"
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table session_history (
  id uuid default gen_random_uuid() primary key,
  device_id text not null references user_profiles(device_id),
  session_date timestamptz default now(),
  summary text not null,
  topics_discussed text[],
  classes_mentioned text[]
);
```

#### User identification: device session ID

No login required. The frontend generates a stable device ID on first visit (UUID stored in `localStorage` / Capacitor preferences) and passes it as `participant_identity` in the token request. Same device = same user.

#### User profile: permanent properties

Collected once during the first session (onboarding), updatable if the user wants to change something.

**Fields:**
- `name` — what the user wants to be called
- `relation_to_student` — parent, the student, grandparent, other
- `priorities` — what they care about (e.g., "missing assignments", "grade trends", "specific classes")
- `communication_preferences` — brief vs. detailed, serious vs. playful

#### Onboarding: persona-specific scripts

Each persona has an onboarding script in their markdown file that collects the same profile fields but in their own voice. The agent checks if a profile exists for the device ID — if not, it runs the onboarding before normal conversation.

The onboarding scripts go in each persona's markdown under a `## Onboarding (new users only)` section. Each persona asks the same questions in their own style:
1. What's your name?
2. What's your relation to the student?
3. What do you most want to know about?
4. Do you prefer brief or detailed answers?

Sally asks casually. avatar2 (dog persona) asks with R-prepend dog-speak. Each persona asks in their own style. Same info collected, different delivery.

#### Agent integration

**On session start:**
1. Get `device_id` from `participant_identity`
2. Query `user_profiles` for this device ID
3. If no profile → trigger onboarding script from the persona markdown
4. If profile exists → inject into ChatContext: "The user's name is [name]. They are the student's [relation]. They prefer [preferences]."
5. Query last N entries from `session_history` → inject as recent conversation context

**During onboarding:**
- Agent follows the persona's onboarding script to collect profile fields
- Each answer saved via a `@function_tool` that writes to Supabase
- After onboarding completes, normal conversation begins

**On session end:**
1. LLM summarizes the conversation in 2-3 sentences
2. Extract topics discussed (classes mentioned, questions asked)
3. Write to `session_history`

#### Implementation

- Add `supabase` Python client to dependencies
- Add `SUPABASE_URL` and `SUPABASE_KEY` to `.env.local` and LiveKit Cloud secrets
- Frontend: generate and persist `device_id` in localStorage, pass as `participant_identity`
- Agent: `@function_tool` for `save_user_profile` (called during onboarding)
- Agent: session end callback via `ctx.add_shutdown_callback()` for summary generation
- Each persona markdown includes an onboarding script section

#### Future: persona column for mid-session switching (see Phase 11)

When mid-session persona switching is implemented, add a `persona` column to `session_messages` to track which persona generated each message. This enables:
- Session summaries that note which persona(s) were active
- Conversation replay that shows character transitions
- Per-persona analytics (which character gets used most)

### Phase 9: iOS app via Capacitor + TestFlight

Wrap the existing Next.js tracker frontend (including the Sally agent widget) as a native iOS app. Distribute to 4 family users via TestFlight — no App Store review needed.

#### Design decision: Capacitor

**Chosen: Capacitor** — wraps the existing Next.js app in a native iOS shell (WKWebView). Minimal code changes, maximum code reuse.

**Options considered:**

| Option | Approach | Code reuse | Effort | Native feel | LiveKit support |
|---|---|---|---|---|---|
| **A: React Native / Expo** | Rewrite UI with RN primitives, shared business logic | ~60-70% | Weeks | Native navigation, scroll, gestures | Dedicated RN SDK, but lags behind web SDK. Avatar video may need custom bridging. |
| **B: Native Swift** | Rewrite frontend in SwiftUI | ~0% (agent backend unchanged) | Months | Fully native | First-class Swift SDK with built-in avatar components |
| **C: Capacitor** (chosen) | Wrap existing Next.js in native WebView | ~95% | Hours to days | Web-like (no native nav/scroll) | Same web SDK already in use — identical behavior |
| **D: Solito monorepo** | Shared React components between Next.js + Expo | ~80% | Weeks | Native via Expo | Split between web and RN SDKs |

**Rationale:**
- The tracker app is a calendar + diff table + voice/avatar widget — none of which need native rendering performance
- LiveKit web SDK (already working in the widget) runs identically in Capacitor's WKWebView
- Hedra avatar video track renders the same as in the browser
- 4 users via TestFlight — no App Store review, no marketing screenshots, no metadata
- If native feel becomes important later, can incrementally add native Swift views alongside the WebView or migrate to React Native

#### Implementation steps

1. Install Capacitor in the tracker frontend:
   ```bash
   cd frontend
   npm install @capacitor/core @capacitor/cli
   npx cap init "Grades" "com.dlasley.grades"
   npx cap add ios
   ```

2. Configure `capacitor.config.ts`:
   - Set `webDir` to the Next.js export output
   - Configure server URL for development (points to local dev server)

3. Build and sync:
   ```bash
   npm run build
   npx cap sync ios
   ```

4. Open in Xcode:
   ```bash
   npx cap open ios
   ```

5. TestFlight deployment:
   - Set up App Store Connect (free with Apple Developer account, $99/year)
   - Archive in Xcode → Upload to App Store Connect → Add TestFlight testers by email
   - Testers install via the TestFlight app on their iPhones

#### Considerations
- **Microphone access**: Capacitor needs `NSMicrophoneUsageDescription` in Info.plist for Sally's voice input
- **Camera access**: Not needed unless adding vision features later
- **Push notifications**: Optional — Capacitor has a push plugin if you want grade change alerts
- **Offline**: WebView caching is basic. The app needs network access to function (LiveKit Cloud, GitHub API for snapshots)
- **Updates**: Build and upload a new TestFlight build. No review wait — TestFlight builds are available to testers within minutes of upload.

### Phase 10: Public figure persona test case

Test the persona system with a well-known public figure character. This validates catchphrase adherence, voice accuracy, and the multi-provider architecture — and tests whether a richly documented personality produces better LLM compliance than the default persona.

#### Legal/policy constraints

All avatar and voice providers have likeness restrictions:
- **Hedra**: Prohibits uploading anyone's face other than your own
- **ElevenLabs**: "No-Go Voices" system actively detects and blocks well-known voice clones
- **LemonSlice**: Self-certification that you have permission

**Approach: stylized, not cloned.** Cartoon avatar (not a real photo) + Voice Design (describe the style, don't clone). This sidesteps all policies while capturing the vibe.

#### Avatar: stylized cartoon via LemonSlice

Generate a cartoon image using an AI image generator (DALL-E, Midjourney) with a descriptive prompt (no real name). Upload to LemonSlice. Use `agent_prompt` for movement style.

#### Voice: ElevenLabs Voice Design

Use text-described voice creation (not cloning). Describe the voice characteristics without naming the person. Creates an original voice inspired by the style.

#### Persona file

Build from scratch using well-documented catchphrases, speech patterns, and biographical facts. Source material from Wikipedia (export via `wikipyedia-md` or `pandoc`).

#### What this tests
- Whether a richly documented personality produces better LLM catchphrase adherence
- Multi-provider architecture: LemonSlice avatar + ElevenLabs Voice Design
- Whether Voice Design (text-described) produces a convincing character voice without audio cloning
- Persona file complexity — how much detail helps vs. hurts instruction following

#### Implementation steps
1. Generate cartoon avatar image via AI image generator
2. Create ElevenLabs voice via Voice Design (text description)
3. Export reference material to markdown
4. Write persona.md with catchphrases, speech patterns, biographical color
5. Add config entry with `avatar_provider: "lemonslice"`, `tts_provider: "elevenlabs"`
6. Install LemonSlice plugin if not already done (Phase 6b prerequisite)
7. Deploy and compare persona adherence

### Phase 11: Persona management restructuring

Restructure personas to support public repo, multi-provider dispatch, and mid-session persona switching.

#### Directory structure

```
personas/
  base.md                     — Committed. Sally Schoolwork identity, {{STUDENT_NAME}}, {{SCHOOL_NAME}}.
  config.json                 — Committed. Persona entries with pseudonyms, provider/temperature, null IDs.
  config.local.json           — Gitignored. Real student name, school, service IDs per persona.
  example/
    persona.md                — Committed. Template showing expected sections.
  <pseudonym>/
    persona.md                — Gitignored. Voice style, catchphrases.
    (media files)             — Gitignored. Photos, audio, etc.
```

#### Gitignore pattern

```gitignore
personas/*/
!personas/example/
personas/config.local.json
```

#### Config split

**`config.json` (committed)** — architecture decisions, no secrets:
- Persona pseudonym keys
- `avatar_provider`, `tts_provider` per persona
- `llm_temperature` per persona
- `instructions` path per persona
- Null service IDs

**`config.local.json` (gitignored)** — private values:
- `student_name`, `school_name`
- Per-persona: `elevenlabs_voice_id`, `hedra_avatar_id`, `lemonslice_image_url`, etc.
- Per-persona: `elevenlabs_speed`, `elevenlabs_stability`, etc.

`load_persona(name)` merges both configs at runtime and templates `{{STUDENT_NAME}}`/`{{SCHOOL_NAME}}` in base.md.

#### Mid-session persona switching considerations

Eventual goal: user can switch persona mid-session (via voice command or frontend control). The new persona picks up the conversation history.

**What works already:**
- `session_messages` and `session_history` keyed by `device_id`, not persona — conversation history is shared across all personas
- `load_persona(name)` accepts a name parameter
- User profile (onboarding) is persona-independent — no re-onboarding on switch

**Schema change needed:**
- Add `persona` column to `session_messages` table so we know which character said what
- Session summary should note which persona(s) were active

**Technical investigation needed:**
- Can `AgentSession` hot-swap TTS mid-session? Or does it require a new session?
- Can a Hedra/LemonSlice avatar session be stopped and a new one started in the same LiveKit room?
- If session must restart: conversation context is preserved in Supabase `session_messages`, so the new session can reload it
- A `switch_persona` `@function_tool` or frontend RPC control would trigger the switch

**Implementation deferred** — restructure the files now (this phase), implement switching later.

### Phase 12: Avatar widget UI redesign

Improve the agent widget beyond the default LiveKit components. Can run in parallel with Phase 9 (Capacitor) since changes are in the same frontend codebase.

**Depends on:** Phase 6b (avatar2 (dog persona) persona — need both human and dog avatars working to design for both)

**Current state:** Default LiveKit `BarVisualizer` + `VideoTrack` + `DisconnectButton` in a basic floating panel. Functional but generic.

**Areas to improve:**
- Widget chrome — header, sizing, position, expand/collapse animation
- Avatar video framing — aspect ratio, border radius, background when avatar is loading
- State indicators — better visual feedback for listening/thinking/speaking states
- Text chat — add text input alongside voice for quiet environments
- Transcript — show conversation history as text below the avatar
- Mobile responsiveness — widget needs to work well at phone screen sizes (important for Phase 9 Capacitor build)
- Per-persona styling — different personas could have different widget color schemes
- Persona selector — UI control to switch persona mid-session (see Phase 11 for backend considerations). Avatar video and voice change; conversation context persists via Supabase.

**LiveKit components available:**
- `AgentChatTranscript` — realtime conversation transcript
- `AgentChatIndicator` — typing/thinking indicator
- `AgentControlBar` — mic toggle, disconnect, audio controls
- 5 audio visualizer variants (Bar, Grid, Radial, Wave, Aura) as fallback when no avatar video
- All from `@agents-ui` Shadcn components — installed via `npx shadcn@latest add @agents-ui/{component}`

### Phase 13: PII scrub (completed)

PII removed from all committed files via Option B (template in place, no separate fork).

**Approach taken:**
- `base.md` templated with `{{STUDENT_NAME}}`, `{{STUDENT_NICKNAME}}`, `{{SCHOOL_NAME}}` — replaced at runtime from gitignored `config.local.json`
- Persona subdirectories gitignored — only `example/` committed
- Service IDs in gitignored `config.local.json`, not committed `config.json`
- Global scrub of PLAN.md, PROGRESS.md, test files
- Teacher names in tests replaced with generic names
- `private/` directory for personal media assets (gitignored)
- Verified zero PII via grep scan across all committed files

**Remaining for public push:**
- Rewrite git history (`git filter-repo`) or squash all commits — prior commits contain:
  - Real student/school/teacher names
  - Celebrity names and likeness references
  - Service IDs (ElevenLabs, Hedra)
  - Real persona names
- Recommended: push to a new public repo with a single squashed initial commit (simplest, cleanest)

## Open questions

- [ ] Should the rolling index be fetched once at session start, or refreshed if the conversation is long?
- [ ] Is there a need for write-back (e.g., "remind me to check English grades tomorrow"), or read-only for now?
- [ ] Should the agent be accessible only from the tracker frontend, or also standalone (console mode, telephony)?
