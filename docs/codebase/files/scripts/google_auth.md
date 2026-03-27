# scripts/google_auth.py - Google OAuth Setup

**Line count:** ~422 lines  
**Dependencies:** `json`, `os`, `shutil`, `subprocess`, `sys`, `pathlib`  
**Purpose:** Google OAuth2 setup using gws CLI (Google Workspace CLI)

## Overview

This script handles Google OAuth authentication for the Atrophy app. It uses the gws CLI (Google Workspace CLI) for the OAuth flow, with automatic dependency installation (Node.js → npm → gws).

**Usage:**
```bash
python scripts/google_auth.py              # Authorize (opens browser)
python scripts/google_auth.py --check      # Check if credentials valid
python scripts/google_auth.py --revoke     # Revoke and delete tokens
```

## Constants

### Services

```python
_SERVICES = "gmail,calendar,drive,tasks,sheets,docs,people,slides,meet,forms,keep"
```

**Purpose:** Google Workspace services to request access to.

### Extra Scopes

```python
_EXTRA_SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/photoslibrary",
    "https://www.googleapis.com/auth/photoslibrary.readonly",
    "https://www.googleapis.com/auth/webmasters",
    "https://www.googleapis.com/auth/webmasters.readonly",
]
_EXTRA_TOKEN_PATH = Path.home() / ".atrophy" / ".google" / "extra_token.json"
```

**Purpose:** Additional OAuth scopes not supported by gws CLI (YouTube, Photos, Search Console).

### OAuth Credentials

```python
_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")

# Fallback: ~/.atrophy/google_oauth.json
_oauth_creds_path = Path.home() / ".atrophy" / "google_oauth.json"

# Fallback: source repo (development)
_source_script = Path.home() / "Projects" / "Claude Code Projects" / "Atrophy App" / "scripts" / "google_auth.py"
```

**Credential resolution order:**
1. Environment variables
2. `~/.atrophy/google_oauth.json`
3. Source repo script (development fallback)

## Dependency Installation

### _ensure_node

```python
def _ensure_node() -> bool:
    """Ensure Node.js and npm are available."""
    # Check common paths (packaged Electron may have limited PATH)
    for p in ["/opt/homebrew/bin/npm", "/usr/local/bin/npm"]:
        if Path(p).exists():
            os.environ["PATH"] = str(Path(p).parent) + ":" + os.environ.get("PATH", "")
            break

    if shutil.which("npm"):
        return True

    # Try installing via Homebrew
    brew = shutil.which("brew")
    if brew:
        print("Node.js is not installed. Installing via Homebrew...")
        try:
            result = subprocess.run([brew, "install", "node"], timeout=120)
            if result.returncode == 0 and shutil.which("npm"):
                print("Node.js installed successfully.")
                return True
        except Exception as e:
            print(f"Node.js install error: {e}")

    # Give manual instructions
    print("error: Node.js is required but is not installed.")
    print("Install Node.js using one of these methods:")
    print("  • Download from https://nodejs.org (no admin required)")
    print("  • Or with Homebrew: brew install node")
    return False
```

**Purpose:** Ensure Node.js and npm are available.

**Installation chain:**
1. Check common paths
2. Install via Homebrew if available
3. Provide manual instructions if all else fails

### _ensure_gws

```python
def _ensure_gws() -> bool:
    """Ensure gws CLI is available. Uses npx as fallback."""
    global _GWS_BIN

    # Check common paths
    for p in ["/opt/homebrew/bin/gws", "/usr/local/bin/gws"]:
        if Path(p).exists():
            _GWS_BIN = p
            return True

    _GWS_BIN = shutil.which("gws")
    if _GWS_BIN:
        return True

    if not _ensure_node():
        return False

    # Try npx first (no install needed)
    npx = shutil.which("npx")
    if npx:
        print("Using npx to run Google Workspace CLI (no install needed)...")
        _GWS_BIN = "__npx__"  # sentinel
        return True

    # Fall back to local install (no -g, no sudo needed)
    npm = shutil.which("npm")
    local_dir = Path.home() / ".atrophy" / "tools" / "gws-cli"
    local_dir.mkdir(parents=True, exist_ok=True)
    print("Installing Google Workspace CLI locally...")
    try:
        result = subprocess.run(
            [npm, "install", "--prefix", str(local_dir), "@googleworkspace/cli"],
            timeout=60,
        )
        if result.returncode == 0:
            _GWS_BIN = str(local_dir / "node_modules" / ".bin" / "gws")
            return True
    except Exception as e:
        print(f"gws install error: {e}")

    return False
```

**Purpose:** Ensure gws CLI is available.

**Installation strategies:**
1. Check common paths
2. Use npx (no install)
3. Local install (no sudo)

## OAuth Flow

### run_oauth_flow

```python
def run_oauth_flow():
    """Run the OAuth flow via gws auth login."""
    if not _ensure_gws():
        return False

    # Set OAuth credentials in env
    env = os.environ.copy()
    env["GOOGLE_WORKSPACE_CLI_CLIENT_ID"] = _CLIENT_ID
    env["GOOGLE_WORKSPACE_CLI_CLIENT_SECRET"] = _CLIENT_SECRET

    # Run gws auth login
    if _GWS_BIN == "__npx__":
        cmd = ["npx", "gws", "auth", "login", "-s", _SERVICES]
    else:
        cmd = [_GWS_BIN, "auth", "login", "-s", _SERVICES]

    print("Opening browser for Google authentication...")
    result = subprocess.run(cmd, env=env)

    if result.returncode == 0:
        print("Authentication successful!")
        return True
    else:
        print("Authentication failed.")
        return False
```

**Purpose:** Run OAuth flow via gws CLI.

**Environment:**
- Sets `GOOGLE_WORKSPACE_CLI_CLIENT_ID`
- Sets `GOOGLE_WORKSPACE_CLI_CLIENT_SECRET`

### run_extra_oauth_flow

```python
def run_extra_oauth_flow():
    """Run OAuth for extra scopes (YouTube, Photos, Search Console)."""
    # These scopes require separate OAuth flow
    # Uses custom OAuth implementation
    pass
```

**Purpose:** Handle extra scopes not supported by gws CLI.

## Commands

### Check Command

```python
def check_auth():
    """Check if credentials are valid."""
    if not _GWS_BIN:
        if not _ensure_gws():
            return False

    env = os.environ.copy()
    env["GOOGLE_WORKSPACE_CLI_CLIENT_ID"] = _CLIENT_ID
    env["GOOGLE_WORKSPACE_CLI_CLIENT_SECRET"] = _CLIENT_SECRET

    if _GWS_BIN == "__npx__":
        cmd = ["npx", "gws", "auth", "status"]
    else:
        cmd = [_GWS_BIN, "auth", "status"]

    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    return result.returncode == 0
```

**Purpose:** Check if credentials are valid.

### Revoke Command

```python
def revoke_auth():
    """Revoke and delete tokens."""
    if not _GWS_BIN:
        if not _ensure_gws():
            return False

    env = os.environ.copy()
    env["GOOGLE_WORKSPACE_CLI_CLIENT_ID"] = _CLIENT_ID
    env["GOOGLE_WORKSPACE_CLI_CLIENT_SECRET"] = _CLIENT_SECRET

    if _GWS_BIN == "__npx__":
        cmd = ["npx", "gws", "auth", "revoke"]
    else:
        cmd = [_GWS_BIN, "auth", "revoke"]

    result = subprocess.run(cmd, env=env)

    # Delete token files
    token_path = Path.home() / ".atrophy" / ".google" / "token.json"
    if token_path.exists():
        token_path.unlink()

    return result.returncode == 0
```

**Purpose:** Revoke credentials and delete tokens.

## Main Entry Point

```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Google OAuth2 setup")
    parser.add_argument("--check", action="store_true", help="Check if credentials are valid")
    parser.add_argument("--revoke", action="store_true", help="Revoke and delete tokens")

    args = parser.parse_args()

    if args.check:
        if check_auth():
            print("Credentials are valid.")
            sys.exit(0)
        else:
            print("Credentials are invalid or missing.")
            sys.exit(1)
    elif args.revoke:
        if revoke_auth():
            print("Credentials revoked.")
            sys.exit(0)
        else:
            print("Failed to revoke credentials.")
            sys.exit(1)
    else:
        if run_oauth_flow():
            sys.exit(0)
        else:
            sys.exit(1)
```

**Commands:**
- No args: Run OAuth flow
- `--check`: Check credentials
- `--revoke`: Revoke credentials

## File I/O

| File | Purpose |
|------|---------|
| `~/.atrophy/google_oauth.json` | OAuth credentials fallback |
| `~/.atrophy/.google/token.json` | gws CLI tokens |
| `~/.atrophy/.google/extra_token.json` | Extra scope tokens |
| `~/.atrophy/tools/gws-cli/` | Local gws install |

## Exported API

| Function | Purpose |
|----------|---------|
| `run_oauth_flow()` | Run main OAuth flow |
| `run_extra_oauth_flow()` | Run extra scope OAuth |
| `check_auth()` | Check credential validity |
| `revoke_auth()` | Revoke credentials |
| `_ensure_node()` | Ensure Node.js installed |
| `_ensure_gws()` | Ensure gws CLI available |

## See Also

- `src/main/config.ts` - Google OAuth configuration
- `mcp/google_server.py` - Google MCP server
- `src/main/ipc/window.ts` - Google OAuth IPC handlers
