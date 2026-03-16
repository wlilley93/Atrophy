# Building and Distribution

The Electron app is built using `electron-vite` for compilation and `electron-builder` for packaging. The result is a self-contained macOS `.app` bundle with auto-update support via GitHub Releases. This guide covers the full build pipeline from source compilation through DMG creation, code signing, auto-update configuration, and common troubleshooting scenarios.

---

## Quick Start

The build system exposes four primary commands through `package.json` scripts. Each command builds on the previous one, so `dist` includes both compilation and packaging in a single invocation.

```bash
pnpm build                    # Compile TypeScript + bundle renderer
pnpm pack                     # Build + create unpacked .app directory
pnpm dist                     # Build + create DMG + ZIP
pnpm dist:mac                 # Same as dist, explicitly targeting macOS
```

For day-to-day development, `pnpm dev` (covered in the Development Workflow section below) is the primary command. The build commands above are used when preparing a release or verifying that the packaged app behaves correctly.

---

## Architecture

The `.app` bundle is a full Electron application containing everything needed to run without external dependencies (aside from the system Python for MCP servers). Understanding what goes into the bundle helps diagnose size issues, missing resources, and runtime path resolution problems.

The bundle contains the following components:

- Compiled TypeScript (main process, preload, renderer) in `out/`
- The Electron runtime (Chromium + Node.js)
- Native dependencies (`better-sqlite3`, rebuilt for Electron's Node.js headers)
- Bundled resources (MCP servers, scripts, agents, database schema)
- The app icon (`TheAtrophiedMind.icns`)

Runtime user data lives in `~/.atrophy/`, separate from the bundle itself. This separation means the bundle is read-only after installation, while all mutable state (databases, config, secrets, models) lives in the user's home directory. The following table lists every user data path and its purpose:

| Path | Purpose |
|------|---------|
| `~/.atrophy/agents/` | Agent data, memory databases, avatar files |
| `~/.atrophy/config.json` | User config (mode 0600) |
| `~/.atrophy/.env` | Secrets - API keys, tokens (mode 0600) |
| `~/.atrophy/models/` | Cached embedding models (Transformers.js WASM) |
| `~/.atrophy/logs/` | Job execution logs |
| `~/.atrophy/server_token` | HTTP API auth token (mode 0600) |
| `~/.atrophy/agent_states.json` | Per-agent muted/enabled state |

The `ensureUserData()` function in `src/main/config.ts` creates this directory structure on first launch, and `migrateAgentData()` copies bundled agent definitions into it so agents can be customised without modifying the bundle.

---

## Build Process

The build pipeline has two distinct steps: compilation (turning TypeScript and Svelte into JavaScript) and packaging (wrapping the compiled output into a distributable `.app` bundle). These steps are separate because compilation is needed during development too, while packaging is only needed for distribution.

### Step 1: Compile (`pnpm build`)

The `build` script runs two separate build steps because of an electron-vite 5 bug that drops Svelte plugins during its config resolution pipeline. The workaround uses a standalone `vite.renderer.config.ts` for the renderer while electron-vite handles the main process and preload.

```bash
electron-vite build -c electron-vite.config.ts && vite build --config vite.renderer.config.ts
```

This two-command approach is a temporary workaround. If electron-vite fixes the Svelte plugin issue in a future release, both builds could be consolidated into a single `electron-vite build` invocation.

#### Main process and preload (`electron-vite.config.ts`)

The main process and preload script are compiled together by electron-vite. The configuration below defines their entry points and externalisation strategy.

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

The `externalizeDepsPlugin()` is critical for the main process build. It ensures that Node.js built-ins and `node_modules` dependencies (like `better-sqlite3`, `electron-updater`) are not bundled into the output - they remain as external requires resolved at runtime from the `node_modules` directory inside the packaged app. Without this, native modules would fail because Rollup cannot bundle compiled C++ addons.

This step produces two output files:

- `out/main/index.js` - compiled main process
- `out/preload/index.mjs` - compiled preload script

#### Renderer (`vite.renderer.config.ts`)

The renderer is compiled separately using a standalone Vite config. Unlike the main process, the renderer bundles all of its dependencies (Svelte runtime, component code, styles) into a single output since it runs in a browser-like environment.

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

Each setting in this config serves a specific purpose in the Electron context:

- `target: 'chrome130'` - targets Electron's Chromium version (Electron 34 ships Chromium 130), enabling modern JS features without polyfills
- `modulePreload: { polyfill: false }` - Electron's Chromium supports native module preload, so the Vite polyfill is unnecessary overhead
- `minify: false` - keeps output readable for debugging; the app is not served over a network, so bundle size matters less than debuggability
- `base: './'` - uses relative paths for loading from the file system, since the renderer loads via `file://` protocol in production
- `envPrefix` - only `RENDERER_VITE_` and `VITE_` prefixed env vars are exposed to the renderer, preventing accidental leakage of secrets

This step produces the renderer output:

- `out/renderer/index.html` - the renderer entry point
- `out/renderer/assets/` - bundled CSS, JS, images

### Step 2: Package (`pnpm pack` or `pnpm dist`)

After compilation, `electron-builder` takes the compiled output and creates the distributable. The packaging step performs several operations that transform the development output into a standalone macOS application.

1. **Copies compiled code** from `out/` into the `.app` bundle
2. **Bundles extra resources** - MCP Python servers, scripts, agent definitions, database schema are copied into `Contents/Resources/`
3. **Installs production dependencies** - only packages listed in `dependencies` (not `devDependencies`) are included
4. **Rebuilds native modules** - `better-sqlite3` is compiled against the Electron Node.js headers
5. **Signs the app** with hardened runtime entitlements (required for macOS notarization)
6. **Creates installers** - DMG with custom background and Applications symlink, plus a ZIP for auto-update

The distinction between `pnpm pack` and `pnpm dist` is that `pack` creates only the unpacked `.app` directory (useful for quick verification), while `dist` also generates the DMG and ZIP installers.

---

## Full electron-builder.yml Reference

The build configuration lives at `electron-builder.yml` in the project root. This file controls everything from the app identifier and icon to the packaging targets and update publishing. Every field is documented inline below.

```yaml
appId: com.atrophy.app
productName: Atrophy
copyright: Copyright (c) 2024-2026 Atrophy

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

These directories are copied into the `.app` bundle's `Contents/Resources/` during packaging and are accessible at runtime via `process.resourcesPath`. They contain the Python and data files that the Electron app needs but does not compile from TypeScript.

| Source | Destination | Filter | Contents |
|--------|------------|--------|----------|
| `mcp/` | `mcp/` | `**/*.py` | Python MCP servers (`memory_server.py`, `google_server.py`) |
| `scripts/` | `scripts/` | `**/*` | Python standalone scripts (Google auth, cron jobs, agent tasks) |
| `agents/` | `agents/` | `**/*` | Default agent definitions (`agent.json`, prompts, avatar source) |
| `db/` | `db/` | `**/*.sql` | Database schema (`schema.sql`) |

At runtime, `BUNDLE_ROOT` in `src/main/config.ts` resolves these paths differently depending on whether the app is running in development or as a packaged bundle. This dual-path resolution is what allows the same code to work in both contexts.

```typescript
// In packaged app:
const BUNDLE_ROOT = process.resourcesPath;  // Contents/Resources/

// In development:
const BUNDLE_ROOT = path.resolve(__dirname, '..', '..');  // Project root
```

With this resolution in place, `path.join(BUNDLE_ROOT, 'mcp', 'memory_server.py')` correctly locates the MCP server script regardless of whether the code is running from `pnpm dev` or from the installed `.app`.

#### Whisper.cpp (currently commented out)

The whisper.cpp binary is not yet bundled because the STT pipeline is still in development. When whisper.cpp is ready to bundle, the following entry should be uncommented in `electron-builder.yml`:

```yaml
    - from: vendor/whisper.cpp
      to: whisper
      filter:
        - "**/*"
```

This will copy the built whisper binary and model into `Contents/Resources/whisper/`. The config paths (`WHISPER_BIN`, `WHISPER_MODEL`) will need to be updated to resolve from `process.resourcesPath` in packaged mode.

---

## DMG Customization

The DMG is created automatically as part of `pnpm dist`. The installer window provides a standard macOS drag-to-install experience with a custom background image and pre-positioned icons. The layout is designed so the user sees the app icon on the left and the Applications folder shortcut on the right, with a visual arrow guiding the drag action.

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

The following table documents each DMG configuration setting and its effect on the installer appearance:

| Setting | Value | Description |
|---------|-------|-------------|
| `title` | `Atrophy` | Window title shown in the Finder title bar |
| `artifactName` | `${productName}-${version}-${arch}.${ext}` | Output filename (e.g. `Atrophy-0.1.2-arm64.dmg`) |
| `background` | `resources/dmg-background.png` | Custom background image (660x400 px recommended) |
| `iconSize` | `80` | Size of icons in the DMG window |
| `window.width` | `660` | DMG window width in pixels |
| `window.height` | `400` | DMG window height in pixels |
| App position | `(180, 200)` | Left side of window, where the app icon appears |
| Applications link | `(480, 200)` | Right side of window, where the Applications symlink appears |

The background image should be placed at `resources/dmg-background.png`. If missing, electron-builder uses a default white background. For Retina displays, consider providing a `@2x` version at 1320x800 pixels.

---

## Code Signing

Code signing is required for macOS distribution. Without it, users see "unidentified developer" warnings and Gatekeeper may block the app entirely. The signing process involves two components: hardened runtime entitlements and a developer certificate.

### Hardened Runtime

The app uses macOS hardened runtime, which restricts the app's capabilities to only those explicitly declared. The entitlements are configured via a plist file at `build/entitlements.mac.plist`. Each entitlement is required for a specific Electron or application feature.

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

The following table explains why each entitlement is necessary. Removing any of these would break a specific feature of the application:

| Entitlement | Why it is needed |
|-------------|-----------------|
| `cs.allow-jit` | Required by Electron's V8 JavaScript engine for JIT compilation |
| `cs.allow-unsigned-executable-memory` | Required by Electron's V8 and WASM (Transformers.js embeddings) |
| `device.audio-input` | Microphone access for speech-to-text via whisper.cpp |
| `network.client` | Outbound HTTP for ElevenLabs TTS, Telegram Bot API, auto-update checks |
| `network.server` | Inbound HTTP for the `--server` mode API |
| `files.user-selected.read-write` | File system access for `~/.atrophy/` user data directory |

The same plist is used for both `entitlements` (main process) and `entitlementsInherit` (child processes like whisper.cpp and Python MCP servers). This means child processes inherit the same capability set, which is necessary because the Python MCP servers need network and file access to function.

### Signing for distribution

The app is signed with a Developer ID Application certificate from Apple. The signing identity is resolved by `CSC_NAME` (just the name and team ID, without the "Developer ID Application:" prefix - electron-builder adds that automatically).

Signing environment variables are stored in `~/.atrophy/signing/.env.signing` and sourced before builds:

```bash
source ~/.atrophy/signing/.env.signing
pnpm dist
```

The `.env.signing` file contains:

```bash
export APPLE_ID="your@email.com"
export APPLE_APP_SPECIFIC_PASSWORD="xxxx-xxxx-xxxx-xxxx"
export APPLE_TEAM_ID="XXXXXXXXXX"
export CSC_NAME="Your Name (TEAMID)"
```

The app-specific password is generated at https://appleid.apple.com/account/manage under "Sign-In and Security" > "App-Specific Passwords". The `CSC_NAME` value comes from `security find-identity -v -p codesigning` and should match the common name of your Developer ID Application certificate without the "Developer ID Application:" prefix.

If this file is missing, check `~/.atrophy-backup3/signing/` for a previous copy. The `scripts/apple-dev-setup.ts` script can regenerate it interactively.

`CSC_NAME` must **not** include the "Developer ID Application:" prefix - electron-builder detects the certificate type automatically and rejects the prefixed form.

If building without a certificate (local development only), skip signing entirely:

```bash
CSC_IDENTITY_AUTO_DISCOVERY=false pnpm dist:mac
```

### Notarization

Notarization is enabled via `notarize: true` in `electron-builder.yml`. When the `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, and `APPLE_TEAM_ID` environment variables are set, electron-builder automatically submits the signed app to Apple's notary service after signing. The notarization process uploads the app, Apple scans it for malware, and the ticket is stapled to the app. This typically takes 1-3 minutes.

### Certificate setup

If setting up signing from scratch:

1. Enroll in the Apple Developer Program
2. Create a Developer ID Application certificate in the Apple Developer portal
3. Download the `.cer` file and your private key, combine into a `.p12` bundle
4. Import the `.p12` into your macOS keychain (use `openssl pkcs12 -export -legacy` if using openssl 3.x - the `-legacy` flag is required for macOS keychain compatibility)
5. Download and import Apple's Developer ID G2 intermediate certificate
6. Verify with `security find-identity -v -p codesigning` - should show your identity

---

## Auto-Update Flow

Auto-update is handled by `electron-updater` (v6.8.3) with GitHub Releases as the update provider. The implementation lives in `src/main/updater.ts` and follows a four-phase lifecycle: check, notify, download, and install. The user has full control over when downloads and installations happen - nothing is forced.

### Configuration

The publish configuration in `electron-builder.yml` tells `electron-updater` where to look for new releases. The `provider`, `owner`, and `repo` fields must match the GitHub repository where release artifacts are uploaded.

```yaml
# In electron-builder.yml
publish:
  provider: github
  owner: wlilley93
  repo: Atrophy
```

### Initialization

`initAutoUpdater()` is called after the main window is created. It configures the updater's behavior and registers event handlers that bridge the update lifecycle to the renderer process via IPC. The function takes the following steps:

1. Skips initialization entirely if `ELECTRON_RENDERER_URL` is set (dev mode), because checking for updates during development is pointless and would hit the GitHub API unnecessarily
2. Disables auto-download (`autoDownload = false`) - the user must explicitly choose to download, preventing surprise bandwidth usage
3. Enables auto-install on quit (`autoInstallOnAppQuit = true`), so a downloaded update is applied next time the user quits naturally
4. Registers event handlers that forward update events to the renderer via IPC for display in the UI
5. Triggers an initial update check after a 5-second delay, giving the app time to finish startup

### Update lifecycle

The update lifecycle follows four phases. Each phase involves communication between the main process (which manages the updater) and the renderer process (which displays UI feedback to the user).

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

The key design decision here is that the download phase is always user-initiated. The app never downloads an update in the background without the user's knowledge. This keeps bandwidth usage predictable and avoids surprises on metered connections.

### IPC events sent to renderer

The following events flow from the main process to the renderer, allowing the UI to display update status, progress bars, and action buttons:

| Event | Payload | Description |
|-------|---------|-------------|
| `updater:available` | `{ version: string, releaseNotes: string }` | A newer version is available |
| `updater:not-available` | (none) | Current version is up to date |
| `updater:progress` | `{ percent: number, bytesPerSecond: number, transferred: number, total: number }` | Download progress for UI progress bars |
| `updater:downloaded` | `{ version: string }` | Update downloaded and ready to install |
| `updater:error` | `string` (error message) | Update check or download failed |

### IPC handlers (renderer to main)

These channels allow the renderer to trigger update actions in response to user interaction (clicking "Download" or "Install" buttons):

| Channel | Action |
|---------|--------|
| `updater:check` | Manually trigger an update check |
| `updater:download` | Start downloading an available update |
| `updater:quitAndInstall` | Quit the app and install the downloaded update |

### Error handling

All update operations (check, download) use `.catch(() => {})` to silently swallow errors. This is intentional - update failures are non-critical, and the app should continue running normally regardless of whether GitHub is reachable or the update manifest is malformed. The error is still forwarded to the renderer as `updater:error` so the UI can display it if desired.

### Creating a release

Releasing a new version involves updating the version number, building the distributables, and uploading them to a GitHub Release. The process is manual to keep full control over what gets published.

First, update the version in `package.json`. This version string becomes the release tag and is embedded in the bundle manifest.

```json
"version": "1.2.7"
```

Then build and sign/notarize the DMG:

```bash
source ~/.atrophy/signing/.env.signing
pnpm build
pnpm electron-rebuild
npx electron-builder --mac dmg
```

Build the hot bundle (for self-updating existing installs):

```bash
pnpm bundle
```

Create a GitHub Release with the version tag (e.g. `v1.2.7`). Upload the following artifacts from `dist/`:

```bash
gh release create v1.2.7 \
  dist/Atrophy-1.2.7-arm64.dmg \
  dist/bundle.tar.gz \
  dist/bundle-manifest.json \
  --title "v1.2.7" --notes "Release notes here"
```

- `Atrophy-1.2.7-arm64.dmg` - the signed+notarized installer for new users
- `bundle.tar.gz` - hot bundle for self-updating existing installs (contains `out/` minus bootstrap)
- `bundle-manifest.json` - version, SHA-256, and timestamp for the hot bundle

The DMG is only needed for first-time installs. Existing users receive updates via the hot bundle system - on each boot, the app checks GitHub Releases for a newer `bundle.tar.gz`, downloads it to `~/.atrophy/bundle/`, and loads it on the next launch. See `src/main/bundle-updater.ts` for the full self-update flow.

### CI/CD - automatic hot bundle releases

A GitHub Actions workflow (`.github/workflows/bundle.yml`) runs on every push to `main` that touches code (docs-only and markdown-only changes are skipped). It:

1. Bumps the patch version in `package.json`
2. Builds the hot bundle (`out/` minus bootstrap)
3. Commits the version bump with `[skip ci]` to prevent loops
4. Creates a GitHub Release with `bundle.tar.gz` and `bundle-manifest.json`

The workflow can also be triggered manually from the Actions tab with a choice of patch/minor/major bump.

This means: push code to main, and existing app installs will pick up the change on their next restart. No manual `pnpm bundle` or `gh release create` needed for code changes. DMG builds (for new installs) are still done locally with notarization since they require macOS and Apple credentials.

---

## Native Dependencies

The project has four runtime dependencies. Only one (`better-sqlite3`) is a native C++ module that requires compilation against Electron's Node.js headers. The others are either pure JavaScript or WASM-based and work without any native compilation step.

| Package | Version | Type | Rebuild Required | Notes |
|---------|---------|------|-----------------|-------|
| `better-sqlite3` | 12.6.2 | Native (C++) | Yes | Synchronous SQLite API. Must be rebuilt against Electron's Node.js headers. |
| `@xenova/transformers` | 2.17.2 | WASM | No | Local ML inference (all-MiniLM-L6-v2 embeddings). Pure WebAssembly, runs in worker threads. |
| `electron-updater` | 6.8.3 | JavaScript | No | Auto-update client for GitHub Releases. |
| `uuid` | 13.0.0 | JavaScript | No | UUID generation for sessions and inference tracking. |

### Rebuilding native modules

The `rebuild` script in `package.json` recompiles `better-sqlite3` against the Electron Node.js headers. This is necessary because Electron ships its own version of Node.js, which may have a different ABI (Application Binary Interface) than the system Node.js used during `pnpm install`.

```bash
electron-rebuild -f -w better-sqlite3
```

The `-f` flag forces a rebuild even if the module appears up to date, which is useful when switching Electron versions. The `-w` flag targets only `better-sqlite3`, skipping other dependencies that do not need native compilation.

This command must be run in three situations:

- After `pnpm install` (first time setup)
- After upgrading Electron to a new major version (ABI may change)
- After upgrading `better-sqlite3` (new native code needs compilation)

---

## Login Item

The Python version of the app used launchd plists to configure start-at-login behavior. The Electron rewrite uses Electron's built-in login item management instead, which is simpler and does not require generating or loading plist files.

The following code shows how login item management works at the Electron API level:

```typescript
import { app } from 'electron';

// Enable start at login
app.setLoginItemSettings({ openAtLogin: true });

// Check status
const settings = app.getLoginItemSettings();
console.log(settings.openAtLogin); // true or false
```

This functionality is exposed to the renderer via two IPC channels, allowing the Settings panel to display and toggle the login item state:

- `install:isEnabled` - returns `boolean` indicating whether the app is configured to start at login
- `install:toggle` - accepts `boolean` to enable or disable start-at-login

The login item can be toggled from the Settings panel under the General tab.

---

## Development Workflow

### Dev mode with HMR

During development, the app runs with hot module replacement for the renderer, enabling instant feedback on UI changes without restarting the entire Electron process.

```bash
pnpm dev
```

The dev script (`scripts/dev.ts`) orchestrates two parallel processes that work together to provide the development experience:

1. **Renderer Vite server** on port 5173 with hot module replacement - serves the Svelte renderer and pushes updates to the running app when component files change
2. **electron-vite** for main/preload compilation + Electron launch - watches for changes in main process files and restarts Electron when they change

The `ELECTRON_RENDERER_URL` environment variable is set to `http://localhost:5173/` so the main process loads the renderer from the dev server instead of the built HTML file. This enables instant Svelte component updates without restarting Electron. The auto-updater detects this variable and skips initialization in dev mode.

Main process changes require a full restart (kill and re-run `pnpm dev`) because the main process runs in Node.js, not in a browser that can hot-swap modules.

### Type checking

Type checking verifies the TypeScript code without producing output. The project uses two separate `tsconfig` files because the main process targets Node.js APIs while the renderer targets browser APIs, and these have different type definitions.

```bash
pnpm typecheck                # Check both main (node) and renderer (web) TypeScript
pnpm typecheck:node           # Main + preload only (tsconfig.node.json)
pnpm typecheck:web            # Renderer only (tsconfig.web.json)
```

### Testing

Tests use Vitest, which shares the same Vite configuration as the build system. This means test module resolution, TypeScript compilation, and path aliases all work identically to the production build.

```bash
pnpm test                     # Run Vitest tests (single run)
pnpm test:watch               # Watch mode (re-runs on file changes)
```

### Build verification

When you need to verify the packaged app works correctly without creating a full DMG, use `pnpm pack` to create an unpacked `.app` directory. This is faster than `pnpm dist` because it skips DMG and ZIP creation.

```bash
pnpm pack                     # Build + create unpacked .app (fast, no DMG)
```

The unpacked `.app` is output to `dist/mac-arm64/` (or `dist/mac/` on Intel). You can run it directly to test the packaged behavior:

```bash
open dist/mac-arm64/Atrophy.app
```

---

## Build Output Structure

Understanding the build output helps with debugging path issues, verifying that resources are correctly bundled, and estimating distribution sizes.

### After `pnpm build`

The `out/` directory contains the compiled source code, organized by process. This is the intermediate output that gets packaged into the `.app` bundle.

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

The `dist/` directory contains everything produced by electron-builder. The unpacked `.app` directory is useful for inspecting the bundle contents, while the DMG and ZIP are the actual distribution artifacts.

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

The following sizes are typical for an arm64 build. The uncompressed `.app` is large because it includes the full Chromium and Node.js runtimes. The DMG and ZIP are significantly smaller due to compression.

| Artifact | Size | Notes |
|----------|------|-------|
| Unpacked `.app` | ~250 MB | Includes Chromium, Node.js, native modules |
| DMG | ~90 MB | Compressed disk image |
| ZIP | ~85 MB | Compressed, used for auto-update |

---

## Troubleshooting Builds

### "better-sqlite3 was compiled against a different Node.js version"

This error occurs when `better-sqlite3` was compiled against the system Node.js but Electron needs it compiled against its own Node.js headers. The ABI versions do not match, so the native module fails to load. Run `pnpm rebuild` to recompile the native module for the current Electron version.

### DMG background not showing

Ensure `resources/dmg-background.png` exists and is 660x400 pixels. Retina displays may need a `@2x` version at 1320x800 pixels. If the file is missing, electron-builder silently falls back to a plain white background rather than failing the build.

### Build fails with code signing errors

For local development, you can skip signing entirely by setting the `CSC_IDENTITY_AUTO_DISCOVERY` environment variable to false:

```bash
CSC_IDENTITY_AUTO_DISCOVERY=false pnpm dist:mac
```

This builds an unsigned app. macOS will show "unidentified developer" warnings when opening it, but it is fully functional for local testing.

### electron-builder can't find the icon

The icon path is `resources/icons/TheAtrophiedMind.icns`. Ensure this file exists. If you need to generate an `.icns` file from a source PNG, the following commands create the required iconset directory and convert it:

```bash
mkdir icon.iconset
sips -z 1024 1024 icon.png --out icon.iconset/icon_512x512@2x.png
# ... (add all required sizes)
iconutil -c icns icon.iconset -o TheAtrophiedMind.icns
```

### Source maps in production build

Source maps are excluded from the package via the `files` filter in `electron-builder.yml`. This keeps the bundle smaller while still generating maps during the build for local debugging.

```yaml
files:
  - out/**/*
  - "!out/**/*.map"
```

The maps remain in the `out/` directory after `pnpm build`, so you can still use them for debugging the compiled output locally. They are only excluded from the packaged `.app` and its installers.
