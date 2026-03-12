# Display System

The GUI provides a frameless Electron BrowserWindow with Svelte 5 components, vibrancy effects, and a dark theme. All rendering happens in the renderer process using Svelte 5 runes for reactive state. The display system is the user-facing half of the application - it owns the conversation transcript, voice controls, overlays (timer, canvas, artefacts, settings, setup wizard), and the procedural orb avatar. It communicates with the main process exclusively through the preload API's typed IPC bridge, never touching the filesystem, SQLite, or Claude CLI directly.

This document covers every renderer-side file: the entry point, root component, all Svelte components, all reactive stores, the global CSS theme, and the preload API surface. It also covers the main-process tray and window management code that directly supports the display layer.

## Entry Point (src/renderer/main.ts)

The renderer entry point is the first code that runs inside the BrowserWindow's web context. It imports the global CSS stylesheet to establish the dark theme and custom properties, then mounts the root `App.svelte` component onto the `#app` DOM element using Svelte 5's `mount()` function. The `#app` element is defined in `src/renderer/index.html` and serves as the sole mount target for the entire Svelte component tree. This file also re-exports the mounted app instance, though nothing currently consumes that export.

The following snippet shows the complete entry point, which is intentionally minimal - all application logic lives in the component tree below:

```typescript
import './styles/global.css';
import App from './App.svelte';
import { mount } from 'svelte';

const app = mount(App, {
  target: document.getElementById('app')!,
});
```

## Root Component (src/renderer/App.svelte)

`App.svelte` is a thin bootstrap layer that sits between the entry point and the main layout component. It imports `Window.svelte` and renders it as the sole child. Its primary responsibility is populating the reactive stores with initial data from the main process before any child components mount, ensuring that config values and agent state are available when the boot sequence begins.

On script initialization (not inside `onMount` - the code runs synchronously during component creation), App.svelte calls the preload API to load configuration and agent data. The initialization function performs the following steps in sequence:

- Calls `api.getConfig()` to fetch the full configuration object from the main process, then populates the `settings` store with `userName`, `version`, `avatarEnabled`, `ttsBackend`, `inputMode`, and sets `loaded = true` to signal that config is ready.
- Sets the `agents` store's `current` and `displayName` fields from the config's `agentName` and `agentDisplayName` values, falling back to `'xan'` and `'Xan'` respectively if unset.
- Calls `api.getAgents()` to fetch the list of discovered agent directory names and populates `agents.list`.
- Sets `session.phase = 'boot'` to indicate the application is in its startup phase.

This initialization runs before Window.svelte's `onMount` fires, so stores are populated by the time the boot sequence begins. If the preload API is unavailable (e.g. during testing outside Electron), the init function returns silently and stores retain their defaults.

## Window Configuration

The main process creates the BrowserWindow with a specific set of options designed to produce a frameless, vibrancy-backed dark window that blends with macOS. The configuration establishes the visual foundation that all renderer-side components build upon. Window dimensions are configurable per-agent via `agent.json` under `WINDOW_WIDTH` and `WINDOW_HEIGHT`, with sensible defaults for the standard chat interface layout.

The following snippet shows the BrowserWindow constructor options used in `src/main/index.ts`:

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

The `titleBarStyle: 'hiddenInset'` hides the standard title bar while keeping the traffic light buttons (close, minimize, fullscreen) inset at coordinate (14, 14). The `vibrancy: 'ultra-dark'` applies macOS's native vibrancy effect, giving the window a translucent backdrop that shows through to the desktop. The `visualEffectState: 'active'` keeps the vibrancy effect active even when the window loses focus. The transparent background colour (`#00000000`) allows the vibrancy layer to show through, and `show: false` prevents a flash of white before the renderer content is ready - the window is shown only after the `ready-to-show` event fires, unless in menu bar mode where it starts hidden.

## Component Hierarchy

The component tree follows a flat structure where Window.svelte acts as the layout root and all major features are direct children. This keeps the hierarchy shallow and makes overlay coordination straightforward - Window.svelte owns all the boolean flags that control which overlays are visible and handles the Escape key dismiss priority.

The tree below shows every component and its z-index layer. Lower z-index values render behind higher ones, creating the visual stacking order from the background orb up through the boot overlay:

```
App.svelte
  Window.svelte
    OrbAvatar.svelte        (z-index: 0, background layer)
    AgentName.svelte         (z-index: 10, top-left)
    ThinkingIndicator.svelte (z-index: 10, next to agent name)
    Transcript.svelte        (z-index: 5, flex body)
    InputBar.svelte          (z-index: 10, bottom)
    Timer.svelte             (z-index: 50, overlay, conditional)
    Canvas.svelte            (z-index: 45, overlay, conditional)
    Artefact.svelte          (z-index: 40, overlay, conditional)
    Settings.svelte          (overlay, conditional)
    SetupWizard.svelte       (z-index: 70, overlay, conditional)
    MirrorSetup.svelte       (z-index: 70, overlay, agent custom setup)
```

---

## Reactive Stores (src/renderer/stores/)

All stores use Svelte 5's module-level `$state` rune pattern - exported reactive objects that can be imported and mutated from any component. This approach replaces Svelte 4's writable stores with a simpler model: each store file exports a plain object wrapped in `$state()`, and any component that imports it can read or write fields directly. Svelte's compiler tracks fine-grained dependencies so that only the components reading a specific field re-render when that field changes.

The stores serve as the single source of truth for all renderer-side state. The main process pushes data into stores via IPC during boot (in App.svelte) and during streaming (in InputBar.svelte's effect listeners). Components read stores reactively and mutate them in response to user actions.

### session.svelte.ts

This store tracks the application lifecycle phase and the current inference state. It is the central coordination point that other components read to determine what the app is doing right now. The `phase` field drives high-level UI decisions (should we show the setup wizard? are we shutting down?), while `inferenceState` drives moment-to-moment UI updates like showing the thinking indicator, disabling the input bar, and controlling the vignette overlay.

The store exports two union types and a single reactive state object that holds all session-related fields:

```typescript
export const session = $state({
  phase: 'boot' as AppPhase,
  inferenceState: 'idle' as InferenceState,
  isRecording: false,
  idleSeconds: 0,
});
```

The following table describes each field, its type, default value, and how it connects to the rest of the system:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `phase` | `AppPhase` | `'boot'` | Current app lifecycle phase. Set to `'boot'` in App.svelte, transitions to `'setup'` or `'ready'` after Window.svelte's boot sequence completes. The `'shutdown'` value is defined but not yet used. |
| `inferenceState` | `InferenceState` | `'idle'` | Current inference state. Set to `'thinking'` when the user sends a message, `'streaming'` when the first text delta arrives, `'compacting'` when Claude signals context compaction, and back to `'idle'` when done or on error. Drives ThinkingIndicator visibility, InputBar disable state, and OrbAvatar breathing rate. |
| `isRecording` | `boolean` | `false` | Whether push-to-talk recording is active. Set by InputBar.svelte during Ctrl key or mic button hold. |
| `idleSeconds` | `number` | `0` | Seconds since the last user interaction. Currently defined but not actively incremented - the silence timer in Window.svelte uses its own `lastInputTime` timestamp instead. |

### transcript.svelte.ts

This store manages the message history displayed in the conversation transcript. It holds the array of messages along with metadata needed for the typewriter reveal animation and auto-scroll behavior. The store also exports helper functions for manipulating the message list, which are called from multiple components (InputBar.svelte for user messages, Window.svelte for opening lines, and the streaming listeners for agent responses).

The Message interface defines the shape of each transcript entry. The `revealed` and `complete` fields work together to drive the character-by-character reveal animation in Transcript.svelte:

```typescript
interface Message {
  id: number;          // auto-incrementing from module-level counter
  role: 'user' | 'agent' | 'divider';
  content: string;     // raw text including prosody tags
  timestamp: number;   // Date.now() at creation
  revealed: number;    // chars revealed so far (for typewriter animation)
  complete: boolean;   // true when fully streamed
}
```

The reactive state object holds the message array and an auto-scroll flag that Transcript.svelte uses to decide whether to follow new messages:

```typescript
export const transcript = $state({
  messages: [] as Message[],
  autoScroll: true,
});
```

The store exports the following functions for manipulating messages. These are used by InputBar.svelte (to add user messages and empty agent placeholders), by the streaming listeners (to append text deltas and mark completion), and by Window.svelte (to add opening lines and dividers):

| Function | Signature | Behaviour |
|----------|-----------|-----------|
| `addMessage` | `(role, content) => Message` | Creates a new message with an auto-incrementing ID and the current timestamp. User messages and dividers are immediately complete with full reveal (`revealed = content.length`, `complete = true`). Agent messages start with `revealed: 0` and `complete: false` to enable the typewriter animation. |
| `appendToLast` | `(text) => void` | Appends text to the last message's `content` field, but only if the last message is an incomplete agent message. This is called on every `textDelta` event during streaming. |
| `completeLast` | `() => void` | Marks the last message as complete and sets `revealed` to the full content length, instantly revealing any remaining text. Called when the `done` or `error` event fires. |
| `addDivider` | `(text) => void` | Shorthand for `addMessage('divider', text)`. Dividers appear as centered green labels between conversation segments. |
| `clearTranscript` | `() => void` | Empties the messages array entirely. Used when switching agents or resetting the session. |

### agents.svelte.ts

This store tracks the list of available agents and which one is currently active. It is populated during App.svelte's initialization and updated when the user cycles agents via keyboard shortcuts or the AgentName chevrons. The `switchDirection` field is particularly important because it tells AgentName.svelte which direction to animate the rolodex transition - up for previous agent, down for next.

The following reactive state object holds all agent-related fields:

```typescript
export const agents = $state({
  list: [] as string[],    // agent directory names
  current: '',             // currently active agent name
  displayName: '',         // human-readable display name
  switchDirection: 0,      // -1 up, +1 down, 0 none (drives rolodex animation)
});
```

The `list` array contains directory names from `~/.atrophy/agents/` (e.g. `['xan', 'kai', 'nova']`). The `current` field matches one of these directory names. The `displayName` is the human-readable name from the agent's `agent.json` (e.g. `'Xan'`). When `list.length < 2`, the cycling chevrons are hidden since there is nothing to switch to.

### audio.svelte.ts

This store manages the TTS playback state. The main process synthesizes speech and plays it via `afplay`, sending events to the renderer to keep the UI synchronized. The store's primary consumer is Window.svelte, which reads `vignetteOpacity` to drive the warm radial gradient overlay that appears during speech playback, creating a subtle visual warmth effect.

The following reactive state object holds all audio playback fields:

```typescript
export const audio = $state({
  queue: [] as string[],   // file paths of pending audio
  isPlaying: false,        // true while any TTS audio is playing
  vignetteOpacity: 0,      // 0.0-0.15, drives the warm vignette overlay
});
```

The `queue` field tracks pending audio file paths for debugging and UI purposes. The `isPlaying` flag is set to `true` when the `tts:started` event fires and `false` when `tts:queueEmpty` fires. The `vignetteOpacity` is set to `0.15` when TTS starts and `0` when the queue empties, producing a gentle fade-in/fade-out on the warm vignette overlay in Window.svelte.

### settings.svelte.ts

This store mirrors a subset of the main process configuration into the renderer. It contains only the fields that renderer components need for display and behavior decisions - the full configuration object stays in the main process. The `loaded` flag is particularly important because it signals that the initial config fetch has completed, allowing components to distinguish between "not yet loaded" and "loaded with default values."

The following reactive state object holds the mirrored config fields:

```typescript
export const settings = $state({
  userName: 'User',
  version: '0.0.0',
  avatarEnabled: false,
  ttsBackend: 'elevenlabs',
  inputMode: 'dual',       // 'text' | 'voice' | 'dual'
  loaded: false,           // true after initial config fetch
});
```

The `userName` is displayed in the settings panel and used for personalization. The `version` appears in the About section of settings. The `avatarEnabled` flag controls whether OrbAvatar attempts to load video clips. The `ttsBackend` indicates which TTS engine is configured (elevenlabs, fal, or say). The `inputMode` determines which input methods are available - text-only, voice-only, or both.

### emotional-state.svelte.ts

This store mirrors the agent's inner emotional state from the main process. The emotional state system gives each agent a set of continuously-varying emotional dimensions (connection, curiosity, confidence, warmth, frustration, playfulness) along with trust dimensions (emotional, intellectual, creative, practical). These values are updated by the main process when the `update_emotional_state` MCP tool is called during inference, then pushed to the renderer via IPC.

The store exports two interfaces and two reactive state objects. The emotional state values range from 0.0 to 1.0, with defaults that represent a neutral starting point:

```typescript
export const emotionalState = $state<EmotionalState>({
  connection: 0.5,
  curiosity: 0.6,
  confidence: 0.5,
  warmth: 0.5,
  frustration: 0.1,
  playfulness: 0.3,
});

export const trustState = $state<TrustState>({
  emotional: 0.5,
  intellectual: 0.5,
  creative: 0.5,
  practical: 0.5,
});
```

These values are consumed by `OrbAvatar.svelte` to compute the procedural orb's hue, saturation, and lightness. Higher warmth shifts the hue toward red/orange, higher connection increases saturation, and frustration above 0.3 introduces a red shift. The trust dimensions are not currently used for visual rendering but are available for future use.

### emotion-colours.svelte.ts

This store provides the emotion-to-colour mapping system that drives the orb avatar's reactive colour changes. It was ported from `source_repo/display/emotion_colour.py` and serves as the bridge between the agent's textual responses and the visual feedback loop of the orb. When the agent says something positive, the orb shifts to green; when it expresses caution, the orb shifts to orange. This creates a subtle but continuous visual indicator of the agent's emotional tone.

The system defines six emotion types, each with an associated HSL colour, an avatar video clip name, and a set of trigger keywords. The following table shows the colour palette used by all emotions:

| Name | H | S | L |
|------|---|---|---|
| `blue` (default) | 220 | 50 | 20 |
| `dark_blue` | 230 | 40 | 15 |
| `red` | 0 | 60 | 25 |
| `green` | 140 | 45 | 22 |
| `orange` | 30 | 55 | 25 |
| `purple` | 270 | 45 | 22 |

Each emotion type maps to a colour, a video clip, and a keyword list. The following table shows these mappings along with the full keyword sets used for text classification:

| Emotion | Colour | Clip Name | Keywords |
|---------|--------|-----------|----------|
| `thinking` | dark_blue | `idle_hover` | (none - triggered programmatically during inference) |
| `alert` | red | `pulse_intense` | warning, danger, urgent, critical, alert, immediately, stop, protect, threat, security, compromised, breach, emergency, do not, must not, cannot allow |
| `frustrated` | red | `itch` | error, failed, broken, crash, bug, wrong, problem, issue, unfortunately, unable, can't, won't work, frustrat, damn, annoying |
| `positive` | green | `drift_close` | done, complete, success, great, excellent, good, ready, confirmed, yes, perfect, resolved, fixed, healthy, growing, progress, well done, nice, happy, glad, proud, love |
| `cautious` | orange | `drift_lateral` | note, caution, cost, price, pay, spend, budget, careful, watch out, heads up, fyi, worth noting, trade-off, consider, maybe, possibly, suggest, however, but, although, risk |
| `reflective` | purple | `crystal_shimmer` | interesting, philosophical, wonder, meaning, think about, reflects, deeper, perspective, soul, evolve, growth, remember when, looking back, pattern, insight, curious, fascinating, profound, existential, beautiful, strange |

**Classifier algorithm (`classifyEmotion`):** The classifier uses a score-based keyword matching approach. For each emotion type, it scans the lowercased text for all keywords. Each keyword hit scores `count * (1 + keyword.length / 10)`, weighting longer (more specific) phrases higher - this means "cannot allow" scores more per hit than "stop". The emotion with the highest score wins, but only if the score exceeds the minimum threshold of 2.0 to filter out weak matches from incidental keyword appearances.

The store exports a reactive state object that holds the currently active emotion and its colour. Components read this to determine the current visual state:

```typescript
export const activeEmotion = $state<{ type: EmotionType | null; colour: HSLColour }>({
  type: null,
  colour: DEFAULT_COLOUR,  // blue { h: 220, s: 50, l: 20 }
});
```

The following functions are exported for setting and clearing the active emotion. They are called by the streaming listener in InputBar.svelte (via `setEmotionFromText` when agent text arrives) and by Window.svelte (via `setEmotion('thinking')` when inference starts):

| Function | Purpose |
|----------|---------|
| `classifyEmotion(text)` | Returns the best-matching `EmotionType` or null if no strong signal is found |
| `getReaction(emotion)` | Returns `{ colour, clip }` for an emotion type, or null if unknown |
| `setEmotionFromText(text)` | Classifies text and sets the active emotion if a match is found, starting the revert timer |
| `setEmotion(emotion)` | Sets a specific emotion directly (e.g. `'thinking'` during inference), starting the revert timer |
| `revertToDefault()` | Immediately reverts to the default blue colour and clears any pending revert timer |
| `getClipPath(colour, clip, agentName)` | Builds the file path to an avatar video loop: `~/.atrophy/agents/{name}/avatar/loops/{colour}/loop_{clip}.mp4` |
| `getDefaultLoop(agentName)` | Returns the path to the default ambient loop (`blue/loop_bounce_playful.mp4`) |

**Revert timer:** After any emotion is set via `setEmotion()` or `setEmotionFromText()`, a `setTimeout` of 12,000ms (`REVERT_TIMEOUT_MS`) automatically reverts to the default blue colour. If a new emotion is set before the timer fires, the old timer is cleared and a new one starts. This ensures the orb always returns to its resting state after the emotional moment passes.

---

## Component Reference

### Window.svelte - Main Orchestrator

**File:** `src/renderer/components/Window.svelte`

Window.svelte is the root layout component and the orchestration hub for the entire display system. It manages the boot sequence that transitions the app from a black screen to the ready state, coordinates which overlays are visible (and in what priority order they dismiss), handles agent switching with clip-path animations, manages agent deferral handoffs with iris wipe transitions, tracks user idle time for the silence prompt, provides wake word and voice call audio capture, and routes keyboard shortcuts to their handlers. Nearly every user-facing feature flows through this component.

**Imports:** Window.svelte imports all child components (`OrbAvatar`, `AgentName`, `ThinkingIndicator`, `Transcript`, `InputBar`, `Timer`, `Canvas`, `Artefact`, `Settings`, `SetupWizard`) and the stores it needs for coordination (`session`, `audio`, `agents`, the transcript functions `addMessage` and `completeLast`, and `getArtifact` from the inline artifacts store).

#### Props

None. This is the top-level layout component and receives no props. It reads all state from imported stores and the preload API.

#### Reactive State ($state)

Window.svelte declares a large number of reactive state variables because it orchestrates many independent features. The following table lists every `$state` variable, organized by feature area:

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `showSettings` | `boolean` | `false` | Settings overlay visibility |
| `showTimer` | `boolean` | `false` | Timer overlay visibility |
| `showCanvas` | `boolean` | `false` | Canvas overlay visibility |
| `showArtefact` | `boolean` | `false` | Artefact overlay visibility |
| `needsSetup` | `boolean` | `false` | Whether first-launch wizard should show |
| `bootPhase` | `'boot' \| 'ready'` | `'boot'` | Boot sequence state |
| `bootOpacity` | `number` | `1.0` | Boot overlay opacity (animates to 0) |
| `bootLabel` | `string` | `'connecting...'` | Text shown during boot |
| `avatarVisible` | `boolean` | `true` | Whether OrbAvatar is rendered |
| `isMuted` | `boolean` | `false` | TTS mute state |
| `wakeListening` | `boolean` | `false` | Wake word detection active |
| `callActive` | `boolean` | `false` | Voice call mode active |
| `hasNewArtefacts` | `boolean` | `false` | Badge indicator for artefact button |
| `eyeMode` | `boolean` | `false` | Hides transcript when true |
| `agentSwitchActive` | `boolean` | `false` | Agent switch animation in progress |
| `agentSwitchClip` | `string` | `'circle(0% at 50% 50%)'` | CSS clip-path for agent switch |
| `deferralActive` | `boolean` | `false` | Agent deferral in progress |
| `deferralTarget` | `string` | `''` | Name of the target agent during deferral |
| `deferralProgress` | `number` | `0` | 0=start, 1=closing, 2=opening |
| `lastInputTime` | `number` | `Date.now()` | Timestamp of last user activity |
| `silencePromptVisible` | `boolean` | `false` | "Still here?" prompt visibility |
| `silenceTimerEnabled` | `boolean` | `true` | Whether the silence timer is active (config-driven default) |
| `silenceTimeoutMs` | `number` | `300000` | Silence timeout duration in ms (config-driven, default 5 minutes) |

#### Boot Sequence

The boot sequence runs once in `onMount` and transitions the app from a black screen to the ready state. It is guarded by a `bootRan` flag to prevent duplicate execution (important because Svelte's strict mode can double-invoke effects in development). The sequence proceeds through these steps:

1. Load config and agent list from the main process via IPC (`getConfig()`, `getAgents()`) in a parallel `Promise.all` call, populating the `agents` store with the results.
2. Apply config-driven defaults from the loaded config: if `eyeModeDefault` is true, enable eye mode; if `muteByDefault` is true, mute TTS; if `silenceTimerEnabled` is false, disable the silence timer; if `silenceTimerMinutes` is set, use it as the silence timeout duration.
3. Check `needsSetup()` - if true, fade out the boot overlay and show the SetupWizard instead of continuing to the normal ready state.
4. If no setup is needed, fetch the opening line via `getOpeningLine()` IPC and add it to the transcript as a completed agent message.
5. Clear the boot label, set `bootOpacity = 0` to trigger the CSS fade-out transition, then wait 1.5 seconds for the animation to complete before setting `bootPhase = 'ready'` to remove the overlay from the DOM.

The boot overlay is a `position: fixed` black div at `z-index: 9999` that transitions from opacity 1 to 0 over 1.5 seconds via CSS. During loading, it displays a subtle "connecting..." label (13px font, 2px letter-spacing, lowercase, `var(--text-dim)` colour) centered in the window.

#### Opening Line

The opening line displayed on launch comes from the `OPENING_LINE` field in the agent's `agent.json`. The main process handler (`opening:get`) returns this value directly, falling back to `"Ready. Where are we?"` if unset. Unlike the Python version (which generates dynamic openings via inference with randomized style directives like question, observation, tease, or admission), the Electron version currently reads a static opening line from config. Dynamic opening generation is not yet ported.

The opening line is configurable in Settings > Agent Identity, where users can set a custom opening for each agent.

#### Overlay Layer Stack (z-index)

The display system uses a carefully ordered z-index stack to ensure overlays render in the correct priority. Higher z-index values render on top, and the Escape key dismisses overlays from highest to lowest. The following table lists every z-index layer in the system:

| z-index | Layer | CSS Class |
|---------|-------|-----------|
| 9999 | Boot overlay | `.boot-overlay` |
| 80 | Agent deferral iris wipe | `.deferral-overlay` |
| 75 | Agent switch clip-path animation | `.agent-switch-overlay` |
| 70 | SetupWizard | `.wizard-overlay` |
| 50 | Timer | `.timer-overlay` |
| 45 | Canvas | `.canvas-overlay` |
| 40 | Artefact | `.artefact-overlay` |
| 15 | Mode buttons | `.mode-buttons` |
| 12 | Silence prompt | `.silence-prompt` |
| 10 | Top bar, Input bar | `.top-bar`, `.bar-container` |
| 5 | Transcript | `.transcript` |
| 1 | Vignette overlay | `.vignette` |
| 0 | OrbAvatar | `.avatar-video`, `.orb-canvas` |

Overlays are conditionally rendered via `{#if}` blocks so they are removed from the DOM entirely when not visible. Escape dismisses them in priority order: settings, then artefact, then canvas, then timer, then silence prompt. This ordering ensures that a settings panel open over a canvas does not accidentally close the canvas when pressing Escape.

#### Agent Switch Animation

When the user switches agents (via Cmd+Up/Down keyboard shortcuts or the AgentName chevrons), a clip-path circle transition expands from centre to reveal the new agent's state. The animation provides a brief visual break between agents, making the switch feel intentional rather than jarring.

The animation works by creating a solid-colour overlay and expanding its clip-path from nothing to full coverage. The following code shows the key state changes that drive the CSS transition:

```typescript
agentSwitchClip = 'circle(0% at 50% 50%)';
requestAnimationFrame(() => {
  agentSwitchClip = 'circle(150% at 50% 50%)';
});
```

The overlay uses a 0.65s `cubic-bezier(0.4, 0, 0.2, 1)` CSS transition on `clip-path`, with `var(--bg)` as the background colour. The `requestAnimationFrame` call is needed to force a reflow between the starting and ending clip-path values so the browser registers the change as an animation rather than a single state. The overlay cleans up after 700ms via `setTimeout`, giving the transition a small buffer to complete.

The `cycleAgent(direction)` function calculates the next agent index with wrapping: `(idx + direction + list.length) % list.length`. It calls `api.switchAgent(next)` to perform the actual switch in the main process, then updates `agents.current`, `agents.displayName`, and sets `agents.switchDirection` to drive the rolodex animation in AgentName.svelte.

#### Agent Deferral (Codec-Style Handoff)

When one agent defers to another (triggered by the `defer_to_agent` MCP tool in the main process, which sends a `deferral:request` IPC event), an iris wipe animation plays. The animation was inspired by codec-style transitions in video games - a circular mask that closes to black, switches context, then reopens. This creates a dramatic visual handoff that makes agent switches feel like a deliberate passing of the baton.

The deferral sequence proceeds through these timed steps:

1. Stop ongoing inference via `api.stopInference()` and clear the audio queue via `api.clearAudioQueue()` to prevent the outgoing agent's voice from continuing.
2. Set `deferralProgress = 0`, then `requestAnimationFrame` to set it to `1`, initiating the iris close animation.
3. Iris close - the clip-path circle shrinks from 150% to 0% over 0.25s with a cubic-bezier transition, collapsing the view to a black point.
4. At 250ms (when the iris is fully closed), call `api.completeDeferral(data)` to switch agents in the main process. This call returns the new agent's name and display name.
5. Update renderer agent state (`agents.current`, `agents.displayName`) with the new agent's information.
6. Set `deferralProgress = 2` to trigger the iris open animation - the circle expands back from 0% to 150%.
7. Clean up after 300ms by setting `deferralActive = false` and `deferralProgress = 0`.

The "Handing off to {target}..." label (14px, 0.7 opacity, `var(--text-secondary)`) appears during the black frame when `deferralProgress === 1`, giving the user a brief indication of who they are being handed off to.

#### Silence Timer

A configurable idle timer that shows a subtle "Still here?" prompt above the input bar. The duration defaults to 5 minutes and can be changed via Settings > Window > Silence Timer Minutes (`SILENCE_TIMER_MINUTES`). The timer can also be disabled entirely via Settings > Window > Silence Timer (`SILENCE_TIMER_ENABLED`). This feature prevents the agent from sitting in an awkward state where neither party is speaking - the prompt gently reminds the user that the agent is waiting. The timer resets on any keypress or mouse movement (via `svelte:window` event bindings for `onkeydown` and `onmousemove`), so normal interaction prevents the prompt from appearing.

On boot, Window.svelte reads `silenceTimerEnabled` and `silenceTimerMinutes` from the config and applies them. If disabled, the timer never fires. The `resetSilenceTimer()` function checks the enabled flag before scheduling the next prompt.

Clicking the prompt dismisses it and resets the timer for another cycle. The prompt fades in with a `silenceFadeIn` CSS animation (1.5s ease, translates 6px up from an offset starting position) to avoid a jarring appearance.

#### Warm Vignette

A radial gradient overlay (`.vignette`) covers the full window to create a warm, lamp-like glow effect during TTS audio playback. The vignette simulates the visual warmth of someone speaking to you in a dimly lit room, reinforcing the intimate feel of the voice interaction.

The vignette uses the following CSS gradient, which is transparent in the centre and adds a warm amber tint at the edges:

```css
background: radial-gradient(
  ellipse at center,
  transparent 30%,
  rgba(40, 25, 10, 0.47) 100%
);
```

The overlay fades in and out during TTS audio playback via `transition: opacity 0.8s ease`. Its opacity is driven by `audio.vignetteOpacity`, which is set to 0.15 when TTS starts playing and 0 when the audio queue empties. The 0.8-second transition creates a gentle fade rather than a sudden appearance.

#### Wake Word Audio Capture

When `wakeListening` is toggled on (via the microphone mode button or Cmd+Shift+W), the component opens a continuous audio stream for wake word detection. The wake word system listens for a configurable trigger phrase and, when detected, starts a full recording session. The audio pipeline for wake word runs independently of push-to-talk and call mode, using its own set of audio resources.

The audio capture pipeline is set up as follows:

1. Calls `navigator.mediaDevices.getUserMedia()` with `sampleRate: 16000`, `channelCount: 1`, `echoCancellation: true` to get a mono 16kHz audio stream suitable for speech recognition.
2. Creates an `AudioContext` at 16kHz to match the stream's sample rate.
3. Creates a `ScriptProcessorNode` with a 4096-sample buffer (approximately 256ms of audio per chunk at 16kHz).
4. On each audio process event, sends the chunk to the main process via `api.sendWakeWordChunk(data.buffer.slice(0))`. The `slice(0)` creates a copy of the ArrayBuffer so it can be transferred without the original being neutered.

Teardown on toggle off disconnects the processor, closes the AudioContext, and stops all MediaStream tracks. Each resource (stream, context, processor) is tracked in separate variables (`wakeStream`, `wakeAudioCtx`, `wakeProcessor`) so they can be cleaned up independently.

#### Voice Call Mode

Voice call mode provides a continuous record/transcribe/send/TTS loop with voice activity detection (VAD). Unlike push-to-talk (which requires holding a key), call mode operates hands-free - it listens for speech, waits for silence, transcribes the utterance, sends it to the agent, and then resumes listening. This creates a natural phone-call-like interaction flow.

The voice activity detection uses the following constants to tune sensitivity and silence detection:

- `CALL_ENERGY_THRESHOLD = 0.015` - RMS energy threshold for speech detection. Audio frames with energy above this level are considered speech.
- `CALL_SILENCE_FRAMES = 15` - approximately 3.8 seconds of silence before an utterance is considered complete (`15 * 4096/16000`). This long silence window prevents mid-sentence pauses from triggering premature transcription.
- `CALL_MIN_CHUNKS = 4` - minimum audio chunks before processing. This prevents very short noise bursts from triggering false transcriptions.

The VAD algorithm processes each 4096-sample buffer through these steps:

1. Opens the microphone at 16kHz mono with all Chromium audio processing disabled (`echoCancellation: false`, `noiseSuppression: false`, `autoGainControl: false`) to avoid Chromium switching macOS to "voice processing" audio mode, which downsamples all system audio to 16kHz.
2. The ScriptProcessor calculates RMS energy for each buffer: `sqrt(sum(sample^2) / length)`.
3. If energy exceeds the threshold, marks speech as started, resets the silence counter, and accumulates the chunk.
4. If energy is below the threshold and speech has started, increments the silence counter while continuing to accumulate chunks (capturing trailing silence).
5. When silence exceeds `CALL_SILENCE_FRAMES` and enough chunks have accumulated, concatenates all chunks into a single Float32Array and sends it for STT transcription.
6. On successful transcription, adds the text as a user message and sends it via `api.sendMessage()`, then resets the accumulators and resumes listening.

#### Mode Buttons

A row of icon buttons in the top-right corner (`position: absolute; top: 14px; right: var(--pad)`), ordered left-to-right. These buttons provide quick access to all the major mode toggles and overlays without cluttering the main interface. Each button uses an inline SVG icon that changes appearance based on the active state.

The following table lists each button, its icon, active state styling, and behavior:

| Button | Icon | State class | Behaviour |
|--------|------|-------------|-----------|
| Eye | Eye shape (slash when hidden) | `.active` when hidden | Toggles `avatarVisible` - removes/adds OrbAvatar from the DOM |
| Mute | Speaker with waves (X when muted) | `.active` when muted | Toggles `isMuted` - controls TTS playback (not yet wired to main process) |
| Wake | Microphone | `.wake-active` | Toggles wake word listener. Green colour (`rgba(120, 255, 140, 0.9)`) with green background (`rgba(30, 80, 40, 0.82)`) to clearly indicate always-listening state |
| Call | Phone icon | `.active` | Toggles voice call mode (continuous VAD loop) |
| Artefact | Document icon | - | Opens artefact overlay. Blue badge dot (6px, `rgba(100, 180, 255, 0.88)`) when `hasNewArtefacts` is true |
| Timer | Clock icon | - | Opens timer overlay |
| Minimize | Horizontal line | - | Calls `api.minimizeWindow()` to native-minimize the window |
| Settings | Gear icon | `.active` | Opens settings overlay |

All buttons share the same base styling: `var(--button-size)` (34px) square with `border-radius: 8px`, transparent background, and `var(--text-dim)` colour. Hover state changes to `var(--text-secondary)` text with `rgba(255, 255, 255, 0.04)` background. Active state changes to `var(--text-primary)` text with `rgba(40, 40, 50, 0.82)` background. The buttons are spaced with a 2px gap in a flex row.

#### Keyboard Shortcuts

Window.svelte registers a global `keydown` handler via `<svelte:window onkeydown={onKeydown}>` that routes keyboard shortcuts to their handlers. All shortcuts also reset the silence timer as a side effect, since any keypress indicates the user is active.

The following table lists all keyboard shortcuts handled by Window.svelte:

| Shortcut | Action | Handler |
|----------|--------|---------|
| Cmd+, | Toggle settings panel | `showSettings = !showSettings` |
| Cmd+Shift+W | Toggle wake word detection | `toggleWake()` |
| Cmd+K | Toggle canvas overlay | `showCanvas = !showCanvas` |
| Cmd+E | Toggle eye mode (hide transcript) | `eyeMode = !eyeMode` |
| Cmd+Up | Cycle to previous agent | `cycleAgent(-1)` |
| Cmd+Down | Cycle to next agent | `cycleAgent(1)` |
| Ctrl (hold) | Push-to-talk recording | Handled in InputBar.svelte |
| Escape | Close overlays in priority order | Closes first open: settings, artefact, canvas, timer, silence prompt |

#### IPC Channels Used

Window.svelte communicates with the main process through a variety of IPC channels for boot, agent management, and overlay coordination. The following table documents every channel used, its direction (invoke for request/response, listener for push events), and its purpose:

| Channel | Direction | Usage |
|---------|-----------|-------|
| `api.getConfig()` | invoke | Load initial config during boot |
| `api.getAgents()` | invoke | Load agent list during boot |
| `api.needsSetup()` | invoke | Check if first-launch wizard needed |
| `api.getOpeningLine()` | invoke | Fetch opening line for transcript |
| `api.switchAgent(name)` | invoke | Switch to a different agent |
| `api.stopInference()` | invoke | Stop ongoing inference during deferral |
| `api.clearAudioQueue()` | invoke | Clear TTS queue during deferral |
| `api.completeDeferral(data)` | invoke | Complete agent handoff |
| `api.minimizeWindow()` | invoke | Minimize window |
| `api.sendWakeWordChunk(buffer)` | invoke | Send wake word audio data |
| `api.sendAudioChunk(buffer)` | invoke | Send call mode audio data |
| `api.stopRecording()` | invoke | Get transcription from accumulated audio |
| `api.sendMessage(text)` | invoke | Send user message for inference |
| `api.on('deferral:request', cb)` | listener | Receive deferral request from main |
| `api.on('canvas:updated', cb)` | listener | Auto-show canvas when content updated |

#### Lifecycle

Window.svelte's lifecycle hooks manage startup, ongoing timers, and cleanup of audio resources. The component uses both `onMount` and `onDestroy` to ensure proper resource management.

- **onMount:** Runs the boot sequence (config load, setup check, opening line, fade-out), starts the silence timer, and registers IPC listeners for deferral requests and canvas updates. The deferral listener calls `handleDeferralRequest()` when the main process signals an agent handoff, and the canvas listener auto-shows the canvas overlay when the agent writes new content via the `render_canvas` MCP tool.
- **onDestroy:** Clears the silence timer, cleans up the agent switch callback, and disconnects/closes all audio resources for both wake word and call mode. Each audio subsystem (wake word, call mode) has its own stream, AudioContext, and processor that are cleaned up independently to avoid resource leaks.

#### Layout CSS

The window's layout uses a simple flexbox column that fills the full viewport. The following CSS establishes the foundation that all child components build upon:

```css
.window {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--bg);
  display: flex;
  flex-direction: column;
}
```

The `.top-bar` uses `padding-top: 36px` to account for the macOS title bar inset area. Even though the traffic lights are visually hidden (positioned at x:-100, y:-100 via the BrowserWindow options), the inset area is still present and serves as the window drag region. The 36px top padding ensures the agent name and mode buttons do not overlap with this invisible drag zone.

---

### Transcript.svelte - Message Display

**File:** `src/renderer/components/Transcript.svelte`

Transcript.svelte renders the conversation history with character-by-character reveal animation for agent messages and a custom markdown renderer for rich text formatting. It is the primary visual element of the chat interface - everything the user reads flows through this component. The transcript occupies the flex body of the window layout, growing to fill available space between the top bar and input bar.

#### Props

None. Reads directly from the `transcript` store, which provides the message array and auto-scroll flag. This keeps the component decoupled from the input mechanism - messages can come from text input, voice transcription, or the opening line, and the transcript renders them identically.

#### Reactive State ($state)

The component maintains minimal local state for copy-button feedback and timestamp display:

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `copiedBlockId` | `string \| null` | `null` | ID of the code block whose "Copy" button was just clicked, used to show "Copied" feedback |
| `now` | `number` | `Date.now()` | Current timestamp, updated every 30 seconds to keep relative timestamps current |

#### Other Instance Variables

Beyond reactive state, the component tracks DOM references, animation timers, and counters as plain instance variables:

| Variable | Type | Purpose |
|----------|------|---------|
| `container` | `HTMLDivElement` | Bound reference to the scroll container, used for programmatic scroll-to-bottom |
| `revealTimers` | `Map<number, interval>` | Active character reveal timers keyed by message ID, cleaned up on completion or unmount |
| `codeBlockCounter` | `number` | Auto-incrementing ID for rendered code blocks, used to match copy buttons to their content |
| `timestampTimer` | `interval` | 30-second interval that updates `now` for relative timestamp recalculation |

#### Reveal Animation

Agent messages animate in character by character to create a typewriter effect that visually mirrors the streaming nature of the response. This animation runs independently of the actual streaming - text is appended to the message content as it arrives from the inference engine, and the reveal animation catches up at its own pace.

The animation uses the following constants to control speed:

```typescript
const REVEAL_RATE = 8;     // characters per tick
const REVEAL_INTERVAL = 25; // milliseconds between ticks
```

A `setInterval` timer increments `msg.revealed` by `REVEAL_RATE` on each tick until it reaches `msg.content.length`. This produces an effective reveal speed of approximately 320 characters per second, fast enough to keep up with streaming but slow enough to be visible. When the reveal reaches the end of the content, the interval is cleared and removed from the `revealTimers` map. User messages and dividers bypass the animation entirely - they are immediately fully revealed at creation time in the transcript store.

#### Display Filtering (`displayText`)

Before rendering, message text is cleaned by slicing to the `revealed` count (for the typewriter effect), then processing through several filters to strip internal markup. These filters ensure that prosody tags used by the TTS engine and audio elements embedded by the system do not appear as visible text in the transcript:

- Prosody tags (`[word_tag]`) are stripped via regex `/\[[\w_]+\]/g`. These tags are inserted by the agent to control TTS pronunciation and emphasis.
- Audio tags (`<audio>...</audio>`) are removed via `/\<audio[^>]*>.*?<\/audio>/gs`. These are used for inline audio playback in the Python version but are not rendered in the Electron UI.
- Multiple consecutive spaces are collapsed to single spaces to clean up artifacts from tag removal.
- Leading/trailing whitespace is trimmed.

#### Markdown Renderer (`renderMarkdown`)

A custom markdown-to-HTML renderer processes agent messages for rich text display. The renderer was written from scratch rather than using a library like marked or remark because the use case is narrow (conversation text, not full documents) and the custom renderer can handle the prosody tag stripping and code block copy buttons in a single pass. The renderer handles the following markdown elements in processing order:

1. **Fenced code blocks** - extracted first with triple-backtick regex, replaced with null-byte placeholders to protect their contents from other processing. Rendered as `.code-block-wrapper` divs with a language label and copy button.
2. **HTML escaping** - all remaining text is escaped (`&`, `<`, `>`, `"`) to prevent XSS from agent output.
3. **Inline code** - backtick-wrapped text rendered as `<code class="inline-code">`.
4. **Bold** - `**text**` rendered as `<strong>`.
5. **Italic** - `*text*` rendered as `<em>`.
6. **Links** - `[text](url)` rendered as `<a class="md-link" target="_blank">`.
7. **Bare URLs** - `https://...` auto-linked (except when already inside an href attribute).
8. **Headers** - `#` through `######` rendered as `<h1>` through `<h6>` with classes `md-header md-hN`.
9. **Blockquotes** - `>` lines rendered as `<blockquote class="md-blockquote">`.
10. **Unordered lists** - `-` or `*` items wrapped in `<ul class="md-list">`.
11. **Ordered lists** - `1.` items wrapped in `<ul class="md-list md-ol">` (uses `list-style-type: decimal`).
12. **Inline artifact placeholders** - `[[artifact:id]]` markers (inserted by the artifact parser when the agent emits `<artifact>` blocks) are replaced with clickable card buttons. Each card shows the artifact type badge (e.g. HTML, SVG, CODE), the title, and the language. Clicking a card dispatches to the parent via the `onArtifactClick` prop, which opens the artifact content in the Artefact overlay.

User messages only receive HTML escaping and bare URL linkification (no full markdown), since users rarely write markdown in a chat interface and full processing could produce unexpected formatting.

#### Code Block Copy

Each code block renders a "Copy" button in its header bar with a `data-copy-target` attribute matching the block ID. When clicked, the button calls `navigator.clipboard.writeText()` with the raw code content and temporarily changes the button text to "Copied" for 1.5 seconds. The copy button text update is driven by a `$effect` that scans all `.copy-btn` elements in the container, comparing their `data-copy-target` against `copiedBlockId` to determine which button should show "Copied" versus "Copy".

#### Inline Artifact Cards

When the agent emits `<artifact>` blocks in its response, the main process extracts them (via `artifact-parser.ts`) and replaces them with `[[artifact:id]]` placeholders in the text sent to the renderer. The `renderMarkdown()` function detects these placeholders and renders them as clickable `.artifact-card` buttons.

Each card displays:
- **Type badge** (`.artifact-card-type`) - 9px bold uppercase label (e.g. HTML, SVG, CODE) with `#4a9eff` blue on `rgba(74, 158, 255, 0.15)` background.
- **Title** (`.artifact-card-title`) - 13px, from the artifact's `title` attribute.
- **Language** (`.artifact-card-lang`) - 10px dim text, from the artifact's `language` attribute.

The card has a blue-tinted background (`rgba(74, 158, 255, 0.08)`) with a matching border that brightens on hover. Clicking a card calls `onArtifactClick(id)`, which Window.svelte handles by looking up the artifact content from the `artifacts` store and dispatching an `inline-artifact` CustomEvent to the Artefact overlay.

**Props:**

| Prop | Type | Description |
|------|------|-------------|
| `onArtifactClick` | `(id: string) => void` | Optional callback when an artifact card is clicked |

#### Auto-Scroll

The transcript automatically scrolls to the bottom after each Svelte `tick()` when `transcript.autoScroll` is true. This keeps the latest message visible during streaming. Auto-scroll is disabled when the user scrolls up (detected by an `onScroll` handler checking if the scroll position is more than 40px from the bottom), allowing the user to read earlier messages without being yanked back to the bottom. Auto-scroll re-enables when the user scrolls back to the bottom, creating an intuitive "follow new messages" behavior.

#### Relative Timestamps

Each message displays a relative timestamp that updates as time passes. The format adapts to the age of the message: `just now` for messages under 10 seconds old, `Xs ago` for messages under a minute, `Xm ago` for messages under an hour, `Xh ago` for messages under 24 hours, and a short time format (e.g. `14:30`) for older messages. Timestamps are hidden by default (`opacity: 0`) and shown on message hover (`opacity: 1`) with a 0.2s transition. The `now` variable updates every 30 seconds to keep timestamps current without excessive re-rendering.

#### Message Styling

Each message role has distinct visual treatment to make it easy to distinguish the user's words from the agent's responses and system dividers. The following table shows the colour and spacing for each role:

| Role | Text Colour | Spacing |
|------|-------------|---------|
| `user` | `var(--text-user)` - `rgba(180, 180, 180, 0.86)` | 24px margin above when following agent |
| `agent` | `var(--text-companion)` - `rgba(255, 255, 255, 0.86)` | 24px margin above when following user |
| `divider` | `var(--divider-green)` - `rgba(120, 200, 120, 0.6)` | Centered, 11px bold uppercase, 3px letter-spacing, green top/bottom borders |

All message text uses 14px `var(--font-sans)`, line-height 1.65, `pre-wrap` whitespace, `break-word` word-break, and a subtle text-shadow (`1px 1px 2px rgba(0, 0, 0, 0.5)`) that improves readability against the dark background and any video/orb content showing through.

#### Code Block Styling

Code blocks use a distinct visual treatment with a dark background, language label, and copy button. The styling is designed to be readable against the dark theme while clearly delineating code from prose:

- **Wrapper:** `border-radius: 6px`, `border: 1px solid var(--border)`, `background: rgba(0, 0, 0, 0.35)`
- **Header:** flex row with language label (10px uppercase mono) and copy button, `background: rgba(255, 255, 255, 0.04)`, bottom border
- **Code body:** `font-family: var(--font-mono)`, 12.5px, line-height 1.5, `padding: 10px 12px`, horizontal scroll for wide content
- **Inline code:** 12.5px mono, `background: var(--bg-secondary)`, 3px border-radius, 1px border

#### Markdown Element Styling

The markdown elements are styled to be visually distinct while maintaining the dark theme aesthetic. Each element type has specific sizing and spacing designed for conversation-length content rather than full documents:

- **Headers:** h1: 18px, h2: 16px, h3: 15px, h4-h6: 14px. Margin `12px 0 4px`, `var(--text-primary)` colour.
- **Blockquotes:** 3px left border `var(--border)`, 12px left padding, italic, `var(--text-secondary)` colour. Used for quotations and asides in agent responses.
- **Lists:** 20px left padding, 4px top/bottom margin, 2px item spacing. Compact spacing for chat context.
- **Links:** `var(--accent-hover)` colour, transparent bottom border that shows on hover. Open in new tab via `target="_blank"`.
- **Bold:** font-weight 600, `var(--text-primary)` colour. Slightly brighter than surrounding text for emphasis.

#### Layout

The transcript fills the available vertical space between the top bar and input bar using flexbox. It constrains its width for readability and centres itself within the window.

The following CSS shows the transcript's positioning within the window layout:

```css
.transcript {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px var(--pad);    /* 8px top, 24px sides */
  z-index: 5;
  max-width: 700px;
  margin: 0 auto;
  width: 100%;
}
```

The transcript has the `.selectable` class for text selection (overriding the global `user-select: none`) and `data-no-drag` to prevent window dragging from the transcript area.

#### Lifecycle

The transcript's lifecycle hooks manage the timestamp interval and reveal animation cleanup:

- **onMount:** Starts the 30-second timestamp update interval. Returns a cleanup function that clears all active reveal timers and the timestamp interval.
- **$effect (messages):** Watches `transcript.messages`. When the last message is an incomplete agent message, starts its reveal animation. Calls `scrollToBottom()` on every change to keep the view current.
- **$effect (copiedBlockId):** Updates all `.copy-btn` text content reactively based on which block was just copied, resetting the text back to "Copy" after the 1.5-second feedback window.

---

### InputBar.svelte - Text Input and Recording

**File:** `src/renderer/components/InputBar.svelte`

InputBar.svelte provides the floating input bar at the bottom of the window. It handles text input submission, push-to-talk voice recording, and - critically - wires up all the inference streaming listeners that drive the transcript and audio state during a conversation. Despite its name suggesting a simple input field, this component is the hub where outgoing messages are sent and incoming streaming events are processed.

#### Props

None. Reads from `session` and `transcript` stores and accesses the preload API via `window.atrophy`. This component is tightly coupled to the inference lifecycle since it manages both the sending and receiving sides of a conversation turn.

#### Reactive State ($state)

The component tracks the current input text and recording state:

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `inputText` | `string` | `''` | Current text input value, bound to the input element |
| `isRecording` | `boolean` | `false` | Push-to-talk recording active, drives visual recording state |

#### Derived State ($derived)

The component derives an activity flag from the session store to control input availability:

| Variable | Expression | Purpose |
|----------|------------|---------|
| `isActive` | `session.inferenceState !== 'idle'` | When true, disables the text input, hides the send arrow, and shows the stop button instead |

#### Other Instance Variables

The component maintains references to audio resources and DOM elements for cleanup and interaction:

| Variable | Type | Purpose |
|----------|------|---------|
| `inputEl` | `HTMLInputElement` | Bound reference to input element for programmatic focus |
| `mediaStream` | `MediaStream \| null` | Active mic stream during push-to-talk |
| `audioContext` | `AudioContext \| null` | Audio processing context for recording |
| `workletNode` | `AudioWorkletNode \| ScriptProcessorNode \| null` | Audio processor node for capturing samples |
| `lastSound` | `number` | Timestamp of last keystroke sound, used for throttling |

#### Keystroke Sound

The input bar plays a subtle keystroke sound on each character typed, providing tactile audio feedback. It plays the macOS Tink system sound (`/System/Library/Sounds/Tink.aiff`) at 0.02 volume (barely audible) on each character keypress. The sound is throttled to a 60ms minimum interval between plays to prevent rapid typing from producing an overwhelming cascade of clicks. Only single-character keys trigger the sound - modifier keys like Cmd and Ctrl are filtered out.

#### Submit Flow

When the user presses Enter or clicks the send button, the submit flow handles the full roundtrip of sending a message and preparing the UI for the streaming response. The steps proceed as follows:

1. Trim input text and return immediately if empty (prevents blank messages).
2. Clear the input field so the user can start typing their next message while the response streams.
3. Add the user message to the transcript via `addMessage('user', text)`.
4. Add an empty agent message via `addMessage('agent', '')` as a placeholder that will be filled by streaming text deltas.
5. Set `session.inferenceState = 'thinking'` to show the ThinkingIndicator and disable the input.
6. Call `api.sendMessage(text)` to send the message to the main process for inference.
7. On error: call `completeLast()` to close the placeholder message and reset `session.inferenceState` to `'idle'`.

#### Push-to-Talk Recording

Push-to-talk allows the user to record voice input by holding a key or button. The audio is captured in the renderer, sent to the main process chunk by chunk, and transcribed by the whisper.cpp STT engine.

**Audio capture setup (16kHz mono):** All three Chromium audio processing flags (`echoCancellation`, `noiseSuppression`, `autoGainControl`) are set to `false` to prevent Chromium from switching macOS to "voice processing" audio mode, which downsamples all system audio to 16kHz. The component uses a `ScriptProcessorNode` with a 4096-sample buffer (wider browser support than AudioWorklet) and sends chunks to the main process via `api.sendAudioChunk(buffer)` as `ArrayBuffer`.

**Ctrl key push-to-talk:** The component registers global `keydown` and `keyup` listeners for the `'Control'` key. Pressing Ctrl starts recording (only when the inference state is idle and not already recording). Releasing Ctrl stops recording, calls `api.stopRecording()` to get the transcription result, and auto-submits non-empty transcriptions through the same submit flow used for text input.

**Mic button hold-to-record:** The mic button in the input bar supports the same hold-to-record pattern via `mousedown` and `mouseup` events. Pressing the mic button starts recording, and releasing it stops recording and triggers transcription. The flow is identical to the Ctrl push-to-talk path.

#### Streaming Listener Setup ($effect)

The InputBar wires up all inference streaming listeners in a `$effect` block that runs once on mount and returns a cleanup function. This is where the real-time conversation data flows into the renderer - every text delta, completion signal, error, and TTS event passes through these listeners.

The following code shows the listener registrations that drive the transcript and audio state during inference:

```typescript
api.onTextDelta((text) => {
  session.inferenceState = 'streaming';
  appendToLast(text);
});
api.onDone((_fullText) => {
  completeLast();
  session.inferenceState = 'idle';
});
api.onError((_msg) => {
  completeLast();
  session.inferenceState = 'idle';
});
api.onCompacting(() => {
  session.inferenceState = 'compacting';
});
api.onTtsStarted(() => {
  audio.isPlaying = true;
  audio.vignetteOpacity = 0.15;
});
api.onTtsQueueEmpty(() => {
  audio.isPlaying = false;
  audio.vignetteOpacity = 0;
});
```

The `onTextDelta` listener transitions the inference state from `'thinking'` to `'streaming'` on the first chunk, then appends each text delta to the last message in the transcript. The `onDone` and `onError` listeners both mark the last message as complete and return to idle. The `onCompacting` listener sets the state to `'compacting'` to show the user that Claude is summarizing context. The TTS listeners control the warm vignette overlay by toggling `audio.isPlaying` and `audio.vignetteOpacity`.

Cleanup removes all IPC listeners and keyboard event listeners to prevent memory leaks when the component unmounts.

#### Layout and Styling

The input bar floats at the bottom of the window with a pill-shaped design that houses the text input, mic button, and send/stop action button. The following CSS shows the container and bar styling:

```css
.bar-container {
  position: relative;
  z-index: 10;
  padding: 12px var(--pad) var(--pad);  /* 12px top, 24px sides+bottom */
}

.input-bar {
  height: var(--bar-height);    /* 48px */
  background: var(--bg-input);  /* rgba(20, 20, 22, 0.82) */
  border: 1px solid var(--border);
  border-radius: var(--bar-radius);  /* 24px */
}
```

The individual elements within the bar are positioned as follows:

- **Input field:** flex: 1, 14px font, `padding: 0 20px` with 90px right padding to accommodate the buttons without overlapping text.
- **Mic button:** 36px circle, `position: absolute`, `right: calc(var(--pad) + 44px)`. During recording, it turns red (`rgba(255, 80, 80, 0.9)`) with a `pulse-mic` animation (1s ease-in-out infinite, opacity oscillating between 0.6 and 1.0).
- **Action button:** 36px circle, `position: absolute`, `right: calc(var(--pad) + 6px)`. In normal state it shows a send arrow with `rgba(255, 255, 255, 0.16)` background. During active inference it shows a stop icon with bright white background (`rgba(255, 255, 255, 0.78)`) and dark icon colour.
- **Recording state:** The entire input bar border turns red (`rgba(255, 80, 80, 0.5)`) and the placeholder text changes to "Listening..." to give clear visual feedback.
- **Focus state:** The border changes to `var(--border-hover)` (`rgba(255, 255, 255, 0.15)`) for a subtle brightness increase.

---

### OrbAvatar.svelte - Avatar Display

**File:** `src/renderer/components/OrbAvatar.svelte`

OrbAvatar.svelte renders the visual avatar that sits behind the conversation transcript. It supports two rendering modes: pre-recorded video clips (loaded from the agent's avatar directory) and a procedural canvas orb (rendered in real time with Canvas 2D). The video mode provides rich, pre-made visual loops tied to specific emotions, while the canvas fallback generates a simpler but always-available animated orb. The component automatically falls back to the canvas orb when video clips are unavailable or fail to load.

#### Props

None. Reads from `session`, `emotionalState`, and `activeEmotion` stores to determine the current visual state. The emotional state drives the orb's colour and breathing rate, connecting the agent's inner feelings to a continuous visual representation.

#### Reactive State ($state)

The component tracks the video element's loading and error state to determine which rendering mode to use:

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `videoSrc` | `string` | `''` | `file://` URL to the current avatar video clip |
| `videoReady` | `boolean` | `false` | Set to true when the video has loaded and started playing |
| `videoError` | `boolean` | `false` | Set to true when the video fails to load, triggering canvas fallback |

#### Other Instance Variables

The component maintains references to canvas elements and animation state for the procedural orb:

| Variable | Type | Purpose |
|----------|------|---------|
| `canvas` | `HTMLCanvasElement` | Canvas element reference for the procedural orb |
| `ctx` | `CanvasRenderingContext2D` | Canvas 2D rendering context |
| `time` | `number` | Animation time counter, increments by 0.016 per frame (approximately 60fps) |
| `animFrame` | `number` | `requestAnimationFrame` handle for cancellation on cleanup |
| `blendFactor` | `number` | Smooth blend factor (0-1) that interpolates between the base emotional colour and the active emotion colour |
| `videoEl` | `HTMLVideoElement` | Video element reference for controlling playback |

#### Video Layer

The video layer loads pre-rendered avatar clips from the agent's avatar directory. Each agent can have a set of video loops organized by colour and clip name (e.g. `blue/loop_bounce_playful.mp4`). The component requests the video path from the main process via `api.getAvatarVideoPath(colour, clip)` IPC, with the default request being `loadVideo('blue', 'bounce_playful')`. Videos play looped, muted, and full-bleed (`object-fit: cover`) to fill the entire window background. The video fades in over 0.8s when the `canplay` event fires, preventing a flash of the first frame.

The following CSS shows how the video layer is positioned behind all other content:

```css
.avatar-video {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  object-fit: cover;
  opacity: 0;            /* hidden until ready */
  transition: opacity 0.8s ease;
}
.avatar-video.visible { opacity: 1; }
```

#### Canvas Fallback (Procedural Orb)

The canvas fallback renders when video is unavailable or fails to load. It draws a softly glowing, breathing orb using the Canvas 2D API with DPR-aware scaling (`window.devicePixelRatio`) to ensure crisp rendering on Retina displays.

**Colour computation (`orbColor()`):** The orb's colour is derived from two sources - the continuous emotional state and any active discrete emotion reaction. The base colour comes from the emotional state dimensions:

- Hue: `220 + (warmth - 0.5) * -40 + (playfulness - 0.3) * 20` - starts at blue (220), shifts toward red with higher warmth, toward green with higher playfulness.
- Saturation: `40 + connection * 30` - more connected emotions produce richer colours.
- Lightness: `15 + warmth * 10` - warmer emotions produce slightly brighter orbs.
- Frustration shift (when > 0.3): hue += `(frustration - 0.3) * 100`, saturation += `frustration * 20` - frustration overrides toward red.

When an emotion reaction is active (`activeEmotion.type !== null`), `blendFactor` smoothly ramps toward 1.0 at `BLEND_SPEED = 0.04` per frame. The orb HSL values are linearly interpolated toward the emotion's HSL colour by `blendFactor`, producing a smooth colour transition rather than an abrupt snap.

**Rendering layers (drawn back to front):** The orb is built from multiple layered draws that create depth and glow. Each frame clears the canvas and redraws all layers:

1. **Glow layers** - 4 concentric radial gradients (i=3 down to 0), each at `r * (1 + i * 0.5)` radius with alpha `0.04 - i * 0.008`. These create a soft ambient glow around the orb.
2. **Core gradient** - offset radial gradient (`cx - r*0.2, cy - r*0.2` origin) with three colour stops: bright centre at 0%, mid at 50%, dark edge at 100%. The offset simulates a light source from the upper left.
3. **Highlight** - small bright spot at `cx - r*0.15, cy - r*0.2` with radius `r * 0.4`, 12% white at centre. Simulates a specular highlight.
4. **Particles** - 5 ambient particles (12 when in the thinking state) orbiting the orb. Each particle has angle `(time*0.3 + i*TAU/count)`, distance `r * (1.2 + sin(time*0.5+i)*0.4)`, alpha `0.08 + sin(time+i*2)*0.04`, radius `1 + sin(time*2+i)*0.5`. These add subtle movement around the orb.

**Breathing animation:** The orb pulses rhythmically to simulate breathing, with different rates for idle and thinking states. In idle state, `breathRate = 1.2` and `breathAmp = 0.03` (3% radius variation), producing a slow, calm breathing rhythm. During thinking, `breathRate = 4.0` and `breathAmp = 0.06` (6% radius variation), producing a faster, more energetic pulse that visually communicates processing. The base radius is `min(canvasWidth, canvasHeight) * 0.18`, scaling proportionally with the window size.

**Canvas setup:** The canvas is configured for Retina-quality rendering by scaling to the device pixel ratio: `canvas.width = rect.width * devicePixelRatio`, then `ctx.scale(dpr, dpr)` for correct coordinate mapping. The animation runs at display refresh rate via `requestAnimationFrame`.

#### Lifecycle

- **onMount:** Calls `loadVideo()` to attempt loading the avatar video clip. If the video is not ready (no path returned or loading fails), calls `initCanvas()` to start the procedural canvas fallback. Returns a cleanup function that cancels the `requestAnimationFrame` to stop the animation loop.

---

### AgentName.svelte - Agent Name Display

**File:** `src/renderer/components/AgentName.svelte`

AgentName.svelte renders the current agent's display name in the top-left corner of the window with a rolodex-style switching animation and up/down chevrons for cycling through available agents. The rolodex effect makes agent switching feel physical and directional - the old name slides up or down out of view while the new name slides in from the opposite direction, like flipping through a card file.

#### Props ($props)

The component receives its data and callbacks through props, keeping it decoupled from the stores and allowing Window.svelte to control the switching logic:

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `name` | `string` | required | Current agent display name |
| `direction` | `number` | required | Animation direction (-1 slides up/previous, +1 slides down/next) |
| `canCycle` | `boolean` | `true` | Whether to show up/down chevrons (false when only one agent exists) |
| `onCycleUp` | `() => void` | required | Callback for cycling to previous agent |
| `onCycleDown` | `() => void` | required | Callback for cycling to next agent |

#### Reactive State ($state)

The component tracks the currently displayed name and animation progress separately from the incoming prop, allowing the animation to show the old name during the first half and the new name during the second half:

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `displayName` | `string` | `''` | Currently displayed name (may differ from `name` prop during animation) |
| `offset` | `number` | `0` | Vertical pixel offset for the rolodex slide animation |
| `animating` | `boolean` | `false` | Whether an animation is in progress, prevents overlapping animations |

#### Rolodex Animation

When the `name` prop changes and the component is not already animating, the rolodex animation plays through these steps:

1. Set `offset` to `+30` (direction > 0, sliding down) or `-30` (direction < 0, sliding up) to position the text off-screen in the direction of travel.
2. Run a 400ms `requestAnimationFrame` loop with ease-out cubic easing: `1 - (1-t)^3`. This produces a fast start and gentle deceleration.
3. At 50% progress (200ms), swap `displayName` to the new `name` value. This creates the illusion of the old name sliding away and the new name sliding in.
4. Animate `offset` from the starting value (+30 or -30) back to 0.
5. Set `animating = false` on completion.

The name text uses `transform: translateY({offset}px)` within a 30px-tall clipped container (`.name-clip`), which hides the text when it slides above or below the visible area.

#### Chevrons

Up/down chevron buttons (14px SVG) appear on hover of the `.agent-name` container, providing a mouse-accessible way to cycle agents. They are hidden by default (`opacity: 0`) with a 0.2s transition for a smooth reveal. Colours are `var(--text-dim)` by default and `var(--text-secondary)` on hover.

#### Styling

The agent name uses bold uppercase typography with a text shadow for readability against the orb background:

- Container: `width: 250px`, flex column layout.
- Name text: 20px bold uppercase, 1px letter-spacing, `rgba(255, 255, 255, 0.78)`, text-shadow `0 1px 3px rgba(0, 0, 0, 0.4)`, `white-space: nowrap`, `will-change: transform` for animation performance.
- Clip: `height: 30px`, `overflow: hidden` to constrain the sliding text.
- `data-no-drag` attribute prevents window dragging from this area so clicks on chevrons work correctly.

---

### ThinkingIndicator.svelte - Inference Status

**File:** `src/renderer/components/ThinkingIndicator.svelte`

ThinkingIndicator.svelte renders a pulsing brain SVG icon next to the agent name during inference. It provides a constant visual indicator that the system is working - whether thinking about the response, actively streaming text, or compacting context. The pulsing animation creates a subtle "breathing" effect that feels alive rather than static, reinforcing the sense that the agent is actively processing.

#### Props

None. The component's visibility is controlled by Window.svelte, which conditionally renders it based on `session.inferenceState !== 'idle'`.

#### Reactive State ($state)

The component tracks a single opacity value that drives the pulsing animation:

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `opacity` | `number` | `0.25` | Current opacity of the brain icon, oscillated by the animation loop |

#### Animation

The pulsing animation uses a `setInterval` at 50ms (20 updates per second). Each tick increments a `frame` counter and computes the opacity using a sine wave:

```typescript
opacity = 0.25 + 0.55 * Math.sin(frame * 0.15);
```

This formula produces a smooth sine wave oscillation between 0.25 (dim but visible) and 0.80 (clearly visible) at approximately 3 Hz. The `will-change: opacity` CSS hint is set on the element to inform the browser's compositor that this property will change frequently, enabling GPU-accelerated opacity transitions.

#### Visibility

The ThinkingIndicator is shown in Window.svelte whenever `session.inferenceState !== 'idle'`, which covers all three active states: `'thinking'` (waiting for first response), `'streaming'` (receiving text deltas), and `'compacting'` (Claude is summarizing context to fit within limits). The component is conditionally rendered via `{#if}`, so it is completely removed from the DOM when not needed.

#### Styling

The indicator uses a compact layout that sits inline with the agent name:

- Container: flex display, `color: var(--text-secondary)`, `margin-left: 4px`, `margin-top: 3px`.
- SVG: 20x20px brain icon, `stroke-width: 1.5`, `fill: none`. The brain icon uses simple path elements to suggest neural connections.

#### Lifecycle

- **onMount:** Starts the 50ms interval that drives the pulsing animation. Returns a cleanup function that clears the interval, preventing the timer from running after the component unmounts.

---

### Timer.svelte - Countdown Timer

**File:** `src/renderer/components/Timer.svelte`

Timer.svelte provides a draggable floating overlay for countdown timers with alarm functionality. It lets the user set a timer duration, watch it count down with a colour-shifting display, and receive both audio and system notification alerts when time expires. The timer is useful for focused work sessions, cooking, or any scenario where the user wants a visible countdown without leaving the app. The component is fully self-contained - it manages its own timing, alarm sounds, and positioning.

#### Props ($props)

| Prop | Type | Description |
|------|------|-------------|
| `onClose` | `() => void` | Callback to dismiss the timer overlay, called by the close button |

#### Reactive State ($state)

The component manages a substantial amount of state for the timer mechanics, alarm, dragging, and visual effects:

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `endTime` | `number` | `0` | `Date.now()` timestamp when the timer expires |
| `totalSeconds` | `number` | `0` | Displayed remaining seconds |
| `running` | `boolean` | `false` | Timer actively counting down |
| `paused` | `boolean` | `false` | Timer paused mid-countdown |
| `pauseRemaining` | `number` | `0` | Seconds remaining when paused, used to resume |
| `done` | `boolean` | `false` | Timer has reached zero |
| `alarming` | `boolean` | `false` | Alarm is currently sounding |
| `dragging` | `boolean` | `false` | Currently being dragged by the user |
| `posRight` | `number` | `20` | Right offset in pixels (initial positioning) |
| `posTop` | `number` | `80` | Top offset in pixels |
| `posMode` | `'right' \| 'left'` | `'right'` | Positioning mode - starts right-anchored, switches to left on first drag |
| `posLeft` | `number` | `0` | Left offset in pixels (used after first drag converts positioning) |
| `timerColor` | `string` | `'rgba(255, 180, 100, 0.9)'` | Current display colour (shifts from amber to red in final 10 seconds) |
| `timerShadow` | `string` | `'0 0 40px rgba(255, 140, 50, 0.2)'` | Current text-shadow glow effect |

#### Timing

The timer uses `setInterval` at 100ms for smooth display updates without excessive CPU usage. Remaining time is computed as `(endTime - Date.now()) / 1000` for drift-free countdown based on wall-clock time rather than accumulated interval deltas. This approach ensures the timer stays accurate even if the main thread is briefly blocked by other work.

**Display format:** Durations under one hour show as `m:ss` (e.g. `5:00`, `0:32`). Longer durations show as `h:mm:ss` (e.g. `1:30:00`).

#### Colour Gradient

In the final 10 seconds, the timer display progressively shifts from its default warm amber to an urgent red. This visual escalation provides a glanceable indication that time is almost up. The transition affects both the text colour and the glow shadow:

- Green channel: 180 decreases to 40 (amber to red).
- Blue channel: 100 decreases to 20 (amber to red).
- Shadow glow intensifies from 0.2 to 0.5 opacity.

At zero, the colour settles to `rgba(255, 100, 100, 0.9)` with a `0 0 40px rgba(255, 60, 60, 0.4)` shadow, providing a clear "time's up" visual signal.

#### Alarm

When the timer reaches zero, it triggers both audio and visual alerts to ensure the user notices even if they are not looking at the window:

1. Plays the Glass.aiff system sound 6 times with 1.5-second spacing via a `setTimeout` chain. The Glass sound is a gentle but attention-getting macOS system alert.
2. Fires a macOS notification via the `Notification` API with the title "Timer complete" and body "Your timer has finished."
3. Requests notification permission if not yet granted (the first timer alarm will prompt the user).
4. Auto-dismisses after 60 seconds if the user does not manually dismiss the alarm.

#### Add Time

The `addMinutes(n)` function handles adding time in four different states, ensuring a consistent user experience regardless of when the button is pressed:

- **Done/alarming:** Stops the alarm, clears the done state, and restarts the timer with `n` minutes.
- **Paused:** Adds `n * 60` seconds to `pauseRemaining` so the extra time is included when the user resumes.
- **Running:** Extends `endTime` by `n * 60 * 1000` milliseconds, seamlessly adding time to the active countdown.
- **Not started:** Adds `n * 60` to `totalSeconds`, adjusting the initial duration before the timer is started.

#### Dragging

The timer supports mouse-drag repositioning so the user can place it anywhere in the window that does not obstruct their conversation. The dragging implementation handles an initial coordinate system conversion:

- `mousedown` on the timer body (but not on buttons, which have their own click handlers) initiates the drag.
- On the first drag, the component converts from right-based positioning (used for the initial bottom-right placement) to left-based positioning by reading `getBoundingClientRect()`. This conversion is needed because drag deltas are more intuitive in left/top coordinates.
- Subsequent drags update `posLeft` and `posTop` by the mouse delta.
- Global `mousemove` and `mouseup` listeners are registered on `window` (not the timer element) to ensure dragging continues even when the mouse moves outside the timer bounds.

#### Styling

The timer uses a frosted glass appearance with a blurred backdrop that lets the conversation show through while remaining clearly distinct as an overlay element:

```css
.timer-overlay {
  position: absolute;
  z-index: 50;
  background: rgba(20, 20, 24, 0.88);
  backdrop-filter: blur(20px);
  border-radius: 12px;
  border: 1px solid var(--border);
  padding: 20px 28px 16px;
  min-width: 220px;
  cursor: grab;
  user-select: none;
}
```

The visual elements within the timer are styled as follows:

- **Display:** `font-family: var(--font-mono)`, 42px, font-weight 300, 2px letter-spacing. The large monospaced digits are easy to read at a glance.
- **Buttons:** Pill-shaped (14px border-radius), amber borders (`rgba(255, 180, 100, 0.3)`), 12px font.
- **Dismiss button:** Red theme (`rgba(255, 80, 80, 0.25)` background, font-weight 600, wider padding) to distinguish it from the add-time buttons.

#### Lifecycle

- **onMount:** Sets the default duration to 5 minutes. Registers global mouse event listeners on `window` for drag handling. Returns a cleanup function that stops the tick interval, cancels any active alarm sounds, and removes the global mouse listeners.

---

### Canvas.svelte - PIP Webview Overlay

**File:** `src/renderer/components/Canvas.svelte`

Canvas.svelte provides a picture-in-picture style overlay for rendering HTML content using the Electron `<webview>` tag. It is triggered by the agent's `render_canvas` MCP tool, which generates HTML pages that need to be displayed alongside the conversation. The canvas overlay anchors to the bottom-right of the window and renders any URL the agent provides, from interactive visualizations to static documentation. When no content has been provided, it shows a placeholder explaining that content will appear when the agent creates it.

#### Props ($props)

| Prop | Type | Description |
|------|------|-------------|
| `onClose` | `() => void` | Callback to dismiss the canvas overlay |
| `onRequestShow` | `() => void` | Optional callback to auto-show the canvas when new content arrives, called by Window.svelte to set `showCanvas = true` |

#### Reactive State ($state)

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `url` | `string` | `''` | Current webview URL, set when the agent writes canvas content |
| `visible` | `boolean` | `false` | Controls the CSS opacity transition for fade-in/fade-out |

#### Other Instance Variables

| Variable | Type | Purpose |
|----------|------|---------|
| `refreshTimer` | `timeout \| null` | 100ms debounce timer to prevent rapid URL updates from causing flicker |
| `cleanups` | `(() => void)[]` | Array of IPC listener cleanup functions, called on destroy |

#### Content Pipeline

The canvas content flows from the agent through the main process to the renderer in a specific sequence. This pipeline ensures that content updates are debounced and the overlay auto-shows when appropriate:

1. The MCP `render_canvas` tool in the main process writes HTML to a temp file and triggers a `canvas:updated` IPC event with the URL.
2. Window.svelte's IPC listener receives the event and sets `showCanvas = true`, mounting the Canvas component if it is not already visible.
3. Inside Canvas.svelte, the `canvas:updated` listener calls `debouncedRefresh(newUrl)`, which delays 100ms before setting `url` and calling `onRequestShow()`. The debounce prevents rapid consecutive tool calls from causing flicker.
4. The `<webview>` element renders the URL with full JavaScript execution capability.
5. When the URL is empty, the component shows a placeholder message: "No canvas content" / "Content will appear here when the agent creates it".

#### Close Animation

On close, the component sets `visible = false` to trigger the CSS opacity fade-out, then waits 300ms for the animation to complete before calling `onClose()` to remove the component from the DOM. This ensures the user sees a smooth fade rather than an abrupt disappearance.

#### Layout

The canvas overlay uses absolute positioning to cover the full window while only making the PIP area interactive. The following CSS shows the overlay and PIP container styles:

```css
.canvas-overlay {
  position: absolute;
  inset: 0;
  z-index: 45;
  pointer-events: none;    /* pass-through except for PIP area */
  opacity: 0;              /* fades in when visible */
  transition: opacity 0.3s ease;
}

.canvas-pip {
  width: 55%;
  height: 50%;
  margin: 0 16px 16px 0;  /* bottom-right positioning */
  border-radius: 12px;
  background: rgba(12, 12, 14, 0.95);
  backdrop-filter: blur(20px);
  pointer-events: auto;   /* interactive area */
  transform: translateY(8px) scale(0.97);  /* entry animation start */
  transition: transform 0.3s ease;
}
```

The PIP window anchors to the bottom-right of the window. The `pointer-events: none` on the overlay allows clicks to pass through to the conversation, while `pointer-events: auto` on the PIP makes only the webview area interactive. The close button is positioned absolutely above the PIP at `bottom: calc(50% + 16px + 8px)` as a 28px circle with a red hover state.

#### Lifecycle

- **onMount:** Fades in via `requestAnimationFrame(() => visible = true)` to trigger the CSS transition. Registers a `canvas:updated` IPC listener for content updates from the agent.
- **onDestroy:** Clears the debounce timer and calls all cleanup functions to remove IPC listeners.

---

### Artefact.svelte - Artefact Display

**File:** `src/renderer/components/Artefact.svelte`

Artefact.svelte provides a full-bleed overlay for displaying artefacts created by the agent via the `create_artefact` MCP tool. Artefacts are rich content objects - HTML pages, SVG graphics, code files, images, or videos - that the agent produces during conversation. Unlike the canvas (which shows ephemeral content), artefacts are saved to the database and can be browsed through a gallery panel. The overlay fills the entire window with a dark frosted backdrop and renders the artefact content at maximum size.

#### Props ($props)

| Prop | Type | Description |
|------|------|-------------|
| `onClose` | `() => void` | Callback to dismiss the artefact overlay |

#### Reactive State ($state)

The component manages state for both the current artefact display and the gallery browser:

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `content` | `string` | `''` | HTML/code/markdown content of the current artefact |
| `contentType` | `'html' \| 'svg' \| 'code' \| 'markdown' \| 'image' \| 'video'` | `'html'` | Determines which rendering strategy to use |
| `contentSrc` | `string` | `''` | `file://` URL for binary artefacts (images and videos) |
| `visible` | `boolean` | `false` | Controls the CSS entrance animation |
| `gallery` | `Array<{id, title, type, description?, path?, file?, created_at?}>` | `[]` | All artefact gallery items loaded from the database |
| `showGallery` | `boolean` | `false` | Whether the gallery side panel is open |
| `searchQuery` | `string` | `''` | Gallery search text for filtering by title or description |
| `activeFilter` | `string` | `'all'` | Gallery type filter (all, html, code, image, video) |
| `loadingName` | `string` | `''` | Name of artefact currently being generated (shown as pulsing indicator) |

#### Derived State ($derived)

| Variable | Expression | Purpose |
|----------|------------|---------|
| `filteredGallery` | Filters `gallery` by `activeFilter` and `searchQuery` | The subset of gallery items currently visible after applying type and text filters |

#### Content Rendering

The component renders artefact content differently based on the `contentType` field. Each type uses the most appropriate HTML element for its content:

- **html / svg:** Rendered in a sandboxed `<iframe>` with `srcdoc={content}`, permissions: `allow-scripts allow-same-origin`. The iframe provides full HTML/CSS/JS rendering in an isolated context.
- **image:** `<img>` with `src={contentSrc}` or a data URI from content, `object-fit: contain` to fit within the overlay without cropping.
- **video:** `<video>` with `src={contentSrc}`, controls, autoplay, and loop for continuous playback.
- **code / markdown / other:** `<pre class="artefact-code">` with 13px monospace font and pre-wrap whitespace for readable code display.

#### Gallery Panel

The gallery panel slides out from the left side of the overlay, providing a browsable index of all artefacts the agent has created. It includes type filtering, text search, and clickable cards that load artefacts into the main display area.

The gallery panel uses the following CSS for its slide-out positioning:

```css
.gallery-panel {
  position: absolute;
  left: var(--pad);
  top: 60px;
  bottom: var(--pad);
  width: 260px;
  background: rgba(20, 20, 24, 0.95);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
}
```

**Filter options:** All, HTML, Code, Image, Video - rendered as pill buttons (12px border-radius, 10px font). The active filter gets `rgba(255, 255, 255, 0.15)` background with `rgba(255, 255, 255, 0.3)` border.

Each artefact type has a distinct badge colour for quick visual identification:

- html/svg: `#4a9eff` (blue)
- code/markdown: `#a8e6a1` (green)
- image: `#ff6b9d` (pink)
- video: `#9b59b6` (purple)

**Card layout:** Each gallery item is a flex column card with 10px/12px padding, 8px border-radius, and 6px bottom margin. Cards display the type badge (9px bold uppercase), creation date, title (13px, formatted with hyphens replaced by spaces and title-cased), and a truncated description (60 character max).

#### Close Animation

On close, the component sets `visible = false` to trigger the CSS scale/opacity transition, clears the iframe content (resetting it to `about:blank` to stop any running scripts), waits 300ms for the animation, then calls `onClose()`.

#### Entrance Animation

The artefact overlay uses a combined opacity and scale transition for a smooth entrance that draws attention to the new content:

```css
.artefact-overlay {
  z-index: 40;
  background: rgba(12, 12, 14, 0.96);
  backdrop-filter: blur(20px);
  opacity: 0;
  transform: scale(0.98);
  transition: opacity 0.3s ease, transform 0.3s ease;
}
.artefact-overlay.visible {
  opacity: 1;
  transform: scale(1);
}
```

#### Lifecycle

- **onMount:** Fades in by setting `visible = true` after a `requestAnimationFrame`. Registers a window resize listener for responsive layout adjustments. Registers an `artefact:updated` IPC listener to receive new artefact content from the main process. Registers an `artefact:loading` IPC listener to show a generating indicator. Registers an `inline-artifact` window CustomEvent listener to receive artifact content from transcript card clicks (these arrive when the user clicks an `[[artifact:id]]` placeholder card in the Transcript). Loads the gallery on mount via `refreshGallery()`.
- **onDestroy:** Removes the resize listener, removes the `inline-artifact` event listener, calls cleanup functions to remove IPC listeners, and clears iframe content to prevent stale scripts from running.

---

### Settings.svelte - Settings Panel

**File:** `src/renderer/components/Settings.svelte`

Settings.svelte provides a full-screen overlay with three tabs: Settings (configuration), Usage (token consumption), and Activity (event log). It is the primary interface for users to configure the application, review resource usage, and debug agent behavior. The settings panel reads the full configuration from the main process on mount, presents it in organized sections with appropriate input types, and writes changes back via the `updateConfig` IPC channel.

#### Props ($props)

| Prop | Type | Description |
|------|------|-------------|
| `onClose` | `() => void` | Callback to dismiss the settings overlay, triggered by the close button or Escape key |

#### Reactive State ($state)

The settings panel maintains a large number of state variables organized by tab and section. The Settings tab alone has approximately 40 form fields covering every configurable aspect of the application.

**Tab state:** These variables control which tab is active and the save status indicator:

| Variable | Type | Default |
|----------|------|---------|
| `activeTab` | `'settings' \| 'usage' \| 'activity'` | `'settings'` |
| `saveStatus` | `string` | `''` |

**Config form fields (Settings tab):** The following table lists all form field groups and their state variables. Each variable is initialized from the config object loaded via `api.getConfig()` on mount:

| Section | State Variables |
|---------|----------------|
| Agents | `agentList` - array of `{name, display_name, description, role}` |
| You | `userName` - the user's display name. When changed, also syncs to the active agent's `agent.json` `user_name` field and writes a system observation to the agent's memory noting the name change |
| Agent Identity | `agentDisplayName`, `openingLine`, `wakeWords` |
| Tools | `disabledTools` - `Set<string>` for 13 toggleable MCP tools |
| Window | `windowWidth` (622), `windowHeight` (830), `avatarEnabled`, `avatarResolution` (512), `eyeModeDefault`, `silenceTimerEnabled`, `silenceTimerMinutes` (5) |
| Voice | `ttsBackend`, `elevenlabsApiKey`, `elevenlabsVoiceId`, `elevenlabsModel`, `elevenlabsStability` (0.5), `elevenlabsSimilarity` (0.75), `elevenlabsStyle` (0.35), `ttsPlaybackRate` (1.12), `falApiKey`, `falVoiceId` |
| Input | `inputMode`, `pttKey`, `wakeWordEnabled`, `wakeChunkSeconds`, `muteByDefault` |
| Notifications | `notificationsEnabled` |
| Audio | `sampleRate` (16000), `maxRecordSec` (120) |
| App | Reset Setup button (sets `setup_complete: false` for next launch) |
| Inference | `claudeBin`, `claudeEffort`, `adaptiveEffort` |
| Memory | `contextSummaries` (3), `maxContextTokens` (180000), `vectorSearchWeight` (0.7), `embeddingModel`, `embeddingDim` (384) |
| Session | `sessionSoftLimitMins` (60) |
| Heartbeat | `heartbeatActiveStart` (9), `heartbeatActiveEnd` (22), `heartbeatIntervalMins` (30) |
| Paths | `obsidianVault`, `dbPath`, `whisperBin` |
| Google | `googleConfigured`, `googleAuthStatus` |
| Telegram | `telegramBotToken`, `telegramChatId` |
| About | `version`, `bundleRoot` |

**Usage tab:** These variables manage the token usage display, which shows historical consumption data:

| Variable | Type | Default |
|----------|------|---------|
| `usagePeriod` | `number \| null` | `null` |
| `usageData` | `any[]` | `[]` |
| `usageLoading` | `boolean` | `false` |

**Activity tab:** These variables manage the event log display, which shows tool calls, heartbeats, and inference events:

| Variable | Type | Default |
|----------|------|---------|
| `activityItems` | `any[]` | `[]` |
| `activityFilter` | `string` | `'all'` |
| `activityAgentFilter` | `string` | `'all'` |
| `activitySearch` | `string` | `''` |
| `activityLoading` | `boolean` | `false` |
| `expandedActivity` | `number \| null` | `null` |

#### Toggleable Tools List

The Tools section allows per-agent enabling/disabling of 13 MCP tools. When a tool is disabled, it is added to the agent's `DISABLED_TOOLS` config list and excluded from the MCP tool manifest during inference. The following table lists all toggleable tools:

| Tool ID | Display Name |
|---------|-------------|
| `mcp__memory__defer_to_agent` | Agent deferral |
| `mcp__memory__send_telegram` | Telegram messaging |
| `mcp__memory__set_reminder` | Reminders |
| `mcp__memory__set_timer` | Timers |
| `mcp__memory__create_task` | Task scheduling |
| `mcp__memory__render_canvas` | Canvas overlay |
| `mcp__memory__write_note` | Write Obsidian notes |
| `mcp__memory__prompt_journal` | Journal prompting |
| `mcp__memory__update_emotional_state` | Emotional state |
| `mcp__memory__create_artefact` | Artefact creation |
| `mcp__memory__manage_schedule` | Schedule management |
| `mcp__puppeteer__*` | Browser (Puppeteer) |
| `mcp__fal__*` | Media generation (fal) |

#### Save Modes

The settings panel provides two save operations that differ in what they persist. Both use the same `gatherUpdates()` function to collect current form values:

- **Apply:** Calls `gatherUpdates()` to collect all form values, then calls `api.updateConfig(updates)` to push changes to the running main process. The changes take effect immediately but are not written to disk, so they will be lost on restart. Shows "Applied" status for 2 seconds.
- **Save:** Calls Apply first to push changes to the running process, then additionally writes the configuration to disk. Shows "Saved" status for 2 seconds.

The `gatherUpdates()` function maps all form state variables to their config key names using the naming convention from the Python codebase (e.g. `userName` maps to `USER_NAME`, `ttsBackend` maps to `TTS_BACKEND`). It includes all toggleable settings: `WAKE_WORDS`, `SILENCE_TIMER_ENABLED`, `SILENCE_TIMER_MINUTES`, `EYE_MODE_DEFAULT`, `MUTE_BY_DEFAULT`, and all other config keys.

Secret keys (ElevenLabs API key, Fal API key, Telegram bot token) are saved separately via `api.saveSecret()` to `~/.atrophy/.env`, not through `gatherUpdates()`. The secret key names must match the `.env` allowlist exactly: `ELEVENLABS_API_KEY`, `FAL_KEY`, `TELEGRAM_BOT_TOKEN`.

#### Activity Tab Features

The Activity tab provides a filterable, searchable event log for debugging and monitoring agent behavior. It loads recent events from the SQLite database via `api.getActivity()` and displays them in an expandable list.

The activity log uses the following visual conventions:

- **Category badges:** TOOL (blue `#4a9eff`), BEAT (purple `#9b59b6`), INFER (green `#2ecc71`). These colour-coded labels make it easy to scan the log for specific event types.
- **Filtering:** Events can be filtered by category (all, flagged, tool_call, heartbeat, inference), by agent name, and by search text. Filters are applied client-side to the loaded data.
- **Expandable rows:** Clicking a row expands it to show the full event detail, including tool arguments, response text, or heartbeat metadata.
- **Limit:** The display shows a maximum of 200 items after filtering to prevent performance issues with very long event histories.

#### Utility Functions

The Settings component includes several formatting functions used across the Usage and Activity tabs:

| Function | Purpose |
|----------|---------|
| `formatTokens(n)` | Formats large numbers with K/M suffixes (e.g. 1500 becomes "1.5K", 2500000 becomes "2.5M") |
| `formatDuration(ms)` | Formats millisecond durations as human-readable strings (e.g. "3s", "2m 15s", "1h 30m") |
| `formatTimestamp(ts)` | Formats Unix timestamps as "Mon DD HH:MM:SS" for the activity log |

#### Keyboard Shortcuts

The settings panel handles the Escape key to close itself, registered via `svelte:window onkeydown`:

| Key | Action |
|-----|--------|
| Escape | Close the settings overlay |

#### IPC Channels Used

The settings panel communicates with the main process through several channels for loading data and saving changes:

| Channel | Usage |
|---------|-------|
| `api.getConfig()` | Load all config values on mount to populate form fields |
| `api.getAgentsFull()` | Load the agent list with full metadata (name, display name, description, role) for the Agents section |
| `api.updateConfig(updates)` | Apply/save config changes to the running main process |
| `api.saveSecret(key, value)` | Save API keys to `~/.atrophy/.env` (ElevenLabs, Fal, Telegram) |
| `api.switchAgent(name)` | Switch active agent when the user selects a different agent in the Agents section |
| `api.getUsage(days?)` | Load token usage data for the Usage tab |
| `api.getActivity(days, limit)` | Load activity event items for the Activity tab |

#### Lifecycle

- **onMount:** Loads config and agent list via a parallel `Promise.all` call, then populates all form state variables from the returned config values. Default values are used for any fields not present in the config object. The parallel loading ensures the settings panel appears quickly even when the database queries take time.

---

### SetupWizard.svelte - First-Launch Overlays

**File:** `src/renderer/components/SetupWizard.svelte`

SetupWizard.svelte provides minimal overlay screens for the first-launch flow. It only handles three phases: welcome (name input), creating (agent scaffolding spinner), and done (brief confirmation). The actual setup conversation - service configuration and AI-driven agent creation - happens in the main chat using the real Transcript and InputBar components, orchestrated by Window.svelte.

#### Props ($props)

| Prop | Type | Description |
|------|------|-------------|
| `phase` | `'welcome' \| 'creating' \| 'done' \| 'hidden'` | Controls which overlay screen is shown, or hides the component entirely |
| `createdAgentName` | `string` | Display name for the creating/done screens |
| `onNameEntered` | `(name: string) => void` | Callback when user submits their name in the welcome phase |
| `onComplete` | `() => void` | Optional callback fired when the done phase auto-dismisses (after 3 seconds) |

#### Reactive State ($state)

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `userName` | `string` | `''` | User's name, entered in the welcome phase |

#### Phase Flow

The wizard phases are controlled externally by Window.svelte via the `phase` prop:

```
welcome -> hidden (chat takes over) -> creating -> done -> hidden
```

| Phase | Content | Transition |
|-------|---------|------------|
| `welcome` | Brain icon, "Atrophy" title, name input | `onNameEntered` callback when Enter or Continue clicked |
| `hidden` | No overlay - main chat visible | Set by Window.svelte after welcome or after done |
| `creating` | Spinner + "Creating {name}..." | Set by Window.svelte when AGENT_CONFIG detected |
| `done` | Brain icon + "Meet {name}." | Auto-dismisses after 3 seconds via `onComplete` |

#### Brain Frames

The welcome and done phases display a brain icon loaded from pre-rendered PNG frames via `import.meta.glob()`. Only frame 0 (pristine) is used.

---

### MirrorSetup.svelte - Per-Agent Custom Setup

**File:** `src/renderer/components/MirrorSetup.svelte`

MirrorSetup.svelte provides a custom setup flow for the Mirror agent. Unlike the first-launch wizard, this only appears when the user switches to an agent that has `custom_setup` set in its manifest. It is triggered by `agent:switch` returning `customSetup: "mirror"` and controlled by Window.svelte's `mirrorSetupVisible` state.

#### Props ($props)

| Prop | Type | Description |
|------|------|-------------|
| `onComplete` | `() => void` | Callback to dismiss the overlay |

#### Phase Flow

```
intro -> downloading -> photo -> generating -> voice -> done
```

| Phase | Content | Transition |
|-------|---------|------------|
| `intro` | Title, description, numbered steps, Begin/Skip buttons | Begin starts asset download |
| `downloading` | Spinner + progress bar for release asset download | Auto-advances to photo when complete (or skips if no assets) |
| `photo` | File picker for user photo upload, preview | "Generate avatar" uploads photo then starts Kling generation |
| `generating` | Spinner + clip progress from `mirror:avatarProgress` IPC events | Auto-advances to voice when all clips done |
| `voice` | Link to ElevenLabs Voice Lab, voice ID input | Save or skip advances to done |
| `done` | Checkmark + "Ready" | Auto-dismisses after 2 seconds via `onComplete` |

#### IPC Calls

- `mirror:uploadPhoto` - sends photo ArrayBuffer + filename to main
- `mirror:generateAvatar` - triggers Fal AI Kling 3.0 image-to-video
- `mirror:avatarProgress` - receives generation progress events
- `mirror:saveVoiceId` - saves ElevenLabs voice ID to agent config
- `mirror:downloadAssets` - triggers release asset download
- `mirror:openExternal` - opens ElevenLabs in browser (allowlisted URL)
- `mirror:checkSetup` - checks if photo/loops exist
- `avatar:download-progress` / `avatar:download-complete` / `avatar:download-error` - asset download events

---

### ServiceCard.svelte - Inline Service Configuration

**File:** `src/renderer/components/ServiceCard.svelte`

ServiceCard.svelte renders an inline service configuration card between the Transcript and InputBar during the setup flow. It handles all four services (ElevenLabs, Fal, Telegram, Google) with input fields, verification, and save/skip actions.

#### Props ($props)

| Prop | Type | Description |
|------|------|-------------|
| `step` | `number` | Current service index (0=ElevenLabs, 1=Fal, 2=Telegram, 3=Google) |
| `onSaved` | `(key: string) => void` | Callback when a service key is saved |
| `onSkipped` | `(key: string) => void` | Callback when a service is skipped |

#### Service Definitions

| Step | Key | Title | Input Type |
|------|-----|-------|------------|
| 0 | `ELEVENLABS_API_KEY` | Voice - ElevenLabs | Password (secure) |
| 1 | `FAL_KEY` | Visual Presence - Fal.ai | Password (secure) |
| 2 | `TELEGRAM` | Messaging - Telegram | Bot Token (secure) + Chat ID (plain) |
| 3 | `GOOGLE` | Google Workspace + YouTube + Photos | Checkbox scopes + OAuth button |

#### Service Verification

Verification happens directly from the renderer via `fetch` calls:

| Service | Endpoint | Success Condition |
|---------|----------|-------------------|
| ElevenLabs | `GET https://api.elevenlabs.io/v1/user` with `xi-api-key` header | `res.ok` (HTTP 200) |
| Fal | `POST https://queue.fal.run/fal-ai/fast-sdxl` with `Authorization: Key ...` header | `res.status < 400` |
| Telegram | `GET https://api.telegram.org/bot.../getMe` | `data.ok === true` in the JSON response |
| Google | OAuth browser flow via `api.startGoogleOAuth()` | Returns `'complete'` |

Verified keys are saved to `~/.atrophy/.env` via `api.saveSecret()`. Non-secret settings (like Telegram chat ID) go to `config.json` via `api.updateConfig()`.

#### Styling

- **Card container:** 14px border-radius, subtle background, full-width within padding
- **Secure inputs:** Orange border (`rgba(220, 140, 40, 0.45)`), mono font, left-aligned
- **Buttons:** Blue accent for save, orange for verify
- **Verification badges:** Green "Verified" or red "Invalid key" pill-shaped badges
- **Fade-in animation:** 0.4s ease entrance

---

### Setup Flow Orchestration (Window.svelte)

The setup flow is orchestrated by Window.svelte, not by SetupWizard. Window manages all setup state and controls the flow:

#### Setup State (in Window.svelte)

| Variable | Type | Purpose |
|----------|------|---------|
| `setupWizardPhase` | `'welcome' \| 'creating' \| 'done' \| 'hidden'` | Controls SetupWizard overlay |
| `setupActive` | `boolean` | Whether setup mode is active in the main chat |
| `setupServiceStep` | `number` | Current service (0-3 = showing card, 4+ = done) |
| `setupShowServiceCard` | `boolean` | Whether ServiceCard is visible |
| `setupServicesSaved` | `string[]` | Services that were saved |
| `setupServicesSkipped` | `string[]` | Services that were skipped |
| `setupCreatedAgentName` | `string` | Agent name for creating/done overlays |
| `setupUserName` | `string` | User name from welcome screen |

#### InputBar Integration

During setup, Window passes props to InputBar:

- `onSubmit`: `setupSubmit` function (routes to `api.wizardInference` instead of normal inference)
- `disabled`: `true` while a service card is showing
- `placeholder`: Context-specific text ("Complete the setup above..." or "Describe who you want to create...")

The `setupSubmit` handler adds messages to the main Transcript, manages inference state, and checks each AI response for `AGENT_CONFIG` JSON blocks.

#### Audio Cues

| Event | Audio File |
|-------|-----------|
| Name entered | `name.mp3` |
| Opening text | `opening.mp3` |
| ElevenLabs saved | `elevenlabs_saved.mp3` |
| ElevenLabs skipped | `voice_farewell.mp3` |
| All services done | `service_complete.mp3` |
| Agent config detected | `voice_farewell.mp3` |

---

## CSS Theme (src/renderer/styles/global.css)

The global CSS file establishes the dark-only visual theme, typography, scrollbar styling, and interaction behaviors that apply to the entire renderer. There is no light mode - the application is designed exclusively for a monochrome dark aesthetic that blends with macOS's dark mode and the vibrancy-backed window. The file imports the Bricolage Grotesque font from Google Fonts as the primary sans-serif typeface, giving the UI a distinctive but readable character.

### CSS Custom Properties

All colours, spacing values, font stacks, and component dimensions are defined as CSS custom properties on `:root`. This centralization makes it easy to adjust the theme and ensures consistency across all components. The following code block shows the complete set of custom properties:

```css
:root {
  --bg: #0C0C0E;
  --bg-alt: #141418;
  --bg-input: rgba(20, 20, 22, 0.82);
  --text-primary: rgba(255, 255, 255, 0.85);
  --text-secondary: rgba(255, 255, 255, 0.5);
  --text-dim: rgba(255, 255, 255, 0.3);
  --text-user: rgba(180, 180, 180, 0.86);
  --text-companion: rgba(255, 255, 255, 0.86);
  --accent: rgba(100, 140, 255, 0.3);
  --accent-hover: rgba(100, 140, 255, 0.5);
  --border: rgba(255, 255, 255, 0.06);
  --border-hover: rgba(255, 255, 255, 0.15);
  --divider-green: rgba(120, 200, 120, 0.6);
  --shadow: rgba(0, 0, 0, 0.5);

  --font-sans: 'Bricolage Grotesque', -apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui, sans-serif;
  --font-mono: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;

  --pad: 24px;
  --bar-height: 48px;
  --bar-radius: 24px;
  --button-size: 34px;
}
```

The colour scheme uses extremely low-opacity whites for text and borders against a near-black background. This creates a high-contrast but soft appearance where text seems to glow against the dark surface. The three text tiers (primary at 85% opacity, secondary at 50%, dim at 30%) provide clear visual hierarchy. The accent colour (blue at 30%/50% opacity) is used sparingly for interactive elements and focus rings.

### Global Resets and Behaviour

The global styles establish several important behaviors that affect how the entire application interacts with the user. These rules are applied at the document level and set the foundation for all component-level styles:

- Universal box-sizing: `border-box` on all elements ensures padding and borders are included in width/height calculations.
- `html`, `body`, `#app`: full width/height with hidden overflow and transparent background. The transparency allows the macOS vibrancy effect to show through.
- Default `user-select: none` and `-webkit-app-region: drag` on body, making the entire window draggable by default and preventing text selection. This is critical for the frameless window design since there is no title bar to drag.
- Interactive elements (`input`, `textarea`, `button`, `a`, `[data-no-drag]`) get `-webkit-app-region: no-drag` to override the window drag behavior, ensuring clicks and typing work correctly.
- `.selectable` class overrides `user-select: text` for the transcript, allowing users to select and copy conversation text.
- Font smoothing: `-webkit-font-smoothing: antialiased` and `-moz-osx-font-smoothing: grayscale` for crisp text rendering on macOS.

### Scrollbar Styling

The application uses custom thin dark scrollbars that are visible but unobtrusive, matching the dark theme aesthetic:

- Width: 6px (much thinner than the default scrollbar).
- Track: transparent (no visible track background).
- Thumb: `rgba(255, 255, 255, 0.12)` with 3px border-radius for a rounded appearance.
- Thumb hover: `rgba(255, 255, 255, 0.2)` for a subtle brightness increase on interaction.

### Utility Classes

The stylesheet provides two utility classes used across multiple components:

- `.section-header`: 11px bold uppercase, 3px letter-spacing, `var(--text-dim)`, 12px bottom margin. Used in Settings.svelte and overlay components for section labels like "VOICE", "INFERENCE", "MEMORY".
- `.selectable`: enables text selection (`user-select: text`, `-webkit-user-select: text`). Applied to the transcript container so users can copy conversation text.

### Focus Ring

The `:focus-visible` pseudo-class applies a consistent focus ring across all focusable elements: 1px solid `var(--accent-hover)` outline with a 2px offset. This provides keyboard accessibility without showing focus rings on mouse clicks (the `:focus-visible` selector only applies when focus comes from keyboard navigation).

### Selection Colour

The `::selection` pseudo-element uses `rgba(100, 140, 255, 0.2)` as the background colour for selected text, providing a blue-tinted selection that matches the accent colour and looks natural against the dark theme.

---

## System Tray (src/main/index.ts)

In menu bar mode (`--app` flag), a system tray icon is created so the application can run as a background process with quick access from the macOS menu bar. The tray provides the primary way to show/hide the window when the dock icon is hidden. The tray uses a hand-crafted brain template image (`resources/icons/menubar_brain@2x.png`) that automatically adapts to macOS light/dark mode, maintaining a native feel regardless of the system appearance. If the brain icon file is not found at the expected path, a procedural orb icon is generated via `getTrayIcon()` as a fallback.

### Tray Menu

The tray's right-click context menu provides two simple actions. The following code shows the menu template used to build the tray context menu:

```typescript
Menu.buildFromTemplate([
  { label: 'Show', click: () => mainWindow.show() },
  { type: 'separator' },
  { label: 'Quit', click: () => app.quit() },
]);
```

Left-clicking the tray icon directly toggles the main window visibility (show/hide), providing the fastest way to access the conversation without opening a context menu.

### Not yet ported from Python

The Python tray has a richer set of menu items that are not yet present in the Electron version. These features represent the gap between the current implementation and full feature parity:

- **Chat** - toggle the floating chat overlay (the Electron version does not have a chat overlay; see the Chat Overlay section below).
- **Agents** - submenu listing all discovered agents for quick switching without opening the main window.
- **Set Away/Active** - toggle user presence status to signal the agent that the user is unavailable.

The tray icon state can be updated programmatically via `updateTrayState(state)` with values `active`, `muted`, `idle`, or `away`. However, this only applies when using the procedural orb fallback icon. The hand-crafted brain template image handles state differently through macOS's built-in template image rendering, which adjusts the icon's appearance based on the menu bar's current style.

## Chat Overlay

**Not yet ported.** The Python version has a `ChatPanel` - a floating 520x380 frameless, always-on-top panel triggered by Cmd+Shift+Space. It provides a lightweight text-only chat interface (no video avatar, no overlays) with a transcript and input bar, and is draggable to any position on screen. The chat overlay is designed for quick interactions when the full window is too heavy.

In the Electron version, Cmd+Shift+Space (in menu bar mode) simply shows/hides the main window rather than opening a separate chat overlay. Implementing the chat overlay would require creating a second BrowserWindow with its own component tree.

## Window Minimize and Close Behavior

The minimize and close behavior varies between the two application modes, reflecting different usage patterns. In GUI mode, the app behaves like a standard desktop application. In menu bar mode, it behaves like a background service with a toggleable interface.

- **GUI mode** (`--gui`): `minimizeWindow()` performs a standard native minimize to the dock. `closeWindow()` closes the window, and when all windows are closed on non-macOS platforms, the app quits. On macOS, the app stays running per platform convention, allowing the window to be reopened from the dock.
- **Menu bar mode** (`--app`): `closeWindow()` hides the window to the tray instead of closing it, keeping the agent running in the background. The dock icon is hidden (`app.dock.hide()`) so the app appears only in the menu bar.

**Not yet ported from Python:** The Python version intercepts Cmd+M and the yellow traffic light button to hide to tray instead of performing a native minimize. The Electron version does not intercept these system controls, so native minimize behavior applies even in menu bar mode.

## Shutdown Screen

**Not yet implemented.** The Python version has a shutdown screen that mirrors the boot screen but plays the brain animation in reverse (rotating from the final "cybernetic" frame back to the initial "organic" frame) with a faster pulse (3.0 Hz vs 2.0 Hz during boot) and a smaller brain icon (90px vs 110px). The shutdown screen provides a graceful visual closing that bookends the boot animation.

The Electron app currently closes immediately without a shutdown animation. The `AppPhase` type in the session store includes a `'shutdown'` value, but no component currently checks for it or renders shutdown-specific UI. Implementing the shutdown screen would involve reversing the brain frame sequence, playing the animation, and calling `app.quit()` after it completes.

## Preload API (src/preload/index.ts)

All communication between the renderer and main process flows through `contextBridge.exposeInMainWorld('atrophy', api)`. The preload script defines the typed `AtrophyAPI` interface that describes every available method, then implements each method as either an `ipcRenderer.invoke()` call (for request/response patterns) or a listener factory (for push events from the main process). This is the sole bridge between the two processes - no renderer code directly accesses Node.js APIs or Electron internals.

### Listener Pattern

All event listeners use a factory function that returns an unsubscribe callback. This pattern integrates cleanly with Svelte's `$effect` cleanup mechanism, where the cleanup function returned from an effect is called when the effect re-runs or the component unmounts. The following code shows the `createListener` factory:

```typescript
function createListener(channel: string) {
  return (cb: (...args: unknown[]) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, ...args: unknown[]) => cb(...args);
    ipcRenderer.on(channel, handler);
    return () => ipcRenderer.removeListener(channel, handler);
  };
}
```

Each listener function (e.g. `onTextDelta`, `onDone`, `onTtsStarted`) is created by calling `createListener` with the appropriate IPC channel name. The returned function accepts a callback, registers it on the channel, and returns an unsubscribe function. This enables clean teardown patterns like `const unsub = api.onTextDelta(handler); /* later */ unsub();`.

### API Surface

The preload API is organized into functional categories. The following table lists every category and its methods. Invoke methods return Promises (request/response via `ipcRenderer.invoke`), while listener methods accept callbacks and return unsubscribe functions (push events via `ipcRenderer.on`):

| Category | Methods |
|----------|---------|
| Inference | `sendMessage`, `stopInference`, `onTextDelta`, `onSentenceReady`, `onToolUse`, `onDone`, `onCompacting`, `onError` |
| Audio | `startRecording`, `stopRecording`, `sendAudioChunk` |
| TTS | `onTtsStarted`, `onTtsDone`, `onTtsQueueEmpty` |
| Wake word | `onWakeWordStart`, `onWakeWordStop`, `sendWakeWordChunk` |
| Agents | `switchAgent`, `getAgents`, `getAgentsFull` |
| Config | `getConfig`, `updateConfig`, `saveSecret` |
| Setup | `needsSetup`, `wizardInference`, `createAgent` |
| Window | `toggleFullscreen`, `minimizeWindow`, `closeWindow` |
| Avatar | `getAvatarVideoPath` |
| Updates | `checkForUpdates`, `downloadUpdate`, `quitAndInstall`, `onUpdate*` |
| Deferral | `completeDeferral`, `on('deferral:request', cb)` |
| Canvas | `on('canvas:updated', cb)` |
| Artefact | `getArtefactGallery`, `getArtefactContent`, `onArtefactLoading`, `on('artefact:updated', cb)` |
| Inline Artifacts | `onArtifact` |
| Ask-User | `onAskUser`, `respondToAsk` |
| Queues | `drainAgentQueue`, `drainAllAgentQueues`, `onQueueMessage` |
| Other | `getOpeningLine`, `isLoginItemEnabled`, `toggleLoginItem`, `getUsage`, `getActivity` |

### Generic Event Listener

In addition to the typed listener functions, an `api.on(channel, callback)` method is available for arbitrary IPC events. This returns an unsubscribe function following the same pattern as the typed listeners. It is used by Window.svelte for `deferral:request`, `canvas:updated`, `artefact:updated`, `artefact:loading`, and `ask:request` events, by Canvas.svelte for `canvas:updated`, and by Artefact.svelte for `artefact:updated` and `artefact:loading`. The generic listener exists because some IPC events are consumed by components that mount conditionally (like Canvas and Artefact overlays), and having a generic method avoids needing to pre-register typed listeners for every possible event.

The channel allowlist in the preload's `on()` method includes: `inference:textDelta`, `inference:sentenceReady`, `inference:toolUse`, `inference:done`, `inference:compacting`, `inference:error`, `inference:artifact`, `tts:started`, `tts:done`, `tts:queueEmpty`, `wakeword:start`, `wakeword:stop`, `queue:message`, `deferral:request`, `updater:*`, `canvas:updated`, `artefact:updated`, `artefact:loading`, `ask:request`, `avatar:download-*`, `mirror:avatarProgress`, and `app:shutdownRequested`.
