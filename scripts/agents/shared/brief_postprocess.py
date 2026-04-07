#!/usr/bin/env python3
"""Brief Post-Processing Pipeline.

Single post-publication function that chains:
1. Multi-source verification scoring
2. Brief-object linking (scan text against ontology objects)
3. Relationship extraction for substantial briefs
4. Channel push to Meridian platform

Usage:
    from brief_postprocess import postprocess_brief
    postprocess_brief(brief_id)

    # Or with explicit channel push
    postprocess_brief(brief_id, push_channel="general_montgomery")

    # CLI
    python3 brief_postprocess.py 42
    python3 brief_postprocess.py 42 --channel general_montgomery
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Optional

# -- path setup ---------------------------------------------------------------
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from verify_brief import verify_brief
from channel_push import push_briefing

# Optional: ontology support
try:
    from ontology import Ontology
    _HAS_ONTOLOGY = True
except ImportError:
    _HAS_ONTOLOGY = False

_ATROPHY_DIR = Path.home() / ".atrophy"
_INTEL_DB = _ATROPHY_DIR / "agents" / "general_montgomery" / "data" / "intelligence.db"

_LOG_DIR = _ATROPHY_DIR / "logs" / "general_montgomery"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Postprocess] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "brief_postprocess.log"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("brief_postprocess")

# Minimum brief length for relationship extraction (skip stubs)
_MIN_CONTENT_FOR_EXTRACTION = 300


# -- brief-object linking -----------------------------------------------------


def link_brief_to_objects(brief_id: int, db_path: str = None) -> int:
    """Scan brief text against ontology objects and create brief_objects links.

    Returns the number of links created.
    """
    db_path = db_path or str(_INTEL_DB)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")

    try:
        # Get the brief content
        row = conn.execute(
            "SELECT title, content FROM briefs WHERE id = ?", (brief_id,)
        ).fetchone()
        if not row:
            log.warning("Brief %d not found", brief_id)
            return 0

        title, content = row
        full_text = f"{title} {content}".upper()

        # Get all objects from the ontology
        objects = conn.execute(
            "SELECT id, name, aliases, type FROM objects WHERE status = 'active'"
        ).fetchall()

        # Check if brief_objects table exists, create if not
        conn.execute("""
            CREATE TABLE IF NOT EXISTS brief_objects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brief_id INTEGER NOT NULL,
                object_id INTEGER NOT NULL,
                relevance REAL DEFAULT 0.5,
                context TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(brief_id, object_id)
            )
        """)

        links_created = 0
        for obj_id, name, aliases_json, obj_type in objects:
            # Build list of searchable names
            searchable = [name]
            if aliases_json:
                try:
                    aliases = json.loads(aliases_json)
                    if isinstance(aliases, list):
                        searchable.extend(aliases)
                except (json.JSONDecodeError, TypeError):
                    pass

            # Check if any name variant appears in the brief text
            matched = False
            matched_name = None
            for search_name in searchable:
                if len(search_name) < 3:
                    continue  # Skip very short names to avoid false matches
                if search_name.upper() in full_text:
                    matched = True
                    matched_name = search_name
                    break

            if not matched:
                continue

            # Calculate relevance based on frequency and position
            name_upper = matched_name.upper()
            # Count occurrences
            count = full_text.count(name_upper)
            # Check if in title (higher relevance)
            in_title = name_upper in title.upper()
            relevance = min(1.0, 0.3 + (count * 0.1) + (0.3 if in_title else 0))

            # Extract context snippet (first occurrence)
            content_lower = content.lower()
            idx = content_lower.find(matched_name.lower())
            if idx >= 0:
                start = max(0, idx - 40)
                end = min(len(content), idx + len(matched_name) + 80)
                context_snippet = content[start:end].replace("\n", " ").strip()
            else:
                context_snippet = None

            try:
                conn.execute(
                    """INSERT OR IGNORE INTO brief_objects
                       (brief_id, object_id, relevance, context)
                       VALUES (?, ?, ?, ?)""",
                    (brief_id, obj_id, relevance, context_snippet),
                )
                if conn.total_changes:
                    links_created += 1
            except sqlite3.IntegrityError:
                pass  # Already linked

        conn.commit()
        return links_created

    finally:
        conn.close()


# -- relationship extraction --------------------------------------------------


def extract_relationships(brief_id: int, db_path: str = None) -> int:
    """Extract new relationships from a substantial brief using the ontology.

    Scans for co-occurring known objects and creates links between them
    when they appear in close proximity within the brief text.

    Returns the number of relationships created.
    """
    db_path = db_path or str(_INTEL_DB)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")

    try:
        row = conn.execute(
            "SELECT title, content FROM briefs WHERE id = ?", (brief_id,)
        ).fetchone()
        if not row:
            return 0

        title, content = row
        if len(content) < _MIN_CONTENT_FOR_EXTRACTION:
            return 0

        # Get objects that are already linked to this brief
        linked_objects = conn.execute(
            """SELECT bo.object_id, o.name, o.type
               FROM brief_objects bo
               JOIN objects o ON o.id = bo.object_id
               WHERE bo.brief_id = ?""",
            (brief_id,),
        ).fetchall()

        if len(linked_objects) < 2:
            return 0  # Need at least 2 objects to create relationships

        # Split content into paragraphs for proximity analysis
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

        relationships_created = 0
        source = f"brief:{brief_id}"

        # For each pair of objects, check if they co-occur in any paragraph
        for i, (id_a, name_a, type_a) in enumerate(linked_objects):
            for id_b, name_b, type_b in linked_objects[i + 1:]:
                if id_a == id_b:
                    continue

                # Check co-occurrence in paragraphs
                for para in paragraphs:
                    para_upper = para.upper()
                    if name_a.upper() in para_upper and name_b.upper() in para_upper:
                        # Determine relationship type based on object types
                        link_type = _infer_link_type(type_a, type_b, para)

                        # Check if link already exists
                        existing = conn.execute(
                            """SELECT id FROM links
                               WHERE from_id = ? AND to_id = ? AND type = ?""",
                            (id_a, id_b, link_type),
                        ).fetchone()

                        if not existing:
                            # Extract context snippet
                            ctx = para[:200].replace("\n", " ")
                            try:
                                conn.execute(
                                    """INSERT INTO links
                                       (from_id, to_id, type, confidence, source, description)
                                       VALUES (?, ?, ?, 0.6, ?, ?)""",
                                    (id_a, id_b, link_type, source, ctx),
                                )
                                relationships_created += 1

                                # Log to changelog if table exists
                                try:
                                    conn.execute(
                                        """INSERT INTO changelog
                                           (object_id, table_name, record_id, action,
                                            field, new_value, source, agent)
                                           VALUES (?, 'links', last_insert_rowid(),
                                                   'create', 'type', ?, ?, 'brief_postprocess')""",
                                        (id_a, link_type, source),
                                    )
                                except sqlite3.OperationalError:
                                    pass  # changelog table may not exist
                            except sqlite3.IntegrityError:
                                pass
                        break  # One co-occurrence per pair is enough

        conn.commit()
        return relationships_created

    finally:
        conn.close()


def _infer_link_type(type_a: str, type_b: str, context: str) -> str:
    """Infer the most likely relationship type from object types and context."""
    context_lower = context.lower()

    # Keyword-based inference from the paragraph context
    if any(w in context_lower for w in ["attack", "strike", "target", "bomb"]):
        return "targets"
    if any(w in context_lower for w in ["sanction", "embargo", "restrict"]):
        return "sanctions"
    if any(w in context_lower for w in ["ally", "alliance", "partner", "cooperat"]):
        return "allied_with"
    if any(w in context_lower for w in ["oppose", "rival", "adversar", "conflict"]):
        return "opposes"
    if any(w in context_lower for w in ["deploy", "stationed", "base"]):
        return "deployed_to"
    if any(w in context_lower for w in ["command", "leads", "chief"]):
        return "commands"
    if any(w in context_lower for w in ["member", "belong", "part of"]):
        return "member_of"
    if any(w in context_lower for w in ["fund", "financ", "sponsor"]):
        return "funds"
    if any(w in context_lower for w in ["arms", "weapon", "supply", "deliver"]):
        return "arms"
    if any(w in context_lower for w in ["trade", "export", "import"]):
        return "trades_with"
    if any(w in context_lower for w in ["mediat", "negotiat", "broker"]):
        return "mediates"

    # Type-based fallback
    type_pair = frozenset([type_a, type_b])
    if type_pair == frozenset(["person", "organization"]):
        return "member_of"
    if type_pair == frozenset(["unit", "location"]):
        return "deployed_to"
    if type_pair == frozenset(["person", "country"]):
        return "leads"
    if "event" in type_pair:
        return "participated_in"

    return "related_to"


# -- channel push wrapper -----------------------------------------------------


def push_brief_to_channel(
    brief_id: int,
    channel_name: str,
    db_path: str = None,
) -> bool:
    """Push a brief's content to the Meridian platform channel."""
    db_path = db_path or str(_INTEL_DB)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute("PRAGMA busy_timeout=10000")

    try:
        row = conn.execute(
            "SELECT title, content, requested_by, product_type FROM briefs WHERE id = ?",
            (brief_id,),
        ).fetchone()
        if not row:
            return False

        title, content, requested_by, product_type = row

        # Build summary from first paragraph
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        summary = paragraphs[0] if paragraphs else content[:200]
        # Strip markdown headers from summary
        if summary.startswith("#"):
            summary = paragraphs[1] if len(paragraphs) > 1 else summary
        summary = summary[:300]

        sources = [requested_by or "intelligence.db"]
        if product_type:
            title_with_type = f"[{product_type}] {title}"
        else:
            title_with_type = title

        return push_briefing(
            channel_name,
            title=title_with_type,
            summary=summary,
            body_md=content,
            sources=sources,
        )
    finally:
        conn.close()


# -- main pipeline ------------------------------------------------------------


def postprocess_brief(
    brief_id: int,
    push_channel: Optional[str] = None,
    db_path: str = None,
    skip_verify: bool = False,
    skip_link: bool = False,
    skip_extract: bool = False,
    skip_push: bool = False,
) -> dict:
    """Run the full post-publication pipeline on a brief.

    Steps:
    1. Verification scoring (multi-source corroboration)
    2. Brief-object linking (scan text against ontology)
    3. Relationship extraction (for substantial briefs)
    4. Channel push to Meridian platform (if channel specified)

    Args:
        brief_id: The brief ID in intelligence.db.
        push_channel: Channel name for platform push (e.g. "general_montgomery").
        db_path: Optional path to intelligence.db.
        skip_verify: Skip verification step.
        skip_link: Skip brief-object linking.
        skip_extract: Skip relationship extraction.
        skip_push: Skip channel push.

    Returns:
        Dict with results from each step.
    """
    db_path = db_path or str(_INTEL_DB)
    results = {"brief_id": brief_id}

    # 1. Verification
    if not skip_verify:
        log.info("[%d] Running verification...", brief_id)
        try:
            verify_result = verify_brief(brief_id, intel_db=db_path)
            results["verification"] = verify_result
            if verify_result and not verify_result.get("skipped"):
                log.info(
                    "[%d] Verification complete: score=%s",
                    brief_id,
                    verify_result.get("overall_score", "?"),
                )
            elif verify_result and verify_result.get("skipped"):
                log.info("[%d] Verification skipped: %s", brief_id, verify_result.get("reason"))
        except Exception as e:
            log.warning("[%d] Verification failed: %s", brief_id, e)
            results["verification"] = {"error": str(e)}
    else:
        results["verification"] = {"skipped": True}

    # 2. Brief-object linking
    if not skip_link:
        log.info("[%d] Linking brief to ontology objects...", brief_id)
        try:
            links_created = link_brief_to_objects(brief_id, db_path=db_path)
            results["object_links"] = links_created
            log.info("[%d] Linked to %d ontology objects", brief_id, links_created)
        except Exception as e:
            log.warning("[%d] Object linking failed: %s", brief_id, e)
            results["object_links"] = {"error": str(e)}
    else:
        results["object_links"] = {"skipped": True}

    # 3. Relationship extraction
    if not skip_extract:
        log.info("[%d] Extracting relationships...", brief_id)
        try:
            rels_created = extract_relationships(brief_id, db_path=db_path)
            results["relationships_extracted"] = rels_created
            if rels_created > 0:
                log.info("[%d] Extracted %d new relationships", brief_id, rels_created)
            else:
                log.info("[%d] No new relationships extracted", brief_id)
        except Exception as e:
            log.warning("[%d] Relationship extraction failed: %s", brief_id, e)
            results["relationships_extracted"] = {"error": str(e)}
    else:
        results["relationships_extracted"] = {"skipped": True}

    # 4. Channel push
    if push_channel and not skip_push:
        log.info("[%d] Pushing to channel '%s'...", brief_id, push_channel)
        try:
            pushed = push_brief_to_channel(brief_id, push_channel, db_path=db_path)
            results["channel_push"] = pushed
            if pushed:
                log.info("[%d] Pushed to channel '%s'", brief_id, push_channel)
            else:
                log.warning("[%d] Channel push failed or skipped", brief_id)
        except Exception as e:
            log.warning("[%d] Channel push failed: %s", brief_id, e)
            results["channel_push"] = {"error": str(e)}
    else:
        results["channel_push"] = {"skipped": True}

    return results


# -- CLI entry point ----------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Brief post-processing pipeline")
    parser.add_argument("brief_id", type=int, help="Brief ID to process")
    parser.add_argument("--channel", type=str, default=None, help="Channel for platform push")
    parser.add_argument("--skip-verify", action="store_true", help="Skip verification step")
    parser.add_argument("--skip-link", action="store_true", help="Skip object linking step")
    parser.add_argument("--skip-extract", action="store_true", help="Skip relationship extraction")
    parser.add_argument("--skip-push", action="store_true", help="Skip channel push")
    parser.add_argument("--db", type=str, default=None, help="Path to intelligence.db")
    args = parser.parse_args()

    results = postprocess_brief(
        args.brief_id,
        push_channel=args.channel,
        db_path=args.db,
        skip_verify=args.skip_verify,
        skip_link=args.skip_link,
        skip_extract=args.skip_extract,
        skip_push=args.skip_push,
    )

    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
