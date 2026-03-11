#!/usr/bin/env python3
"""Google OAuth2 setup — browser-based flow for Gmail + Calendar access.

Usage:
    python scripts/google_auth.py              # Authorize (opens browser)
    python scripts/google_auth.py --check      # Check if credentials are valid
    python scripts/google_auth.py --revoke     # Revoke and delete tokens

OAuth client credentials are bundled with the app (they identify the app,
not the user). The user just authorizes via a browser consent screen.

Tokens stored at ~/.atrophy/.google/token.json (auto-generated, 600 perms).
"""
import json
import sys
from pathlib import Path

GOOGLE_DIR = Path.home() / ".atrophy" / ".google"
TOKEN_FILE = GOOGLE_DIR / "token.json"

# Bundled OAuth client credentials — identifies the app, not the user.
# These are safe to ship: Google's security model for "Desktop" apps treats
# client_id/secret as public (the user still authorizes via consent screen).
_BUNDLED_CREDENTIALS_FILE = Path(__file__).parent.parent / "config" / "google_oauth.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def ensure_dir():
    GOOGLE_DIR.mkdir(parents=True, exist_ok=True)
    GOOGLE_DIR.chmod(0o700)


def _credentials_file() -> Path:
    """Find OAuth client credentials — bundled with the app."""
    if _BUNDLED_CREDENTIALS_FILE.exists():
        return _BUNDLED_CREDENTIALS_FILE
    raise FileNotFoundError(
        f"Bundled Google OAuth credentials not found at {_BUNDLED_CREDENTIALS_FILE}. "
        "This file should be included with the app."
    )


def run_oauth_flow() -> bool:
    """Run the OAuth2 browser flow. Opens consent screen, saves tokens. Returns True on success."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Missing dependency: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")
        return False

    try:
        creds_file = _credentials_file()
    except FileNotFoundError as e:
        print(str(e))
        return False

    ensure_dir()

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(creds.to_json())
    TOKEN_FILE.chmod(0o600)
    print("Google OAuth tokens saved.")
    return True


def load_credentials():
    """Load and refresh credentials. Returns google.oauth2.credentials.Credentials or None."""
    if not TOKEN_FILE.exists():
        return None

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json())
            TOKEN_FILE.chmod(0o600)

        if creds and creds.valid:
            return creds
    except Exception as e:
        print(f"Error loading Google credentials: {e}")

    return None


def check_credentials() -> bool:
    """Check if valid credentials exist."""
    creds = load_credentials()
    if creds:
        print("Google credentials are valid.")
        return True
    else:
        print("No valid Google credentials found.")
        return False


def revoke_credentials():
    """Revoke tokens and delete local files."""
    creds = load_credentials()
    if creds:
        try:
            from google.auth.transport.requests import Request
            import requests
            requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": creds.token},
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            print("Tokens revoked.")
        except Exception:
            print("Could not revoke remotely (tokens may already be invalid).")

    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
        print(f"Deleted {TOKEN_FILE}")

    print("Google credentials removed.")


def is_configured() -> bool:
    """Quick check — do we have a token file at all?"""
    return TOKEN_FILE.exists()


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(0 if check_credentials() else 1)
    elif "--revoke" in sys.argv:
        revoke_credentials()
    else:
        print("Google OAuth Setup")
        print("=" * 40)
        print()
        print("This will open your browser to authorize Gmail + Calendar access.")
        print("Your Google account data stays on your machine — nothing is sent to Atrophy.")
        print()
        if run_oauth_flow():
            print("\nDone. Google integration is ready.")
        else:
            sys.exit(1)
