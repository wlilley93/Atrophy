# Building and Distribution

`scripts/build_app.py` builds a macOS `.app` bundle for distribution. The app is a thin launcher — the actual code lives at `~/.atrophy/src/` and auto-updates from GitHub.

---

## Quick Start

```bash
python scripts/build_app.py              # Build to build/
python scripts/build_app.py --install    # Build and install to ~/Applications
python scripts/build_app.py --open       # Build, install, and launch
python scripts/build_app.py --dmg        # Build and create a DMG for distribution
```

---

## Architecture

The `.app` bundle is deliberately thin. It contains:

- A bash launcher script (`Contents/MacOS/TheAtrophiedMind`)
- A bootstrap snapshot of the source (fallback for offline first-run)
- A compiled splash screen binary (Swift/Cocoa)
- The app icon (`.icns`)
- `Info.plist` with `LSUIElement=true` (menu bar app, no Dock icon)

Everything else lives in `~/.atrophy/`:

| Path | Purpose |
|------|---------|
| `~/.atrophy/src/` | Source code (auto-updated from GitHub) |
| `~/.atrophy/venv/` | Python virtual environment |
| `~/.atrophy/agents/` | Agent data, memory databases |
| `~/.atrophy/config.json` | User config |
| `~/.atrophy/logs/` | Launcher and app logs |

---

## Auto-Update Mechanism

On every launch, the launcher:

1. Checks if source exists at `~/.atrophy/src/main.py`
2. If missing (first run), downloads the latest source zip from GitHub. Falls back to the bundled bootstrap snapshot if offline
3. If source exists, downloads the latest zip in the background (non-blocking)
4. Performs an **atomic swap** — downloads to a temp directory, preserves `.env`, renames old → `.old`, new → `src`, cleans up
5. Skips update if last update was less than 5 minutes ago
6. Creates/updates the Python venv if needed
7. Re-installs dependencies if `requirements.txt` hash has changed

**Pushing to GitHub is all you need to ship changes.** No git is required on the user's machine — updates use `curl` + `unzip` from the GitHub archive URL.

---

## First-Run Splash Screen

On first launch (or when dependencies change), the launcher shows a native splash window:

- Dark themed Cocoa window (AppleScript-driven on the launcher side, compiled Swift for the app bundle)
- Progress bar tracking: downloading source → creating venv → installing packages
- Package-level progress updates during `pip install`
- Auto-dismisses when setup completes

---

## Build Process

`build_app.py` performs these steps:

1. **Icon generation** — converts PNGs from `display/icons/` into a `.icns` file via `iconutil` (skipped if `.icns` already exists)
2. **Bootstrap snapshot** — copies a subset of the source tree (main.py, config.py, core/, mcp/, display/, voice/, etc.) into `Resources/bootstrap/`, excluding `__pycache__`, `.pyc`, databases, and avatar files
3. **Info.plist** — generates the plist with bundle ID `com.atrophiedmind.companion`, version from `VERSION` file, microphone usage description, and `LSUIElement=true`
4. **Launcher script** — writes the bash launcher to `Contents/MacOS/TheAtrophiedMind`
5. **Splash screen** — compiles the Swift splash binary into `Resources/splash`
6. **Quarantine clear** — runs `xattr -cr` on the built `.app`

---

## DMG Creation

`--dmg` creates a compressed DMG with:
- The `.app` bundle
- An `Applications` symlink for drag-to-install
- Named `Atrophy-<version>.dmg`

---

## Installation

`--install` copies the `.app` to `/Applications` (if writable) or `~/Applications`. The install location is detected automatically.

To set up as a login item (starts at login, runs in menu bar):

```bash
python scripts/install_app.py install
```

See `scripts/install_app.py` for launchd-based login item management.
