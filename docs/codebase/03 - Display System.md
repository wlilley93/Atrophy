# Display System

The GUI mode (`--gui`) provides a PyQt5 window with video playback, streaming text overlay, and a canvas panel.

## display/window.py -- CompanionWindow

The main application window. Full-bleed video with overlaid text and a floating input bar.

### Video Playback

`FrameGrabSurface` (subclass of `QAbstractVideoSurface`) captures frames from `QMediaPlayer` for custom rendering. Supports ARGB32, RGB32, and RGB565 pixel formats. Each frame is converted to a `QImage` and emitted via the `frame_ready` signal.

Video loops (idle animations) play continuously in the background. The companion's current state determines which loop plays.

### Streaming Text Display

Text arrives token-by-token via `TextDelta` events. The window renders each token immediately, building up the response character by character. Prosody tags and code blocks are stripped for display via `_strip_tags()`.

### Input Bar

A floating `QLineEdit` at the bottom of the window with rounded corners. Users type and press Enter to send messages.

### Icon Buttons

A row of circular 34px toggle buttons in the top-right corner, ordered right-to-left:

| Button | Class | Icon | Behaviour |
|--------|-------|------|-----------|
| Eye | `_EyeButton` | Eye shape (slash through when active) | Collapses window to a minimal input-only bar. Hides all other buttons except itself. Restores previous geometry on toggle-off. |
| Mute | `_MuteButton` | Speaker with sound waves (X when muted) | Toggles TTS audio playback. When muted, inference still runs but audio is suppressed. |
| Minimize | `_MinimizeButton` | Horizontal line | Hides window to system tray. Native Cmd+M / yellow button is intercepted to do the same (hide, not minimize). |
| Wake | `_WakeButton` | Microphone with radio waves | Toggles wake word listener on/off. Background turns green when active. Starts/stops `WakeWordListener`. |
| Settings | `_SettingsButton` | Gear | Opens/closes `SettingsPanel` full-screen overlay. Background changes when active. |

All buttons use custom `paintEvent` rendering (no image assets) with dark semi-transparent pill backgrounds and white icons at 120 alpha (220 when active).

### Settings Panel

`SettingsPanel` is a full-screen overlay (`QWidget`) with a scrollable form. Sections: Agents, Agent Identity, Tools, Window, Voice & TTS, Input, Notifications, Audio Capture, Inference, Memory & Context, Session, Heartbeat, Paths, Telegram, About.

The **Agents** section lists all discovered agents with Switch/Muted/Enabled controls per agent, plus a **+ New Agent** button that launches `scripts/create_agent.py` in a Terminal window.

The **Tools** section has per-agent checkboxes to enable/disable specific MCP tools (deferral, Telegram, reminders, timers, etc.).

The **About** section shows the current version (from `VERSION` file), install path, and a **Check for Updates** button. If updates are available (checked via `git fetch` + `git rev-list`), an **Update Now** button appears that runs `git pull --ff-only`.

Control types: sliders (for floats like stability/similarity), combo boxes (for enums like TTS backend), checkboxes (for booleans like avatar enabled), spinboxes (for integers like sample rate), text inputs (for strings like API keys, with password mode for secrets), and read-only info labels (for paths).

Two save modes:
- **Apply** -- writes values to the live `config` module and updates `os.environ` for child processes. Also restarts the wake word listener if wake words changed, and updates the audio player playback rate.
- **Save to .env** -- calls Apply first, then writes `agent.json` (agent-specific settings) and `.env` (environment variables and secrets).

### Keyboard Shortcuts

| Shortcut | Action | Scope |
|----------|--------|-------|
| Cmd+, | Toggle settings panel | Window |
| Cmd+Shift+W | Toggle wake word detection | Window |
| Cmd+K | Toggle canvas overlay | Window |
| Cmd+C | Copy selected text, or last companion message if nothing selected | Window |
| Cmd+M | Minimize to tray (intercepted from native) | Window |
| Cmd+Shift+Space | Toggle chat overlay panel | Global (works even when app is not focused, via NSEvent monitor) |
| Escape | Close chat overlay | Chat overlay |

### Chat Overlay (ChatPanel)

A floating `520x380` frameless, always-on-top panel triggered by Cmd+Shift+Space. Text-only (no video). Contains a `TranscriptOverlay` for message history and an `InputBar` for text input. Draggable. Centres on screen when opened. Uses the same inference pipeline as the main window.

The global hotkey is registered via macOS `NSEvent` monitors (both global and local) so it works even when the app is not focused.

### System Tray (TrayIcon)

Provides a menu bar icon with actions:
- **Show/Hide** -- toggles the main window
- **Chat** -- toggles the chat overlay
- **Set Away/Active** -- toggles user presence status
- **Quit** -- closes the application

Clicking the tray icon directly toggles the main window.

### StreamingPipelineWorker

A `QThread` subclass that runs inference + TTS in parallel:

- **Thread 1** (the QThread): Reads the inference stream, emits signals for text and tool use
- **Thread 2** (spawned internally): Picks up completed sentences, synthesises audio, emits `sentence_ready` signals

Signals:

| Signal | Payload | Purpose |
|--------|---------|---------|
| `text_ready` | `(text, index)` | Sentence text available (before TTS) |
| `sentence_ready` | `(text, audio_path, index)` | TTS done, audio file ready |
| `tool_use` | `(name, tool_id)` | Agent invoked a tool |
| `compacting` | -- | Context window compaction detected |
| `done` | `(full_text, session_id)` | Stream complete |
| `error` | `(message)` | Error during inference |

### MemoryFlushWorker

A separate `QThread` that runs a silent memory flush (via `run_memory_flush()`) when context compaction is detected. Emits `finished_flush` with the new session ID.

### System Tray

The window integrates with the macOS system tray for background presence.

### Opening Line Generation

On GUI launch, the companion generates an opening line via `run_inference_oneshot()` with:

- Time-of-day context
- Active thread awareness
- Randomised style directive (from 12 styles: playful, direct, quiet, strange, honest, etc.)
- Explicit instruction to avoid status updates

Openings can be cached (with time-of-day bracket validation) for faster startup.

### Window Dimensions

Configurable per-agent via `agent.json`:

```json
{
  "display": {
    "window_width": 622,
    "window_height": 830
  }
}
```

## display/canvas.py -- CanvasOverlay

A PIP (picture-in-picture) overlay that sits on top of the video surface. Uses `QWebEngineView` for rendering HTML content.

### Behavior

- Fades in when content is written (300ms InOutCubic animation via `QPropertyAnimation`)
- Fades out on dismiss (Cmd+K or close button)
- Auto-refreshes when the content file changes (via `QFileSystemWatcher` with 100ms debounce)
- Voice and text streaming continue independently under the overlay

### Content Pipeline

1. MCP `render_canvas` tool writes HTML to `.canvas_content.html`
2. `QFileSystemWatcher` detects the file change
3. Overlay auto-shows and loads the HTML into `QWebEngineView`
4. Content is a full HTML document -- CSS/JS are supported

Or programmatically:

```python
canvas.set_content(html)      # write + show
canvas.show_canvas()          # fade in
canvas.dismiss()              # fade out
canvas.toggle()               # toggle visibility
canvas.reposition(x, y, w, h) # called by parent on resize
```

### Close Button

A small "x" button in the top-right corner with hover effects (grey -> red). The overlay can also be dismissed with a keyboard shortcut.

### Fallback

If `PyQtWebEngine` is not installed, the canvas overlay is gracefully disabled. The rest of the GUI works without it.

## display/templates/

HTML templates for canvas rendering:

- `default_canvas.html` -- General-purpose canvas template
- `memory_graph.html` -- Visual graph of threads and observations (used by `render_memory_graph` MCP tool)

Templates use a dark theme (`#1a1a1a` background, `#e0e0e0` text) to match the application aesthetic.
