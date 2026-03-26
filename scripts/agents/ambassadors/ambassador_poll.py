#!/usr/bin/env python3
"""
Ambassador polling script - parameterised per country.

Usage: python3 ambassador_poll.py --country "Iran" --slug "iran"

Each ambassador agent polls WorldMonitor for country-specific activity,
writes a structured summary to intelligence.db, and updates the entity
record for that country with fresh context.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_ATROPHY_DIR = Path.home() / ".atrophy"
_INTEL_DB    = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "intelligence.db"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "ambassadors"

_APP_DIR = Path("/Users/williamlilley/Projects/Claude Code Projects/Atrophy App Electron")
sys.path.insert(0, str(_APP_DIR / "mcp"))



CLAUDE_BIN = "/Users/williamlilley/.local/bin/claude"


def call_claude(system: str, prompt: str, model: str = "sonnet") -> str:
    """One-shot Claude call via CLI. Returns response text."""
    import subprocess
    result = subprocess.run(
        [CLAUDE_BIN, "-p", "--model", model, "--system-prompt", system,
         "--no-session-persistence", "--output-format", "text"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr[:200]}")
    return result.stdout.strip()

def setup_logging(country_slug: str):
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [AMB-{country_slug.upper()}] %(message)s",
        handlers=[
            logging.FileHandler(_LOG_DIR / f"{country_slug}.log"),
            logging.StreamHandler(sys.stderr)
        ]
    )
    return logging.getLogger(f"ambassador_{country_slug}")


COUNTRY_PROFILES = {
    "usa": {
        "name": "United States",
        "keywords": ["united states", "usa", "washington", "pentagon", "white house", "us navy", "centcom", "nato"],
        "tracks": ["Track 02 European Security", "Track 03 Gulf-Iran-Israel", "Track 04 Russia-Ukraine", "Track 05 Indo-Pacific"],
        "focus": "US foreign policy posture, military deployments, NATO leadership, CENTCOM operations, China/Taiwan stance"
    },
    "russia": {
        "name": "Russia",
        "keywords": ["russia", "moscow", "kremlin", "putin", "russian", "fsb", "svr", "gru", "black sea fleet"],
        "tracks": ["Track 04 Russia-Ukraine", "Track 02 European Security"],
        "focus": "Ukraine war trajectory, hybrid operations against UK/NATO, Black Sea posture, Arctic activities, energy leverage"
    },
    "china": {
        "name": "China",
        "keywords": ["china", "beijing", "prc", "pla", "xi jinping", "taiwan", "south china sea", "bri"],
        "tracks": ["Track 05 Indo-Pacific", "Track 06 Economic Security"],
        "focus": "Taiwan strait activity, South China Sea incidents, PLA exercises, economic leverage on UK, BRI developments"
    },
    "iran": {
        "name": "Iran",
        "keywords": ["iran", "tehran", "irgc", "irgcn", "rouhani", "khamenei", "nuclear", "natanz", "fordow"],
        "tracks": ["Track 03 Gulf-Iran-Israel"],
        "focus": "Nuclear programme status, IRGCN maritime activity, proxy network (Houthi, Hezbollah, Iraqi militia), Hormuz posture"
    },
    "israel": {
        "name": "Israel",
        "keywords": ["israel", "idf", "mossad", "netanyahu", "tel aviv", "haifa", "israeli", "iron dome"],
        "tracks": ["Track 03 Gulf-Iran-Israel"],
        "focus": "IDF operational posture, covert operations vs Iran, Gaza/Lebanon status, normalization diplomacy, US alignment"
    },
    "uae": {
        "name": "UAE",
        "keywords": ["uae", "emirates", "abu dhabi", "dubai", "mbz", "emirati", "adnoc"],
        "tracks": ["Track 03 Gulf-Iran-Israel", "Track 06 Economic Security"],
        "focus": "RSF financial backing (Sudan), gold trade networks, Iran tensions, normalization with Israel, UK/US basing"
    },
    "ukraine": {
        "name": "Ukraine",
        "keywords": ["ukraine", "kyiv", "zelensky", "ukrainian", "afu", "azov", "odessa", "kharkiv", "bakhmut"],
        "tracks": ["Track 04 Russia-Ukraine"],
        "focus": "Frontline status, Western weapons utilisation, Zelensky political position, peace talks posture, reconstruction"
    },
    "uk": {
        "name": "United Kingdom",
        "keywords": ["uk", "britain", "british", "london", "mod", "fcdo", "downing street", "royal navy", "raf"],
        "tracks": ["Track 01 UK Defence", "Track 02 European Security"],
        "focus": "Defence spending vs commitment, procurement delays, Falklands/NATO posture, AUKUS delivery, Five Eyes activity"
    },
    "saudi_arabia": {
        "name": "Saudi Arabia",
        "keywords": ["saudi", "riyadh", "mbs", "aramco", "opec", "yemen", "houthi"],
        "tracks": ["Track 03 Gulf-Iran-Israel", "Track 06 Economic Security"],
        "focus": "Yemen war posture, Iran normalisation, OPEC+ decisions, Vision 2030, UK defence relationship, US reliability assessment"
    },
    "turkey": {
        "name": "Turkey",
        "keywords": ["turkey", "ankara", "erdogan", "turkish", "taf", "nato", "bosphorus", "syria", "f-16"],
        "tracks": ["Track 02 European Security", "Track 04 Russia-Ukraine"],
        "focus": "NATO reliability, Bosphorus closure authority, Ukraine grain deal, Syria presence, F-16 dispute, Kurdish operations"
    },
}


def fetch_country_data(country_profile: dict) -> str:
    parts = []
    try:
        from worldmonitor_server import WorldMonitorClient
        client = WorldMonitorClient(cache_db=str(Path.home() / '.atrophy' / 'worldmonitor_cache.db'))

        news = client.get_news_summary()
        if news:
            news_str = json.dumps(news)
            # Filter for country keywords
            relevant_lines = [
                line for line in news_str.split("\n")
                if any(kw in line.lower() for kw in country_profile["keywords"])
            ]
            if relevant_lines:
                parts.append("NEWS:\n" + "\n".join(relevant_lines[:20]))

        conflicts, _wm_delta = client.fetch_cached("api/conflict/v1/list-acled-events")
        if conflicts:
            cf_str = json.dumps(conflicts)
            if any(kw in cf_str.lower() for kw in country_profile["keywords"]):
                parts.append(f"CONFLICTS:\n{cf_str[:1500]}")

    except Exception as e:
        logging.getLogger("ambassador").warning(f"WorldMonitor fetch failed: {e}")
    return "\n\n".join(parts)


def generate_country_update(country_profile: dict, context: str) -> str:
    system = f"""You are a country-desk analyst at the Meridian Institute covering {country_profile['name']}.
Produce a terse weekly country update. Focus: {country_profile['focus']}
Relevant tracks: {', '.join(country_profile['tracks'])}
Voice: analytical, factual. Under 250 words. No em dashes."""
    return call_claude(system, f"Weekly update - {datetime.now().strftime('%Y-%m-%d')}\n\n{context or 'No live data available. Provide standing assessment based on known posture.'}", "haiku")


def update_entity_in_db(db: sqlite3.Connection, country_name: str, update_text: str):
    c = db.cursor()
    c.execute("UPDATE entities SET description = ?, updated_at = CURRENT_TIMESTAMP WHERE lower(name) = lower(?)",
              (update_text[:1000], country_name))
    if c.rowcount == 0:
        c.execute("""
            INSERT OR IGNORE INTO entities (name, type, subtype, description, status)
            VALUES (?, 'country', 'state', ?, 'active')
        """, (country_name, update_text[:1000]))
    db.commit()


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--country", required=True, help="Display name (e.g. 'Iran')")
    parser.add_argument("--slug", required=True, help="Slug key (e.g. 'iran')")
    args = parser.parse_args()

    log = setup_logging(args.slug)
    profile = COUNTRY_PROFILES.get(args.slug)
    if not profile:
        log.error(f"Unknown country slug: {args.slug}")
        sys.exit(1)

    log.info(f"Ambassador poll starting: {profile['name']}")
    db = sqlite3.connect(str(_INTEL_DB))

    try:
        context = fetch_country_data(profile)
        update = generate_country_update(profile, context)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Log as a brief
        db.execute("""
            INSERT INTO briefs (conflict_id, date, title, content, requested_by)
            VALUES (NULL, ?, ?, ?, 'ambassador')
        """, (date_str, f"{profile['name']} - Weekly Country Update", update))

        update_entity_in_db(db, profile["name"], update)
        db.commit()
        log.info(f"Country update logged for {profile['name']}")

    finally:
        db.close()


if __name__ == "__main__":
    run()
