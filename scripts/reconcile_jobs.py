#!/usr/bin/env python3
"""Reconcile launchd jobs against agent.json definitions.

Reads each agent's agent.json, generates the correct launchd plists,
compares against what's installed, and installs/removes as needed.

This ensures scheduled jobs run even when the Electron app isn't open
(e.g. 3am sleep_cycle, 7am morning_brief). The in-process cron scheduler
handles jobs while the app is running; launchd handles persistence.

Usage:
    python reconcile_jobs.py                    # reconcile all agents
    python reconcile_jobs.py --agent companion  # single agent
    python reconcile_jobs.py --dry-run          # preview only
    python reconcile_jobs.py --remove-stale     # also unload jobs not in agent.json
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path

AGENTS_DIR = Path.home() / ".atrophy" / "agents"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PREFIX = "com.atrophy"

# Resolve project root - works whether called from scripts/ or anywhere
_SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _SCRIPT_DIR.parent  # scripts/ -> project root

# Python interpreter to use in plists
PYTHON = str(Path.home() / ".pyenv" / "versions" / "3.12.7" / "bin" / "python3")
if not os.path.exists(PYTHON):
    # Fallback: use whichever python is running this script
    PYTHON = sys.executable


def discover_agents() -> list[str]:
    """Find all agent directories in ~/.atrophy/agents/."""
    if not AGENTS_DIR.is_dir():
        return []
    return [
        d.name for d in AGENTS_DIR.iterdir()
        if d.is_dir() and (d / "data" / "agent.json").exists()
    ]


def load_manifest(agent_name: str) -> dict:
    """Load an agent's agent.json manifest."""
    path = AGENTS_DIR / agent_name / "data" / "agent.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def _expand_cron_token(token: str, field_max: int = 59) -> list[int]:
    """Expand a single cron token (e.g. '3', '1-5', '*/6') into a list of ints."""
    if token.startswith("*/"):
        step = int(token[2:])
        return list(range(0, field_max + 1, step))
    if "-" in token:
        lo, hi = token.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(token)]


def _parse_field(value: str, field_max: int = 59):
    """Parse a single cron field. Returns int or list[int] for comma/range values."""
    parts: list[int] = []
    for token in value.split(","):
        parts.extend(_expand_cron_token(token.strip(), field_max))
    return parts[0] if len(parts) == 1 else parts


def parse_cron_expr(cron: str):
    """Convert a cron expression to a launchd StartCalendarInterval dict or list.

    Supports: "min hour * * *" (daily), "min hour dom * *" (monthly),
    and simple 5-field cron expressions. Comma-separated values in any
    field produce an array of StartCalendarInterval dicts (one per combo).
    """
    parts = cron.strip().split()
    if len(parts) != 5:
        return {}

    minute, hour, dom, month, dow = parts
    keys = ["Minute", "Hour", "Day", "Month", "Weekday"]
    parsed = {}

    for key, val in zip(keys, [minute, hour, dom, month, dow]):
        if val != "*":
            parsed[key] = _parse_field(val)

    # If any field has a list, expand into multiple dicts for launchd
    list_keys = [k for k, v in parsed.items() if isinstance(v, list)]
    if not list_keys:
        return parsed

    # Expand combinations - launchd wants an array of dicts
    from itertools import product as _product

    combos = []
    list_vals = [parsed[k] if isinstance(parsed[k], list) else [parsed[k]] for k in keys if k in parsed]
    combo_keys = [k for k in keys if k in parsed]
    for combo in _product(*list_vals):
        combos.append(dict(zip(combo_keys, combo)))
    return combos


def resolve_script_path(agent_name: str, script_rel: str) -> str:
    """Resolve a script path from agent.json to an absolute path.

    Scripts are relative to the project root. The /tmp/atrophy symlink
    points there, so we use that for consistency with existing plists.
    """
    # Prefer /tmp/atrophy if it exists (standard deployment)
    if os.path.islink("/tmp/atrophy") or os.path.isdir("/tmp/atrophy"):
        candidate = os.path.join("/tmp/atrophy", script_rel)
        if os.path.exists(candidate):
            return candidate

    # Fallback to resolved project root
    candidate = str(PROJECT_ROOT / script_rel)
    if os.path.exists(candidate):
        return candidate

    # Return the /tmp/atrophy version anyway (will fail at runtime with clear error)
    return os.path.join("/tmp/atrophy", script_rel)


def build_plist(agent_name: str, job_name: str, job_def: dict) -> dict:
    """Build a launchd plist dict for a job definition."""
    label = f"{PLIST_PREFIX}.{agent_name}.{job_name}"

    # Resolve script path
    script_rel = job_def.get("script", f"scripts/agents/shared/{job_name}.py")
    script_path = resolve_script_path(agent_name, script_rel)

    # Build program arguments
    prog_args = [PYTHON, script_path]

    # Handle args - can be string or list
    args = job_def.get("args", [])
    if isinstance(args, str):
        prog_args.extend(args.split())
    elif isinstance(args, list):
        prog_args.extend(args)

    # Log path
    log_dir = f"/tmp/atrophy/logs/{agent_name}"
    log_path = f"{log_dir}/{job_name}.log"

    # Environment
    env = {
        "AGENT": agent_name,
        "PATH": f"/usr/local/bin:/usr/bin:/bin:{os.path.dirname(PYTHON)}",
        "PYTHONPATH": "/tmp/atrophy",
    }

    plist = {
        "Label": label,
        "ProgramArguments": prog_args,
        "EnvironmentVariables": env,
        "StandardOutPath": log_path,
        "StandardErrorPath": log_path,
        "WorkingDirectory": "/tmp/atrophy",
    }

    # Schedule - interval or calendar
    job_type = job_def.get("type", "")
    interval_secs = job_def.get("interval_seconds")
    cron_expr = job_def.get("cron")

    if interval_secs or job_type == "interval":
        plist["StartInterval"] = int(interval_secs or 1800)
    elif cron_expr:
        cal = parse_cron_expr(cron_expr)
        if cal:
            plist["StartCalendarInterval"] = cal
    else:
        # Default to daily at a reasonable time
        plist["StartCalendarInterval"] = {"Hour": 3, "Minute": 0}

    return plist


def get_expected_jobs(agent_name: str, manifest: dict) -> dict[str, dict]:
    """Extract all expected jobs from an agent manifest."""
    jobs = {}

    # Jobs from the jobs section
    for name, job_def in manifest.get("jobs", {}).items():
        jobs[name] = job_def

    # Heartbeat from the heartbeat config (if not already in jobs)
    if manifest.get("heartbeat") and "heartbeat" not in jobs:
        hb = manifest["heartbeat"]
        jobs["heartbeat"] = {
            "type": "interval",
            "interval_seconds": hb.get("interval_mins", 30) * 60,
            "script": "scripts/agents/shared/heartbeat.py",
            "description": "Periodic check-in evaluation",
        }

    return jobs


def get_installed_jobs(agent_name: str) -> dict[str, str]:
    """Get currently installed launchd jobs for an agent.

    Returns {job_name: label}.
    """
    prefix = f"{PLIST_PREFIX}.{agent_name}."
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return {}

    installed = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2].startswith(prefix):
            job_name = parts[2].replace(prefix, "")
            installed[job_name] = parts[2]
    return installed


def plist_path(agent_name: str, job_name: str) -> Path:
    """Get the plist file path for an agent job."""
    return LAUNCH_AGENTS_DIR / f"{PLIST_PREFIX}.{agent_name}.{job_name}.plist"


def ensure_log_dir(agent_name: str):
    """Create the log directory for an agent."""
    log_dir = Path("/tmp/atrophy/logs") / agent_name
    log_dir.mkdir(parents=True, exist_ok=True)


def install_job(agent_name: str, job_name: str, plist_dict: dict, dry_run: bool = False) -> str:
    """Write plist and load into launchd."""
    path = plist_path(agent_name, job_name)

    if dry_run:
        return f"  WOULD INSTALL  {job_name}"

    # Ensure log directory exists
    ensure_log_dir(agent_name)

    # Write plist
    with open(path, "wb") as f:
        plistlib.dump(plist_dict, f)

    # Load
    result = subprocess.run(
        ["launchctl", "load", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return f"  INSTALL FAILED  {job_name}: {result.stderr.strip()}"

    return f"  INSTALLED  {job_name}"


def remove_job(agent_name: str, job_name: str, dry_run: bool = False) -> str:
    """Unload from launchd and remove plist."""
    path = plist_path(agent_name, job_name)

    if dry_run:
        return f"  WOULD REMOVE  {job_name}"

    # Unload
    subprocess.run(
        ["launchctl", "unload", str(path)],
        capture_output=True, text=True,
    )

    # Remove file
    if path.exists():
        path.unlink()

    return f"  REMOVED  {job_name}"


def update_job(agent_name: str, job_name: str, plist_dict: dict, dry_run: bool = False) -> str:
    """Update a job - unload old, write new, reload."""
    path = plist_path(agent_name, job_name)

    if dry_run:
        return f"  WOULD UPDATE  {job_name}"

    # Unload existing
    subprocess.run(
        ["launchctl", "unload", str(path)],
        capture_output=True, text=True,
    )

    # Write new plist
    ensure_log_dir(agent_name)
    with open(path, "wb") as f:
        plistlib.dump(plist_dict, f)

    # Reload
    result = subprocess.run(
        ["launchctl", "load", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return f"  UPDATE FAILED  {job_name}: {result.stderr.strip()}"

    return f"  UPDATED  {job_name}"


def plist_matches(agent_name: str, job_name: str, expected: dict) -> bool:
    """Check if the installed plist matches the expected definition."""
    path = plist_path(agent_name, job_name)
    if not path.exists():
        return False

    try:
        with open(path, "rb") as f:
            installed = plistlib.load(f)
    except Exception:
        return False

    # Compare key fields
    if installed.get("ProgramArguments") != expected.get("ProgramArguments"):
        return False
    if installed.get("StartInterval") != expected.get("StartInterval"):
        return False
    if installed.get("StartCalendarInterval") != expected.get("StartCalendarInterval"):
        return False
    # Check PYTHONPATH is set (older plists may lack it)
    env = installed.get("EnvironmentVariables", {})
    if "PYTHONPATH" not in env:
        return False

    return True


def reconcile_agent(agent_name: str, dry_run: bool = False, remove_stale: bool = False) -> list[str]:
    """Reconcile launchd jobs for a single agent."""
    manifest = load_manifest(agent_name)
    if not manifest:
        return [f"  SKIP  {agent_name} - no agent.json"]

    expected_jobs = get_expected_jobs(agent_name, manifest)
    installed_jobs = get_installed_jobs(agent_name)

    results = []
    changes = 0

    # Install missing or update changed
    for job_name, job_def in expected_jobs.items():
        plist_dict = build_plist(agent_name, job_name, job_def)

        if job_name not in installed_jobs:
            results.append(install_job(agent_name, job_name, plist_dict, dry_run))
            changes += 1
        elif not plist_matches(agent_name, job_name, plist_dict):
            results.append(update_job(agent_name, job_name, plist_dict, dry_run))
            changes += 1
        else:
            results.append(f"  OK  {job_name}")

    # Remove stale jobs (in agent's namespace but not in agent.json)
    if remove_stale:
        for job_name in installed_jobs:
            if job_name not in expected_jobs:
                results.append(remove_job(agent_name, job_name, dry_run))
                changes += 1

    if changes == 0:
        results.append(f"  No changes needed.")

    return results


def reconcile_all(dry_run: bool = False, remove_stale: bool = False, agent_filter: str | None = None) -> str:
    """Reconcile jobs for all agents (or a specific one)."""
    agents = [agent_filter] if agent_filter else discover_agents()
    if not agents:
        return "No agents found in ~/.atrophy/agents/"

    sections = ["# Job Reconciliation Report\n"]

    total_changes = 0
    for agent_name in sorted(agents):
        sections.append(f"## {agent_name}")
        results = reconcile_agent(agent_name, dry_run, remove_stale)
        for line in results:
            sections.append(line)
            if any(word in line for word in ["INSTALLED", "UPDATED", "REMOVED", "WOULD"]):
                total_changes += 1
        sections.append("")

    if dry_run:
        sections.append(f"DRY RUN - {total_changes} change(s) would be made.")
    else:
        sections.append(f"Done. {total_changes} change(s) applied.")

    return "\n".join(sections)


def main():
    parser = argparse.ArgumentParser(description="Reconcile launchd jobs against agent.json definitions")
    parser.add_argument("--agent", help="Reconcile a single agent")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    parser.add_argument("--remove-stale", action="store_true", help="Remove jobs not in agent.json")
    parser.add_argument("--quiet", action="store_true", help="Only print if changes were made")
    args = parser.parse_args()

    report = reconcile_all(
        dry_run=args.dry_run,
        remove_stale=args.remove_stale,
        agent_filter=args.agent,
    )

    if args.quiet and "No changes needed" in report and "change(s)" not in report:
        return

    print(report)


if __name__ == "__main__":
    main()
