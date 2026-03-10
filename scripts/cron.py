#!/usr/bin/env python3
"""Companion scheduled tasks — launchd control plane.

Usage:
    python scripts/cron.py list                     # Show all companion jobs
    python scripts/cron.py add <name> <cron> <cmd>  # Add a job
    python scripts/cron.py remove <name>            # Remove a job
    python scripts/cron.py edit <name> <cron>       # Change schedule
    python scripts/cron.py run <name>               # Run a job now (manual trigger)
    python scripts/cron.py install                  # Install all jobs to launchd
    python scripts/cron.py uninstall                # Uninstall all jobs from launchd

Jobs are defined in a YAML-like config at scripts/jobs.json.
Plists are generated and managed in ~/Library/LaunchAgents/.
"""
import argparse
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
AGENT_NAME = os.environ.get("AGENT", "companion")
JOBS_FILE = PROJECT_ROOT / "scripts" / "agents" / AGENT_NAME / "jobs.json"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
LABEL_PREFIX = f"com.atrophiedmind.{AGENT_NAME}."
PYTHON = sys.executable
LOGS_DIR = PROJECT_ROOT / "logs" / AGENT_NAME


def _load_jobs() -> dict:
    if JOBS_FILE.exists():
        return json.loads(JOBS_FILE.read_text())
    return {}


def _save_jobs(jobs: dict):
    JOBS_FILE.write_text(json.dumps(jobs, indent=2))


def _parse_cron(cron_str: str) -> dict:
    """Parse '17 3 * * *' into launchd StartCalendarInterval dict."""
    parts = cron_str.split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron: '{cron_str}' — need 5 fields: min hour dom month dow")

    minute, hour, dom, month, dow = parts
    interval = {}

    if minute != '*':
        interval['Minute'] = int(minute)
    if hour != '*':
        interval['Hour'] = int(hour)
    if dom != '*':
        interval['Day'] = int(dom)
    if month != '*':
        interval['Month'] = int(month)
    if dow != '*':
        interval['Weekday'] = int(dow)

    return interval


def _plist_path(name: str) -> Path:
    return LAUNCH_AGENTS / f"{LABEL_PREFIX}{name}.plist"


def _generate_plist(name: str, job: dict) -> dict:
    """Generate a launchd plist dict for a job.

    Supports two types:
      - "calendar" (default): uses StartCalendarInterval with a cron string
      - "interval": uses StartInterval with seconds-based scheduling
    """
    label = f"{LABEL_PREFIX}{name}"
    script_path = str(PROJECT_ROOT / job["script"])

    log_path = str(LOGS_DIR / f"{name}.log")

    extra_args = job.get("args", [])
    plist = {
        'Label': label,
        'ProgramArguments': [PYTHON, script_path] + extra_args,
        'WorkingDirectory': str(PROJECT_ROOT),
        'StandardOutPath': log_path,
        'StandardErrorPath': log_path,
        'EnvironmentVariables': {
            'PATH': f"/usr/local/bin:/usr/bin:/bin:{Path(PYTHON).parent}",
            'AGENT': AGENT_NAME,
        },
    }

    job_type = job.get("type", "calendar")
    if job_type == "interval":
        plist['StartInterval'] = int(job["interval_seconds"])
    else:
        plist['StartCalendarInterval'] = _parse_cron(job["cron"])

    return plist


def cmd_list(args):
    jobs = _load_jobs()
    if not jobs:
        print("  No jobs configured.")
        return

    print()
    print(f"  {'Name':<20} {'Schedule':<20} {'Script':<35} {'Installed'}")
    print(f"  {'─'*20} {'─'*20} {'─'*35} {'─'*10}")

    for name, job in jobs.items():
        installed = "yes" if _plist_path(name).exists() else "no"
        if job.get("type") == "interval":
            schedule = f"every {job['interval_seconds']}s"
        else:
            schedule = job.get("cron", "?")
        print(f"  {name:<20} {schedule:<20} {job['script']:<35} {installed}")
    print()


def cmd_add(args):
    jobs = _load_jobs()
    name = args.name
    cron = args.cron
    script = args.script

    # Validate cron
    try:
        _parse_cron(cron)
    except ValueError as e:
        print(f"  Error: {e}")
        return

    # Validate script exists
    script_path = PROJECT_ROOT / script
    if not script_path.exists():
        print(f"  Warning: Script not found at {script_path}")

    jobs[name] = {
        "cron": cron,
        "script": script,
        "description": args.description or "",
    }
    _save_jobs(jobs)
    print(f"  Added job '{name}': {cron} → {script}")

    if args.install:
        _install_job(name, jobs[name])


def cmd_remove(args):
    jobs = _load_jobs()
    name = args.name

    if name not in jobs:
        print(f"  Job '{name}' not found.")
        return

    # Uninstall first
    _uninstall_job(name)

    del jobs[name]
    _save_jobs(jobs)
    print(f"  Removed job '{name}'.")


def cmd_edit(args):
    jobs = _load_jobs()
    name = args.name

    if name not in jobs:
        print(f"  Job '{name}' not found.")
        return

    try:
        _parse_cron(args.cron)
    except ValueError as e:
        print(f"  Error: {e}")
        return

    old_cron = jobs[name]["cron"]
    jobs[name]["cron"] = args.cron
    _save_jobs(jobs)
    print(f"  Updated '{name}': {old_cron} → {args.cron}")

    # Reinstall if already installed
    if _plist_path(name).exists():
        _uninstall_job(name)
        _install_job(name, jobs[name])
        print(f"  Reinstalled with new schedule.")


def cmd_run(args):
    jobs = _load_jobs()
    name = args.name

    if name not in jobs:
        print(f"  Job '{name}' not found.")
        return

    job = jobs[name]
    script_path = PROJECT_ROOT / job["script"]
    extra_args = job.get("args", [])
    print(f"  Running {script_path} {' '.join(extra_args)}...")
    result = subprocess.run(
        [PYTHON, str(script_path)] + extra_args,
        cwd=str(PROJECT_ROOT),
    )
    sys.exit(result.returncode)


def _install_job(name: str, job: dict):
    LOGS_DIR.mkdir(exist_ok=True)
    plist = _generate_plist(name, job)
    plist_path = _plist_path(name)

    with open(plist_path, 'wb') as f:
        plistlib.dump(plist, f)

    subprocess.run(["launchctl", "load", str(plist_path)], check=False)
    print(f"  Installed {name} → {plist_path}")


def _uninstall_job(name: str):
    plist_path = _plist_path(name)
    if plist_path.exists():
        subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
        plist_path.unlink()
        print(f"  Uninstalled {name}")


def cmd_install(args):
    jobs = _load_jobs()
    if not jobs:
        print("  No jobs to install.")
        return

    LOGS_DIR.mkdir(exist_ok=True)
    for name, job in jobs.items():
        _install_job(name, job)
    print(f"\n  Installed {len(jobs)} job(s).")


def cmd_uninstall(args):
    jobs = _load_jobs()
    if not jobs:
        print("  No jobs configured.")
        return

    for name in jobs:
        _uninstall_job(name)
    print(f"\n  Uninstalled {len(jobs)} job(s).")


def main():
    global AGENT_NAME, JOBS_FILE, LABEL_PREFIX, LOGS_DIR

    parser = argparse.ArgumentParser(description="Agent scheduled tasks")
    parser.add_argument("--agent", default=None, help="Agent name (default: from AGENT env var)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="Show all jobs")

    add_p = sub.add_parser("add", help="Add a job")
    add_p.add_argument("name", help="Job name (e.g. introspect)")
    add_p.add_argument("cron", help="Cron schedule (e.g. '17 3 * * *')")
    add_p.add_argument("script", help="Script path relative to project root (e.g. scripts/introspect.py)")
    add_p.add_argument("-d", "--description", help="Job description")
    add_p.add_argument("--install", action="store_true", help="Install immediately")

    rm_p = sub.add_parser("remove", help="Remove a job")
    rm_p.add_argument("name", help="Job name")

    edit_p = sub.add_parser("edit", help="Change a job's schedule")
    edit_p.add_argument("name", help="Job name")
    edit_p.add_argument("cron", help="New cron schedule")

    run_p = sub.add_parser("run", help="Run a job now")
    run_p.add_argument("name", help="Job name")

    sub.add_parser("install", help="Install all jobs to launchd")
    sub.add_parser("uninstall", help="Uninstall all jobs from launchd")

    args = parser.parse_args()

    if args.agent:
        AGENT_NAME = args.agent
        JOBS_FILE = PROJECT_ROOT / "scripts" / "agents" / AGENT_NAME / "jobs.json"
        LABEL_PREFIX = f"com.atrophiedmind.{AGENT_NAME}."
        LOGS_DIR = PROJECT_ROOT / "logs" / AGENT_NAME

    if not args.command:
        parser.print_help()
        return

    {
        "list": cmd_list,
        "add": cmd_add,
        "remove": cmd_remove,
        "edit": cmd_edit,
        "run": cmd_run,
        "install": cmd_install,
        "uninstall": cmd_uninstall,
    }[args.command](args)


if __name__ == "__main__":
    main()
