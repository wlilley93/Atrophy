# Display System

The GUI provides a frameless Electron BrowserWindow with Svelte 5 components, vibrancy effects, and a dark theme. All rendering happens in the renderer process using Svelte 5 runes for reactive state.

## Window Configuration

```typescript
new BrowserWindow({
  width: config.WINDOW_WIDTH,   // default 622
  height: config.WINDOW_HEIGHT, // default 830
  minWidth: 360, minHeight: 480,
  titleBarStyle: 'hiddenInset',
  trafficLightPosition: { x: 14, y: 14 },
  vibrancy: 'ultra-dark',
  visualEffectState: 'active',
  backgroundColor: '#00000000',
  show: false,  // shown after ready-to-show (unless menu bar mode)
});
```

Window dimensions are configurable per-agent via `agent.json` under `WINDOW_WIDTH` and `WINDOW_HEIGHT`.

## Component Hierarchy

```
App.svelte
  Window.svelte
    OrbAvatar.svelte
    AgentName.svelte
    ThinkingIndicator.svelte
    Transcript.svelte
    InputBar.svelte
    Timer.svelte          (overlay, conditional)
    Canvas.svelte         (overlay, conditional)
    Artefact.svelte       (overlay, conditional)
    Settings.svelte       (overlay, conditional)
    SetupWizard.svelte    (overlay, conditional)
```

## Reactive Stores

State is managed via Svelte 5 `$state` runes in `src/renderer/stores/`:

| Store | File | Key Fields |
|-------|------|------------|
| `session` | `session.svelte.ts` | `phase`, `inferenceState`, `isRecording`, `idleSeconds` |
| `transcript` | `transcript.svelte.ts` | `messages[]` with `revealed`/`complete` state for animation |
| `agents` | `agents.svelte.ts` | `current`, `displayName`, `list`, `switchDirection` |
| `settings` | `settings.svelte.ts` | `userName`, `version`, `avatarEnabled`, `ttsBackend`, `inputMode` |
| `audio` | `audio.svelte.ts` | `queue`, `isPlaying`, `vignetteOpacity` |
| `emotionalState` | `emotional-state.svelte.ts` | `connection`, `curiosity`, `confidence`, `warmth`, `frustration`, `playfulness` |
| `activeEmotion` | `emotion-colours.svelte.ts` | `type` (EmotionType or null), `colour` (HSL) |

## src/renderer/components/Window.svelte - Main Orchestrator

The main window layout. Manages boot sequence, overlay coordination, agent switching, silence timer, deferral handling, and keyboard shortcuts.

### Boot Sequence

1. Load config and agent list from main process via IPC (`getConfig()`, `getAgents()`)
2. Check `needsSetup()` - if true, fade out boot overlay and show SetupWizard
3. If no setup needed, fetch opening line via `getOpeningLine()` IPC
4. Add opening line to transcript with character reveal animation
5. Fade out boot overlay (1.5s transition)

The boot overlay is a full-screen black div that transitions from opacity 1 to 0, with a subtle "connecting..." label during load.

### Opening Line

The opening line displayed on launch comes from the `OPENING_LINE` field in the agent's `agent.json`. The main process handler (`opening:get`) returns this value directly, falling back to `"Ready. Where are we?"` if unset.

Unlike the Python version (which generates dynamic openings via inference with randomised style directives), the Electron version currently reads a static opening line from config. Dynamic opening generation with style directives (question, observation, tease, admission, etc.) is not yet ported.

The opening line is configurable in Settings > Agent Identity.

### Overlay Layer Stack

| z-index | Layer |
|---------|-------|
| 9999 | Boot overlay |
| 80 | Agent deferral iris wipe |
| 75 | Agent switch clip-path animation |
| 70 | SetupWizard |
| 50 | Timer |
| 45 | Canvas |
| 40 | Artefact |
| 15 | Mode buttons |
| 12 | Silence prompt |
| 10 | Top bar, Input bar |
| 5 | Transcript |
| 1 | Vignette overlay |
| 0 | OrbAvatar |

Overlays are conditionally rendered via `{#if}` blocks and dismissed via Escape in priority order (settings -> artefact -> canvas -> timer -> silence prompt).

### State

```typescript
let showSettings = $state(false);
let showTimer = $state(false);
let showCanvas = $state(false);
let showArtefact = $state(false);
let needsSetup = $state(false);
let bootPhase = $state<'boot' | 'ready'>('boot');
let avatarVisible = $state(true);
let isMuted = $state(false);
let wakeListening = $state(false);
let callActive = $state(false);
let eyeMode = $state(false);
```

### Agent Switch Animation

When switching agents (via Cmd+Up/Down or the AgentName chevrons), a clip-path circle transition expands from centre:

```typescript
agentSwitchClip = 'circle(0% at 50% 50%)';
requestAnimationFrame(() => {
  agentSwitchClip = 'circle(150% at 50% 50%)';
});
```

The overlay uses a 0.65s cubic-bezier CSS transition. The agent name updates via rolodex animation in AgentName.svelte.

### Agent Deferral (Codec-Style Handoff)

When one agent defers to another, an iris wipe animation plays:

1. Stop ongoing inference and clear audio queue
2. Iris close (clip-path circle shrinks to 0%) - 250ms
3. At peak black, call `completeDeferral()` IPC to switch agents in main process
4. Update renderer agent state
5. Iris open (clip-path circle expands to 150%) - 300ms

The "Handing off to {target}..." label appears during the black frame.

### Silence Timer

A 5-minute idle timer shows a subtle "Still here?" prompt above the input bar. Resets on any keypress or mouse movement. Clicking the prompt dismisses it and resets the timer.

### Warm Vignette

A radial gradient overlay (`rgba(40, 25, 10, 0.47)`) that fades in during TTS audio playback, creating a warm visual effect. Opacity is driven by the `audio.vignetteOpacity` store value.

### Mode Buttons

A row of icon buttons in the top-right corner, ordered left-to-right:

| Button | Icon | Behaviour |
|--------|------|-----------|
| Eye | Eye shape (slash when active) | Toggles transcript visibility (eye mode). Hides the chat area, leaving only the orb and input bar. |
| Mute | Speaker with waves (X when muted) | Toggles TTS audio playback |
| Wake | Microphone with radio waves | Toggles wake word listener. Background turns green when active (`rgba(120, 255, 140, 0.9)`) |
| Call | Phone icon | Toggles hands-free voice call mode |
| Artefact | Document icon | Opens artefact overlay. Shows a blue notification badge when new artefacts are available |
| Timer | Clock icon | Opens timer overlay |
| Settings | Gear icon | Opens settings overlay. Background changes when active |

All buttons are 34px SVG icons with transparent backgrounds, dim white colour (`var(--text-dim)`), and hover/active state transitions.

### Keyboard Shortcuts

| Shortcut | Action | Scope |
|----------|--------|-------|
| Cmd+, | Toggle settings panel | Window |
| Cmd+Shift+W | Toggle wake word detection | Window |
| Cmd+K | Toggle canvas overlay | Window |
| Cmd+E | Toggle eye mode (hide transcript) | Window |
| Cmd+Up / Cmd+Down | Cycle through agents | Window |
| Ctrl (hold) | Push-to-talk recording | Window |
| Escape | Close overlays in priority order | Window |
| Cmd+Shift+Space | Show/hide the app window | Global (menu bar mode only, registered via `globalShortcut`) |

**Not yet ported from Python:** Cmd+C (copy selected text or last companion message) and Cmd+M (intercept native minimize to hide to tray). The Electron version currently relies on the OS default for Cmd+C (standard copy) and uses native traffic light minimize behavior.

## src/renderer/components/Transcript.svelte - Message Display

Displays the conversation history with character-by-character reveal animation for agent messages.

### Reveal Animation

Agent messages start with `revealed: 0` and animate characters at 8 chars per 25ms tick:

```typescript
const REVEAL_RATE = 8;
const REVEAL_INTERVAL = 25;
```

A `setInterval` timer increments `msg.revealed` until it reaches `msg.content.length`. User messages and dividers are immediately fully revealed.

### Display Filtering

Before rendering, message text is cleaned:
- Prosody tags (`[word]`) are stripped
- Audio tags (`<audio>...</audio>`) are removed
- Multiple consecutive spaces are collapsed

### Auto-Scroll

The transcript auto-scrolls to the bottom when new content appears, unless the user has scrolled up (detected by checking if the scroll position is within 40px of the bottom).

### Message Types

| Role | Styling |
|------|---------|
| `user` | `var(--text-user)` colour |
| `agent` | `var(--text-companion)` colour |
| `divider` | Centered uppercase text with green borders, 11px font, 3px letter spacing |

Messages have 24px vertical spacing between different roles (user -> agent or agent -> user).

## src/renderer/components/InputBar.svelte - Text Input & Recording

A floating input bar at the bottom of the window with text input, mic button, and send/stop button.

### Input Field

Standard text input with rounded corners. Disabled during inference or recording. Placeholder changes from "Message..." to "Listening..." during recording. Border turns red (`rgba(255, 80, 80, 0.5)`) when recording.

### Keystroke Sound

Plays a quiet (0.02 volume) macOS Tink sound on each keypress, throttled to 60ms minimum interval between sounds.

### Mic Button

Positioned to the right of the input field. Supports hold-to-record (mousedown/mouseup) as an alternative to Ctrl push-to-talk. Pulses red during recording.

### Send / Stop Button

Dual-purpose button:
- **Idle**: Up-arrow icon, sends the current input text
- **Active** (during inference): Square stop icon, cancels the current inference stream

### Streaming Listener Setup

The InputBar wires up all inference streaming listeners in a `$effect`:

```typescript
api.onTextDelta((text) => {
  session.inferenceState = 'streaming';
  appendToLast(text);
});
api.onDone((_fullText) => {
  completeLast();
  session.inferenceState = 'idle';
});
api.onCompacting(() => {
  session.inferenceState = 'compacting';
});
```

TTS events are also wired here to drive vignette opacity.

## src/renderer/components/OrbAvatar.svelte - Avatar Display

Video playback with procedural canvas orb fallback.

### Video Layer

Loads avatar video clips from the agent's avatar directory via `getAvatarVideoPath()` IPC. Videos play looped, muted, and full-bleed (`object-fit: cover`). Fades in over 0.8s when ready.

### Canvas Fallback

When video is unavailable (or hasn't loaded yet), renders a procedural orb using Canvas 2D:

- **Breathing animation** - orb radius pulses at 1.2 Hz (idle) or 4.0 Hz (thinking), with 3%/6% amplitude
- **Colour driven by emotional state** - hue shifts based on warmth, playfulness, and frustration values from the `emotionalState` store
- **Emotion colour blending** - when an emotion reaction is active (`activeEmotion.type !== null`), the orb smoothly blends toward the emotion's HSL colour at a rate of 0.04 per frame
- **Glow layers** - 4 concentric radial gradient layers with decreasing alpha
- **Core gradient** - offset radial gradient for a 3D glass-like appearance
- **Highlight** - small bright spot offset from centre
- **Particles** - 5 ambient particles (12 when thinking) orbit the core at varying distances

DPR-aware canvas scaling ensures crisp rendering on Retina displays.

### Emotion Colour System

`emotion-colours.svelte.ts` defines a keyword-based emotion classifier:

| Emotion | Colour | Example Keywords |
|---------|--------|------------------|
| `thinking` | dark blue (h:230) | Triggered programmatically during inference |
| `alert` | red (h:0) | warning, danger, urgent, critical |
| `frustrated` | red (h:0) | error, failed, broken, crash |
| `positive` | green (h:140) | done, success, great, fixed |
| `cautious` | orange (h:30) | caution, careful, consider, risk |
| `reflective` | purple (h:270) | interesting, wonder, philosophical |

The classifier scores keywords by frequency weighted by length (`count * (1 + keyword.length / 10)`). A minimum score of 2.0 filters out weak matches. Emotion colours revert to default blue after 12 seconds.

## src/renderer/components/AgentName.svelte - Agent Name Display

Top-left agent name with rolodex-style switching animation.

### Rolodex Animation

When the agent name changes, the text slides vertically with an ease-out cubic easing over 400ms. Direction is determined by `agents.switchDirection` (-1 slides up, +1 slides down). The name text swaps at the 50% mark of the animation.

### Chevrons

Up/down chevron buttons appear on hover, allowing agent cycling. The chevrons are invisible by default (opacity 0) and fade in when the agent name area is hovered.

### Styling

- 20px bold uppercase text with 1px letter spacing
- `rgba(255, 255, 255, 0.78)` colour with subtle text shadow
- Clipped to 30px height to contain the rolodex animation

## src/renderer/components/ThinkingIndicator.svelte - Inference Status

A pulsing brain SVG icon displayed next to the agent name during inference. Opacity oscillates between 0.25 and 0.80 using a sine wave at ~3 Hz (via `setInterval` at 50ms with `Math.sin(frame * 0.15)`).

Shown when `session.inferenceState !== 'idle'` (covers thinking, streaming, and compacting states).

## src/renderer/components/Timer.svelte - Countdown Timer

A full-screen overlay triggered by the timer mode button or the `set_timer` MCP tool.

**Features:**
- Default 5-minute countdown, initialised in `onMount`
- Controls: Start/Pause toggle, +1m, +5m pill buttons with amber borders
- Monospace display at 72px with warm amber colour (`rgba(255, 180, 100, 0.9)`) and subtle glow (`text-shadow: 0 0 40px rgba(255, 140, 50, 0.2)`)
- Semi-transparent backdrop (`rgba(12, 12, 14, 0.92)`) with 20px blur
- Close button in top-right corner (X icon, dismisses via `onClose` prop)

### Timing

The timer uses `setInterval` with a 1-second tick. Each tick decrements `totalSeconds` by 1. When `totalSeconds` reaches 0, the interval is cleared and the timer pauses. The display format switches between `m:ss` and `h:mm:ss` depending on whether hours are present.

**Note:** Unlike the Python version which uses `time.monotonic()` for drift-free countdown, the Electron timer uses a simple `setInterval` at 1000ms. This is adequate for the intended use (cooking timers, break reminders) but may drift slightly over long durations.

### Not yet ported from Python

The following Python timer features are not yet implemented:
- **Alarm sound** - no sound plays when the timer reaches zero (Python loops the system Glass sound up to 6 chimes)
- **macOS notification** - no notification is fired at completion
- **Color shift** - the display colour does not fade to red in the final seconds (Python shifts to red in the last 10 seconds)
- **Auto-dismiss** - the timer does not auto-dismiss after the alarm period (Python auto-dismisses after 60 seconds)
- **Click-to-dismiss during alarm** - not applicable since there is no alarm state
- **Draggable positioning** - the overlay is full-screen rather than a small floating window; it is not draggable

## src/renderer/components/Canvas.svelte - PIP Webview Overlay

A full-screen overlay for rendering HTML content using the Electron `<webview>` tag.

### Behaviour

- Toggled via Cmd+K or the canvas button
- Shows an empty state ("No canvas content") when no URL is set
- Close button in top-right corner
- Semi-transparent backdrop (`rgba(12, 12, 14, 0.95)`) with 20px blur
- Content area has rounded corners (12px) and a border

### Content Pipeline

1. MCP `render_canvas` tool sets the canvas URL via IPC
2. The `<webview>` element loads the URL
3. Content is a full HTML document - CSS/JS are supported

The canvas URL is stored in a reactive `$state` variable. When set, the `<webview>` element renders; when empty, an empty state is shown with placeholder text ("No canvas content" / "Content will appear here when the agent creates it").

### Not yet ported from Python

- **Fade animations** - Python uses 300ms InOutCubic `QPropertyAnimation` for fade in/out. The Electron version currently appears/disappears instantly via conditional rendering (`{#if}`)
- **File watcher auto-refresh** - Python uses `QFileSystemWatcher` with 100ms debounce to detect changes to `.canvas_content.html` and auto-refresh. The Electron version loads a URL once and does not watch for file changes
- **Programmatic API** - Python exposes `set_content()`, `show_canvas()`, `dismiss()`, `toggle()`, and `reposition()` methods. The Electron version is controlled entirely via the `showCanvas` state toggle and URL assignment
- **HTML templates** - Python includes `display/templates/` with `default_canvas.html` and `memory_graph.html`. The Electron version has no bundled canvas templates

## src/renderer/components/Artefact.svelte - Artefact Display

Full-bleed overlay for displaying artefacts created by the agent via the `create_artefact` MCP tool.

### Content Display

Supports multiple content types via a `contentType` state variable:
- `html` / `svg` - rendered directly via `{@html content}` into the scrollable content area
- Other types (markdown, code) - displayed in a monospace `<pre>` block with `word-break: break-word` and `white-space: pre-wrap`

When no content is loaded, an empty state ("No artefact to display") is shown.

### Artefact Types

The Python version supports three artefact types with different generation pipelines:
- **html** - rendered directly in the overlay. No external cost.
- **image** - generated via Flux on fal.ai. Requires user approval before generation.
- **video** - generated via Kling on fal.ai. Requires user approval before generation.

The Electron version currently handles `html`, `svg`, and fallback text display. Image and video artefact types, along with the approval flow for generation, are not yet ported.

### Loading Indicator

**Not yet ported.** The Python version polls `.artefact_display.json` every 2 seconds. While an artefact has `"status": "generating"`, a slim indeterminate `QProgressBar` appears at the window bottom. The Electron version does not yet have a loading indicator during artefact generation.

### Gallery Panel

A slide-out panel on the left (240px wide) listing all artefacts for the current agent. Each entry shows a type badge (10px uppercase with letter spacing) and title. Toggled via the grid icon button in the artefact header. The panel has a dark background (`rgba(20, 20, 24, 0.95)`) with rounded corners and scrollable overflow.

Artefacts are stored in `~/.atrophy/agents/<name>/artefacts/` with a sorted, deduplicated JSON index.

## src/renderer/components/Settings.svelte - Settings Panel

A full-screen overlay with three tabs: Settings, Usage, and Activity.

### Settings Tab

A scrollable form with 16 sections:

| Section | Controls |
|---------|----------|
| Agents | Agent list with Switch / Delete per agent. Shows display name and role |
| You | User name text input |
| Agent Identity | Agent display name, opening line, wake words |
| Tools | Per-agent toggleable MCP tools (deferral, Telegram, reminders, timers, task scheduling, canvas, Obsidian notes, journal prompting, emotional state, artefact creation, schedule management, Puppeteer, fal media generation) |
| Window | Width/height number inputs, avatar enabled checkbox, startup at login toggle |
| Voice & TTS | Backend selector (ElevenLabs/Fal/say/off), ElevenLabs settings (API key, voice ID, model selector, stability/similarity/style sliders), fal voice ID, playback rate slider |
| Input | Input mode (text/voice/dual), PTT key, wake word enabled toggle, wake chunk seconds |
| Notifications | Notification enabled toggle |
| Audio Capture | Sample rate, max record seconds |
| Inference | Claude binary path, effort level (low/medium/high), adaptive effort toggle, max turns |
| Memory & Context | Context summaries toggle, max context tokens, vector search weight slider, embedding model, embedding dimensions |
| Session | Session soft limit (minutes) |
| Heartbeat | Active hours start/end, heartbeat interval (minutes) |
| Paths | Obsidian vault path, database path, whisper binary path (read-only info labels) |
| Google | Google configured status display, launch auth button |
| Telegram | Bot token (password field), chat ID |
| About | Version, install path, check for updates / download update / install update via electron-updater, reset setup wizard button |

### Usage Tab

Displays token usage data from the main process via `getUsage()` IPC. Shows daily breakdown.

### Activity Tab

Shows recent activity from `getActivity()` IPC.

### Control Types

- **Sliders** - for floats (stability, similarity, style, playback rate, VAD threshold)
- **Select dropdowns** - for enums (TTS backend, input mode, model)
- **Checkboxes** - for booleans (avatar enabled, wake word enabled, tool toggles)
- **Number inputs** - for integers (window width/height, sample rate, max turns)
- **Text inputs** - for strings (user name, display name, voice ID), with password mode for secrets (API keys, bot tokens)
- **Toggle switches** - for login item, notifications

### Save Modes

- **Apply** - writes values to config via `updateConfig()` IPC. Updates take effect immediately in the running app.
- **Save** - calls Apply, then persists to `~/.atrophy/config.json` and `agent.json` on disk.

### Updates

The About section uses `electron-updater` via the preload API:
- `checkForUpdates()` - checks GitHub Releases for new versions
- `downloadUpdate()` - downloads in the background, shows progress bar
- `quitAndInstall()` - restarts the app with the update

Update lifecycle events (`onUpdateAvailable`, `onUpdateProgress`, `onUpdateDownloaded`, `onUpdateError`) are forwarded from main to renderer via IPC.

## src/renderer/components/SetupWizard.svelte - First-Launch Flow

A full-screen overlay shown on first launch (when `setup_complete` is false in `~/.atrophy/config.json`).

### Phases

| Phase | Content |
|-------|---------|
| `intro` | Brain frame animation (10-frame cycle at 180ms per frame, auto-advances after 3.2s) |
| `welcome` | "Hello." - asks the user's name via text input |
| `create` | AI-driven chat interface for agent creation. Xan walks through identity, voice, and personality. Sends messages via `wizardInference()` IPC. Detects `AGENT_CONFIG` JSON in responses to scaffold the agent via `createAgent()` IPC |
| `elevenlabs` | Service card for ElevenLabs API key. Orange-bordered secure input. Verify button tests the key against `api.elevenlabs.io/v1/user` |
| `telegram` | Service card for Telegram bot token and chat ID. Verify button tests against `api.telegram.org/bot.../getMe` |
| `done` | "Ready." with a green orb. Auto-dismisses after 2s |

### Service Cards

Verification happens directly from the renderer (fetch to external APIs). Verified keys are passed to main via `updateConfig()` on finish.

### Brain Animation

Uses pre-rendered brain frame PNGs loaded via `import.meta.glob()` (Vite static imports). The frames cycle through organic warm, cybernetic blue, and decay green-brown states with a subtle pulse animation.

### Secure Input

API key inputs use `type="password"` with an orange border (`rgba(220, 140, 40, 0.45)`) and monospace font. Keys are never displayed in the conversation log.

The wizard is accessible again via Settings > About > Reset Setup Wizard (sets `setup_complete` to false).

## System Tray (src/main/index.ts)

In menu bar mode (`--app`), a system tray icon is created. The tray uses a hand-crafted brain template image (`resources/icons/menubar_brain@2x.png`) that adapts to macOS light/dark mode automatically. If the brain icon is not found, a procedural orb icon is generated via `getTrayIcon()`.

### Tray Menu

```typescript
Menu.buildFromTemplate([
  { label: 'Show', click: () => mainWindow.show() },
  { type: 'separator' },
  { label: 'Quit', click: () => app.quit() },
]);
```

Clicking the tray icon directly toggles the main window visibility (show/hide).

### Not yet ported from Python

The Python tray has richer menu items that are not yet present in Electron:
- **Chat** - toggle the floating chat overlay (the Electron version does not have a chat overlay; see below)
- **Agents** - submenu listing all discovered agents for quick switching
- **Set Away/Active** - toggle user presence status

The tray icon state can be updated programmatically via `updateTrayState(state)` (active, muted, idle, away), but this only applies when using the procedural orb icon. The brain template image handles state differently.

## Chat Overlay

**Not yet ported.** The Python version has a `ChatPanel` - a floating `520x380` frameless, always-on-top panel triggered by Cmd+Shift+Space. It provides text-only chat (no video) with a transcript and input bar, and is draggable.

In the Electron version, Cmd+Shift+Space (in menu bar mode) simply shows/hides the main window rather than opening a separate chat overlay.

## Window Minimize & Close Behavior

The minimize and close behavior depends on the app mode:

- **GUI mode** (`--gui`): `minimizeWindow()` performs a standard native minimize. `closeWindow()` closes the window, and when all windows are closed on non-macOS platforms, the app quits. On macOS, the app stays running (standard behavior).
- **Menu bar mode** (`--app`): `closeWindow()` hides the window to the tray instead of closing it. The dock icon is hidden (`app.dock.hide()`). The app stays running in the background.

**Not yet ported from Python:** The Python version intercepts Cmd+M and the yellow traffic light button to hide to tray instead of native minimize. The Electron version does not intercept these - native minimize behavior applies.

## Shutdown Screen

**Not yet implemented.** The Python version has a shutdown screen that mirrors the boot screen but plays the brain animation in reverse (rot to cybernetic to organic) with a faster pulse (3.0 Hz vs 2.0 Hz) and smaller brain icon (90px vs 110px). The Electron app currently closes immediately without a shutdown animation. The `AppPhase` type includes a `'shutdown'` state but it is not used.

## Preload API (src/preload/index.ts)

All communication between renderer and main flows through `contextBridge.exposeInMainWorld('atrophy', api)`. The preload defines the typed `AtrophyAPI` interface.

### Listener Pattern

All event listeners use a factory function that returns an unsubscribe callback:

```typescript
function createListener(channel: string) {
  return (cb: (...args: unknown[]) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, ...args: unknown[]) => cb(...args);
    ipcRenderer.on(channel, handler);
    return () => ipcRenderer.removeListener(channel, handler);
  };
}
```

This enables clean teardown in Svelte `$effect` cleanup functions.

### API Surface

| Category | Methods |
|----------|---------|
| Inference | `sendMessage`, `stopInference`, `onTextDelta`, `onSentenceReady`, `onToolUse`, `onDone`, `onCompacting`, `onError` |
| Audio | `startRecording`, `stopRecording`, `sendAudioChunk` |
| TTS | `onTtsStarted`, `onTtsDone`, `onTtsQueueEmpty` |
| Wake word | `onWakeWordStart`, `onWakeWordStop`, `sendWakeWordChunk` |
| Agents | `switchAgent`, `getAgents`, `getAgentsFull` |
| Config | `getConfig`, `updateConfig` |
| Setup | `needsSetup`, `wizardInference`, `createAgent` |
| Window | `toggleFullscreen`, `minimizeWindow`, `closeWindow` |
| Avatar | `getAvatarVideoPath` |
| Updates | `checkForUpdates`, `downloadUpdate`, `quitAndInstall`, `onUpdate*` |
| Deferral | `completeDeferral`, `onDeferralRequest` |
| Queues | `drainAgentQueue`, `drainAllAgentQueues`, `onQueueMessage` |
| Other | `getOpeningLine`, `isLoginItemEnabled`, `toggleLoginItem`, `getUsage`, `getActivity` |

## CSS Theme

Defined in `src/renderer/styles/global.css`:

```css
:root {
  --bg: #141418;
  --bg-secondary: rgba(255, 255, 255, 0.04);
  --text-primary: rgba(255, 255, 255, 0.85);
  --text-secondary: rgba(255, 255, 255, 0.5);
  --text-dim: rgba(255, 255, 255, 0.3);
  --accent: rgba(100, 140, 255, 0.3);
  --accent-hover: rgba(100, 140, 255, 0.5);
  --border: rgba(255, 255, 255, 0.1);
  --font-sans: -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui;
  --font-mono: 'SF Mono', 'Fira Code', monospace;
}
```

All components use scoped `<style>` blocks. The theme is dark-only - no light mode.
