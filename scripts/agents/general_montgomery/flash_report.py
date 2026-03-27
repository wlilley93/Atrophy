#!/usr/bin/env python3
"""
Flash Report - Event-triggered intelligence alert.

Fires when:
  - WorldMonitor alerts contain CRITICAL status items
  - Active OREF alerts exceed 50
  - Theater status escalation detected
  - worldmonitor_alerts returns high-priority items

Generates a concise flash assessment via Claude API and sends immediately.
"""
from __future__ import annotations

import json
import logging
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path

_ATROPHY_DIR = Path.home() / ".atrophy"
_AGENT_DIR   = _ATROPHY_DIR / "agents" / "general_montgomery"
_AGENT_JSON  = _AGENT_DIR / "data" / "agent.json"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "general_montgomery"
_STATE_FILE  = _AGENT_DIR / "data" / "flash_report_state.json"

_APP_DIR = Path(__file__).resolve().parent.parent.parent.parent
_MCP_DIR = _APP_DIR / "mcp"
sys.path.insert(0, str(_MCP_DIR))

_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "flash_report.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("flash_report")

OREF_THRESHOLD = 50
CRITICAL_CONFIDENCE_THRESHOLD = 0.7



CLAUDE_BIN = shutil.which("claude") or str(Path.home() / ".local/bin/claude")


def call_claude(system: str, prompt: str, model: str = "sonnet") -> str:
    """One-shot Claude call via CLI. Returns response text."""
    import subprocess
    result = subprocess.run(
        [CLAUDE_BIN, "-p", "--model", model, "--system-prompt", system,
         "--no-session-persistence", "--output-format", "text"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr[:200]}")
    return result.stdout.strip()

def load_credentials():
    from shared.credentials import load_telegram_credentials
    return load_telegram_credentials("general_montgomery")


def load_state() -> dict:
    if _STATE_FILE.exists():
        with open(_STATE_FILE) as f:
            return json.load(f)
    return {"sent_alerts": []}


def save_state(state: dict):
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)




def generate_flash_text(trigger: str, raw_data: str) -> str:
    system = """You are General Montgomery producing a flash intelligence report.
Three sentences maximum. State the event. State why it matters. State the immediate implication.
No hedging. No em dashes. Hyphens only. Prefix with FLASH REPORT."""
    return call_claude(system, f"Trigger: {trigger}\n\nRaw data:\n{raw_data[:1500]}", "sonnet")


def check_alerts(state: dict) -> list[tuple[str, str]]:
    """Returns list of (trigger_description, raw_data_snippet) tuples."""
    triggers = []
    try:
        from worldmonitor_server import WorldMonitorClient
        client = WorldMonitorClient(cache_db=str(Path.home() / '.atrophy' / 'worldmonitor_cache.db'))
        alerts_data, _wm_delta = client.fetch_cached("api/oref-alerts")

        # Check for CRITICAL items
        alerts = []
        if isinstance(alerts_data, dict):
            alerts = alerts_data.get("data", {}).get("alerts", [])
            if not alerts:
                alerts = alerts_data.get("alerts", [])

        critical_alerts = []
        for alert in alerts:
            if isinstance(alert, dict):
                confidence = alert.get("confidence", 0)
                level = alert.get("threatLevel", alert.get("level", "")).upper()
                alert_id = alert.get("id") or alert.get("title", "")[:50]
                if ("CRITICAL" in level or confidence >= CRITICAL_CONFIDENCE_THRESHOLD) and \
                   str(alert_id) not in state.get("sent_alerts", []):
                    critical_alerts.append(alert)
                    state.setdefault("sent_alerts", []).append(str(alert_id))

        if critical_alerts:
            raw = json.dumps(critical_alerts[:3], indent=2)[:1500]
            triggers.append((f"{len(critical_alerts)} CRITICAL alert(s) detected", raw))

        # Check OREF count
        oref_count = sum(
            1 for a in alerts
            if isinstance(a, dict) and "oref" in str(a).lower()
        )
        if oref_count > OREF_THRESHOLD:
            oref_key = f"oref_{oref_count // 10 * 10}"
            if oref_key not in state.get("sent_alerts", []):
                state["sent_alerts"].append(oref_key)
                triggers.append((
                    f"OREF alert volume: {oref_count} active alerts (threshold: {OREF_THRESHOLD})",
                    f"Active OREF alerts: {oref_count}"
                ))

    except Exception as e:
        log.error(f"Alert check failed: {e}")

    # Trim sent_alerts
    if len(state.get("sent_alerts", [])) > 200:
        state["sent_alerts"] = state["sent_alerts"][-200:]

    return triggers


def run():
    log.info("Flash report check starting")
    token, chat_id = load_credentials()
    state = load_state()

    triggers = check_alerts(state)
    save_state(state)

    if not triggers:
        log.info("No flash triggers this cycle")
        return

    for trigger, raw_data in triggers:
        log.info(f"Flash trigger: {trigger}")
        try:
            flash_text = generate_flash_text(trigger, raw_data)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            message = f"*{timestamp}*\n\n{flash_text}"
            send_telegram(token, chat_id, message)
            log.info("Flash report sent")

            # Push channel state to WorldMonitor
            try:
                from shared.channel_push import push_channel

                # Try to derive center from raw_data location fields
                center = [30, 30]
                zoom = 2
                try:
                    parsed = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                    if isinstance(parsed, list) and parsed:
                        first = parsed[0] if isinstance(parsed[0], dict) else {}
                    elif isinstance(parsed, dict):
                        first = parsed
                    else:
                        first = {}
                    lat = first.get("lat", first.get("latitude"))
                    lon = first.get("lon", first.get("longitude"))
                    if lat is not None and lon is not None:
                        center = [float(lat), float(lon)]
                        zoom = 6
                except Exception:
                    pass

                push_channel("general_montgomery", {
                    "agent": "general_montgomery",
                    "display_name": "Gen. Montgomery",
                    "alert_level": "critical",
                    "briefing": {
                        "title": f"FLASH - {trigger}",
                        "summary": flash_text.split("\n")[0] if flash_text else trigger,
                        "body_md": flash_text,
                        "sources": ["WorldMonitor", "OREF"],
                    },
                    "map": {
                        "center": center,
                        "zoom": zoom,
                        "layers": ["oref-alerts"],
                    },
                })
            except Exception:
                pass  # channel push is best-effort

        except Exception as e:
            log.error(f"Flash report generation/send failed: {e}")


if __name__ == "__main__":
    run()
