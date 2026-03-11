#!/usr/bin/env python3
"""Build a macOS .app bundle for Atrophy.

Usage:
  python scripts/build_app.py              — Build to build/
  python scripts/build_app.py --install    — Build and install to ~/Applications
  python scripts/build_app.py --open       — Build, install, and launch
  python scripts/build_app.py --dmg        — Build, install, and create a DMG

Architecture:
  The .app is a thin launcher. The actual code lives in ~/.atrophy/src/.
  On every launch the app downloads the latest source zip from GitHub
  in the background, so pushing to the repo is all you need to ship changes.

  No git required. Updates via curl + unzip from GitHub archive URL.

  ~/Applications/Atrophy.app   — launcher (rarely changes)
  ~/.atrophy/src/              — source (auto-updates from GitHub zip)
  ~/.atrophy/venv/             — Python virtual environment
  ~/.atrophy/agents/, etc.     — user data (never overwritten)
"""
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
APP_NAME = "Atrophy"
BUNDLE_ID = "com.atrophiedmind.companion"
BUILD_DIR = PROJECT_DIR / "build"
APP_PATH = BUILD_DIR / f"{APP_NAME}.app"
ICONS_DIR = PROJECT_DIR / "display" / "icons"
ICNS_PATH = ICONS_DIR / "TheAtrophiedMind.icns"
VERSION_FILE = PROJECT_DIR / "VERSION"
ARCHIVE_URL = "https://github.com/wlilley93/Atrophy/archive/refs/heads/main.zip"

# Files/dirs to include in the bootstrap snapshot
INCLUDE = [
    "main.py", "config.py", "server.py", "VERSION",
    "requirements.txt", "db/", "core/", "mcp/", "display/",
    "voice/", "channels/", "agents/", "scripts/", "docs/",
]
# Patterns to exclude from the snapshot
EXCLUDE_PATTERNS = [
    "__pycache__", "*.pyc", "*.pyo", ".DS_Store",
    "agents/*/data/*.db", "agents/*/data/.*",
    "agents/*/avatar/",
]


def _version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text().strip()
    return "0.1.0"


def build_icns():
    """Convert existing PNGs into a macOS .icns file using iconutil."""
    if ICNS_PATH.exists():
        print(f"  .icns exists: {ICNS_PATH.name}")
        return

    iconset = BUILD_DIR / "icon.iconset"
    iconset.mkdir(parents=True, exist_ok=True)

    mappings = [
        ("icon_16x16.png", "icon_16x16.png"),
        ("icon_32x32.png", "icon_16x16@2x.png"),
        ("icon_32x32.png", "icon_32x32.png"),
        ("icon_128x128.png", "icon_32x32@2x.png"),
        ("icon_128x128.png", "icon_128x128.png"),
        ("icon_256x256.png", "icon_128x128@2x.png"),
        ("icon_256x256.png", "icon_256x256.png"),
        ("icon_512x512.png", "icon_256x256@2x.png"),
        ("icon_512x512.png", "icon_512x512.png"),
        ("icon_1024x1024.png", "icon_512x512@2x.png"),
    ]

    for src_name, dst_name in mappings:
        src = ICONS_DIR / src_name
        if not src.exists():
            print(f"  Warning: missing {src}")
            continue
        shutil.copy2(src, iconset / dst_name)

    result = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS_PATH)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  Error building .icns: {result.stderr}")
        sys.exit(1)

    shutil.rmtree(iconset)
    print(f"  Built {ICNS_PATH.name}")


def _copy_snapshot(dest: Path):
    """Copy a bootstrap snapshot of the source tree into dest/."""
    for item in INCLUDE:
        src = PROJECT_DIR / item
        dst = dest / item
        if src.is_dir():
            shutil.copytree(
                src, dst,
                ignore=shutil.ignore_patterns(*EXCLUDE_PATTERNS),
                dirs_exist_ok=True,
            )
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    print(f"  Snapshot: {sum(1 for _ in dest.rglob('*') if _.is_file())} files")


LAUNCHER_SCRIPT = r'''#!/bin/bash
# ─────────────────────────────────────────────────────
#  Atrophy — App Launcher
# ─────────────────────────────────────────────────────
#
#  Code lives in ~/.atrophy/src/ (auto-updated from GitHub).
#  No git required — downloads source zip on each launch.
#  User data lives in ~/.atrophy/ (never overwritten).
#

set -euo pipefail

DATA_DIR="$HOME/.atrophy"
SRC_DIR="$DATA_DIR/src"
VENV_DIR="$DATA_DIR/venv"
LOG_DIR="$DATA_DIR/logs"
BOOTSTRAP="$(dirname "$(dirname "$0")")/Resources/bootstrap"
ARCHIVE_URL="''' + ARCHIVE_URL + r'''"
UPDATE_MARKER="$DATA_DIR/.last_update"

mkdir -p "$DATA_DIR" "$LOG_DIR"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG_DIR/launcher.log"; }

# ── Setup state ──
FIRST_RUN=false

# ── PATH — ensure claude and common tools are discoverable ──
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.local/share/claude:$PATH"

# ── Download source from GitHub zip archive ──
download_source() {
    local tmp_zip="$DATA_DIR/.update.zip"
    local tmp_dir="$DATA_DIR/.update_tmp"

    if ! curl -fsSL --connect-timeout 10 --max-time 60 \
         -o "$tmp_zip" "$ARCHIVE_URL" 2>>"$LOG_DIR/launcher.log"; then
        log "Download failed"
        rm -f "$tmp_zip"
        return 1
    fi

    rm -rf "$tmp_dir"
    mkdir -p "$tmp_dir"
    unzip -qo "$tmp_zip" -d "$tmp_dir" 2>>"$LOG_DIR/launcher.log"

    # GitHub archives extract to repo-name-branch/ — find it
    local extracted
    extracted=$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d | head -1)
    if [ -z "$extracted" ] || [ ! -f "$extracted/main.py" ]; then
        log "Archive extraction failed — no main.py found"
        rm -rf "$tmp_zip" "$tmp_dir"
        return 1
    fi

    # Swap in the new source, preserving user state files
    # Save any local .env so it isn't clobbered
    local saved_env=""
    [ -f "$SRC_DIR/.env" ] && saved_env=$(cat "$SRC_DIR/.env")

    rm -rf "$SRC_DIR"
    mv "$extracted" "$SRC_DIR"

    # Restore .env if it existed
    if [ -n "$saved_env" ]; then
        echo "$saved_env" > "$SRC_DIR/.env"
    fi

    rm -rf "$tmp_zip" "$tmp_dir"
    date -u +%Y-%m-%dT%H:%M:%SZ > "$UPDATE_MARKER"
    log "Updated source from GitHub archive"
    return 0
}

# ── First run: set up source ──
if [ ! -f "$SRC_DIR/main.py" ]; then
    FIRST_RUN=true
    log "First run — setting up source"

    # Try downloading from GitHub
    if ! download_source; then
        # Fallback: use bundled bootstrap
        if [ -d "$BOOTSTRAP" ] && [ -f "$BOOTSTRAP/main.py" ]; then
            log "Using bootstrap snapshot"
            mkdir -p "$SRC_DIR"
            cp -R "$BOOTSTRAP/" "$SRC_DIR/"
        else
            osascript -e 'display alert "Setup Failed" message "Could not download Atrophy source and no bootstrap available.\nCheck your internet connection and try again.\n\nLogs: ~/.atrophy/logs/launcher.log" as critical'
            exit 1
        fi
    fi

    if [ ! -f "$SRC_DIR/main.py" ]; then
        osascript -e 'display alert "Setup Failed" message "Could not set up Atrophy. Check ~/.atrophy/logs/launcher.log" as critical'
        exit 1
    fi
fi

# ── Auto-update in background ──
# Only update if last update was more than 5 minutes ago (avoid hammering GitHub)
should_update=true
if [ -f "$UPDATE_MARKER" ]; then
    last_update=$(date -jf "%Y-%m-%dT%H:%M:%SZ" "$(cat "$UPDATE_MARKER")" +%s 2>/dev/null || echo 0)
    now=$(date +%s)
    elapsed=$(( now - last_update ))
    if [ "$elapsed" -lt 300 ]; then
        should_update=false
    fi
fi

if [ "$should_update" = true ]; then
    (download_source) >>"$LOG_DIR/launcher.log" 2>&1 &
fi

# ── Secrets: source .env from user data, then source dir ──
[ -f "$DATA_DIR/.env" ] && set -a && source "$DATA_DIR/.env" && set +a
[ -f "$SRC_DIR/.env" ] && set -a && source "$SRC_DIR/.env" && set +a

# ── Virtual environment ──
if [ ! -f "$VENV_DIR/bin/python" ]; then
    log "Creating virtual environment"
    PYTHON=""
    for p in python3.12 python3.11 python3 python; do
        if command -v "$p" &>/dev/null; then
            PYTHON="$p"
            break
        fi
    done
    if [ -z "$PYTHON" ]; then
        osascript -e 'display alert "Python Not Found" message "Python 3.11+ is required.\n\nInstall from python.org or:\n  brew install python" as critical'
        exit 1
    fi
    "$PYTHON" -m venv "$VENV_DIR" 2>>"$LOG_DIR/launcher.log"
    "$VENV_DIR/bin/pip" install -q --upgrade pip 2>>"$LOG_DIR/launcher.log"
    log "Venv created with $PYTHON"
fi

# ── Install/update dependencies ──
REQ_FILE="$SRC_DIR/requirements.txt"
HASH_FILE="$VENV_DIR/.requirements_hash"
if [ -f "$REQ_FILE" ]; then
    CURRENT_HASH=$(md5 -q "$REQ_FILE" 2>/dev/null || md5sum "$REQ_FILE" | cut -d' ' -f1)
    STORED_HASH=""
    [ -f "$HASH_FILE" ] && STORED_HASH=$(cat "$HASH_FILE")
    if [ "$CURRENT_HASH" != "$STORED_HASH" ]; then
        log "Installing dependencies"
        "$VENV_DIR/bin/pip" install -q -r "$REQ_FILE" 2>>"$LOG_DIR/launcher.log"
        echo "$CURRENT_HASH" > "$HASH_FILE"
        log "Dependencies installed"
    fi
fi

# ── Launch ──
export ATROPHY_BUNDLE="$SRC_DIR"
source "$VENV_DIR/bin/activate"
cd "$SRC_DIR"
exec python main.py --app 2>>"$LOG_DIR/app.stderr.log"
'''


def build_app():
    """Create the .app bundle."""
    version = _version()

    if APP_PATH.exists():
        shutil.rmtree(APP_PATH)

    contents = APP_PATH / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    bootstrap = resources / "bootstrap"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)

    # ── Bootstrap snapshot (used for offline first-run only) ──
    _copy_snapshot(bootstrap)

    # ── Info.plist ──
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>{APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>{APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>{BUNDLE_ID}</string>
    <key>CFBundleVersion</key>
    <string>{version}</string>
    <key>CFBundleShortVersionString</key>
    <string>{version}</string>
    <key>CFBundleExecutable</key>
    <string>TheAtrophiedMind</string>
    <key>CFBundleIconFile</key>
    <string>TheAtrophiedMind</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSMicrophoneUsageDescription</key>
    <string>Atrophy needs microphone access for voice input.</string>
</dict>
</plist>
"""
    (contents / "Info.plist").write_text(plist)

    # ── Launcher script ──
    launcher_path = macos / "TheAtrophiedMind"
    launcher_path.write_text(LAUNCHER_SCRIPT)
    launcher_path.chmod(launcher_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    # ── Icon ──
    if ICNS_PATH.exists():
        shutil.copy2(ICNS_PATH, resources / "TheAtrophiedMind.icns")

    # ── Clear quarantine ──
    subprocess.run(["xattr", "-cr", str(APP_PATH)], capture_output=True)

    print(f"  Built {APP_PATH}")
    print(f"  Version: {version}")
    return APP_PATH


def _install_dir() -> Path:
    """Pick install location — /Applications if writable, else ~/Applications."""
    system_apps = Path("/Applications")
    try:
        test = system_apps / ".atrophy_write_test"
        test.touch()
        test.unlink()
        return system_apps
    except (PermissionError, OSError):
        return Path.home() / "Applications"


def install():
    """Install to Applications folder."""
    apps_dir = _install_dir()
    apps_dir.mkdir(exist_ok=True)
    dest = apps_dir / f"{APP_NAME}.app"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(APP_PATH, dest)
    subprocess.run(["xattr", "-cr", str(dest)], capture_output=True)
    print(f"  Installed to {dest}")
    return dest


def build_dmg(app_path: Path):
    """Create a DMG with the .app and an Applications symlink for drag-install."""
    version = _version()
    dmg_name = f"{APP_NAME}-{version}"
    dmg_path = BUILD_DIR / f"{dmg_name}.dmg"
    staging = BUILD_DIR / f"{dmg_name}-staging"

    # Clean previous
    if dmg_path.exists():
        dmg_path.unlink()
    if staging.exists():
        shutil.rmtree(staging)

    staging.mkdir(parents=True)

    # Copy .app into staging
    shutil.copytree(app_path, staging / f"{APP_NAME}.app")

    # Create Applications symlink (the drag-to-install target)
    os.symlink("/Applications", staging / "Applications")

    # Create the DMG
    result = subprocess.run([
        "hdiutil", "create",
        "-volname", APP_NAME,
        "-srcfolder", str(staging),
        "-ov",
        "-format", "UDZO",  # compressed
        str(dmg_path),
    ], capture_output=True, text=True)

    shutil.rmtree(staging)

    if result.returncode != 0:
        print(f"  DMG creation failed: {result.stderr}")
        sys.exit(1)

    print(f"  DMG: {dmg_path}")
    print(f"  Size: {dmg_path.stat().st_size / 1024 / 1024:.1f} MB")
    return dmg_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description=f"Build {APP_NAME}.app")
    parser.add_argument("--install", action="store_true", help="Install to ~/Applications")
    parser.add_argument("--open", action="store_true", help="Install and launch")
    parser.add_argument("--dmg", action="store_true", help="Build a DMG for distribution")
    args = parser.parse_args()

    print()
    print(f"  Building {APP_NAME}.app")
    print(f"  Source: {PROJECT_DIR}")
    print(f"  Archive: {ARCHIVE_URL}")
    print()

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    build_icns()
    app_path = build_app()

    if args.install or args.open:
        app_path = install()

    if args.dmg:
        build_dmg(APP_PATH)

    if args.open:
        subprocess.run(["open", str(app_path)])

    print()
    print("  Done.")
    print()
    print("  How it works:")
    print("    1. First launch downloads source from GitHub (or uses bootstrap)")
    print("    2. Creates a Python venv at ~/.atrophy/venv/")
    print("    3. Every launch checks for updates via GitHub zip archive")
    print("    4. Push to GitHub → app updates automatically (no git needed)")
    print()
    if args.dmg:
        print(f"  Distribute: {BUILD_DIR / f'{APP_NAME}-{_version()}.dmg'}")
    else:
        print(f"  To create a DMG: python scripts/build_app.py --dmg")
    print()


if __name__ == "__main__":
    main()
