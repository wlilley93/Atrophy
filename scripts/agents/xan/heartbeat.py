#!/usr/bin/env python3
"""Xan heartbeat - operational status check.

Runs via launchd every 30 minutes. Unlike the companion's heartbeat
(which evaluates whether to reach out emotionally), Xan's heartbeat
is operational: checks system health, approaching reminders, queued
message backlog, and agent cron job status.

If something needs attention, fires a notification and queues the
alert for next app launch.

Schedule: every 30 minutes (StartInterval)
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from config import (
    DB_PATH, MESSAGE_QUEUE, AGENTS_DIR,
    HEARTBEAT_ACTIVE_START, HEARTBEAT_ACTIVE_END,
    AGENT_DISPLAY_NAME,
)
from core.queue import queue_message
from core.memory import _connect, log_heartbeat
from core.notify import send_notification


def _in_active_hours() -> bool:
    hour = datetime.now().hour
    return HEARTBEAT_ACTIVE_START <= hour < HEARTBEAT_ACTIVE_END


def _check_agent_cron_jobs() -> list[str]:
    """Check if other agents' launchd jobs are loaded and running."""
    issues = []
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=5,
        )
        loaded_jobs = result.stdout if result.returncode == 0 else ""
    except Exception:
        issues.append("Could not query launchctl - unable to verify cron jobs.")
        return issues

    # Discover all agents
    if not AGENTS_DIR.exists():
        return issues

    for agent_dir in AGENTS_DIR.iterdir():
        if not agent_dir.is_dir():
            continue
        agent_name = agent_dir.name
        jobs_file = PROJECT_ROOT / "scripts" / "agents" / agent_name / "jobs.json"
        if not jobs_file.exists():
            continue

        try:
            jobs = json.loads(jobs_file.read_text())
        except (json.JSONDecodeError, OSError):
            issues.append(f"Corrupt jobs.json for agent '{agent_name}'.")
            continue

        for job_name in jobs:
            label = f"com.atrophiedmind.{agent_name}.{job_name}"
            if label not in loaded_jobs:
                issues.append(f"Cron job not loaded: {label} ({agent_name}/{job_name})")

    return issues


def _check_approaching_reminders() -> list[str]:
    """Check for reminders due in the next 2 hours."""
    alerts = []
    # Check all agents' reminder files
    if not AGENTS_DIR.exists():
        return alerts

    now = datetime.now()
    horizon = now + timedelta(hours=2)

    for agent_dir in AGENTS_DIR.iterdir():
        if not agent_dir.is_dir():
            continue
        reminders_file = agent_dir / "data" / ".reminders.json"
        if not reminders_file.exists():
            continue
        try:
            reminders = json.loads(reminders_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        agent_name = agent_dir.name
        for r in reminders:
            try:
                remind_time = datetime.fromisoformat(r["time"])
            except (ValueError, KeyError):
                continue
            if now < remind_time <= horizon:
                delta = remind_time - now
                mins = int(delta.total_seconds() / 60)
                msg = r.get("message", "unnamed reminder")
                alerts.append(f"[{agent_name}] in {mins}m: {msg}")

    return alerts


def _check_queued_messages() -> list[str]:
    """Check for undelivered queued messages across all agents."""
    alerts = []
    if not AGENTS_DIR.exists():
        return alerts

    for agent_dir in AGENTS_DIR.iterdir():
        if not agent_dir.is_dir():
            continue
        queue_file = agent_dir / "data" / ".message_queue.json"
        if not queue_file.exists():
            continue
        try:
            messages = json.loads(queue_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        if messages:
            agent_name = agent_dir.name
            count = len(messages)
            # Check age of oldest message
            oldest = None
            for m in messages:
                ts = m.get("timestamp") or m.get("created_at")
                if ts:
                    try:
                        t = datetime.fromisoformat(ts)
                        if oldest is None or t < oldest:
                            oldest = t
                    except ValueError:
                        pass

            age_str = ""
            if oldest:
                age = datetime.now() - oldest
                if age.total_seconds() > 3600:
                    hours = int(age.total_seconds() / 3600)
                    age_str = f" (oldest: {hours}h ago)"

            alerts.append(f"[{agent_name}] {count} queued message(s){age_str}")

    return alerts


def heartbeat():
    # Gate: active hours
    if not _in_active_hours():
        print(f"[heartbeat] Outside active hours ({HEARTBEAT_ACTIVE_START}-{HEARTBEAT_ACTIVE_END}). Skipping.")
        return

    print("[heartbeat] Running operational status check...")

    issues = []

    # 1. Check agent cron jobs
    cron_issues = _check_agent_cron_jobs()
    if cron_issues:
        issues.extend(cron_issues)

    # 2. Check approaching reminders
    reminder_alerts = _check_approaching_reminders()
    if reminder_alerts:
        issues.append("Approaching reminders:")
        issues.extend(f"  {a}" for a in reminder_alerts)

    # 3. Check queued message backlog
    queue_alerts = _check_queued_messages()
    if queue_alerts:
        issues.append("Undelivered messages:")
        issues.extend(f"  {a}" for a in queue_alerts)

    if not issues:
        log_heartbeat("HEARTBEAT_OK", "All systems nominal")
        print("[heartbeat] All systems nominal.")
        return

    # Something needs attention
    report = "\n".join(issues)
    print(f"[heartbeat] Issues found:\n{report}")

    log_heartbeat("REACH_OUT", "", report)

    # Notify
    summary = f"{len(issues)} issue(s) detected"
    send_notification(
        title=f"{AGENT_DISPLAY_NAME} - Status",
        body=summary,
    )

    # Queue for next interaction
    queue_message(
        MESSAGE_QUEUE,
        f"Operational status check:\n{report}",
        source="heartbeat",
    )

    # Send via Telegram if Mac is idle
    try:
        from core.status import is_mac_idle
        if is_mac_idle():
            from channels.telegram import send_message as send_telegram
            send_telegram(f"Status check:\n{report}")
            print("[heartbeat] Sent via Telegram (Mac idle)")
    except Exception as e:
        print(f"[heartbeat] Telegram send failed: {e}")


if __name__ == "__main__":
    heartbeat()
