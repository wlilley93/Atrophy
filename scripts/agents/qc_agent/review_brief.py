#!/usr/bin/env python3
"""
Editorial QC - review_brief.py

Importable review function called by all outbound scripts before Telegram delivery.
Can also be called standalone for manual review.

Usage as library:
    from scripts.agents.qc_agent.review_brief import review
    result = review(title, content, source_agent)
    if result["pass"]:
        send_telegram(...)
    else:
        # log flags, send anyway with caveat or hold

Usage standalone:
    python3 review_brief.py --title "..." --content "..." --agent "montgomery"
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_ATROPHY_DIR = Path.home() / ".atrophy"
_INTEL_DB    = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "intelligence.db"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "qc_agent"
_QC_LOG_DB   = _ATROPHY_DIR / "agents" / "qc_agent" / "data" / "qc_log.db"

_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [QC] %(message)s",
    handlers=[logging.FileHandler(_LOG_DIR / "review.log"), logging.StreamHandler(sys.stderr)]
)
log = logging.getLogger("qc_agent")

# Style violations - patterns that should never appear
STYLE_VIOLATIONS = [
    (r'\u2014',         "Em dash (unicode) - use hyphen"),
    (r'&mdash;',        "Em dash (HTML entity) - use hyphen"),
    (r' -- ',           "Double hyphen - use single hyphen with spaces"),
    (r'\bI think\b',    "Hedging phrase 'I think' - remove or assert"),
    (r'\bone might\b',  "Hedging phrase 'one might' - remove or assert"),
    (r'\bperhaps\b',    "Vague qualifier 'perhaps' - assert or omit"),
]

# Confidence language that should trigger a warning (not block)
UNCERTAINTY_PATTERNS = [
    r'\b(allegedly|reportedly|unconfirmed|rumoured|suggests)\b',
    r'\b(it is believed|it appears|may have|might have)\b',
]

# Minimum word count for a brief (single-line flash reports exempt)
MIN_WORDS_BRIEF = 50
MIN_WORDS_FLASH = 10


def init_qc_db():
    _QC_LOG_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_QC_LOG_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS qc_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_agent TEXT,
            title TEXT,
            result TEXT,  -- 'pass', 'flag', 'block'
            flags TEXT,   -- JSON array of flag descriptions
            reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


def check_style(content: str) -> list[str]:
    flags = []
    for pattern, description in STYLE_VIOLATIONS:
        if re.search(pattern, content, re.IGNORECASE):
            flags.append(f"STYLE: {description}")
    return flags


def check_uncertainty_language(content: str) -> list[str]:
    warnings = []
    for pattern in UNCERTAINTY_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            warnings.append(f"UNCERTAINTY: '{matches[0]}' used without qualification - source?")
    return warnings


def check_entity_consistency(content: str) -> list[str]:
    """Check if named entities in the brief exist in intelligence.db."""
    warnings = []
    try:
        if not _INTEL_DB.exists():
            return []
        db = sqlite3.connect(str(_INTEL_DB))
        c = db.cursor()
        c.execute("SELECT name FROM entities WHERE type IN ('country','organization')")
        known = {row[0].lower() for row in c.fetchall()}
        db.close()

        # Extract capitalised multi-word phrases (crude NER)
        candidates = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', content)
        for candidate in candidates:
            if candidate.lower() not in known and len(candidate) > 4:
                # Only flag if it looks like an org or country, not a common phrase
                if any(kw in candidate.lower() for kw in ["force", "army", "corp", "ministry", "institute", "agency", "command"]):
                    warnings.append(f"ENTITY: '{candidate}' not in intelligence.db - file or verify")
    except Exception as e:
        log.warning(f"Entity check failed: {e}")
    return warnings


def check_length(content: str, brief_type: str = "brief") -> list[str]:
    word_count = len(content.split())
    minimum = MIN_WORDS_FLASH if brief_type == "flash" else MIN_WORDS_BRIEF
    if word_count < minimum:
        return [f"LENGTH: Only {word_count} words - expected at least {minimum} for {brief_type}"]
    return []


def review(title: str, content: str, source_agent: str = "unknown",
           brief_type: str = "brief") -> dict:
    """
    Review a brief before sending.

    Returns:
        dict with keys:
            pass (bool): True if the brief passes QC
            result (str): 'pass', 'flag', or 'block'
            flags (list): blocking issues
            warnings (list): non-blocking concerns
            reviewed_at (str): ISO timestamp
    """
    blocking_flags = []
    warnings = []

    # Style - blocking
    style_flags = check_style(content)
    blocking_flags.extend(style_flags)

    # Length - blocking
    length_flags = check_length(content, brief_type)
    blocking_flags.extend(length_flags)

    # Uncertainty language - warning only
    uncertainty_warnings = check_uncertainty_language(content)
    warnings.extend(uncertainty_warnings)

    # Entity consistency - warning only
    entity_warnings = check_entity_consistency(content)
    warnings.extend(entity_warnings)

    if blocking_flags:
        result = "block"
        passed = False
    elif warnings:
        result = "flag"
        passed = True  # Warnings do not block; they are logged
    else:
        result = "pass"
        passed = True

    # Log to QC DB
    try:
        qc_db = init_qc_db()
        all_flags = blocking_flags + warnings
        qc_db.execute("""
            INSERT INTO qc_log (source_agent, title, result, flags)
            VALUES (?, ?, ?, ?)
        """, (source_agent, title[:200], result, json.dumps(all_flags)))
        qc_db.commit()
        qc_db.close()
    except Exception as e:
        log.warning(f"QC log write failed: {e}")

    timestamp = datetime.now(timezone.utc).isoformat()

    if blocking_flags:
        log.warning(f"QC BLOCK [{source_agent}] '{title[:60]}': {blocking_flags}")
    elif warnings:
        log.info(f"QC FLAG [{source_agent}] '{title[:60]}': {warnings}")
    else:
        log.info(f"QC PASS [{source_agent}] '{title[:60]}'")

    return {
        "pass": passed,
        "result": result,
        "flags": blocking_flags,
        "warnings": warnings,
        "reviewed_at": timestamp,
    }


def format_qc_note(result: dict) -> str:
    """Format a QC note to append to a flagged brief."""
    if result["result"] == "pass":
        return ""
    lines = ["_[QC NOTE:"]
    if result["flags"]:
        lines.append(f"Blocked issues: {'; '.join(result['flags'])}"]
    if result["warnings"]:
        lines.append(f"Warnings: {'; '.join(result['warnings'][:2])}"]
    lines.append("]_")
    return " ".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", default="Test brief")
    parser.add_argument("--content", default="")
    parser.add_argument("--agent", default="test")
    parser.add_argument("--type", default="brief")
    args = parser.parse_args()

    result = review(args.title, args.content, args.agent, args.type)
    print(json.dumps(result, indent=2))
