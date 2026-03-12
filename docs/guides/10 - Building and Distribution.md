# Building and Distribution

The Electron app is built using `electron-vite` for compilation and `electron-builder` for packaging. The result is a self-contained macOS `.app` bundle with auto-update support via GitHub Releases.

---

## Quick Start

```bash
pnpm build                    # Compile TypeScript + bundle renderer
pnpm pack                     # Build + create unpacked .app directory
pnpm dist                     # Build + create DMG + ZIP
pnpm dist:mac                 # Same as dist, explicitly targeting macOS
```

---

## Architecture

The `.app` bundle is a full Electron application. It contains:

- Compiled TypeScript (main process, preload, renderer) in `out/`
- The Electron runtime
- Native dependencies (`better-sqlite3`, rebuilt for Electron)
- Bundled resources (MCP servers, scripts, agents, database schema)
- The app icon (`.icns`)

Runtime user data lives in `~/.atrophy/`:

| Path | Purpose |
|------|---------|
| `~/.atrophy/agents/` | Agent data, memory databases, avatar files |
| `~/.atrophy/config.json` | User config |
| `~/.atrophy/.env` | Secrets (API keys, tokens) |
| `~/.atrophy/models/` | Cached embedding models (Transformers.js) |
| `~/.atrophy/logs/` | Job execution logs |
| `~/.atrophy/server_token` | HTTP API auth token |

---

## Build Process

### Step 1: Compile (`pnpm build`)

Runs `electron-vite build` followed by `vite build` for the renderer:

1. **Main process** - TypeScript in `src/main/` compiled to `out/main/`
2. **Preload** - TypeScript in `src/preload/` compiled to `out/preload/`
3. **Renderer** - Svelte + TypeScript in `src/renderer/` bundled to `out/renderer/`

Source maps are excluded from the final package (filtered in `electron-builder.yml`).

### Step 2: Package (`pnpm pack` or `pnpm dist`)

`electron-builder` takes the compiled output and creates the distributable:

1. **Copies compiled code** from `out/` into the `.app` bundle
2. **Bundles extra resources** - MCP Python servers, scripts, agent definitions, database schema are copied into `Contents/Resources/`
3. **Rebuilds native modules** - `better-sqlite3` is compiled against the Electron Node.js headers
4. **Signs the app** with hardened runtime entitlements (required for macOS notarization)
5. **Creates installers** - DMG with custom background and Applications symlink, plus a ZIP for auto-update

---

## electron-builder.yml

The build configuration lives at `electron-builder.yml` in the project root:

```yaml
appId: com.atrophiedmind.app
productName: Atrophy
mac:
  category: public.app-category.utilities
  target:
    - dmg
    - zip
  hardenedRuntime: true
  entitlements: build/entitlements.mac.plist
  entitlementsInherit: build/entitlements.mac.plist
  extraResources:
    - from: mcp/
      to: mcp
    - from: scripts/
      to: scripts
    - from: agents/
      to: agents
    - from: db/
      to: db
```

### Extra Resources

These directories are copied into the `.app` bundle's `Contents/Resources/` and are accessible at runtime via `process.resourcesPath`:

| Source | Destination | Contents |
|--------|------------|----------|
| `mcp/` | `mcp/` | Python MCP servers (`memory_server.py`, `google_server.py`) |
| `scripts/` | `scripts/` | Python standalone scripts (Google auth, cron jobs, agent tasks) |
| `agents/` | `agents/` | Default agent definitions (`agent.json`, prompts, avatar source) |
| `db/` | `db/` | Database schema (`schema.sql`) |

When whisper.cpp is bundled, uncomment the whisper entry in `electron-builder.yml` to include `vendor/whisper.cpp` as well.

---

## DMG Creation

The DMG is created automatically as part of `pnpm dist`. Configuration in `electron-builder.yml`:

- Custom background image (`resources/dmg-background.png`)
- Icon layout with the app on the left and Applications symlink on the right
- Window size 660x400
- Named `Atrophy-<version>-<arch>.dmg`

The DMG and ZIP are output to the `dist/` directory.

---

## Auto-Update

Auto-update is handled by `electron-updater` with GitHub Releases as the update provider.

### How it works

1. On app launch, `electron-updater` checks the configured GitHub repository for new releases
2. If a newer version is found, the update ZIP is downloaded in the background
3. The user is notified and can choose to install immediately (quit and install) or defer
4. On next launch after install, the app runs the new version

### Configuration

The publish target is defined in `electron-builder.yml`:

```yaml
publish:
  provider: github
  owner: wlilley93
  repo: Atrophy
```

### Creating a release

1. Update the version in `package.json`
2. Build the distributable: `pnpm dist:mac`
3. Create a GitHub Release with the version tag
4. Upload the DMG and ZIP artifacts from `dist/`

`electron-updater` uses the ZIP artifact for updates (differential download is not supported - the full ZIP is downloaded each time).

---

## Native Dependencies

| Package | Type | Rebuild Required | Notes |
|---------|------|-----------------|-------|
| `better-sqlite3` | Native (C++) | Yes | Must be rebuilt against Electron's Node.js headers. Run `pnpm rebuild` after install. |
| `@xenova/transformers` | WASM | No | Pure WebAssembly, no native compilation needed. Works across platforms without rebuild. |

The `pnpm rebuild` script runs `electron-rebuild -f -w better-sqlite3` to ensure the native module is compatible with the Electron version.

---

## Code Signing

The app uses macOS hardened runtime, configured via entitlements plists:

- `build/entitlements.mac.plist` - main process entitlements
- `build/entitlements.mac.plist` (inherited) - child process entitlements

Hardened runtime is required for:
- macOS notarization
- Microphone access (audio recording for STT)
- File system access for `~/.atrophy/` user data

---

## Login Item

The Electron app uses Electron's built-in login item management:

```typescript
import { app } from 'electron';

// Enable start at login
app.setLoginItemSettings({ openAtLogin: true });

// Check status
const settings = app.getLoginItemSettings();
console.log(settings.openAtLogin); // true or false
```

This is simpler than the Python version's launchd-based approach. The login item can be toggled from the Settings panel or programmatically.

---

## Development Workflow

### Dev mode with HMR

```bash
pnpm dev                      # Starts electron-vite dev server with hot reload
```

The renderer uses Vite's HMR for instant updates. Main process changes require a restart.

### Type checking

```bash
pnpm typecheck                # Check both main (node) and renderer (web) TypeScript
pnpm typecheck:node           # Main + preload only
pnpm typecheck:web            # Renderer only
```

### Testing

```bash
pnpm test                     # Run Vitest tests
pnpm test:watch               # Watch mode
```

---

## Directory Structure (Built Output)

```
out/
  main/
    index.js                  # Compiled main process entry point
  preload/
    index.mjs                 # Compiled preload script
  renderer/
    index.html                # Bundled renderer HTML
    assets/                   # Bundled CSS, JS, images

dist/
  mac-arm64/                  # Unpacked .app (from pnpm pack)
  Atrophy-<version>-arm64.dmg
  Atrophy-<version>-arm64.zip
  Atrophy-<version>-arm64-mac.zip.blockmap
```
