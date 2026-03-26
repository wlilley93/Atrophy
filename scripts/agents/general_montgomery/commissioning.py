#!/usr/bin/env python3
"""
Commissioning Log - research request management.

Provides a structured pipeline for Will and Henry to submit research requests.
Montgomery tracks status, assigns to the appropriate Research Fellow, and reports completion.

Usage:
    python3 commissioning.py --action submit --title "..." --brief "..." --requestor "will" --priority "high"
    python3 commissioning.py --action list
    python3 commissioning.py --action complete --id 3 --output "Brief text here"
    python3 commissioning.py --action status
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_ATROPHY_DIR  = Path.home() / ".atrophy"
_AGENT_DIR    = _ATROPHY_DIR / "agents" / "general_montgomery"
_AGENT_JSON   = _AGENT_DIR / "data" / "agent.json"
_INTEL_DB     = _AGENT_DIR / "data" / "intelligence.db"

# Commissioning table lives in intelligence.db
def get_db():
    db = sqlite3.connect(str(_INTEL_DB))
    db.execute("""
        CREATE TABLE IF NOT EXISTS commissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            brief TEXT,
            requestor TEXT NOT NULL,       -- 'will', 'henry', 'montgomery'
            priority TEXT DEFAULT 'normal', -- 'urgent', 'high', 'normal', 'low'
            assigned_to TEXT,              -- agent name
            status TEXT DEFAULT 'open',    -- 'open', 'in_progress', 'complete', 'cancelled'
            output TEXT,                   -- completed brief or summary
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    """)
    db.commit()
    return db


def submit(title: str, brief: str, requestor: str, priority: str = "normal") -> int:
    """Submit a new research commission."""
    # Auto-assign based on topic keywords
    assignment = auto_assign(title + " " + brief)
    db = get_db()
    c = db.cursor()
    c.execute("""
        INSERT INTO commissions (title, brief, requestor, priority, assigned_to, status)
        VALUES (?, ?, ?, ?, ?, 'open')
    """, (title, brief, requestor, priority, assignment))
    db.commit()
    commission_id = c.lastrowid
    db.close()
    return commission_id


def auto_assign(text: str) -> str:
    """Route commission to appropriate Research Fellow based on topic."""
    text_lower = text.lower()
    if any(k in text_lower for k in ["iran", "israel", "gulf", "hormuz", "houthi", "centcom"]):
        return "rf_gulf_iran_israel"
    if any(k in text_lower for k in ["ukraine", "russia", "black sea", "nato east", "ukraine front"]):
        return "rf_russia_ukraine"
    if any(k in text_lower for k in ["uk defence", "type 26", "f-35", "gcap", "aukus", "mod", "british military"]):
        return "rf_uk_defence"
    if any(k in text_lower for k in ["nato", "europe", "european", "lancaster house", "germany", "france"]):
        return "rf_european_security"
    if any(k in text_lower for k in ["taiwan", "china", "pacific", "indo-pacific", "japan", "aukus"]):
        return "rf_indo_pacific"
    if any(k in text_lower for k in ["sanctions", "economic", "trade", "supply chain", "energy"]):
        return "economic_io"
    if any(k in text_lower for k in ["maritime", "ship", "vessel", "ais", "fleet", "naval"]):
        return "sigint_analyst"
    return "general_montgomery"  # Default to Montgomery


def list_commissions(status: str = None) -> list[dict]:
    db = get_db()
    c = db.cursor()
    if status:
        c.execute("SELECT * FROM commissions WHERE status = ? ORDER BY priority DESC, submitted_at DESC", (status,))
    else:
        c.execute("SELECT * FROM commissions ORDER BY status, priority DESC, submitted_at DESC")
    cols = [d[0] for d in c.description]
    rows = [dict(zip(cols, row)) for row in c.fetchall()]
    db.close()
    return rows


def complete(commission_id: int, output: str):
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    db.execute("""
        UPDATE commissions SET status = 'complete', output = ?, completed_at = ?
        WHERE id = ?
    """, (output, now, commission_id))
    # Also log to briefs
    c = db.cursor()
    c.execute("SELECT title, requestor FROM commissions WHERE id = ?", (commission_id,))
    row = c.fetchone()
    if row:
        db.execute("""
            INSERT INTO briefs (conflict_id, date, title, content, requested_by)
            VALUES (NULL, ?, ?, ?, ?)
        """, (datetime.now(timezone.utc).strftime("%Y-%m-%d"), f"[Commissioned] {row[0]}", output, row[1]))
    db.commit()
    db.close()


def status_summary() -> str:
    commissions = list_commissions()
    open_c = [c for c in commissions if c["status"] == "open"]
    in_prog = [c for c in commissions if c["status"] == "in_progress"]
    done    = [c for c in commissions if c["status"] == "complete"]

    lines = [f"COMMISSIONING PIPELINE - {datetime.now().strftime('%Y-%m-%d')}"]
    lines.append(f"Open: {len(open_c)} | In Progress: {len(in_prog)} | Complete: {len(done)}")

    if open_c:
        lines.append("\nOPEN:")
        for c in open_c[:5]:
            lines.append(f"  [{c['id']}] [{c['priority'].upper()}] {c['title'][:60]} -> {c['assigned_to']}")
    if in_prog:
        lines.append("\nIN PROGRESS:")
        for c in in_prog:
            lines.append(f"  [{c['id']}] {c['title'][:60]} -> {c['assigned_to']}")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=["submit", "list", "complete", "status"], required=True)
    parser.add_argument("--title",     default="")
    parser.add_argument("--brief",     default="")
    parser.add_argument("--requestor", default="will")
    parser.add_argument("--priority",  default="normal")
    parser.add_argument("--id",        type=int)
    parser.add_argument("--output",    default="")
    parser.add_argument("--filter",    default=None)
    args = parser.parse_args()

    if args.action == "submit":
        commission_id = submit(args.title, args.brief, args.requestor, args.priority)
        print(f"Commission submitted. ID: {commission_id}")
        print(f"Assigned to: {auto_assign(args.title + ' ' + args.brief)}")

    elif args.action == "list":
        commissions = list_commissions(args.filter)
        print(json.dumps(commissions, indent=2, default=str))

    elif args.action == "complete":
        if not args.id:
            print("Error: --id required for complete action")
            sys.exit(1)
        complete(args.id, args.output)
        print(f"Commission {args.id} marked complete")

    elif args.action == "status":
        print(status_summary())
