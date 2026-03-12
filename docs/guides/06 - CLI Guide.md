# CLI Guide

The Electron rewrite of The Atrophied Mind is a GUI application. There are no CLI or text-only modes. All interaction happens through the graphical window, the menu bar tray, or the HTTP API.

---

## Available Modes

### Menu Bar App (primary)

```bash
pnpm dev -- --app
```

Hides from the Dock. Lives in the macOS menu bar. Starts silent - no window, no voice, no opening line. Click the tray icon or press **Cmd+Shift+Space** to summon the window. This is the mode for daily use.

### Full GUI

```bash
pnpm dev -- --gui
```

Opens the Svelte window immediately with an AI-generated opening line. Shows avatar if enabled. Use this when you want the full visual experience without the menu-bar-only behaviour.

### HTTP Server

```bash
pnpm dev -- --server
pnpm dev -- --server --port 8080
```

Headless REST API. Runs on `127.0.0.1:5000` by default. Bearer token auth on all endpoints except `/health`. Token auto-generated on first run and stored at `~/.atrophy/server_token`.

See [05 - API Guide](05%20-%20API%20Guide.md) for the full endpoint reference, authentication details, and integration examples.

### Selecting an Agent

Any mode accepts the `AGENT` environment variable:

```bash
AGENT=oracle pnpm dev -- --app
AGENT=companion pnpm dev -- --gui
AGENT=xan pnpm dev -- --server
```

If not set, defaults to `xan`.

---

## Terminal-Based Interaction

If you need to interact with an agent from the terminal, use the **server mode** and call the REST API with `curl` or any HTTP client:

```bash
# Start the server in one terminal
pnpm dev -- --server

# Chat from another terminal
TOKEN=$(cat ~/.atrophy/server_token)
curl -X POST http://localhost:5000/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "How are you?"}'
```

For streaming responses:

```bash
curl -N -X POST http://localhost:5000/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Tell me something interesting."}'
```

---

## Python App CLI Modes

The original Python app at `/Users/williamlilley/Projects/Claude Code Projects/Atrophy App/` still supports the full set of terminal modes:

```bash
python main.py --text         # Text-only (no mic, no TTS - just type)
python main.py --cli          # Voice + text (needs whisper.cpp + mic)
```

These modes were not ported to the Electron app because the Electron architecture is built around BrowserWindow rendering and IPC. For pure terminal interaction, use the server mode API or the Python app directly.
