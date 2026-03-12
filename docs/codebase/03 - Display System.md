# Display System

The GUI provides a frameless Electron BrowserWindow with Svelte 5 components, vibrancy effects, and a dark theme. All rendering happens in the renderer process using Svelte 5 runes for reactive state.

## Entry Point (src/renderer/main.ts)

The renderer entry point imports the global CSS, then mounts the root `App.svelte` component onto the `#app` DOM element using Svelte 5's `mount()` function:

```typescript
import './styles/global.css';
import App from './App.svelte';
import { mount } from 'svelte';

const app = mount(App, {
  target: document.getElementById('app')!,
});
```

## Root Component (src/renderer/App.svelte)

`App.svelte` is a thin bootstrap layer. It imports `Window.svelte` and renders it as the sole child. On script initialization (not in `onMount` - runs synchronously during component creation), it calls the preload API to load config and populate stores:

- Calls `api.getConfig()` and `api.getAgents()` in sequence
- Populates `settings` store: `userName`, `version`, `avatarEnabled`, `ttsBackend`, `inputMode`, `loaded`
- Populates `agents` store: `current`, `displayName`, `list`
- Sets `session.phase = 'boot'`

This runs before Window.svelte's `onMount`, so stores are populated by the time the boot sequence begins.

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
```

---

## Reactive Stores (src/renderer/stores/)

All stores use Svelte 5's module-level `$state` rune pattern - exported reactive objects that can be imported and mutated from any component.

### session.svelte.ts

Tracks application lifecycle and inference state.

**Exported types:**

- `AppPhase` - `'boot' | 'setup' | 'ready' | 'shutdown'`
- `InferenceState` - `'idle' | 'thinking' | 'streaming' | 'compacting'`

**Exported state:**

```typescript
export const session = $state({
  phase: 'boot' as AppPhase,
  inferenceState: 'idle' as InferenceState,
  isRecording: false,
  idleSeconds: 0,
});
```

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `phase` | `AppPhase` | `'boot'` | Current app lifecycle phase |
| `inferenceState` | `InferenceState` | `'idle'` | Current inference state; drives ThinkingIndicator visibility and InputBar disable state |
| `isRecording` | `boolean` | `false` | Whether push-to-talk recording is active |
| `idleSeconds` | `number` | `0` | Seconds since last user interaction |

### transcript.svelte.ts

Message history for the conversation display.

**Exported interface:**

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

**Exported state:**

```typescript
export const transcript = $state({
  messages: [] as Message[],
  autoScroll: true,
});
```

**Exported functions:**

| Function | Signature | Behaviour |
|----------|-----------|-----------|
| `addMessage` | `(role, content) => Message` | Creates a new message. User messages and dividers are immediately complete with full reveal. Agent messages start with `revealed: 0` and `complete: false` |
| `appendToLast` | `(text) => void` | Appends text to the last message's `content` if it is an incomplete agent message |
| `completeLast` | `() => void` | Marks the last message as complete and sets `revealed` to full content length |
| `addDivider` | `(text) => void` | Shorthand for `addMessage('divider', text)` |
| `clearTranscript` | `() => void` | Empties the messages array |

### agents.svelte.ts

Agent list and switching state.

```typescript
export const agents = $state({
  list: [] as string[],    // agent directory names
  current: '',             // currently active agent name
  displayName: '',         // human-readable display name
  switchDirection: 0,      // -1 up, +1 down, 0 none (drives rolodex animation)
});
```

### audio.svelte.ts

TTS playback queue state.

```typescript
export const audio = $state({
  queue: [] as string[],   // file paths of pending audio
  isPlaying: false,        // true while any TTS audio is playing
  vignetteOpacity: 0,      // 0.0-0.15, drives the warm vignette overlay
});
```

### settings.svelte.ts

Config values mirrored from the main process.

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

### emotional-state.svelte.ts

Inner life / emotional state - mirrors the agent's current feelings.

**Exported interfaces:**

```typescript
interface EmotionalState {
  connection: number;   // 0.0-1.0
  curiosity: number;
  confidence: number;
  warmth: number;
  frustration: number;
  playfulness: number;
}

interface TrustState {
  emotional: number;    // 0.0-1.0
  intellectual: number;
  creative: number;
  practical: number;
}
```

**Exported state:**

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

These values are used by `OrbAvatar.svelte` to compute the orb's hue, saturation, and lightness.

### emotion-colours.svelte.ts

Emotion-to-colour mapping for the orb avatar. Ported from `source_repo/display/emotion_colour.py`.

**Colour palette (HSL):**

| Name | H | S | L |
|------|---|---|---|
| `blue` (default) | 220 | 50 | 20 |
| `dark_blue` | 230 | 40 | 15 |
| `red` | 0 | 60 | 25 |
| `green` | 140 | 45 | 22 |
| `orange` | 30 | 55 | 25 |
| `purple` | 270 | 45 | 22 |

**Emotion definitions:**

| Emotion | Colour | Clip Name | Keywords |
|---------|--------|-----------|----------|
| `thinking` | dark_blue | `idle_hover` | (none - triggered programmatically during inference) |
| `alert` | red | `pulse_intense` | warning, danger, urgent, critical, alert, immediately, stop, protect, threat, security, compromised, breach, emergency, do not, must not, cannot allow |
| `frustrated` | red | `itch` | error, failed, broken, crash, bug, wrong, problem, issue, unfortunately, unable, can't, won't work, frustrat, damn, annoying |
| `positive` | green | `drift_close` | done, complete, success, great, excellent, good, ready, confirmed, yes, perfect, resolved, fixed, healthy, growing, progress, well done, nice, happy, glad, proud, love |
| `cautious` | orange | `drift_lateral` | note, caution, cost, price, pay, spend, budget, careful, watch out, heads up, fyi, worth noting, trade-off, consider, maybe, possibly, suggest, however, but, although, risk |
| `reflective` | purple | `crystal_shimmer` | interesting, philosophical, wonder, meaning, think about, reflects, deeper, perspective, soul, evolve, growth, remember when, looking back, pattern, insight, curious, fascinating, profound, existential, beautiful, strange |

**Classifier algorithm (`classifyEmotion`):**

For each emotion type, scans the lowercased text for all keywords. Each keyword hit scores `count * (1 + keyword.length / 10)`, weighting longer (more specific) phrases higher. The emotion with the highest score wins, but only if the score exceeds the minimum threshold of 2.0.

**Exported reactive state:**

```typescript
export const activeEmotion = $state<{ type: EmotionType | null; colour: HSLColour }>({
  type: null,
  colour: DEFAULT_COLOUR,  // blue { h: 220, s: 50, l: 20 }
});
```

**Exported functions:**

| Function | Purpose |
|----------|---------|
| `classifyEmotion(text)` | Returns best-matching `EmotionType` or null |
| `getReaction(emotion)` | Returns `{ colour, clip }` for an emotion type |
| `setEmotionFromText(text)` | Classifies text and sets active emotion if match found |
| `setEmotion(emotion)` | Sets a specific emotion directly (e.g. 'thinking' during inference) |
| `revertToDefault()` | Immediately revert to default blue colour |
| `getClipPath(colour, clip, agentName)` | Build avatar video file path |
| `getDefaultLoop(agentName)` | Get the default ambient loop path |

**Revert timer:** After any emotion is set, a `setTimeout` of 12,000ms (`REVERT_TIMEOUT_MS`) automatically reverts to the default colour.

---

## Component Reference

### Window.svelte - Main Orchestrator

**File:** `src/renderer/components/Window.svelte`

The root layout component. Manages boot sequence, overlay coordination, agent switching, silence timer, deferral handling, voice call mode, wake word, and keyboard shortcuts.

**Imports:** `OrbAvatar`, `AgentName`, `ThinkingIndicator`, `Transcript`, `InputBar`, `Timer`, `Canvas`, `Artefact`, `Settings`, `SetupWizard`, plus stores `session`, `audio`, `agents`, and transcript functions `addMessage`/`completeLast`.

#### Props

None. This is the top-level layout component.

#### Reactive State ($state)

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

#### Boot Sequence

1. Load config and agent list from main process via IPC (`getConfig()`, `getAgents()`)
2. Check `needsSetup()` - if true, fade out boot overlay and show SetupWizard
3. If no setup needed, fetch opening line via `getOpeningLine()` IPC
4. Add opening line to transcript with character reveal animation
5. Fade out boot overlay (1.5s CSS transition on opacity)

The boot overlay is a `position: fixed` black div at `z-index: 9999` that transitions from opacity 1 to 0, with a subtle "connecting..." label (13px, 2px letter-spacing, lowercase) during load. A guard variable `bootRan` prevents duplicate execution.

#### Opening Line

The opening line displayed on launch comes from the `OPENING_LINE` field in the agent's `agent.json`. The main process handler (`opening:get`) returns this value directly, falling back to `"Ready. Where are we?"` if unset.

Unlike the Python version (which generates dynamic openings via inference with randomised style directives), the Electron version currently reads a static opening line from config. Dynamic opening generation with style directives (question, observation, tease, admission, etc.) is not yet ported.

The opening line is configurable in Settings > Agent Identity.

#### Overlay Layer Stack (z-index)

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

Overlays are conditionally rendered via `{#if}` blocks and dismissed via Escape in priority order: settings -> artefact -> canvas -> timer -> silence prompt.

#### Agent Switch Animation

When switching agents (via Cmd+Up/Down or the AgentName chevrons), a clip-path circle transition expands from centre:

```typescript
agentSwitchClip = 'circle(0% at 50% 50%)';
requestAnimationFrame(() => {
  agentSwitchClip = 'circle(150% at 50% 50%)';
});
```

The overlay uses a 0.65s `cubic-bezier(0.4, 0, 0.2, 1)` CSS transition on `clip-path`. Background colour is `var(--bg)`. Cleans up after 700ms via `setTimeout`. The agent name updates via rolodex animation in AgentName.svelte.

The `cycleAgent(direction)` function calculates the next agent index with wrapping: `(idx + direction + list.length) % list.length`. It calls `api.switchAgent(next)` and updates `agents.current`, `agents.displayName`, and sets `agents.switchDirection` for the rolodex animation.

#### Agent Deferral (Codec-Style Handoff)

When one agent defers to another (triggered by `deferral:request` IPC event from main process), an iris wipe animation plays:

1. Stop ongoing inference via `api.stopInference()`
2. Clear audio queue via `api.clearAudioQueue()`
3. Set `deferralProgress = 0`, then `requestAnimationFrame` to set it to `1`
4. Iris close - clip-path circle shrinks from 150% to 0% (0.25s cubic-bezier transition)
5. At 250ms, call `api.completeDeferral(data)` to switch agents in main process
6. Update renderer agent state (`agents.current`, `agents.displayName`)
7. Set `deferralProgress = 2` - iris open (circle expands back to 150%)
8. Clean up after 300ms

The "Handing off to {target}..." label (14px, 0.7 opacity, `var(--text-secondary)`) appears during the black frame when `deferralProgress === 1`.

#### Silence Timer

A 5-minute (`SILENCE_TIMEOUT_MS = 300000`) idle timer that shows a subtle "Still here?" prompt above the input bar. The timer resets on any keypress or mouse movement (via `svelte:window` event bindings for `onkeydown` and `onmousemove`). Clicking the prompt dismisses it and resets the timer. The prompt fades in with a `silenceFadeIn` animation (1.5s ease, translates 6px up from offset).

#### Warm Vignette

A radial gradient overlay (`.vignette`) that covers the full window:

```css
background: radial-gradient(
  ellipse at center,
  transparent 30%,
  rgba(40, 25, 10, 0.47) 100%
);
```

Fades in during TTS audio playback via `transition: opacity 0.8s ease`. Opacity driven by `audio.vignetteOpacity` (set to 0.15 when TTS starts, 0 when queue empties).

#### Wake Word Audio Capture

When `wakeListening` is toggled on:
1. Calls `navigator.mediaDevices.getUserMedia()` with `sampleRate: 16000`, `channelCount: 1`, `echoCancellation: true`
2. Creates an `AudioContext` at 16kHz
3. Creates a `ScriptProcessorNode` with 4096-sample buffer
4. On each audio process event, sends chunk to main via `api.sendWakeWordChunk(data.buffer.slice(0))`

Teardown on toggle off: disconnects processor, closes AudioContext, stops all MediaStream tracks.

#### Voice Call Mode

Continuous record/transcribe/send/TTS loop with voice activity detection (VAD):

**Constants:**
- `CALL_ENERGY_THRESHOLD = 0.015` - RMS energy threshold for speech detection
- `CALL_SILENCE_FRAMES = 15` - ~3.8 seconds of silence before utterance end (`15 * 4096/16000`)
- `CALL_MIN_CHUNKS = 4` - minimum audio chunks before processing

**Algorithm:**
1. Opens mic at 16kHz mono (with echoCancellation false, noiseSuppression false, autoGainControl false to avoid Chromium voice processing)
2. ScriptProcessor calculates RMS energy per 4096-sample buffer
3. If energy exceeds threshold, marks speech started, resets silence counter, accumulates chunks
4. If energy below threshold and speech started, increments silence counter
5. When silence exceeds `CALL_SILENCE_FRAMES` and enough chunks accumulated, sends merged Float32Array for STT
6. On successful transcription, adds user message and sends via `api.sendMessage()`

#### Mode Buttons

A row of icon buttons in the top-right corner (`position: absolute; top: 14px; right: var(--pad)`), ordered left-to-right:

| Button | Icon | State class | Behaviour |
|--------|------|-------------|-----------|
| Eye | Eye shape (slash when hidden) | `.active` when hidden | Toggles `avatarVisible` |
| Mute | Speaker with waves (X when muted) | `.active` when muted | Toggles `isMuted` |
| Wake | Microphone | `.wake-active` | Toggles wake word listener. Green colour (`rgba(120, 255, 140, 0.9)`) with green background (`rgba(30, 80, 40, 0.82)`) |
| Call | Phone icon | `.active` | Toggles voice call mode |
| Artefact | Document icon | - | Opens artefact overlay. Blue badge dot (6px, `rgba(100, 180, 255, 0.88)`) when `hasNewArtefacts` is true |
| Timer | Clock icon | - | Opens timer overlay |
| Minimize | Horizontal line | - | Calls `api.minimizeWindow()` |
| Settings | Gear icon | `.active` | Opens settings overlay |

All buttons are `var(--button-size)` (34px) with `border-radius: 8px`, transparent background, `var(--text-dim)` colour. Hover: `var(--text-secondary)` with `rgba(255, 255, 255, 0.04)` background. Active: `var(--text-primary)` with `rgba(40, 40, 50, 0.82)` background.

#### Keyboard Shortcuts

| Shortcut | Action | Handler |
|----------|--------|---------|
| Cmd+, | Toggle settings panel | `showSettings = !showSettings` |
| Cmd+Shift+W | Toggle wake word detection | `toggleWake()` |
| Cmd+K | Toggle canvas overlay | `showCanvas = !showCanvas` |
| Cmd+E | Toggle eye mode (hide transcript) | `eyeMode = !eyeMode` |
| Cmd+Up | Cycle to previous agent | `cycleAgent(-1)` |
| Cmd+Down | Cycle to next agent | `cycleAgent(1)` |
| Ctrl (hold) | Push-to-talk recording | Handled in InputBar.svelte |
| Escape | Close overlays in priority order | Closes first open: settings -> artefact -> canvas -> timer -> silence prompt |

All shortcuts also reset the silence timer.

#### IPC Channels Used

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

- **onMount:** Runs boot sequence, starts silence timer, registers IPC listeners for deferral requests and canvas updates
- **onDestroy:** Clears silence timer, cleans up agent switch callback, disconnects and closes all audio resources (wake word and call mode separately)

#### Layout CSS

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

The `.top-bar` uses `padding-top: 36px` to account for the macOS title bar inset area (traffic lights hidden at x:-100, y:-100 but area still present for drag region).

---

### Transcript.svelte - Message Display

**File:** `src/renderer/components/Transcript.svelte`

Displays the conversation history with character-by-character reveal animation for agent messages and a custom markdown renderer.

#### Props

None. Reads directly from the `transcript` store.

#### Reactive State ($state)

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `copiedBlockId` | `string \| null` | `null` | ID of the code block whose "Copy" button was just clicked |
| `now` | `number` | `Date.now()` | Current timestamp, updated every 30s for relative time display |

#### Other Instance Variables

| Variable | Type | Purpose |
|----------|------|---------|
| `container` | `HTMLDivElement` | Bound reference to the scroll container |
| `revealTimers` | `Map<number, interval>` | Active character reveal timers keyed by message ID |
| `codeBlockCounter` | `number` | Auto-incrementing ID for rendered code blocks |
| `timestampTimer` | `interval` | 30-second interval for updating `now` |

#### Reveal Animation

Agent messages start with `revealed: 0` and animate characters at 8 chars per 25ms tick:

```typescript
const REVEAL_RATE = 8;     // characters per tick
const REVEAL_INTERVAL = 25; // milliseconds between ticks
```

A `setInterval` timer increments `msg.revealed` until it reaches `msg.content.length`. When complete, the interval is cleared and removed from the `revealTimers` map. User messages and dividers are immediately fully revealed (set at creation time in the store).

#### Display Filtering (`displayText`)

Before rendering, message text is cleaned by slicing to the `revealed` count, then:
- Prosody tags (`[word_tag]`) are stripped via regex `/\[[\w_]+\]/g`
- Audio tags (`<audio>...</audio>`) are removed via `/\<audio[^>]*>.*?<\/audio>/gs`
- Multiple consecutive spaces are collapsed to single spaces
- Leading/trailing whitespace is trimmed

#### Markdown Renderer (`renderMarkdown`)

A custom markdown-to-HTML renderer that handles:

1. **Fenced code blocks** - extracted first with `\`\`\`lang\n...\`\`\`` regex, replaced with null-byte placeholders to protect from other processing. Rendered as `.code-block-wrapper` divs with language label and copy button.
2. **HTML escaping** - all remaining text is escaped (`&`, `<`, `>`, `"`)
3. **Inline code** - `` `text` `` rendered as `<code class="inline-code">`
4. **Bold** - `**text**` rendered as `<strong>`
5. **Italic** - `*text*` rendered as `<em>`
6. **Links** - `[text](url)` rendered as `<a class="md-link" target="_blank">`
7. **Bare URLs** - `https://...` auto-linked (except when already inside href)
8. **Headers** - `#` through `######` rendered as `<h1>` through `<h6>` with classes `md-header md-hN`
9. **Blockquotes** - `>` lines rendered as `<blockquote class="md-blockquote">`
10. **Unordered lists** - `-` or `*` items wrapped in `<ul class="md-list">`
11. **Ordered lists** - `1.` items wrapped in `<ul class="md-list md-ol">` (uses `list-style-type: decimal`)

User messages only get HTML escaping and bare URL linkification (no full markdown).

#### Code Block Copy

Each code block renders a "Copy" button with a `data-copy-target` attribute matching the block ID. Clicking calls `navigator.clipboard.writeText()` and temporarily changes the button text to "Copied" for 1.5 seconds. The copy button text update is driven by a `$effect` that scans all `.copy-btn` elements in the container.

#### Auto-Scroll

Scrolls to bottom after each `tick()` when `transcript.autoScroll` is true. Auto-scroll is disabled when the user scrolls up (detected by `onScroll` handler checking if scroll position is more than 40px from the bottom). Re-enabled when the user scrolls back to the bottom.

#### Relative Timestamps

Each message shows a relative timestamp (`just now`, `Xs ago`, `Xm ago`, `Xh ago`, or short time format for 24h+). Timestamps are hidden by default (`opacity: 0`) and shown on message hover (`opacity: 1`) with a 0.2s transition. The `now` variable updates every 30 seconds to keep timestamps current.

#### Message Styling

| Role | Text Colour | Spacing |
|------|-------------|---------|
| `user` | `var(--text-user)` - `rgba(180, 180, 180, 0.86)` | 24px margin above when following agent |
| `agent` | `var(--text-companion)` - `rgba(255, 255, 255, 0.86)` | 24px margin above when following user |
| `divider` | `var(--divider-green)` - `rgba(120, 200, 120, 0.6)` | Centered, 11px bold uppercase, 3px letter-spacing, green top/bottom borders |

All message text: 14px `var(--font-sans)`, line-height 1.65, `pre-wrap` whitespace, `break-word`, text-shadow `1px 1px 2px rgba(0, 0, 0, 0.5)`.

#### Code Block Styling

- **Wrapper:** `border-radius: 6px`, `border: 1px solid var(--border)`, `background: rgba(0, 0, 0, 0.35)`
- **Header:** flex row with language label (10px uppercase mono) and copy button, `background: rgba(255, 255, 255, 0.04)`, bottom border
- **Code body:** `font-family: var(--font-mono)`, 12.5px, line-height 1.5, `padding: 10px 12px`, horizontal scroll
- **Inline code:** 12.5px mono, `background: var(--bg-secondary)`, 3px border-radius, 1px border

#### Markdown Element Styling

- **Headers:** h1: 18px, h2: 16px, h3: 15px, h4-h6: 14px. Margin `12px 0 4px`, `var(--text-primary)` colour
- **Blockquotes:** 3px left border `var(--border)`, 12px left padding, italic, `var(--text-secondary)` colour
- **Lists:** 20px left padding, 4px top/bottom margin, 2px item spacing
- **Links:** `var(--accent-hover)` colour, transparent bottom border that shows on hover
- **Bold:** font-weight 600, `var(--text-primary)` colour

#### Layout

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

The transcript has the `.selectable` class for text selection and `data-no-drag` to prevent window dragging.

#### Lifecycle

- **onMount:** Starts 30-second timestamp update interval. Returns cleanup function that clears all reveal timers and the timestamp interval.
- **$effect (messages):** Watches `transcript.messages`. When the last message is an incomplete agent message, starts its reveal animation. Calls `scrollToBottom()` on every change.
- **$effect (copiedBlockId):** Updates all `.copy-btn` text content reactively based on which block was just copied.

---

### InputBar.svelte - Text Input and Recording

**File:** `src/renderer/components/InputBar.svelte`

Floating input bar at the bottom of the window with text input, mic button, and send/stop button.

#### Props

None. Reads from `session` and `transcript` stores. Accesses `window.atrophy` API directly.

#### Reactive State ($state)

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `inputText` | `string` | `''` | Current text input value |
| `isRecording` | `boolean` | `false` | Push-to-talk recording active |

#### Derived State ($derived)

| Variable | Expression | Purpose |
|----------|------------|---------|
| `isActive` | `session.inferenceState !== 'idle'` | Disables input, shows stop button |

#### Other Instance Variables

| Variable | Type | Purpose |
|----------|------|---------|
| `inputEl` | `HTMLInputElement` | Bound reference to input element |
| `mediaStream` | `MediaStream \| null` | Active mic stream |
| `audioContext` | `AudioContext \| null` | Audio processing context |
| `workletNode` | `AudioWorkletNode \| ScriptProcessorNode \| null` | Audio processor node |
| `lastSound` | `number` | Timestamp of last keystroke sound |

#### Keystroke Sound

Plays macOS Tink sound (`/System/Library/Sounds/Tink.aiff`) at 0.02 volume on each character keypress. Throttled to 60ms minimum interval. Only plays for single-character keys (not Cmd, Ctrl, etc.).

#### Submit Flow

1. Trim input text, return if empty
2. Clear input field
3. Add user message to transcript (`addMessage('user', text)`)
4. Add empty agent message (`addMessage('agent', '')`) as placeholder for streaming
5. Set `session.inferenceState = 'thinking'`
6. Call `api.sendMessage(text)`
7. On error: `completeLast()` and reset to idle

#### Push-to-Talk Recording

**Audio capture setup (16kHz mono):**
- All three Chromium audio processing flags (`echoCancellation`, `noiseSuppression`, `autoGainControl`) set to `false` to prevent Chromium from switching macOS to "voice processing" audio mode, which downsamples all system audio to 16kHz
- Uses `ScriptProcessorNode` with 4096-sample buffer (wider browser support than AudioWorklet)
- Sends chunks to main process via `api.sendAudioChunk(buffer)` as `ArrayBuffer`

**Ctrl key push-to-talk:**
- Global `keydown` on `'Control'` starts recording (only when idle and not already recording)
- Global `keyup` on `'Control'` stops recording
- On stop: calls `api.stopRecording()` for transcription, then auto-submits non-empty result

**Mic button hold-to-record:**
- `mousedown` on mic button starts recording
- `mouseup` stops recording
- Same flow as Ctrl push-to-talk

#### Streaming Listener Setup ($effect)

The InputBar wires up all inference streaming listeners in a `$effect` that runs once on mount and returns cleanup:

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

Cleanup removes all IPC listeners and keyboard event listeners.

#### Layout and Styling

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

- **Input field:** flex: 1, 14px font, `padding: 0 20px` with 90px right padding to accommodate buttons
- **Mic button:** 36px circle, `position: absolute`, `right: calc(var(--pad) + 44px)`. Recording state: red colour (`rgba(255, 80, 80, 0.9)`) with `pulse-mic` animation (1s ease-in-out infinite opacity 0.6-1.0)
- **Action button:** 36px circle, `position: absolute`, `right: calc(var(--pad) + 6px)`. Normal: `rgba(255, 255, 255, 0.16)` background. Active (during inference): bright white background (`rgba(255, 255, 255, 0.78)`) with dark icon
- **Recording state:** Input bar border turns red (`rgba(255, 80, 80, 0.5)`), placeholder changes to "Listening..."
- **Focus state:** Border changes to `var(--border-hover)` - `rgba(255, 255, 255, 0.15)`

---

### OrbAvatar.svelte - Avatar Display

**File:** `src/renderer/components/OrbAvatar.svelte`

Video playback with procedural canvas orb fallback.

#### Props

None. Reads from `session`, `emotionalState`, and `activeEmotion` stores.

#### Reactive State ($state)

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `videoSrc` | `string` | `''` | `file://` URL to avatar video |
| `videoReady` | `boolean` | `false` | Video loaded and playing |
| `videoError` | `boolean` | `false` | Video failed to load |

#### Other Instance Variables

| Variable | Type | Purpose |
|----------|------|---------|
| `canvas` | `HTMLCanvasElement` | Canvas element reference |
| `ctx` | `CanvasRenderingContext2D` | Canvas 2D context |
| `time` | `number` | Animation time counter (increments by 0.016 per frame) |
| `animFrame` | `number` | `requestAnimationFrame` handle |
| `blendFactor` | `number` | Smooth blend toward emotion colour (0-1) |
| `videoEl` | `HTMLVideoElement` | Video element reference |

#### Video Layer

Loads avatar video clips from the agent's avatar directory via `api.getAvatarVideoPath(colour, clip)` IPC. Default request is `loadVideo('blue', 'bounce_playful')`. Videos play looped, muted, and full-bleed (`object-fit: cover`). Fades in over 0.8s CSS transition when `canplay` event fires.

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

Rendered when video is unavailable. Uses Canvas 2D API with DPR-aware scaling (`window.devicePixelRatio`).

**Colour computation (`orbColor()`):**

Base colour derived from emotional state:
- Hue: `220 + (warmth - 0.5) * -40 + (playfulness - 0.3) * 20`
- Saturation: `40 + connection * 30`
- Lightness: `15 + warmth * 10`
- Frustration shift (when > 0.3): hue += `(frustration - 0.3) * 100`, saturation += `frustration * 20`

When an emotion reaction is active (`activeEmotion.type !== null`), `blendFactor` smoothly ramps toward 1.0 at `BLEND_SPEED = 0.04` per frame. The orb HSL values are linearly interpolated toward the emotion's HSL colour by `blendFactor`.

**Rendering layers (drawn back to front):**

1. **Glow layers** - 4 concentric radial gradients (i=3 down to 0), each at `r * (1 + i * 0.5)` radius with alpha `0.04 - i * 0.008`
2. **Core gradient** - offset radial gradient (`cx - r*0.2, cy - r*0.2` origin) with three colour stops: bright centre at 0%, mid at 50%, dark edge at 100%
3. **Highlight** - small bright spot at `cx - r*0.15, cy - r*0.2` with radius `r * 0.4`, 12% white at centre
4. **Particles** - 5 ambient (12 when thinking) orbiting points. Each particle has angle `(time*0.3 + i*TAU/count)`, distance `r * (1.2 + sin(time*0.5+i)*0.4)`, alpha `0.08 + sin(time+i*2)*0.04`, radius `1 + sin(time*2+i)*0.5`

**Breathing animation:**
- Idle: `breathRate = 1.2`, `breathAmp = 0.03` (3% radius variation)
- Thinking: `breathRate = 4.0`, `breathAmp = 0.06` (6% radius variation)
- Base radius: `min(canvasWidth, canvasHeight) * 0.18`

**Canvas setup:**
- DPR-scaled: `canvas.width = rect.width * devicePixelRatio`
- `ctx.scale(dpr, dpr)` for correct rendering
- Animation runs at display refresh rate via `requestAnimationFrame`

#### Lifecycle

- **onMount:** Calls `loadVideo()`. If video not ready, calls `initCanvas()` to start procedural fallback. Returns cleanup that cancels animation frame.

---

### AgentName.svelte - Agent Name Display

**File:** `src/renderer/components/AgentName.svelte`

Top-left agent name with rolodex-style switching animation and up/down chevrons for cycling.

#### Props ($props)

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `name` | `string` | required | Current agent display name |
| `direction` | `number` | required | Animation direction (-1 up, +1 down) |
| `canCycle` | `boolean` | `true` | Whether to show up/down chevrons |
| `onCycleUp` | `() => void` | required | Callback for cycling to previous agent |
| `onCycleDown` | `() => void` | required | Callback for cycling to next agent |

#### Reactive State ($state)

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `displayName` | `string` | `''` | Currently displayed name (may differ from `name` during animation) |
| `offset` | `number` | `0` | Vertical pixel offset for rolodex animation |
| `animating` | `boolean` | `false` | Whether animation is in progress |

#### Rolodex Animation

When `name` prop changes and not already animating:
1. Set `offset` to `+30` (direction > 0) or `-30` (direction < 0)
2. Run a 400ms `requestAnimationFrame` loop with ease-out cubic easing: `1 - (1-t)^3`
3. At 50% progress, swap `displayName` to the new `name`
4. Animate `offset` from starting value to 0
5. Set `animating = false` on completion

The name text uses `transform: translateY({offset}px)` within a 30px-tall clipped container (`.name-clip`).

#### Chevrons

Up/down chevron buttons (14px SVG) appear on hover of the `.agent-name` container. Hidden by default (`opacity: 0`) with 0.2s transition. Colours: `var(--text-dim)` default, `var(--text-secondary)` on hover.

#### Styling

- Container: `width: 250px`, flex column
- Name text: 20px bold uppercase, 1px letter-spacing, `rgba(255, 255, 255, 0.78)`, text-shadow `0 1px 3px rgba(0, 0, 0, 0.4)`, `white-space: nowrap`, `will-change: transform`
- Clip: `height: 30px`, `overflow: hidden`
- `data-no-drag` attribute prevents window dragging from this area

---

### ThinkingIndicator.svelte - Inference Status

**File:** `src/renderer/components/ThinkingIndicator.svelte`

A pulsing brain SVG icon displayed next to the agent name during inference.

#### Props

None.

#### Reactive State ($state)

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `opacity` | `number` | `0.25` | Current opacity of the brain icon |

#### Animation

Uses `setInterval` at 50ms. Each tick increments a `frame` counter and computes opacity as:

```typescript
opacity = 0.25 + 0.55 * Math.sin(frame * 0.15);
```

This produces a smooth sine wave oscillation between 0.25 and 0.80 at approximately 3 Hz. The `will-change: opacity` CSS hint is set for performance.

#### Visibility

Shown in Window.svelte when `session.inferenceState !== 'idle'` (covers thinking, streaming, and compacting states). Conditionally rendered via `{#if}`.

#### Styling

- Container: flex, `color: var(--text-secondary)`, `margin-left: 4px`, `margin-top: 3px`
- SVG: 20x20px brain icon, `stroke-width: 1.5`, `fill: none`

#### Lifecycle

- **onMount:** Starts the 50ms interval. Returns cleanup function that clears it.

---

### Timer.svelte - Countdown Timer

**File:** `src/renderer/components/Timer.svelte`

A draggable floating overlay for countdown timers with alarm functionality.

#### Props ($props)

| Prop | Type | Description |
|------|------|-------------|
| `onClose` | `() => void` | Callback to dismiss the timer |

#### Reactive State ($state)

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `endTime` | `number` | `0` | `Date.now()` timestamp when timer expires |
| `totalSeconds` | `number` | `0` | Displayed remaining seconds |
| `running` | `boolean` | `false` | Timer actively counting |
| `paused` | `boolean` | `false` | Timer paused |
| `pauseRemaining` | `number` | `0` | Seconds remaining when paused |
| `done` | `boolean` | `false` | Timer reached zero |
| `alarming` | `boolean` | `false` | Alarm currently sounding |
| `dragging` | `boolean` | `false` | Currently being dragged |
| `posRight` | `number` | `20` | Right offset in pixels |
| `posTop` | `number` | `80` | Top offset in pixels |
| `posMode` | `'right' \| 'left'` | `'right'` | Positioning mode (switches to left on first drag) |
| `posLeft` | `number` | `0` | Left offset (used after first drag) |
| `timerColor` | `string` | `'rgba(255, 180, 100, 0.9)'` | Current display colour |
| `timerShadow` | `string` | `'0 0 40px rgba(255, 140, 50, 0.2)'` | Current text-shadow |

#### Timing

Uses `setInterval` at 100ms for smooth display updates. Remaining time computed as `(endTime - Date.now()) / 1000` for drift-free countdown based on monotonic clock deltas.

**Display format:** `m:ss` for durations under 1 hour, `h:mm:ss` for longer durations.

#### Colour Gradient

In the final 10 seconds, colour shifts progressively from amber to red:
- Green channel: 180 -> 40
- Blue channel: 100 -> 20
- Shadow glow intensifies from 0.2 to 0.5 opacity

At zero: `rgba(255, 100, 100, 0.9)` with `0 0 40px rgba(255, 60, 60, 0.4)` shadow.

#### Alarm

When timer reaches zero:
1. Plays Glass.aiff system sound 6 times with 1.5s spacing (`setTimeout` chain)
2. Fires a macOS notification via `Notification` API ("Timer complete" / "Your timer has finished.")
3. Requests notification permission if not yet granted
4. Auto-dismisses after 60 seconds if not manually dismissed

#### Add Time

`addMinutes(n)` handles four states:
- **Done/alarming:** Stops alarm, restarts with `n` minutes
- **Paused:** Adds to `pauseRemaining`
- **Running:** Extends `endTime` by `n * 60 * 1000`
- **Not started:** Adds to `totalSeconds`

#### Dragging

Mouse-drag support:
- `mousedown` on timer body (not buttons) initiates drag
- On first drag, converts from right-based to left-based positioning by reading `getBoundingClientRect()`
- Subsequent drags update `posLeft`/`posTop` by mouse delta
- Global `mousemove`/`mouseup` listeners registered on `window`

#### Styling

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

- **Display:** `font-family: var(--font-mono)`, 42px, font-weight 300, 2px letter-spacing
- **Buttons:** Pill-shaped (14px border-radius), amber borders (`rgba(255, 180, 100, 0.3)`), 12px font
- **Dismiss button:** Red theme - `rgba(255, 80, 80, 0.25)` background, font-weight 600, wider padding

#### Lifecycle

- **onMount:** Sets default to 5 minutes. Registers global mouse event listeners for dragging. Returns cleanup that stops tick, alarm, and removes listeners.

---

### Canvas.svelte - PIP Webview Overlay

**File:** `src/renderer/components/Canvas.svelte`

A picture-in-picture style overlay for rendering HTML content using the Electron `<webview>` tag.

#### Props ($props)

| Prop | Type | Description |
|------|------|-------------|
| `onClose` | `() => void` | Callback to dismiss the canvas |
| `onRequestShow` | `() => void` | Optional callback to auto-show canvas when content arrives |

#### Reactive State ($state)

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `url` | `string` | `''` | Current webview URL |
| `visible` | `boolean` | `false` | Visibility for fade animation |

#### Other Instance Variables

| Variable | Type | Purpose |
|----------|------|---------|
| `refreshTimer` | `timeout \| null` | 100ms debounce for rapid URL updates |
| `cleanups` | `(() => void)[]` | IPC listener cleanup functions |

#### Content Pipeline

1. MCP `render_canvas` tool triggers `canvas:updated` IPC event with URL
2. `debouncedRefresh(newUrl)` delays 100ms, then sets `url` and calls `onRequestShow()`
3. The `<webview>` element renders the URL
4. When URL is empty, shows placeholder: "No canvas content" / "Content will appear here when the agent creates it"

#### Close Animation

On close: sets `visible = false`, waits 300ms for fade-out, then calls `onClose()`.

#### Layout

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

The PIP window anchors to the bottom-right. Close button positioned absolutely above the PIP at `bottom: calc(50% + 16px + 8px)`, 28px circle with red hover state.

#### Lifecycle

- **onMount:** Fades in via `requestAnimationFrame(() => visible = true)`. Registers `canvas:updated` IPC listener.
- **onDestroy:** Clears debounce timer, calls all cleanup functions.

---

### Artefact.svelte - Artefact Display

**File:** `src/renderer/components/Artefact.svelte`

Full-bleed overlay for displaying artefacts created by the agent via the `create_artefact` MCP tool.

#### Props ($props)

| Prop | Type | Description |
|------|------|-------------|
| `onClose` | `() => void` | Callback to dismiss the overlay |

#### Reactive State ($state)

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `content` | `string` | `''` | HTML/code/markdown content |
| `contentType` | `'html' \| 'svg' \| 'code' \| 'markdown' \| 'image' \| 'video'` | `'html'` | Current content type |
| `contentSrc` | `string` | `''` | `file://` URL for image/video |
| `visible` | `boolean` | `false` | Visibility for entrance animation |
| `gallery` | `Array<{id, title, type, description?, path?, file?, created_at?}>` | `[]` | Gallery items |
| `showGallery` | `boolean` | `false` | Gallery panel visibility |
| `searchQuery` | `string` | `''` | Gallery search text |
| `activeFilter` | `string` | `'all'` | Gallery type filter |

#### Derived State ($derived)

| Variable | Expression | Purpose |
|----------|------------|---------|
| `filteredGallery` | Filters `gallery` by `activeFilter` and `searchQuery` | Displayed gallery items |

#### Content Rendering

Based on `contentType`:
- **html / svg:** Rendered in sandboxed `<iframe>` with `srcdoc={content}`, permissions: `allow-scripts allow-same-origin`
- **image:** `<img>` with `src={contentSrc}` or data URI from content, `object-fit: contain`
- **video:** `<video>` with `src={contentSrc}`, controls, autoplay, loop
- **code / markdown / other:** `<pre class="artefact-code">` with 13px mono font, pre-wrap

#### Gallery Panel

Slide-out panel on the left side:

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

**Filter options:** All, HTML, Code, Image, Video - rendered as pill buttons (12px border-radius, 10px font). Active state: `rgba(255, 255, 255, 0.15)` background with `rgba(255, 255, 255, 0.3)` border.

**Badge colours:**
- html/svg: `#4a9eff`
- code/markdown: `#a8e6a1`
- image: `#ff6b9d`
- video: `#9b59b6`

**Card layout:** Flex column, 10px/12px padding, 8px border-radius, 6px bottom margin. Shows type badge (9px bold uppercase), date, title (13px, formatted with hyphens replaced by spaces and title-cased), and truncated description (60 char max).

#### Close Animation

Sets `visible = false`, clears content (resets iframe to `about:blank`), waits 300ms, then calls `onClose()`.

#### Entrance Animation

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

- **onMount:** Fades in, registers window resize listener, registers `artefact:updated` IPC listener.
- **onDestroy:** Removes resize listener, calls cleanup functions, clears iframe content.

---

### Settings.svelte - Settings Panel

**File:** `src/renderer/components/Settings.svelte`

Full-screen overlay with three tabs: Settings, Usage, and Activity.

#### Props ($props)

| Prop | Type | Description |
|------|------|-------------|
| `onClose` | `() => void` | Callback to dismiss settings |

#### Reactive State ($state)

**Tab state:**

| Variable | Type | Default |
|----------|------|---------|
| `activeTab` | `'settings' \| 'usage' \| 'activity'` | `'settings'` |
| `saveStatus` | `string` | `''` |

**Config form fields (Settings tab) - ~40 state variables covering:**

| Section | State Variables |
|---------|----------------|
| Agents | `agentList` - array of `{name, display_name, description, role}` |
| Identity | `userName`, `agentDisplayName`, `openingLine`, `wakeWords` |
| Tools | `disabledTools` - `Set<string>` for 13 toggleable MCP tools |
| Window | `windowWidth` (622), `windowHeight` (830), `avatarEnabled`, `avatarResolution` (512) |
| Voice | `ttsBackend`, `elevenlabsApiKey`, `elevenlabsVoiceId`, `elevenlabsModel`, `elevenlabsStability` (0.5), `elevenlabsSimilarity` (0.75), `elevenlabsStyle` (0.35), `ttsPlaybackRate` (1.12), `falVoiceId` |
| Input | `inputMode`, `pttKey`, `wakeWordEnabled`, `wakeChunkSeconds` |
| Notifications | `notificationsEnabled` |
| Audio | `sampleRate` (16000), `maxRecordSec` (120) |
| Inference | `claudeBin`, `claudeEffort`, `adaptiveEffort` |
| Memory | `contextSummaries` (3), `maxContextTokens` (180000), `vectorSearchWeight` (0.7), `embeddingModel`, `embeddingDim` (384) |
| Session | `sessionSoftLimitMins` (60) |
| Heartbeat | `heartbeatActiveStart` (9), `heartbeatActiveEnd` (22), `heartbeatIntervalMins` (30) |
| Paths | `obsidianVault`, `dbPath`, `whisperBin` |
| Google | `googleConfigured`, `googleAuthStatus` |
| Telegram | `telegramBotToken`, `telegramChatId` |
| About | `version`, `bundleRoot` |

**Usage tab:**

| Variable | Type | Default |
|----------|------|---------|
| `usagePeriod` | `number \| null` | `null` |
| `usageData` | `any[]` | `[]` |
| `usageLoading` | `boolean` | `false` |

**Activity tab:**

| Variable | Type | Default |
|----------|------|---------|
| `activityItems` | `any[]` | `[]` |
| `activityFilter` | `string` | `'all'` |
| `activityAgentFilter` | `string` | `'all'` |
| `activitySearch` | `string` | `''` |
| `activityLoading` | `boolean` | `false` |
| `expandedActivity` | `number \| null` | `null` |

#### Toggleable Tools List

13 MCP tools that can be enabled/disabled per-agent:

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

- **Apply:** Gathers all form values via `gatherUpdates()`, calls `api.updateConfig(updates)`. Shows "Applied" status for 2s.
- **Save:** Calls Apply, shows "Saved" status for 2s.

`gatherUpdates()` maps all form state variables to their config key names (e.g. `userName` -> `USER_NAME`, `ttsBackend` -> `TTS_BACKEND`).

#### Activity Tab Features

- **Category badges:** TOOL (blue `#4a9eff`), BEAT (purple `#9b59b6`), INFER (green `#2ecc71`)
- **Filtering:** By category (all, flagged, tool_call, heartbeat, inference), by agent, by search text
- **Expandable rows:** Click to expand detail view
- **Limit:** Shows max 200 items after filtering

#### Utility Functions

| Function | Purpose |
|----------|---------|
| `formatTokens(n)` | Formats numbers as K/M (e.g. 1500 -> "1.5K") |
| `formatDuration(ms)` | Formats as Xs, Xm Xs, or Xh Xm |
| `formatTimestamp(ts)` | Formats as "Mon DD HH:MM:SS" |

#### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Escape | Close settings (via `svelte:window onkeydown`) |

#### IPC Channels Used

| Channel | Usage |
|---------|-------|
| `api.getConfig()` | Load all config values on mount |
| `api.getAgentsFull()` | Load agent list with full metadata |
| `api.updateConfig(updates)` | Apply/save config changes |
| `api.switchAgent(name)` | Switch active agent |
| `api.getUsage(days?)` | Load usage data for Usage tab |
| `api.getActivity(days, limit)` | Load activity items for Activity tab |

#### Lifecycle

- **onMount:** Loads config and agent list via parallel `Promise.all`. Populates all form state variables from config values with defaults.

---

### SetupWizard.svelte - First-Launch Flow

**File:** `src/renderer/components/SetupWizard.svelte`

Full-screen overlay shown on first launch (when `setup_complete` is false in config).

#### Props ($props)

| Prop | Type | Description |
|------|------|-------------|
| `onComplete` | `() => void` | Optional callback when setup finishes |

#### Reactive State ($state)

| Variable | Type | Default | Purpose |
|----------|------|---------|---------|
| `phase` | `Phase` | `'intro'` | Current wizard phase |
| `userName` | `string` | `''` | User's name |
| `conversationLog` | `Array<{role, text}>` | `[]` | AI chat history during agent creation |
| `currentInput` | `string` | `''` | Current chat input |
| `isInferring` | `boolean` | `false` | Waiting for AI response |
| `elevenLabsKey` | `string` | `''` | ElevenLabs API key |
| `falKey` | `string` | `''` | Fal AI API key |
| `telegramToken` | `string` | `''` | Telegram bot token |
| `telegramChatId` | `string` | `''` | Telegram chat ID |
| `elevenLabsVerifying` | `boolean` | `false` | Verification in progress |
| `elevenLabsVerified` | `boolean \| null` | `null` | Verification result |
| `falVerifying` | `boolean` | `false` | Verification in progress |
| `falVerified` | `boolean \| null` | `null` | Verification result |
| `telegramVerifying` | `boolean` | `false` | Verification in progress |
| `telegramVerified` | `boolean \| null` | `null` | Verification result |
| `servicesSaved` | `string[]` | `[]` | Keys that were configured |
| `servicesSkipped` | `string[]` | `[]` | Keys that were skipped |
| `brainFrame` | `number` | `0` | Current brain animation frame index |

#### Phase Flow

```
intro -> welcome -> elevenlabs -> fal -> telegram -> create -> done
```

| Phase | Content | Transition Trigger |
|-------|---------|-------------------|
| `intro` | Brain frame animation (10-frame cycle at 180ms) | Auto-advances after 3.2s |
| `welcome` | "Hello." title, name input | Enter or Continue button when name entered |
| `elevenlabs` | Service card with API key input + verify | Next/Skip button |
| `fal` | Service card with API key input + verify | Next/Skip button |
| `telegram` | Service card with bot token + chat ID + verify | Finish/Skip & Finish button |
| `create` | AI chat for agent creation (Xan metaprompt) | Agent config JSON detected in response, or Skip |
| `done` | "Ready." with green orb | Auto-dismisses after 2s |

#### Brain Animation

Uses pre-rendered PNG frames loaded via Vite's `import.meta.glob()`:

```typescript
const frameModules = import.meta.glob(
  '../../../resources/icons/brain_frames/brain_*.png',
  { eager: true, query: '?url', import: 'default' }
);
```

Frames sorted by filename, cycled at 180ms interval. Brain image: 200x200px, `object-fit: contain`, with brightness/contrast filter and 2.4s pulse animation (scale 1.0 to 1.03).

#### Service Verification

Verification happens directly from the renderer via `fetch`:

| Service | Endpoint | Success Condition |
|---------|----------|-------------------|
| ElevenLabs | `GET https://api.elevenlabs.io/v1/user` with `xi-api-key` header | `res.ok` |
| Fal | `POST https://queue.fal.run/fal-ai/fast-sdxl` with `Authorization: Key ...` header | `res.status < 400` |
| Telegram | `GET https://api.telegram.org/bot.../getMe` | `data.ok === true` |

Verified keys are saved to `~/.atrophy/.env` via `api.saveSecret()` (not to `config.json`). Non-secret settings go to `config.json` via `api.updateConfig()`.

#### Agent Creation Chat

During the `create` phase, messages are sent via `api.wizardInference(text)`. The wizard monitors responses for `AGENT_CONFIG` JSON blocks in fenced code blocks. When detected, it parses the config and calls `api.createAgent(agentConfig)` to scaffold the new agent.

Service context is injected into the conversation log so Xan knows which services are available.

#### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Enter | Advance to next phase, or send chat message in create phase |

#### Styling

```css
.wizard-overlay {
  position: absolute;
  inset: 0;
  z-index: 70;
  background: var(--bg);
}

.wizard-content {
  max-width: 460px;
  padding: var(--pad);
}
```

- **Orb:** 60px radial gradient circle, blue for normal, green for done state, 3s pulse animation
- **Inputs:** 44px height, 320px max-width, centered text, 10px border-radius
- **Secure inputs:** Orange border (`rgba(220, 140, 40, 0.45)`), mono font, left-aligned, focus glow
- **Buttons:** 10px/28px padding, blue accent border/background, 10px border-radius
- **Verify buttons:** Orange theme (`rgba(220, 140, 40, *)`)
- **Service cards:** 380px max-width, 14px border-radius, 28px/24px padding
- **Verification badges:** Green "Verified" or red "Invalid key", pill-shaped (6px radius)
- **Chat area:** 600px max-height, scrollable messages, 22px rounded input bar
- **Fade-in animation:** 0.5s ease, translates 8px up from start

#### Lifecycle

- **onMount:** Starts brain animation if phase is `intro`
- **onDestroy:** Stops brain animation interval

---

## CSS Theme (src/renderer/styles/global.css)

Dark-only theme. No light mode. Imports Bricolage Grotesque font from Google Fonts.

### CSS Custom Properties

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

### Global Resets and Behaviour

- Universal box-sizing: `border-box`
- `html`, `body`, `#app`: full width/height, hidden overflow, transparent background
- Default `user-select: none` and `-webkit-app-region: drag` on body (entire window is draggable)
- Interactive elements (`input`, `textarea`, `button`, `a`, `[data-no-drag]`) get `-webkit-app-region: no-drag`
- `.selectable` class overrides `user-select: text` for the transcript
- Font smoothing: `-webkit-font-smoothing: antialiased`

### Scrollbar Styling

Thin dark scrollbars:
- Width: 6px
- Track: transparent
- Thumb: `rgba(255, 255, 255, 0.12)`, 3px border-radius
- Thumb hover: `rgba(255, 255, 255, 0.2)`

### Utility Classes

- `.section-header`: 11px bold uppercase, 3px letter-spacing, `var(--text-dim)`, 12px bottom margin
- `.selectable`: enables text selection

### Focus Ring

`:focus-visible` outline: 1px solid `var(--accent-hover)`, 2px offset.

### Selection Colour

`::selection` background: `rgba(100, 140, 255, 0.2)`.

---

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
- **Chat** - toggle the floating chat overlay (the Electron version does not have a chat overlay)
- **Agents** - submenu listing all discovered agents for quick switching
- **Set Away/Active** - toggle user presence status

The tray icon state can be updated programmatically via `updateTrayState(state)` (active, muted, idle, away), but this only applies when using the procedural orb icon. The brain template image handles state differently.

## Chat Overlay

**Not yet ported.** The Python version has a `ChatPanel` - a floating `520x380` frameless, always-on-top panel triggered by Cmd+Shift+Space. It provides text-only chat (no video) with a transcript and input bar, and is draggable.

In the Electron version, Cmd+Shift+Space (in menu bar mode) simply shows/hides the main window rather than opening a separate chat overlay.

## Window Minimize and Close Behavior

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
| Config | `getConfig`, `updateConfig`, `saveSecret` |
| Setup | `needsSetup`, `wizardInference`, `createAgent` |
| Window | `toggleFullscreen`, `minimizeWindow`, `closeWindow` |
| Avatar | `getAvatarVideoPath` |
| Updates | `checkForUpdates`, `downloadUpdate`, `quitAndInstall`, `onUpdate*` |
| Deferral | `completeDeferral`, `on('deferral:request', cb)` |
| Canvas | `on('canvas:updated', cb)` |
| Artefact | `on('artefact:updated', cb)` |
| Queues | `drainAgentQueue`, `drainAllAgentQueues`, `onQueueMessage` |
| Other | `getOpeningLine`, `isLoginItemEnabled`, `toggleLoginItem`, `getUsage`, `getActivity` |

### Generic Event Listener

In addition to typed listener functions, an `api.on(channel, callback)` method is available for arbitrary IPC events. Returns an unsubscribe function. Used by Window.svelte for `deferral:request` and `canvas:updated`, by Canvas.svelte for `canvas:updated`, and by Artefact.svelte for `artefact:updated`.
