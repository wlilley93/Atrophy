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
- The Electron runtime (Chromium + Node.js)
- Native dependencies (`better-sqlite3`, rebuilt for Electron's Node.js headers)
- Bundled resources (MCP servers, scripts, agents, database schema)
- The app icon (`TheAtrophiedMind.icns`)

Runtime user data lives in `~/.atrophy/`:

| Path | Purpose |
|------|---------|
| `~/.atrophy/agents/` | Agent data, memory databases, avatar files |
| `~/.atrophy/config.json` | User config (mode 0600) |
| `~/.atrophy/.env` | Secrets - API keys, tokens (mode 0600) |
| `~/.atrophy/models/` | Cached embedding models (Transformers.js WASM) |
| `~/.atrophy/logs/` | Job execution logs |
| `~/.atrophy/server_token` | HTTP API auth token (mode 0600) |
| `~/.atrophy/agent_states.json` | Per-agent muted/enabled state |

---

## Build Process

### Step 1: Compile (`pnpm build`)

The `build` script runs two separate build steps:

```bash
electron-vite build -c electron-vite.config.ts && vite build --config vite.renderer.config.ts
```

This is split into two commands because of an electron-vite 5 bug that drops Svelte plugins during its config resolution pipeline. The workaround uses a standalone `vite.renderer.config.ts` for the renderer.

#### Main process and preload (`electron-vite.config.ts`)

```typescript
export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: { index: resolve('src/main/index.ts') },
      },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: { index: resolve('src/preload/index.ts') },
      },
    },
  },
});
```

`externalizeDepsPlugin()` ensures Node.js built-ins and `node_modules` dependencies (like `better-sqlite3`, `electron-updater`) are not bundled into the output - they remain as external requires resolved at runtime.

Output:
- `out/main/index.js` - compiled main process
- `out/preload/index.mjs` - compiled preload script

#### Renderer (`vite.renderer.config.ts`)

```typescript
export default defineConfig({
  root: resolve('src/renderer'),
  plugins: [svelte({ configFile: resolve('svelte.config.js') })],
  build: {
    outDir: resolve('out/renderer'),
    emptyOutDir: true,
    target: 'chrome130',
    modulePreload: { polyfill: false },
    minify: false,
  },
  base: './',
  envPrefix: ['RENDERER_VITE_', 'VITE_'],
});
```

Key settings:
- `target: 'chrome130'` - targets Electron's Chromium version (Electron 34 ships Chromium 130)
- `modulePreload: { polyfill: false }` - Electron's Chromium supports native module preload
- `minify: false` - keeps output readable for debugging
- `base: './'` - relative paths for loading from the file system
- `envPrefix` - only `RENDERER_VITE_` and `VITE_` prefixed env vars are exposed to the renderer

Output:
- `out/renderer/index.html` - the renderer entry point
- `out/renderer/assets/` - bundled CSS, JS, images

### Step 2: Package (`pnpm pack` or `pnpm dist`)

`electron-builder` takes the compiled output and creates the distributable:

1. **Copies compiled code** from `out/` into the `.app` bundle
2. **Bundles extra resources** - MCP Python servers, scripts, agent definitions, database schema are copied into `Contents/Resources/`
3. **Installs production dependencies** - only packages listed in `dependencies` (not `devDependencies`) are included
4. **Rebuilds native modules** - `better-sqlite3` is compiled against the Electron Node.js headers
5. **Signs the app** with hardened runtime entitlements (required for macOS notarization)
6. **Creates installers** - DMG with custom background and Applications symlink, plus a ZIP for auto-update

---

## Full electron-builder.yml Reference

The build configuration lives at `electron-builder.yml` in the project root:

```yaml
appId: com.atrophiedmind.app
productName: Atrophy
copyright: Copyright (c) 2024-2026 Will Lilley

directories:
  output: dist                    # Where DMG/ZIP/unpacked .app goes
  buildResources: resources       # Icons, DMG background, etc.

files:
  - out/**/*                      # Include all compiled output
  - "!out/**/*.map"               # Exclude source maps from the bundle

mac:
  category: public.app-category.utilities
  target:
    - dmg                         # Drag-to-install disk image
    - zip                         # Used by electron-updater for auto-update
  icon: resources/icons/TheAtrophiedMind.icns
  hardenedRuntime: true
  entitlements: build/entitlements.mac.plist
  entitlementsInherit: build/entitlements.mac.plist
  extraResources:
    - from: mcp/
      to: mcp
      filter:
        - "**/*.py"               # Only Python files from MCP directory
    - from: scripts/
      to: scripts
      filter:
        - "**/*"                  # All files from scripts directory
    - from: agents/
      to: agents
      filter:
        - "**/*"                  # All agent definitions
    - from: db/
      to: db
      filter:
        - "**/*.sql"              # Only SQL schema files

dmg:
  title: Atrophy
  artifactName: "${productName}-${version}-${arch}.${ext}"
  background: resources/dmg-background.png
  iconSize: 80
  contents:
    - x: 180                      # App icon position (left)
      y: 200
      type: file
    - x: 480                      # Applications symlink (right)
      y: 200
      type: link
      path: /Applications
  window:
    width: 660
    height: 400

publish:
  provider: github
  owner: wlilley93
  repo: Atrophy
```

### Extra Resources

These directories are copied into the `.app` bundle's `Contents/Resources/` and are accessible at runtime via `process.resourcesPath`:

| Source | Destination | Filter | Contents |
|--------|------------|--------|----------|
| `mcp/` | `mcp/` | `**/*.py` | Python MCP servers (`memory_server.py`, `google_server.py`) |
| `scripts/` | `scripts/` | `**/*` | Python standalone scripts (Google auth, cron jobs, agent tasks) |
| `agents/` | `agents/` | `**/*` | Default agent definitions (`agent.json`, prompts, avatar source) |
| `db/` | `db/` | `**/*.sql` | Database schema (`schema.sql`) |

At runtime, `BUNDLE_ROOT` in `src/main/config.ts` resolves these:

```typescript
// In packaged app:
const BUNDLE_ROOT = process.resourcesPath;  // Contents/Resources/

// In development:
const BUNDLE_ROOT = path.resolve(__dirname, '..', '..');  // Project root
```

So `path.join(BUNDLE_ROOT, 'mcp', 'memory_server.py')` works in both contexts.

#### Whisper.cpp (currently commented out)

When whisper.cpp is ready to bundle, uncomment the whisper entry:

```yaml
    - from: vendor/whisper.cpp
      to: whisper
      filter:
        - "**/*"
```

This copies the built whisper binary and model into `Contents/Resources/whisper/`. The config paths (`WHISPER_BIN`, `WHISPER_MODEL`) will need to be updated to resolve from `process.resourcesPath` in packaged mode.

---

## DMG Customization

The DMG is created automatically as part of `pnpm dist`. The installer window shows:

```
+-----------------------------------------------+
|                                                 |
|  [dmg-background.png - 660x400]                |
|                                                 |
|        [App Icon]     --->     [Applications]   |
|         (180,200)               (480,200)       |
|                                                 |
+-----------------------------------------------+
```

Configuration details:

| Setting | Value | Description |
|---------|-------|-------------|
| `title` | `Atrophy` | Window title |
| `artifactName` | `${productName}-${version}-${arch}.${ext}` | Output filename (e.g. `Atrophy-0.1.2-arm64.dmg`) |
| `background` | `resources/dmg-background.png` | Custom background image (660x400 px recommended) |
| `iconSize` | `80` | Size of icons in the DMG window |
| `window.width` | `660` | DMG window width |
| `window.height` | `400` | DMG window height |
| App position | `(180, 200)` | Left side of window |
| Applications link | `(480, 200)` | Right side of window |

The background image should be placed at `resources/dmg-background.png`. If missing, electron-builder uses a default white background.

---

## Code Signing

### Hardened Runtime

The app uses macOS hardened runtime, configured via an entitlements plist at `build/entitlements.mac.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>com.apple.security.cs.allow-jit</key>
  <true/>
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
  <true/>
  <key>com.apple.security.cs.allow-dyld-environment-variables</key>
  <true/>
  <key>com.apple.security.device.audio-input</key>
  <true/>
  <key>com.apple.security.network.client</key>
  <true/>
  <key>com.apple.security.network.server</key>
  <true/>
  <key>com.apple.security.files.user-selected.read-write</key>
  <true/>
</dict>
</plist>
```

Entitlement breakdown:

| Entitlement | Why it is needed |
|-------------|-----------------|
| `cs.allow-jit` | Required by Electron's V8 JavaScript engine for JIT compilation |
| `cs.allow-unsigned-executable-memory` | Required by Electron's V8 and WASM (Transformers.js embeddings) |
| `cs.allow-dyld-environment-variables` | Required for native module loading (`better-sqlite3`) |
| `device.audio-input` | Microphone access for speech-to-text via whisper.cpp |
| `network.client` | Outbound HTTP for ElevenLabs TTS, Telegram Bot API, auto-update checks |
| `network.server` | Inbound HTTP for the `--server` mode API |
| `files.user-selected.read-write` | File system access for `~/.atrophy/` user data directory |

The same plist is used for both `entitlements` (main process) and `entitlementsInherit` (child processes like whisper.cpp and Python MCP servers).

### Signing for distribution

To sign for distribution (required for notarization), set these environment variables before running `pnpm dist`:

```bash
export CSC_LINK="path/to/certificate.p12"   # or base64-encoded
export CSC_KEY_PASSWORD="certificate-password"
```

electron-builder will use these to sign the `.app` and DMG. Without them, the app is built unsigned (fine for local development but macOS will show warnings).

### Notarization

For notarization with Apple's notary service, configure:

```bash
export APPLE_ID="your@email.com"
export APPLE_APP_SPECIFIC_PASSWORD="xxxx-xxxx-xxxx-xxxx"
export APPLE_TEAM_ID="XXXXXXXXXX"
```

electron-builder handles notarization automatically when these are set and `hardenedRuntime: true` is configured.

---

## Auto-Update Flow

Auto-update is handled by `electron-updater` (v6.8.3) with GitHub Releases as the update provider. The implementation is in `src/main/updater.ts`.

### Configuration

```yaml
# In electron-builder.yml
publish:
  provider: github
  owner: wlilley93
  repo: Atrophy
```

### Initialization

`initAutoUpdater()` is called after the main window is created. It:

1. Skips initialization entirely if `ELECTRON_RENDERER_URL` is set (dev mode)
2. Disables auto-download (`autoDownload = false`) - the user must explicitly choose to download
3. Enables auto-install on quit (`autoInstallOnAppQuit = true`)
4. Registers event handlers that forward update events to the renderer via IPC
5. Triggers an initial update check after a 5-second delay

### Update lifecycle

```
1. CHECK
   initAutoUpdater() -> setTimeout(5s) -> checkForUpdates()

2. NOTIFY
   autoUpdater 'update-available' event ->
     IPC 'updater:available' { version, releaseNotes }

   autoUpdater 'update-not-available' event ->
     IPC 'updater:not-available'

3. DOWNLOAD (user-initiated)
   IPC 'updater:download' -> downloadUpdate()

   autoUpdater 'download-progress' event ->
     IPC 'updater:progress' { percent, bytesPerSecond, transferred, total }

   autoUpdater 'update-downloaded' event ->
     IPC 'updater:downloaded' { version }

4. INSTALL (user-initiated or on quit)
   IPC 'updater:quitAndInstall' -> quitAndInstall()
   Or: app quits normally -> autoInstallOnAppQuit kicks in
```

### IPC events sent to renderer

| Event | Payload | Description |
|-------|---------|-------------|
| `updater:available` | `{ version: string, releaseNotes: string }` | A newer version is available |
| `updater:not-available` | (none) | Current version is up to date |
| `updater:progress` | `{ percent: number, bytesPerSecond: number, transferred: number, total: number }` | Download progress |
| `updater:downloaded` | `{ version: string }` | Update downloaded and ready to install |
| `updater:error` | `string` (error message) | Update check or download failed |

### IPC handlers (renderer to main)

| Channel | Action |
|---------|--------|
| `updater:check` | Manually trigger an update check |
| `updater:download` | Start downloading an available update |
| `updater:quitAndInstall` | Quit the app and install the downloaded update |

### Error handling

All update operations (check, download) use `.catch(() => {})` to silently swallow errors. Update failures are non-critical - the app continues running normally and the error is forwarded to the renderer as `updater:error`.

### Creating a release

1. Update the version in `package.json`:
   ```json
   "version": "0.2.0"
   ```

2. Build the distributable:
   ```bash
   pnpm dist:mac
   ```

3. Create a GitHub Release with the version tag (e.g. `v0.2.0`)

4. Upload the artifacts from `dist/`:
   - `Atrophy-0.2.0-arm64.dmg` - the installer
   - `Atrophy-0.2.0-arm64-mac.zip` - used by electron-updater
   - `latest-mac.yml` - the update manifest (generated automatically by electron-builder)

`electron-updater` uses the ZIP artifact for updates (differential download is not supported - the full ZIP is downloaded each time). The `latest-mac.yml` file contains the version, file hash, and download URL.

---

## Native Dependencies

| Package | Version | Type | Rebuild Required | Notes |
|---------|---------|------|-----------------|-------|
| `better-sqlite3` | 12.6.2 | Native (C++) | Yes | Synchronous SQLite API. Must be rebuilt against Electron's Node.js headers. |
| `@xenova/transformers` | 2.17.2 | WASM | No | Local ML inference (all-MiniLM-L6-v2 embeddings). Pure WebAssembly, runs in worker threads. |
| `electron-updater` | 6.8.3 | JavaScript | No | Auto-update client for GitHub Releases. |
| `uuid` | 13.0.0 | JavaScript | No | UUID generation for sessions and inference tracking. |

### Rebuilding native modules

The `rebuild` script in `package.json` runs:

```bash
electron-rebuild -f -w better-sqlite3
```

This must be run:
- After `pnpm install` (first time)
- After upgrading Electron to a new major version
- After upgrading `better-sqlite3`

The `-f` flag forces a rebuild even if the module appears up to date. The `-w` flag targets only `better-sqlite3`.

---

## Login Item

The Electron app uses Electron's built-in login item management rather than launchd plists:

```typescript
import { app } from 'electron';

// Enable start at login
app.setLoginItemSettings({ openAtLogin: true });

// Check status
const settings = app.getLoginItemSettings();
console.log(settings.openAtLogin); // true or false
```

This is exposed via IPC:
- `install:isEnabled` - returns `boolean`
- `install:toggle` - accepts `boolean` to enable/disable

The login item can be toggled from the Settings panel.

---

## Development Workflow

### Dev mode with HMR

```bash
pnpm dev
```

The dev script (`scripts/dev.ts`) starts two processes:

1. **Renderer Vite server** on port 5173 with hot module replacement
2. **electron-vite** for main/preload compilation + Electron launch

The `ELECTRON_RENDERER_URL` environment variable is set to `http://localhost:5173/` so the main process loads the renderer from the dev server instead of the built HTML file. This enables instant Svelte component updates without restarting Electron.

Main process changes require a full restart (kill and re-run `pnpm dev`).

### Type checking

```bash
pnpm typecheck                # Check both main (node) and renderer (web) TypeScript
pnpm typecheck:node           # Main + preload only (tsconfig.node.json)
pnpm typecheck:web            # Renderer only (tsconfig.web.json)
```

### Testing

```bash
pnpm test                     # Run Vitest tests (single run)
pnpm test:watch               # Watch mode (re-runs on file changes)
```

### Build verification

```bash
pnpm pack                     # Build + create unpacked .app (fast, no DMG)
```

The unpacked `.app` is output to `dist/mac-arm64/` (or `dist/mac/` on Intel). You can run it directly:

```bash
open dist/mac-arm64/Atrophy.app
```

---

## Build Output Structure

### After `pnpm build`

```
out/
  main/
    index.js                  # Compiled main process entry point
  preload/
    index.mjs                 # Compiled preload script (ES module)
  renderer/
    index.html                # Bundled renderer HTML
    assets/
      index-[hash].js         # Bundled Svelte app
      index-[hash].css        # Bundled styles
```

### After `pnpm dist`

```
dist/
  mac-arm64/                  # Unpacked .app directory
    Atrophy.app/
      Contents/
        MacOS/
          Atrophy             # Electron binary
        Resources/
          app.asar            # Packed application code
          mcp/                # MCP Python servers
          scripts/            # Python scripts
          agents/             # Default agent definitions
          db/                 # Database schema
          icons/              # App and tray icons
  Atrophy-0.1.2-arm64.dmg    # Installer disk image
  Atrophy-0.1.2-arm64-mac.zip  # ZIP for auto-update
  Atrophy-0.1.2-arm64-mac.zip.blockmap  # Blockmap for differential updates
  latest-mac.yml              # Auto-update manifest
  builder-debug.yml           # Build debug info
```

### File sizes (approximate)

| Artifact | Size | Notes |
|----------|------|-------|
| Unpacked `.app` | ~250 MB | Includes Chromium, Node.js, native modules |
| DMG | ~90 MB | Compressed |
| ZIP | ~85 MB | Compressed, used for auto-update |

---

## Troubleshooting Builds

### "better-sqlite3 was compiled against a different Node.js version"

Run `pnpm rebuild` to recompile the native module for the current Electron version.

### DMG background not showing

Ensure `resources/dmg-background.png` exists and is 660x400 pixels. Retina displays may need a `@2x` version.

### Build fails with code signing errors

For local development, you can skip signing:

```bash
CSC_IDENTITY_AUTO_DISCOVERY=false pnpm dist:mac
```

This builds an unsigned app. macOS will show "unidentified developer" warnings when opening it.

### electron-builder can't find the icon

The icon path is `resources/icons/TheAtrophiedMind.icns`. Ensure this file exists. You can generate `.icns` from a 1024x1024 PNG using:

```bash
mkdir icon.iconset
sips -z 1024 1024 icon.png --out icon.iconset/icon_512x512@2x.png
# ... (add all required sizes)
iconutil -c icns icon.iconset -o TheAtrophiedMind.icns
```

### Source maps in production build

Source maps are excluded from the package via the `files` filter in `electron-builder.yml`:

```yaml
files:
  - out/**/*
  - "!out/**/*.map"
```

This keeps the bundle smaller while still generating maps during the build for debugging.
