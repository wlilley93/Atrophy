"""User presence status - active/away tracking.

Status is persisted to disk so cron jobs can check it.
Any user input (text or voice) sets status to active.
10 minutes of no input sets status to away.
User can explicitly say "going to bed", "logging off", etc.
"""
import json
import re
from datetime import datetime
from config import USER_STATUS_FILE

_AWAY_PATTERNS = re.compile(
    r'\b('
    r'going to bed|going to sleep|heading to bed|off to bed|'
    r'logging off|signing off|heading off|heading out|'
    r'going out|stepping out|stepping away|'
    r'gotta go|got to go|have to go|need to go|'
    r'talk later|talk tomorrow|see you later|see you tomorrow|'
    r'goodnight|good night|night night|nighty night|'
    r'i\'m out|i\'m off|i\'m done|'
    r'catch you later|brb|be right back|'
    r'shutting down|closing up|calling it'
    r')\b',
    re.IGNORECASE,
)

IDLE_TIMEOUT_SECS = 600  # 10 minutes


def get_status() -> dict:
    """Read current status. Returns {status, reason, since}."""
    if USER_STATUS_FILE.exists():
        try:
            return json.loads(USER_STATUS_FILE.read_text())
        except Exception:
            pass
    return {"status": "active", "reason": "", "since": datetime.now().isoformat()}


def set_status(status: str, reason: str = ""):
    """Write status to disk."""
    USER_STATUS_FILE.write_text(json.dumps({
        "status": status,
        "reason": reason,
        "since": datetime.now().isoformat(),
    }))


def set_active():
    """Mark user as active (any input resets this).
    Preserves previous away reason in 'returned_from' for one cycle.
    """
    current = get_status()
    if current["status"] != "active":
        data = {
            "status": "active",
            "reason": "",
            "since": datetime.now().isoformat(),
            "returned_from": current.get("reason", ""),
            "away_since": current.get("since", ""),
        }
        USER_STATUS_FILE.write_text(json.dumps(data))
    else:
        # Already active - clear returned_from after first read
        if current.get("returned_from"):
            current.pop("returned_from", None)
            current.pop("away_since", None)
            USER_STATUS_FILE.write_text(json.dumps(current))


def set_away(reason: str = ""):
    """Mark user as away."""
    set_status("away", reason)


def is_away() -> bool:
    return get_status()["status"] == "away"


def is_mac_idle(threshold_secs: int = IDLE_TIMEOUT_SECS) -> bool:
    """Check if the Mac has been idle (no keyboard/mouse) for threshold seconds.

    Uses macOS IOKit HIDIdleTime. Returns True if idle, False if active.
    Falls back to False (assume active) on error.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem", "-d", "4"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "HIDIdleTime" in line and "=" in line:
                # Value is in nanoseconds
                ns_str = line.split("=")[-1].strip()
                idle_ns = int(ns_str)
                idle_secs = idle_ns / 1_000_000_000
                return idle_secs >= threshold_secs
    except Exception:
        pass
    return False  # assume active on error


def detect_away_intent(text: str) -> str | None:
    """Check if user's message implies they're leaving.
    Returns the matched reason phrase, or None.
    """
    match = _AWAY_PATTERNS.search(text)
    if match:
        return match.group(0)
    return None
