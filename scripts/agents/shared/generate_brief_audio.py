#!/usr/bin/env python3
"""Generate TTS audio for intelligence briefs using ElevenLabs.

Reads brief text from intelligence.db, cleans it for speech, calls the
ElevenLabs API, and saves the resulting MP3 alongside the brief record.

Usage:
    # Generate audio for a specific brief
    python generate_brief_audio.py --brief-id 28

    # Process all eligible briefs without audio
    python generate_brief_audio.py

    # Dry run - show what would be generated
    python generate_brief_audio.py --dry-run

Importable:
    from generate_brief_audio import generate_audio
    generate_audio(brief_id=28)
"""
import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

# ── Logging ──

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [brief-audio] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Paths ──

AGENT_DIR = Path.home() / ".atrophy" / "agents" / "general_montgomery"
DB_PATH = AGENT_DIR / "data" / "intelligence.db"
MANIFEST_PATH = AGENT_DIR / "data" / "agent.json"
AUDIO_DIR = AGENT_DIR / "audio" / "briefs"
ENV_PATH = Path.home() / ".atrophy" / ".env"

ELIGIBLE_TYPES = ("FLASH", "WEEKLY_DIGEST", "SITREP", "SYNTHESIS")
MIN_LENGTH = 200
MAX_LENGTH = 5000
TTS_CHAR_LIMIT = 5000
INTER_CALL_DELAY = 2  # seconds between ElevenLabs API calls


def _load_env() -> None:
    """Load .env file manually - no dotenv dependency required."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


def _get_voice_id() -> str:
    """Read the ElevenLabs voice ID from the agent manifest."""
    manifest = json.loads(MANIFEST_PATH.read_text())
    voice_id = manifest.get("voice", {}).get("elevenlabs_voice_id", "")
    if not voice_id:
        raise ValueError("No elevenlabs_voice_id found in agent manifest")
    return voice_id


def _connect() -> sqlite3.Connection:
    """Open a connection to the intelligence database."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Intelligence database not found: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def clean_text_for_tts(text: str) -> str:
    """Strip markdown formatting to produce clean prose for TTS.

    Removes:
    - Markdown headers (## Header)
    - Bold/italic markers (**bold**, *italic*, __bold__, _italic_)
    - Links [text](url) - keeps the text
    - Image references ![alt](url)
    - Code blocks (``` ... ```)
    - Inline code (`code`)
    - Horizontal rules (---, ***)
    - HTML tags
    - Bullet markers (-, *, numbered lists)
    - Excessive whitespace
    """
    # Remove code blocks (fenced)
    text = re.sub(r"```[\s\S]*?```", "", text)

    # Remove inline code
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Remove images
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", "", text)

    # Convert links to just the text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Remove markdown headers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # Remove horizontal rules
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)

    # Remove bold/italic markers
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)

    # Remove bullet markers (-, *, +) at start of lines
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)

    # Remove numbered list markers
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)

    # Collapse multiple newlines to double
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Collapse multiple spaces
    text = re.sub(r" {2,}", " ", text)

    return text.strip()


def _call_elevenlabs(text: str, voice_id: str, api_key: str) -> bytes:
    """Call the ElevenLabs TTS API and return raw MP3 bytes."""
    import urllib.request
    import urllib.error

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    body = json.dumps({
        "text": text[:TTS_CHAR_LIMIT],
        "model_id": "eleven_v3",
        "voice_settings": {
            "stability": 0.6,
            "similarity_boost": 0.8,
            "style": 0.2,
        },
    }).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f"ElevenLabs API returned status {resp.status}"
                )
            return resp.read()
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"ElevenLabs API error {e.code}: {error_body}"
        ) from e


def generate_audio(brief_id: int, dry_run: bool = False) -> str | None:
    """Generate audio for a single brief by ID.

    Returns the file path of the generated MP3, or None if skipped.
    """
    _load_env()

    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        log.warning("ELEVENLABS_API_KEY not set - skipping audio generation")
        return None

    voice_id = _get_voice_id()
    conn = _connect()

    try:
        row = conn.execute(
            "SELECT id, title, content, product_type, audio_url FROM briefs WHERE id = ?",
            (brief_id,),
        ).fetchone()

        if not row:
            log.warning("Brief %d not found", brief_id)
            return None

        return _process_brief(dict(row), voice_id, api_key, dry_run)
    finally:
        conn.close()


def _process_brief(
    brief: dict,
    voice_id: str,
    api_key: str,
    dry_run: bool = False,
) -> str | None:
    """Process a single brief dict - clean, generate audio, save, update DB.

    Returns the file path on success, None if skipped.
    """
    brief_id = brief["id"]
    title = brief["title"]
    content = brief["content"]
    product_type = brief.get("product_type", "unknown")

    # Check content length
    if len(content) < MIN_LENGTH:
        log.info(
            "Skipping brief %d (%s) - too short (%d chars)",
            brief_id, title, len(content),
        )
        return None

    if len(content) > MAX_LENGTH:
        log.info(
            "Skipping brief %d (%s) - too long (%d chars)",
            brief_id, title, len(content),
        )
        return None

    # Check if audio file already exists
    output_path = AUDIO_DIR / f"brief_{brief_id}.mp3"
    if output_path.exists():
        log.info(
            "Skipping brief %d (%s) - audio already exists at %s",
            brief_id, title, output_path,
        )
        return str(output_path)

    # Clean text for TTS
    cleaned = clean_text_for_tts(content)
    if len(cleaned) < 50:
        log.info(
            "Skipping brief %d (%s) - cleaned text too short (%d chars)",
            brief_id, title, len(cleaned),
        )
        return None

    if dry_run:
        log.info(
            "[DRY RUN] Would generate audio for brief %d (%s, %s) - %d chars -> %d cleaned",
            brief_id, product_type, title, len(content), len(cleaned),
        )
        return None

    log.info(
        "Generating audio for brief %d (%s) - %d chars cleaned text",
        brief_id, title, len(cleaned),
    )

    # Call ElevenLabs
    try:
        audio_bytes = _call_elevenlabs(cleaned, voice_id, api_key)
    except Exception as e:
        log.error("Failed to generate audio for brief %d: %s", brief_id, e)
        return None

    # Save MP3
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)
    log.info(
        "Saved audio for brief %d: %s (%d bytes)",
        brief_id, output_path, len(audio_bytes),
    )

    # Update database
    conn = _connect()
    try:
        conn.execute(
            "UPDATE briefs SET audio_url = ? WHERE id = ?",
            (str(output_path), brief_id),
        )
        conn.commit()
        log.info("Updated audio_url for brief %d", brief_id)
    finally:
        conn.close()

    return str(output_path)


def generate_all(dry_run: bool = False) -> int:
    """Generate audio for all eligible briefs without audio.

    Returns the number of audio files generated.
    """
    _load_env()

    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        log.warning("ELEVENLABS_API_KEY not set - skipping audio generation")
        return 0

    voice_id = _get_voice_id()
    conn = _connect()

    try:
        placeholders = ",".join("?" for _ in ELIGIBLE_TYPES)
        rows = conn.execute(
            f"""
            SELECT id, title, content, product_type, audio_url
            FROM briefs
            WHERE product_type IN ({placeholders})
              AND (audio_url IS NULL OR audio_url = '')
            ORDER BY created_at DESC
            """,
            ELIGIBLE_TYPES,
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        log.info("No eligible briefs without audio found")
        return 0

    log.info("Found %d briefs without audio", len(rows))

    generated = 0
    for i, row in enumerate(rows):
        result = _process_brief(dict(row), voice_id, api_key, dry_run)
        if result:
            generated += 1

        # Rate limit - delay between API calls (not after last one)
        if not dry_run and result and i < len(rows) - 1:
            log.debug("Waiting %ds for rate limit...", INTER_CALL_DELAY)
            time.sleep(INTER_CALL_DELAY)

    action = "Would generate" if dry_run else "Generated"
    log.info("%s %d audio files from %d eligible briefs", action, generated, len(rows))
    return generated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate TTS audio for intelligence briefs",
    )
    parser.add_argument(
        "--brief-id",
        type=int,
        help="Generate audio for a specific brief ID",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be generated without calling the API",
    )
    args = parser.parse_args()

    if args.brief_id:
        result = generate_audio(args.brief_id, dry_run=args.dry_run)
        if result:
            print(f"Generated: {result}")
        else:
            print("No audio generated (check logs for details)")
    else:
        count = generate_all(dry_run=args.dry_run)
        print(f"Generated {count} audio file(s)")


if __name__ == "__main__":
    main()
