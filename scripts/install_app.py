#!/usr/bin/env python3
"""Install / uninstall The Atrophied Mind as a login item.

Usage:
  python scripts/install_app.py install   — Register launchd agent (starts at login)
  python scripts/install_app.py uninstall — Remove launchd agent
  python scripts/install_app.py status    — Check if installed and running

The launchd agent opens the .app at login. The .app itself handles
source updates (git pull), venv management, and launching Python.
"""

import subprocess
import sys
from pathlib import Path

LABEL = "com.atrophiedmind.companion"
PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = PLIST_DIR / f"{LABEL}.plist"

APP_NAME = "Atrophy"
USER_DATA = Path.home() / ".atrophy"
LOG_DIR = USER_DATA / "logs"


def _find_app() -> Path:
    """Find the installed .app — check /Applications first, then ~/Applications."""
    for base in [Path("/Applications"), Path.home() / "Applications"]:
        candidate = base / f"{APP_NAME}.app"
        if candidate.exists():
            return candidate
    return Path.home() / "Applications" / f"{APP_NAME}.app"


APP_PATH = _find_app()


def _plist_content() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/open</string>
        <string>-a</string>
        <string>{APP_PATH}</string>
        <string>--args</string>
        <string>--launched-by-launchd</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>StandardOutPath</key>
    <string>{LOG_DIR}/launchd.stdout.log</string>

    <key>StandardErrorPath</key>
    <string>{LOG_DIR}/launchd.stderr.log</string>

    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
"""


def install():
    if not APP_PATH.exists():
        print(f"  Error: {APP_PATH} not found.")
        print(f"  Run 'python scripts/build_app.py --install' first.")
        return

    PLIST_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Unload first if already installed
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)],
                       capture_output=True)

    PLIST_PATH.write_text(_plist_content())
    print(f"  Wrote {PLIST_PATH}")

    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
    print(f"  Loaded {LABEL}")
    print()
    print("  The Atrophied Mind will now start at login.")
    print("  It restarts automatically if it crashes.")
    print(f"  Logs: {LOG_DIR}/")


def uninstall():
    if not PLIST_PATH.exists():
        print("  Not installed.")
        return

    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=True)
    PLIST_PATH.unlink()
    print(f"  Unloaded and removed {LABEL}")


def status():
    result = subprocess.run(
        ["launchctl", "list", LABEL],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"  {LABEL}: running")
        for line in result.stdout.strip().splitlines():
            print(f"    {line}")
    else:
        installed = "installed" if PLIST_PATH.exists() else "not installed"
        print(f"  {LABEL}: not running ({installed})")

    # Also check the .app
    if APP_PATH.exists():
        print(f"  App: {APP_PATH}")
    else:
        print(f"  App: not found at {APP_PATH}")

    src = USER_DATA / "src"
    if src.exists():
        print(f"  Source: {src}")
    else:
        print(f"  Source: not yet cloned (will clone on first launch)")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("install", "uninstall", "status"):
        print(__doc__)
        sys.exit(1)

    {"install": install, "uninstall": uninstall, "status": status}[sys.argv[1]]()


if __name__ == "__main__":
    main()
