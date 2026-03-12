# Setup Wizard

The setup wizard runs on first launch. It collects the user's name, then runs the entire setup flow inside the main Xan chat - using the real Transcript and InputBar components, not static overlay screens. Service configuration and AI-driven agent creation all happen conversationally.

---

## When It Runs

The wizard checks `~/.atrophy/config.json` for a `setup_complete` flag via the `setup:check` IPC handler. If `setup_complete` is missing or `false`, the wizard activates before the main conversation begins.

---

## Architecture

The setup flow is split across three components:

| Component | Role |
|-----------|------|
| `SetupWizard.svelte` | Minimal overlay for welcome (name input), creating (spinner), and done screens only |
| `ServiceCard.svelte` | Inline service card rendered between Transcript and InputBar during setup |
| `Window.svelte` | Orchestrates the entire flow - manages state, routes InputBar submissions to wizard inference |

The key design decision: the setup conversation happens in the real chat, not in a separate overlay. After the welcome screen dismisses, the user sees Xan's opening message in the main Transcript, service cards appear inline above the InputBar, and AI agent creation uses the same InputBar with submissions routed to `wizardInference` instead of normal inference.

---

## Flow

```
SplashScreen -> SetupWizard (welcome) -> Main Chat (services + AI creation) -> SetupWizard (creating) -> SetupWizard (done)
```

### Step 1: Welcome Overlay

A minimal overlay with the brain icon, title ("Atrophy"), subtitle ("Offload your mind."), and a single input field: "What is your name, human?"

The user types their name and presses Enter or clicks Continue. The name is saved to `~/.atrophy/config.json` via `api.updateConfig({ USER_NAME: name })`. The overlay dismisses and setup enters the main chat.

### Step 2: Opening Text (Main Chat)

The welcome overlay is hidden (`setupWizardPhase = 'hidden'`). After a brief pause:

1. `name.mp3` transition audio plays
2. Xan's pre-baked opening text appears in the main Transcript via `addMessage('agent', ...)`
3. `opening.mp3` audio plays alongside

The opening text introduces Xan and tells the user they need to set up their system.

### Step 3: Service Cards (Main Chat)

After the opening settles (2 second delay), service cards appear one at a time between the Transcript and InputBar. The InputBar is disabled while a service card is active (placeholder: "Complete the setup above...").

Four services are offered in order:

#### ElevenLabs - Voice ($5+/month)

- Password input with orange secure border
- Verify button tests `GET https://api.elevenlabs.io/v1/user` with the `xi-api-key` header
- Save writes to `~/.atrophy/.env` via `api.saveSecret()`
- On save: `elevenlabs_saved.mp3` plays
- On skip: `voice_farewell.mp3` plays (last pre-baked audio if voice not configured)

#### Fal.ai - Visual Presence (pay-as-you-go)

- Password input with orange secure border
- Verify button tests `POST https://queue.fal.run/fal-ai/fast-sdxl`
- Save writes to `~/.atrophy/.env`

#### Telegram - Messaging (free)

- Two fields: Bot Token (secure) and Chat ID (plain text)
- Verify button tests `GET https://api.telegram.org/bot.../getMe`
- Bot token saved to `.env`, chat ID saved to `config.json`

#### Google - Workspace + YouTube + Photos (free)

- Two checkboxes: Workspace (Gmail, Calendar, Drive, etc.) and Extra (YouTube, Photos, Search Console)
- "Connect selected" button spawns `scripts/google_auth.py` for OAuth browser flow
- Result shows as "Connected" or error message

Each card has Save/Skip buttons. Skipping advances to the next service immediately.

### Step 4: Agent Creation (Main Chat)

After all four services are handled:

1. `service_complete.mp3` plays
2. "System configured. Now - who do you want to create?" appears in the Transcript
3. The InputBar enables with placeholder "Describe who you want to create..."
4. A subtle "Skip agent creation" button appears below the InputBar

User messages now route to `api.wizardInference()` instead of normal `api.sendMessage()`. The wizard inference uses a separate Claude CLI session (`wizardSessionId`) with Xan's metaprompt system prompt. Responses appear in the main Transcript.

#### The Metaprompt

The system prompt puts the AI in character as Xan. Key instructions:

- Jump straight into creation - no preamble, no repeating the intro
- One or two questions per message, never a questionnaire
- Push on vagueness - "warm and helpful" isn't a character
- After 3-5 exchanges, output `AGENT_CONFIG` JSON
- If ElevenLabs was saved, ask about voice ID
- Keep messages short (2-4 sentences)
- Agents can be anything: strategist, journal companion, fictional character, shadow self, etc.

#### AGENT_CONFIG Detection

Each AI response is checked for a fenced JSON block containing `AGENT_CONFIG`:

````
```json
{
    "AGENT_CONFIG": {
        "display_name": "...",
        "opening_line": "First words they ever say",
        "origin_story": "A 2-3 sentence origin",
        "core_nature": "What they fundamentally are",
        "character_traits": "How they talk, their temperament, edges",
        "values": "What they care about",
        "relationship": "How they relate to the user",
        "wont_do": "What they refuse to do",
        "friction_modes": "How they push back",
        "writing_style": "How they write",
        "elevenlabs_voice_id": "Voice ID if provided, empty string if not"
    }
}
```
````

When detected, the flow transitions to the creating overlay.

### Step 5: Creating Overlay

`SetupWizard.svelte` shows the creating phase:

- Spinner animation
- "Creating {agentName}..." title
- "Building identity, voice, and prompts." subtitle

During this overlay, `api.createAgent(agentConfig)` scaffolds the agent directory and `api.switchAgent()` makes it active. After 2.5 seconds, the overlay transitions to done.

### Step 6: Done Overlay

Shows the brain icon, "Meet {agentName}." (or "Ready." if skipped), and "Starting up..." subtitle. Auto-dismisses after 3 seconds.

On dismissal, `finishSetup()` runs:

1. Writes `setup_complete: true` and `USER_NAME` to config
2. Reloads config and agent list
3. Fetches the new agent's opening line and shows it in the Transcript

---

## Agent Scaffolding

The `setup:createAgent` IPC handler calls `createAgent()` which:

- Derives a slug from the display name
- Creates the full agent directory structure under `~/.atrophy/agents/<slug>/`
- Writes `agent.json` with identity, boundaries, voice defaults, channels, heartbeat, and autonomy settings
- Generates prompts from templates
- Sets up the SQLite database

Voice defaults: stability 0.5, similarity 0.75, style 0.35, playback rate 1.12. Wake words: `hey <slug>, <slug>`. Active hours: 9-22, 30 minute heartbeat interval.

---

## InputBar Integration

During setup, `Window.svelte` passes props to `InputBar`:

| Prop | Value during setup | Purpose |
|------|-------------------|---------|
| `onSubmit` | `setupSubmit` function (after services done) | Routes messages to `wizardInference` instead of normal inference |
| `disabled` | `true` while service card is showing | Prevents input during service configuration |
| `placeholder` | Context-specific text | "Complete the setup above..." or "Describe who you want to create..." |

The `setupSubmit` handler:
1. Adds the user message to the Transcript
2. Sets `session.inferenceState = 'thinking'` (shows ThinkingIndicator)
3. Calls `api.wizardInference(text)`
4. Adds the AI response to the Transcript
5. Checks for `AGENT_CONFIG` in the response
6. Resets inference state to idle

---

## Skip Behavior

- **Skip agent creation**: The "Skip agent creation" button below InputBar calls `finishSetup()` directly - marks setup complete with Xan as the default agent
- **Skip individual services**: Each service card's Skip button advances to the next card. The AI's system prompt knows services were handled deterministically and adjusts accordingly

---

## Resetting Setup

Two ways to re-run the wizard:

1. **Settings panel**: Under the **APP** section at the bottom, click **Reset Setup**. On next launch, the wizard runs again.

2. **Manual**: Edit `~/.atrophy/config.json` and set `"setup_complete": false` (or remove the key entirely).

Resetting setup does not delete existing agents or their data. The wizard will create a new agent alongside any existing ones.
