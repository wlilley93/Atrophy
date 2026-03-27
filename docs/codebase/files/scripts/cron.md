# scripts/cron.py - Cron Job Management

**Line count:** ~327 lines  
**Dependencies:** `argparse`, `json`, `os`, `plistlib`, `subprocess`, `sys`, `pathlib`  
**Purpose:** Launchd control plane for companion scheduled tasks

## Overview

This script manages launchd jobs for scheduled tasks. It provides commands to list, add, remove, edit, run, install, and uninstall jobs. Jobs are defined in `scripts/jobs.json` and plists are generated in `~/Library/LaunchAgents/`.

**Usage:**
```bash
python scripts/cron.py list                     # Show all jobs
python scripts/cron.py add <name> <cron> <cmd>  # Add a job
python scripts/cron.py remove <name>            # Remove a job
python scripts/cron.py edit <name> <cron>       # Change schedule
python scripts/cron.py run <name>               # Run job now
python scripts/cron.py install                  # Install all jobs
python scripts/cron.py uninstall                # Uninstall all jobs
```

## Constants

```python
PROJECT_ROOT = Path(__file__).parent.parent
AGENT_NAME = os.environ.get("AGENT", "companion")
JOBS_FILE = PROJECT_ROOT / "scripts" / "agents" / AGENT_NAME / "jobs.json"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
LABEL_PREFIX = f"com.atrophy.{AGENT_NAME}."
PYTHON = sys.executable
LOGS_DIR = PROJECT_ROOT / "logs" / AGENT_NAME
```

**Purpose:** Define paths and configuration.

**Environment:**
- `AGENT`: Agent name (default: "companion")

## Job Loading

### _load_jobs

```python
def _load_jobs() -> dict:
    if JOBS_FILE.exists():
        return json.loads(JOBS_FILE.read_text())
    return {}
```

**Purpose:** Load jobs from jobs.json.

### _save_jobs

```python
def _save_jobs(jobs: dict):
    JOBS_FILE.write_text(json.dumps(jobs, indent=2))
```

**Purpose:** Save jobs to jobs.json.

## Cron Parsing

### _parse_cron

```python
def _parse_cron(cron_str: str) -> dict:
    """Parse '17 3 * * *' into launchd StartCalendarInterval dict."""
    parts = cron_str.split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron: '{cron_str}' - need 5 fields")

    minute, hour, dom, month, dow = parts
    interval = {}

    def _parse_field(val: str, name: str) -> int:
        """Parse a cron field to int. Ranges/steps/lists not supported."""
        val = val.strip()
        if any(c in val for c in ('/', '-', ',')):
            raise ValueError(
                f"launchd does not support '{val}' in {name} field. "
                f"Use a simple integer or '*'."
            )
        try:
            return int(val)
        except ValueError:
            raise ValueError(
                f"Invalid value '{val}' in {name} field. Must be an integer or '*'."
            )

    if minute != '*':
        interval['Minute'] = _parse_field(minute, 'minute')
    if hour != '*':
        interval['Hour'] = _parse_field(hour, 'hour')
    if dom != '*':
        interval['Day'] = _parse_field(dom, 'day')
    if month != '*':
        interval['Month'] = _parse_field(month, 'month')
    if dow != '*':
        interval['Weekday'] = _parse_field(dow, 'weekday')

    return interval
```

**Purpose:** Convert cron expression to launchd format.

**Limitations:** launchd doesn't support ranges (`1-5`), steps (`*/6`), or lists (`1,3,5`). Use simple integers or `*`.

**Examples:**
- `"0 3 * * *"` → `{"Minute": 0, "Hour": 3}` (3am daily)
- `"0 9 * * 1"` → `{"Minute": 0, "Hour": 9, "Weekday": 1}` (9am Mondays)
- `"*/30 * * * *"` → Error (steps not supported)

## Plist Generation

### _plist_path

```python
def _plist_path(name: str) -> Path:
    return LAUNCH_AGENTS / f"{LABEL_PREFIX}{name}.plist"
```

**Purpose:** Get plist file path.

### _generate_plist

```python
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
```

**Purpose:** Build launchd plist dictionary.

**Job types:**
- `calendar`: Cron-based scheduling
- `interval`: Seconds-based interval

**Plist structure:**
```python
{
    'Label': 'com.atrophy.companion.sleep_cycle',
    'ProgramArguments': ['/usr/bin/python3', 'scripts/agents/shared/sleep_cycle.py'],
    'WorkingDirectory': '/path/to/project',
    'StandardOutPath': '/path/to/logs/sleep_cycle.log',
    'StandardErrorPath': '/path/to/logs/sleep_cycle.log',
    'EnvironmentVariables': {'PATH': '...', 'AGENT': 'companion'},
    'StartCalendarInterval': {'Minute': 0, 'Hour': 3},  # 3am daily
}
```

## Commands

### cmd_list

```python
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
```

**Purpose:** List all configured jobs.

### cmd_add

```python
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
```

**Purpose:** Add a new job.

### cmd_remove

```python
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
```

**Purpose:** Remove a job.

### cmd_edit

```python
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
    print(f"  Edited job '{name}': {old_cron} → {args.cron}")

    # Reinstall if installed
    if _plist_path(name).exists():
        _install_job(name, jobs[name])
```

**Purpose:** Edit job schedule.

### cmd_run

```python
def cmd_run(args):
    jobs = _load_jobs()
    name = args.name

    if name not in jobs:
        print(f"  Job '{name}' not found.")
        return

    job = jobs[name]
    script_path = PROJECT_ROOT / job["script"]
    extra_args = job.get("args", [])

    cmd = [PYTHON, str(script_path)] + extra_args
    env = os.environ.copy()
    env["AGENT"] = AGENT_NAME

    print(f"  Running {name}...")
    result = subprocess.run(cmd, env=env)
    print(f"  Exit code: {result.returncode}")
```

**Purpose:** Run job manually.

### cmd_install

```python
def cmd_install(args):
    jobs = _load_jobs()
    for name, job in jobs.items():
        _install_job(name, job)
```

**Purpose:** Install all jobs to launchd.

### cmd_uninstall

```python
def cmd_uninstall(args):
    jobs = _load_jobs()
    for name in jobs:
        _uninstall_job(name)
```

**Purpose:** Uninstall all jobs from launchd.

## Internal Functions

### _install_job

```python
def _install_job(name: str, job: dict):
    """Install a single job to launchd."""
    plist = _generate_plist(name, job)
    plist_path = _plist_path(name)

    # Ensure logs directory exists
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Write plist
    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)

    # Load into launchd
    subprocess.run(["launchctl", "load", str(plist_path)], check=True)
    print(f"  Installed {name}")
```

**Purpose:** Install single job.

### _uninstall_job

```python
def _uninstall_job(name: str):
    """Unload and remove a single job."""
    plist_path = _plist_path(name)

    # Unload from launchd
    subprocess.run(["launchctl", "unload", str(plist_path)], check=False)

    # Remove plist
    if plist_path.exists():
        plist_path.unlink()
        print(f"  Uninstalled {name}")
```

**Purpose:** Uninstall single job.

## Main Entry Point

```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Companion scheduled tasks")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    list_parser = subparsers.add_parser("list", help="Show all jobs")
    list_parser.set_defaults(func=cmd_list)

    # add
    add_parser = subparsers.add_parser("add", help="Add a job")
    add_parser.add_argument("name", help="Job name")
    add_parser.add_argument("cron", help="Cron expression")
    add_parser.add_argument("script", help="Script path")
    add_parser.add_argument("--description", default="", help="Description")
    add_parser.add_argument("--install", action="store_true", help="Install immediately")
    add_parser.set_defaults(func=cmd_add)

    # remove
    remove_parser = subparsers.add_parser("remove", help="Remove a job")
    remove_parser.add_argument("name", help="Job name")
    remove_parser.set_defaults(func=cmd_remove)

    # edit
    edit_parser = subparsers.add_parser("edit", help="Edit job schedule")
    edit_parser.add_argument("name", help="Job name")
    edit_parser.add_argument("cron", help="New cron expression")
    edit_parser.set_defaults(func=cmd_edit)

    # run
    run_parser = subparsers.add_parser("run", help="Run job now")
    run_parser.add_argument("name", help="Job name")
    run_parser.set_defaults(func=cmd_run)

    # install
    install_parser = subparsers.add_parser("install", help="Install all jobs")
    install_parser.set_defaults(func=cmd_install)

    # uninstall
    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall all jobs")
    uninstall_parser.set_defaults(func=cmd_uninstall)

    args = parser.parse_args()
    args.func(args)
```

**Commands:**
- `list`: Show all jobs
- `add`: Add new job
- `remove`: Remove job
- `edit`: Edit schedule
- `run`: Run manually
- `install`: Install all
- `uninstall`: Uninstall all

## File I/O

| File | Purpose |
|------|---------|
| `scripts/agents/<name>/jobs.json` | Job definitions |
| `~/Library/LaunchAgents/com.atrophy.<name>.<job>.plist` | Launchd plists |
| `logs/<agent>/<job>.log` | Job logs |

## Exported API

| Function | Purpose |
|----------|---------|
| `cmd_list(args)` | List jobs |
| `cmd_add(args)` | Add job |
| `cmd_remove(args)` | Remove job |
| `cmd_edit(args)` | Edit schedule |
| `cmd_run(args)` | Run manually |
| `cmd_install(args)` | Install all |
| `cmd_uninstall(args)` | Uninstall all |
| `_parse_cron(cron_str)` | Parse cron expression |
| `_generate_plist(name, job)` | Generate plist |

## See Also

- `scripts/reconcile_jobs.py` - Automatic job reconciliation
- `src/main/channels/cron/scheduler.ts` - In-process cron scheduler
- `src/main/jobs/index.ts` - Job runner framework
