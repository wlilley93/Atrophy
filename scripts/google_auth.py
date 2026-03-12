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

# OAuth client credentials - loaded from env or ~/.atrophy/.env
_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")

_GWS_BIN = shutil.which("gws")


def _ensure_node() -> bool:
    """Ensure Node.js and npm are installed. Install via Homebrew if missing."""
    if shutil.which("npm"):
        return True

    print("Node.js is not installed. Attempting to install via Homebrew...")

    brew = shutil.which("brew")
    if not brew:
        print("Homebrew is not installed. Installing Homebrew...")
        try:
            result = subprocess.run(
                ["/bin/bash", "-c",
                 'NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'],
                timeout=300,
            )
            # Homebrew on Apple Silicon installs to /opt/homebrew
            for p in ["/opt/homebrew/bin/brew", "/usr/local/bin/brew"]:
                if Path(p).exists():
                    brew = p
                    break
            if not brew:
                brew = shutil.which("brew")
        except Exception as e:
            print(f"Homebrew install failed: {e}")

        if not brew:
            print()
            print("Homebrew install failed. Please install manually:")
            print('  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"')
            print()
            print("Or install Node.js directly: https://nodejs.org")
            return False
        print("Homebrew installed successfully.")

    try:
        result = subprocess.run(
            [brew, "install", "node"],
            timeout=120,
        )
        if result.returncode == 0 and shutil.which("npm"):
            print("Node.js installed successfully.")
            return True
        print("Homebrew install of Node.js failed.")
    except subprocess.TimeoutExpired:
        print("Node.js install timed out.")
    except Exception as e:
        print(f"Node.js install error: {e}")

    print()
    print("Please install Node.js manually: https://nodejs.org")
    return False


def _ensure_gws() -> bool:
    """Ensure gws CLI is installed. Install via npm if missing."""
    global _GWS_BIN
    _GWS_BIN = shutil.which("gws")
    if _GWS_BIN:
        return True

    if not _ensure_node():
        return False

    npm = shutil.which("npm")
    if not npm:
        print("npm still not found after Node install. Please restart your terminal and try again.")
        return False

    print("Installing Google Workspace CLI (gws)...")
    try:
        result = subprocess.run(
            [npm, "install", "-g", "@googleworkspace/cli"],
            timeout=60,
        )
        _GWS_BIN = shutil.which("gws")
        if result.returncode == 0 and _GWS_BIN:
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

    result = subprocess.run(
        [_GWS_BIN, "auth", "login", "-s", _SERVICES],
        env=env,
        timeout=120,
    )
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
    import webbrowser

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
    webbrowser.open(auth_url)

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


def check_credentials() -> bool:
    """Check if valid credentials exist via gws auth status."""
    global _GWS_BIN
    _GWS_BIN = shutil.which("gws")
    if not _GWS_BIN:
        print("gws CLI not installed.")
        return False

    result = subprocess.run(
        [_GWS_BIN, "auth", "status"],
        capture_output=True, text=True, timeout=10,
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
    global _GWS_BIN
    _GWS_BIN = shutil.which("gws")
    if not _GWS_BIN:
        print("gws CLI not installed.")
        return

    subprocess.run([_GWS_BIN, "auth", "logout"], timeout=10)
    print("Google credentials removed.")


def is_configured() -> bool:
    """Quick check — is gws authenticated?"""
    global _GWS_BIN
    _GWS_BIN = shutil.which("gws")
    if not _GWS_BIN:
        return False
    try:
        result = subprocess.run(
            [_GWS_BIN, "auth", "status"],
            capture_output=True, text=True, timeout=5,
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
