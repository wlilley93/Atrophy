#!/usr/bin/env python3
"""Install / uninstall The Atrophied Mind as a menu bar app.

Usage:
  python scripts/install_app.py install   — Register launchd agent (starts at login)
  python scripts/install_app.py uninstall — Remove launchd agent
  python scripts/install_app.py status    — Check if installed and running
"""

import os
import subprocess
import sys
from pathlib import Path

LABEL = "com.atrophiedmind.companion"
PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH = PLIST_DIR / f"{LABEL}.plist"

PROJECT_DIR = Path(__file__).resolve().parent.parent
MAIN_PY = PROJECT_DIR / "main.py"
USER_DATA = Path.home() / ".atrophy"
LOG_DIR = USER_DATA / "logs"


def _python_path() -> str:
    """Find the python that has the project's dependencies."""
    # Prefer the venv in the project, then pyenv, then system
    venv = PROJECT_DIR / ".venv" / "bin" / "python"
    if venv.exists():
        return str(venv)
    return sys.executable


def _plist_content() -> str:
    python = _python_path()
    log_dir = str(LOG_DIR)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{MAIN_PY}</string>
        <string>--app</string>
    </array>

    <key>WorkingDirectory</key>
    <string>{PROJECT_DIR}</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>StandardOutPath</key>
    <string>{log_dir}/app.stdout.log</string>

    <key>StandardErrorPath</key>
    <string>{log_dir}/app.stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:{Path(python).parent}</string>
    </dict>
</dict>
</plist>
"""


def install():
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
    print("  The Atrophied Mind is now a menu bar app.")
    print("  It will start at login and restart if it crashes.")
    print(f"  Logs: {LOG_DIR}/app.*.log")


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


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("install", "uninstall", "status"):
        print(__doc__)
        sys.exit(1)

    {"install": install, "uninstall": uninstall, "status": status}[sys.argv[1]]()


if __name__ == "__main__":
    main()
