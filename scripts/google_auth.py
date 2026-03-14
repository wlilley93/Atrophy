#!/usr/bin/env python3
"""Google OAuth2 setup — uses the gws CLI (Google Workspace CLI).

Usage:
    python scripts/google_auth.py              # Authorize (opens browser via gws)
    python scripts/google_auth.py --check      # Check if credentials are valid
    python scripts/google_auth.py --revoke     # Revoke and delete tokens

Dependency chain: Homebrew → Node.js → npm → gws CLI → gws auth login
Each step is checked and installed if missing (with user-facing instructions on failure).
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Services we request access to
_SERVICES = "gmail,calendar,drive,tasks,sheets,docs,people,slides,meet,forms,keep"


# Extra scopes (separate OAuth flow — gws CLI doesn't support these)
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

# Google's security model for Desktop apps treats these as public
# (the user still authorizes via browser consent screen).
# Load from env vars, then fall back to ~/.atrophy/google_oauth.json
_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")

if not _CLIENT_ID or not _CLIENT_SECRET:
    # Try loading from local config file
    _oauth_creds_path = Path.home() / ".atrophy" / "google_oauth.json"
    if _oauth_creds_path.exists():
        try:
            _creds = json.loads(_oauth_creds_path.read_text())
            _CLIENT_ID = _creds.get("client_id", _CLIENT_ID)
            _CLIENT_SECRET = _creds.get("client_secret", _CLIENT_SECRET)
        except Exception:
            pass

if not _CLIENT_ID or not _CLIENT_SECRET:
    # Try loading from source repo's google_auth.py (development fallback)
    _source_script = Path.home() / "Projects" / "Claude Code Projects" / "Atrophy App" / "scripts" / "google_auth.py"
    if _source_script.exists():
        try:
            import re as _re
            _src = _source_script.read_text()
            _id_match = _re.search(r'_CLIENT_ID\s*=\s*"([^"]+)"', _src)
            _secret_match = _re.search(r'_CLIENT_SECRET\s*=\s*"([^"]+)"', _src)
            if _id_match and not _CLIENT_ID:
                _CLIENT_ID = _id_match.group(1)
            if _secret_match and not _CLIENT_SECRET:
                _CLIENT_SECRET = _secret_match.group(1)
        except Exception:
            pass

_GWS_BIN = shutil.which("gws")


def _ensure_node() -> bool:
    """Ensure Node.js and npm are available. Gives clear instructions if missing."""
    # Check common paths (packaged Electron may have limited PATH)
    for p in ["/opt/homebrew/bin/npm", "/usr/local/bin/npm"]:
        if Path(p).exists():
            os.environ["PATH"] = str(Path(p).parent) + ":" + os.environ.get("PATH", "")
            break

    if shutil.which("npm"):
        return True

    # Check if brew exists — if so, try installing node (no sudo needed)
    brew = shutil.which("brew")
    if not brew:
        for p in ["/opt/homebrew/bin/brew", "/usr/local/bin/brew"]:
            if Path(p).exists():
                brew = p
                break

    if brew:
        print("Node.js is not installed. Installing via Homebrew...")
        try:
            result = subprocess.run([brew, "install", "node"], timeout=120)
            if result.returncode == 0 and shutil.which("npm"):
                print("Node.js installed successfully.")
                return True
        except Exception as e:
            print(f"Node.js install error: {e}")

    # Don't try to install Homebrew — it requires admin and will fail for
    # non-admin users. Give clear manual instructions instead.
    print()
    print("error: Node.js is required for Google integration but is not installed.")
    print()
    print("Install Node.js using one of these methods:")
    print("  • Download from https://nodejs.org (no admin required)")
    print("  • Or with Homebrew: brew install node")
    print()
    print("Then re-run Google setup from Settings.")
    return False


def _ensure_gws() -> bool:
    """Ensure gws CLI is available. Uses npx as fallback to avoid global install."""
    global _GWS_BIN

    # Check common paths (packaged Electron may have limited PATH)
    for p in ["/opt/homebrew/bin/gws", "/usr/local/bin/gws"]:
        if Path(p).exists():
            _GWS_BIN = p
            return True

    _GWS_BIN = shutil.which("gws")
    if _GWS_BIN:
        return True

    if not _ensure_node():
        return False

    # Try npx first — runs without global install and without sudo
    npx = shutil.which("npx")
    if npx:
        print("Using npx to run Google Workspace CLI (no install needed)...")
        _GWS_BIN = "__npx__"  # sentinel; run_oauth_flow handles this
        return True

    # Fall back to local install (no -g, no sudo needed)
    npm = shutil.which("npm")
    if not npm:
        print("npm not found. Please restart your terminal and try again.")
        return False

    # Install to user-local directory instead of global
    local_dir = Path.home() / ".atrophy" / "tools" / "gws-cli"
    local_dir.mkdir(parents=True, exist_ok=True)
    print("Installing Google Workspace CLI locally...")
    try:
        result = subprocess.run(
            [npm, "install", "--prefix", str(local_dir), "@googleworkspace/cli"],
            timeout=60,
        )
        local_bin = local_dir / "node_modules" / ".bin" / "gws"
        if result.returncode == 0 and local_bin.exists():
            _GWS_BIN = str(local_bin)
            print("gws CLI installed successfully.")
            return True
        print("gws install failed.")
    except subprocess.TimeoutExpired:
        print("gws install timed out.")
    except Exception as e:
        print(f"gws install error: {e}")

    print()
    print("Please install manually:")
    print("  npm install -g @googleworkspace/cli")
    return False


def _gws_cmd() -> list:
    """Return the command prefix to run gws (direct binary or via npx)."""
    if _GWS_BIN == "__npx__":
        npx = shutil.which("npx")
        return [npx, "-y", "@googleworkspace/cli"]
    return [_GWS_BIN]


def _open_browser(url: str):
    """Open a URL in the user's browser.

    Prints an OPEN_URL: marker so the Electron parent process can intercept it
    and call shell.openExternal() — which is reliable even from packaged apps.
    Falls back to Python's webbrowser.open() for standalone usage.
    """
    import webbrowser

    # Marker for Electron IPC handler to detect and open reliably
    print(f"OPEN_URL:{url}", flush=True)
    # Also try Python's webbrowser as fallback (works when run from terminal)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def run_oauth_flow() -> bool:
    """Run OAuth2 via gws auth login. Opens browser for consent. Returns True on success."""
    if not _ensure_gws():
        return False

    print(f"\nAuthenticating with Google for: {_SERVICES}")
    print("This will open your browser for consent.\n")

    # Pass bundled OAuth client credentials via env vars
    env = dict(os.environ)
    env["GOOGLE_WORKSPACE_CLI_CLIENT_ID"] = _CLIENT_ID
    env["GOOGLE_WORKSPACE_CLI_CLIENT_SECRET"] = _CLIENT_SECRET
    # Help gws find the system browser when spawned from Electron
    if sys.platform == "darwin":
        env.setdefault("BROWSER", "/usr/bin/open")

    # Capture gws output so we can detect and forward auth URLs
    result = subprocess.run(
        [*_gws_cmd(), "auth", "login", "-s", _SERVICES],
        env=env,
        capture_output=True, text=True,
        timeout=120,
    )

    # Forward output
    combined = (result.stdout or "") + (result.stderr or "")
    if combined.strip():
        print(combined.strip())

    # If gws printed an auth URL, open it via the Electron-intercepted channel
    import re
    url_match = re.search(r'(https://accounts\.google\.com\S+)', combined)
    if url_match:
        _open_browser(url_match.group(1))

    if result.returncode != 0:
        return False

    # Extra APIs auth (YouTube, Photos, Search Console — gws doesn't support these scopes)
    print("\nNow authenticating YouTube, Photos, and Search Console...")
    return run_extra_oauth()


def run_extra_oauth() -> bool:
    """Lightweight OAuth2 flow for YouTube, Photos, and Search Console scopes."""
    import http.server
    import urllib.parse
    import urllib.request

    _EXTRA_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Find a free port
    import socket
    sock = socket.socket()
    sock.bind(("", 0))
    port = sock.getsockname()[1]
    sock.close()

    redirect_uri = f"http://localhost:{port}"
    scope = " ".join(_EXTRA_SCOPES)
    auth_url = (
        "https://accounts.google.com/o/oauth2/auth?"
        + urllib.parse.urlencode({
            "client_id": _CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
            "access_type": "offline",
            "prompt": "consent",
        })
    )

    auth_code = None

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal auth_code
            qs = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(qs)
            auth_code = params.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Authenticated. You can close this tab.</h2></body></html>")

        def log_message(self, *args):
            pass  # Suppress logs

    server = http.server.HTTPServer(("", port), Handler)
    server.timeout = 120

    print(f"Opening browser for YouTube, Photos, and Search Console consent...")
    print(f"If it doesn't open, visit: {auth_url}\n")
    _open_browser(auth_url)

    server.handle_request()
    server.server_close()

    if not auth_code:
        print("Auth failed — no authorization code received.")
        return False

    # Exchange code for tokens
    data = urllib.parse.urlencode({
        "code": auth_code,
        "client_id": _CLIENT_ID,
        "client_secret": _CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            token_data = json.loads(resp.read())
    except Exception as e:
        print(f"Token exchange failed: {e}")
        return False

    # Save token
    _EXTRA_TOKEN_PATH.write_text(json.dumps(token_data, indent=2) + "\n")
    _EXTRA_TOKEN_PATH.chmod(0o600)
    print("YouTube, Photos, and Search Console authenticated.")
    return True


def _find_gws() -> bool:
    """Locate the gws binary, checking common paths."""
    global _GWS_BIN
    # Check common paths first (packaged Electron has limited PATH)
    for p in ["/opt/homebrew/bin/gws", "/usr/local/bin/gws"]:
        if Path(p).exists():
            _GWS_BIN = p
            return True
    # Local install path
    local_bin = Path.home() / ".atrophy" / "tools" / "gws-cli" / "node_modules" / ".bin" / "gws"
    if local_bin.exists():
        _GWS_BIN = str(local_bin)
        return True
    _GWS_BIN = shutil.which("gws")
    if _GWS_BIN:
        return True
    # npx fallback
    if shutil.which("npx"):
        _GWS_BIN = "__npx__"
        return True
    return False


def check_credentials() -> bool:
    """Check if valid credentials exist via gws auth status."""
    if not _find_gws():
        print("gws CLI not installed.")
        return False

    result = subprocess.run(
        [*_gws_cmd(), "auth", "status"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        print("No valid Google credentials found.")
        return False

    try:
        status = json.loads(result.stdout)
        auth_method = status.get("auth_method", "none")
        if auth_method != "none":
            print(f"Google credentials valid (method: {auth_method}).")
            return True
        print("No valid Google credentials found.")
        return False
    except (json.JSONDecodeError, KeyError):
        print("Could not check auth status.")
        return False


def revoke_credentials():
    """Revoke tokens via gws auth logout."""
    if not _find_gws():
        print("gws CLI not installed.")
        return

    subprocess.run([*_gws_cmd(), "auth", "logout"], timeout=10)
    print("Google credentials removed.")


def is_configured() -> bool:
    """Quick check — is gws authenticated?"""
    if not _find_gws():
        return False
    try:
        result = subprocess.run(
            [*_gws_cmd(), "auth", "status"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return False
        status = json.loads(result.stdout)
        return status.get("auth_method", "none") != "none"
    except Exception:
        return False


# Backward compat
def load_credentials():
    return True if is_configured() else None


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(0 if check_credentials() else 1)
    elif "--revoke" in sys.argv:
        revoke_credentials()
    else:
        print("Google Workspace Setup")
        print("=" * 40)
        print()
        print("This will install dependencies and open your browser")
        print("to authorize Gmail, Calendar, Drive, Sheets, Docs, Slides, Tasks,")
        print("People, Meet, Forms, Keep, YouTube, Photos, and Search Console.")
        print("Your Google data stays on your machine.")
        print()
        if run_oauth_flow():
            print("\nDone. Google integration is ready.")
        else:
            print("\nSetup incomplete. Follow the instructions above, then re-run this script.")
            sys.exit(1)
