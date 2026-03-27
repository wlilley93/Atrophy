# scripts/reconcile_jobs.py - Launchd Job Reconciliation

**Line count:** ~437 lines  
**Dependencies:** `argparse`, `json`, `os`, `plistlib`, `re`, `subprocess`, `sys`, `pathlib`  
**Purpose:** Reconcile launchd jobs against agent.json definitions

## Overview

This script ensures scheduled jobs run even when the Electron app isn't open (e.g., 3am sleep_cycle, 7am morning_brief). It reads each agent's agent.json, generates correct launchd plists, compares against what's installed, and installs/removes as needed.

**The in-process cron scheduler handles jobs while the app is running; launchd handles persistence.**

**Usage:**
```bash
python reconcile_jobs.py                    # Reconcile all agents
python reconcile_jobs.py --agent companion  # Single agent
python reconcile_jobs.py --dry-run          # Preview only
python reconcile_jobs.py --remove-stale     # Also unload jobs not in agent.json
```

## Constants

```python
AGENTS_DIR = Path.home() / ".atrophy" / "agents"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PREFIX = "com.atrophy"

# Python interpreter to use in plists
PYTHON = str(Path.home() / ".pyenv" / "versions" / "3.12.7" / "bin" / "python3")
if not os.path.exists(PYTHON):
    PYTHON = sys.executable  # Fallback to running Python
```

**Purpose:** Define paths and Python interpreter for launchd jobs.

## Agent Discovery

### discover_agents

```python
def discover_agents() -> list[str]:
    """Find all agent directories in ~/.atrophy/agents/."""
    if not AGENTS_DIR.is_dir():
        return []
    return [
        d.name for d in AGENTS_DIR.iterdir()
        if d.is_dir() and (d / "data" / "agent.json").exists()
    ]
```

**Purpose:** Find all configured agents.

### load_manifest

```python
def load_manifest(agent_name: str) -> dict:
    """Load an agent's agent.json manifest."""
    path = AGENTS_DIR / agent_name / "data" / "agent.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)
```

**Purpose:** Load agent configuration.

## Cron Parsing

### _expand_cron_token

```python
def _expand_cron_token(token: str, field_max: int = 59) -> list[int]:
    """Expand a single cron token into a list of ints."""
    if token.startswith("*/"):
        step = int(token[2:])
        return list(range(0, field_max + 1, step))
    if "-" in token:
        lo, hi = token.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(token)]
```

**Purpose:** Expand cron tokens like `*/6`, `1-5`, `3` into lists.

### _parse_field

```python
def _parse_field(value: str, field_max: int = 59):
    """Parse a single cron field."""
    parts: list[int] = []
    for token in value.split(","):
        parts.extend(_expand_cron_token(token.strip(), field_max))
    return parts[0] if len(parts) == 1 else parts
```

**Purpose:** Parse comma-separated cron fields.

### parse_cron_expr

```python
def parse_cron_expr(cron: str):
    """Convert a cron expression to a launchd StartCalendarInterval dict or list.

    Supports: "min hour * * *" (daily), "min hour dom * *" (monthly),
    and simple 5-field cron expressions. Comma-separated values produce
    an array of StartCalendarInterval dicts (one per combo).
    """
    parts = cron.strip().split()
    if len(parts) != 5:
        return {}

    minute, hour, dom, month, dow = parts
    keys = ["Minute", "Hour", "Day", "Month", "Weekday"]
    field_maxes = [59, 23, 31, 12, 6]
    parsed = {}

    for key, val, fmax in zip(keys, [minute, hour, dom, month, dow], field_maxes):
        if val != "*":
            parsed[key] = _parse_field(val, fmax)

    # If any field has a list, expand into multiple dicts
    list_keys = [k for k, v in parsed.items() if isinstance(v, list)]
    if not list_keys:
        return parsed

    from itertools import product as _product
    combos = []
    list_vals = [parsed[k] if isinstance(parsed[k], list) else [parsed[k]] for k in keys if k in parsed]
    combo_keys = [k for k in keys if k in parsed]
    for combo in _product(*list_vals):
        combos.append(dict(zip(combo_keys, combo)))
    return combos
```

**Purpose:** Convert cron expressions to launchd format.

**Examples:**
- `"0 9 * * *"` → `{"Minute": 0, "Hour": 9}`
- `"0 9,17 * * *"` → `[{"Minute": 0, "Hour": 9}, {"Minute": 0, "Hour": 17}]`
- `"*/30 * * * *"` → `{"Minute": [0, 30]}`

## Script Path Resolution

### resolve_script_path

```python
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

    # Return /tmp/atrophy version (will fail at runtime with clear error)
    return os.path.join("/tmp/atrophy", script_rel)
```

**Purpose:** Resolve script paths for launchd plists.

**Resolution order:**
1. `/tmp/atrophy` symlink (standard deployment)
2. Project root (development)
3. `/tmp/atrophy` (will fail with clear error)

## Plist Building

### build_plist

```python
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

    # Build environment
    env = {
        "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
        "AGENT": agent_name,
    }

    # Add job-specific env vars
    if "env" in job_def:
        env.update(job_def["env"])

    # Build plist
    plist = {
        "Label": label,
        "ProgramArguments": prog_args,
        "WorkingDirectory": str(PROJECT_ROOT),
        "EnvironmentVariables": env,
        "StandardOutPath": str(Path.home() / ".atrophy" / "logs" / f"{agent_name}.{job_name}.stdout.log"),
        "StandardErrorPath": str(Path.home() / ".atrophy" / "logs" / f"{agent_name}.{job_name}.stderr.log"),
    }

    # Handle schedule type
    job_type = job_def.get("type", "calendar")
    if job_type == "interval":
        plist["StartInterval"] = job_def.get("interval_seconds", 60)
    else:
        cron = job_def.get("cron", "* * * * *")
        interval = parse_cron_expr(cron)
        plist["StartCalendarInterval"] = interval

    return plist
```

**Purpose:** Build launchd plist dictionary.

**Plist structure:**
```python
{
    "Label": "com.atrophy.companion.sleep_cycle",
    "ProgramArguments": ["/usr/bin/python3", "scripts/agents/shared/sleep_cycle.py"],
    "WorkingDirectory": "/path/to/project",
    "EnvironmentVariables": {"PATH": "...", "AGENT": "companion"},
    "StandardOutPath": "~/.atrophy/logs/companion.sleep_cycle.stdout.log",
    "StandardErrorPath": "~/.atrophy/logs/companion.sleep_cycle.stderr.log",
    "StartCalendarInterval": {"Minute": 0, "Hour": 3},  # 3am daily
}
```

## Job Installation

### install_job

```python
def install_job(agent_name: str, job_name: str, job_def: dict, dry_run: bool = False) -> bool:
    """Install a launchd job."""
    plist = build_plist(agent_name, job_name, job_def)
    plist_path = LAUNCH_AGENTS_DIR / f"{plist['Label']}.plist"

    if dry_run:
        print(f"Would install {plist['Label']} to {plist_path}")
        print(plistlib.dumps(plist).decode())
        return True

    # Write plist
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)

    # Load into launchd
    try:
        subprocess.run(["launchctl", "load", str(plist_path)], check=True)
        print(f"Installed {plist['Label']}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to load {plist['Label']}: {e}")
        return False
```

**Purpose:** Install a launchd job.

### uninstall_job

```python
def uninstall_job(agent_name: str, job_name: str, dry_run: bool = False) -> bool:
    """Unload and remove a launchd job."""
    label = f"{PLIST_PREFIX}.{agent_name}.{job_name}"
    plist_path = LAUNCH_AGENTS_DIR / f"{label}.plist"

    if dry_run:
        print(f"Would uninstall {label}")
        return True

    # Unload from launchd
    try:
        subprocess.run(["launchctl", "unload", str(plist_path)], check=True)
    except subprocess.CalledProcessError:
        pass  # May not be loaded

    # Remove plist
    if plist_path.exists():
        plist_path.unlink()
        print(f"Uninstalled {label}")
        return True

    return False
```

**Purpose:** Uninstall a launchd job.

## Reconciliation

### reconcile_agent

```python
def reconcile_agent(agent_name: str, dry_run: bool = False, remove_stale: bool = False) -> bool:
    """Reconcile jobs for a single agent."""
    manifest = load_manifest(agent_name)
    jobs = manifest.get("jobs", {})

    if not jobs:
        print(f"No jobs defined for {agent_name}")
        return True

    success = True
    installed_jobs = get_installed_jobs(agent_name)

    # Install jobs from manifest
    for job_name, job_def in jobs.items():
        if job_name not in installed_jobs:
            if not install_job(agent_name, job_name, job_def, dry_run):
                success = False
        else:
            # Check if plist needs update
            current_plist = build_plist(agent_name, job_name, job_def)
            installed_plist = load_installed_plist(agent_name, job_name)
            if current_plist != installed_plist:
                if dry_run:
                    print(f"Would update {agent_name}.{job_name}")
                else:
                    uninstall_job(agent_name, job_name, dry_run)
                    install_job(agent_name, job_name, job_def, dry_run)

    # Remove stale jobs
    if remove_stale:
        for job_name in installed_jobs:
            if job_name not in jobs:
                uninstall_job(agent_name, job_name, dry_run)

    return success
```

**Purpose:** Reconcile jobs for an agent.

**Flow:**
1. Load agent manifest
2. Get installed jobs
3. Install missing jobs
4. Update changed jobs
5. Remove stale jobs (if `--remove-stale`)

### get_installed_jobs

```python
def get_installed_jobs(agent_name: str) -> list[str]:
    """Get list of installed job names for an agent."""
    installed = []
    for plist in LAUNCH_AGENTS_DIR.glob(f"{PLIST_PREFIX}.{agent_name}.*.plist"):
        job_name = plist.stem.split(".")[-1]
        installed.append(job_name)
    return installed
```

**Purpose:** Find installed jobs for an agent.

## Main Entry Point

```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reconcile launchd jobs")
    parser.add_argument("--agent", help="Single agent to reconcile")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--remove-stale", action="store_true", help="Remove jobs not in manifest")

    args = parser.parse_args()

    if args.agent:
        agents = [args.agent]
    else:
        agents = discover_agents()

    success = True
    for agent in agents:
        if not reconcile_agent(agent, args.dry_run, args.remove_stale):
            success = False

    sys.exit(0 if success else 1)
```

**Options:**
- `--agent`: Single agent
- `--dry-run`: Preview changes
- `--remove-stale`: Remove undefined jobs

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/agents/<name>/data/agent.json` | Agent job definitions |
| `~/Library/LaunchAgents/com.atrophy.*.plist` | Launchd job plists |
| `~/.atrophy/logs/<agent>.<job>.stdout.log` | Job stdout |
| `~/.atrophy/logs/<agent>.<job>.stderr.log` | Job stderr |

## Exported API

| Function | Purpose |
|----------|---------|
| `discover_agents()` | Find all agents |
| `load_manifest(agent_name)` | Load agent manifest |
| `parse_cron_expr(cron)` | Parse cron to launchd format |
| `resolve_script_path(agent_name, script_rel)` | Resolve script path |
| `build_plist(agent_name, job_name, job_def)` | Build launchd plist |
| `install_job(agent_name, job_name, job_def)` | Install job |
| `uninstall_job(agent_name, job_name)` | Uninstall job |
| `reconcile_agent(agent_name)` | Reconcile agent jobs |

## See Also

- `src/main/channels/cron/scheduler.ts` - In-process cron scheduler
- `src/main/jobs/index.ts` - Job runner framework
- `src/main/ipc/system.ts` - Job IPC handlers
