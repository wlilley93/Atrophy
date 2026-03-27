#!/usr/bin/env python3
"""
Librarian - Entity Resolution and Linking
Deduplicates entities in intelligence.db (via Claude Haiku review),
then links entities to briefs by scanning brief text for mentions.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ATROPHY_DIR = Path.home() / ".atrophy"
_AGENT_DIR   = _ATROPHY_DIR / "agents" / "general_montgomery"
_INTEL_DB    = _AGENT_DIR / "data" / "intelligence.db"
_LOG_DIR     = _ATROPHY_DIR / "logs" / "librarian"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_CLAUDE_CLI  = Path.home() / ".local" / "bin" / "claude"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Librarian-Resolve] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "entity_resolve.log"),
        logging.StreamHandler(sys.stderr),
    ]
)
log = logging.getLogger("entity_resolve")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def call_haiku(prompt: str) -> str:
    """Call Claude Haiku via CLI and return the text response."""
    result = subprocess.run(
        [str(_CLAUDE_CLI), "--model", "haiku", "--print", "-p", prompt],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI error: {result.stderr.strip()}")
    return result.stdout.strip()


def extract_json(text: str) -> list | dict:
    """Extract JSON from LLM response, stripping markdown fences if present."""
    # Strip markdown code fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()
    return json.loads(cleaned)


# ---------------------------------------------------------------------------
# Part 1: Entity Deduplication
# ---------------------------------------------------------------------------

def get_all_entities(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute(
        "SELECT id, name, type, aliases, description FROM entities ORDER BY name"
    )
    return [
        {"id": r[0], "name": r[1], "type": r[2], "aliases": r[3], "description": r[4]}
        for r in cur.fetchall()
    ]


def build_candidate_groups(entities: list[dict]) -> list[list[dict]]:
    """
    Pre-group entities that might be duplicates using heuristics:
    - Same name (case-insensitive)
    - One name is a substring of another
    - Acronym matches (e.g., "BIS" in "Bureau of Industry and Security (BIS)")
    - Known geographic synonyms (city-for-country like Tehran/Iran, Riyadh/Saudi Arabia)
    """
    # Build union-find structure
    n = len(entities)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Index by lowercase name
    name_lower = [e["name"].lower().strip() for e in entities]

    # Known city-to-country mappings
    city_country = {
        "tehran": "iran",
        "riyadh": "saudi arabia",
        "moscow": "russia",
        "beijing": "china",
        "kyiv": "ukraine",
    }

    # Known synonym pairs (bidirectional)
    known_synonyms = [
        ("baltics", "baltic states"),
        ("mod", "ministry of defence"),
        ("uk mod", "uk ministry of defence"),
        ("uk mod", "ministry of defence (uk)"),
        ("uk ministry of defence", "ministry of defence (uk)"),
    ]
    # Build a lookup set for fast checks
    synonym_set = set()
    for a, b in known_synonyms:
        synonym_set.add((a, b))
        synonym_set.add((b, a))

    # Normalize name: lowercase, strip underscores, collapse whitespace
    def normalize(s: str) -> str:
        return re.sub(r"\s+", " ", s.lower().replace("_", " ").strip())

    name_norm = [normalize(e["name"]) for e in entities]

    for i in range(n):
        for j in range(i + 1, n):
            ni, nj = name_lower[i], name_lower[j]

            # Exact match (case-insensitive)
            if ni == nj:
                union(i, j)
                continue

            # Normalized match (handles underscores, extra spaces)
            if name_norm[i] == name_norm[j]:
                union(i, j)
                continue

            # One is substring of other (min length 3 to avoid spurious matches)
            if len(ni) >= 3 and len(nj) >= 3:
                if ni in nj or nj in ni:
                    union(i, j)
                    continue

            # Acronym-in-parentheses pattern: "Bureau of Industry and Security (BIS)"
            # Also handles "Iraqi Popular Mobilization Forces (PMF)" matching "Iraqi PMF"
            paren_match_i = re.search(r"\(([A-Z]{2,})\)$", entities[i]["name"])
            paren_match_j = re.search(r"\(([A-Z]{2,})\)$", entities[j]["name"])
            if paren_match_i:
                acronym = paren_match_i.group(1).lower()
                if acronym == nj or nj.endswith(" " + acronym):
                    union(i, j)
                    continue
            if paren_match_j:
                acronym = paren_match_j.group(1).lower()
                if acronym == ni or ni.endswith(" " + acronym):
                    union(i, j)
                    continue

            # Acronym derived from initials: "CSIS" matches "Center for Strategic and International Studies"
            for short_idx, long_idx in [(i, j), (j, i)]:
                short_name = entities[short_idx]["name"]
                long_name = entities[long_idx]["name"]
                if short_name.isupper() and len(short_name) >= 2 and len(long_name) > len(short_name):
                    # Build acronym from first letters of significant words
                    words = [w for w in long_name.split() if w[0].isupper() or w.isupper()]
                    initials = "".join(w[0].upper() for w in words if len(w) > 0)
                    if initials == short_name:
                        union(short_idx, long_idx)

            # Abbreviation matching: "MoD" in "Ministry of Defence"
            # Check if one name is a known abbreviation pattern of the other
            for short_idx, long_idx in [(i, j), (j, i)]:
                short_name = entities[short_idx]["name"].strip()
                long_name = entities[long_idx]["name"].strip()
                # UK MoD / UK Ministry of Defence pattern
                if len(short_name) < len(long_name):
                    # Strip common prefixes like "UK " for comparison
                    for prefix in ["UK ", "US ", "EU "]:
                        s_stripped = short_name[len(prefix):] if short_name.startswith(prefix) else None
                        l_stripped = long_name[len(prefix):] if long_name.startswith(prefix) else None
                        if s_stripped and l_stripped:
                            # Check if stripped short is an abbrev of stripped long
                            s_lower = s_stripped.lower()
                            l_lower = l_stripped.lower()
                            if s_lower in l_lower or l_lower.startswith(s_lower):
                                union(short_idx, long_idx)

            # Known synonym pairs
            if (ni, nj) in synonym_set:
                union(i, j)
                continue

            # City-for-country synonyms
            ci = city_country.get(ni)
            cj = city_country.get(nj)
            if ci and ci == nj:
                union(i, j)
                continue
            if cj and cj == ni:
                union(i, j)
                continue

            # Existing aliases mention the other name
            for src, tgt in [(i, j), (j, i)]:
                alias_str = entities[src].get("aliases")
                if alias_str:
                    try:
                        aliases = json.loads(alias_str)
                        if any(a.lower().strip() == name_lower[tgt] for a in aliases):
                            union(src, tgt)
                    except (json.JSONDecodeError, TypeError):
                        pass

    # Collect groups with 2+ members
    groups: dict[int, list[dict]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(entities[i])

    return [g for g in groups.values() if len(g) > 1]


def ask_haiku_for_merges(batch: list[list[dict]]) -> list[dict]:
    """
    Send a batch of candidate groups to Haiku for confirmation.
    Returns confirmed merge instructions.
    """
    # Format groups for the prompt
    group_descriptions = []
    for idx, group in enumerate(batch):
        names = [f"  - id={e['id']}, name=\"{e['name']}\", type={e['type']}" for e in group]
        group_descriptions.append(f"Group {idx + 1}:\n" + "\n".join(names))

    prompt = (
        "Given these groups of potentially duplicate entities from an intelligence database, "
        "confirm which ones refer to the same real-world entity. For each confirmed duplicate group, "
        "pick the most descriptive name as the primary. Return ONLY a JSON array of merge instructions:\n"
        "[{\"primary_id\": <id>, \"primary_name\": \"best name\", \"merge_ids\": [<other ids>], "
        "\"aliases\": [\"other name\", ...], \"reason\": \"why\"}]\n\n"
        "Rules:\n"
        "- Only group entities you are CERTAIN are duplicates\n"
        "- City metonyms (Tehran = Iran, Riyadh = Saudi Arabia) ARE duplicates in this context\n"
        "- Acronyms and their expansions are duplicates (BIS = Bureau of Industry and Security)\n"
        "- Person and their administration may be different (Trump vs Trump Administration) - keep separate\n"
        "- IRGC-Navy is a sub-unit of IRGC - do NOT merge them\n"
        "- If a group has no real duplicates, omit it\n\n"
        + "\n\n".join(group_descriptions)
    )

    log.info(f"Sending {len(batch)} candidate groups to Haiku for review")
    response = call_haiku(prompt)
    log.info(f"Haiku response length: {len(response)} chars")

    try:
        merges = extract_json(response)
        if not isinstance(merges, list):
            log.warning("Haiku returned non-list JSON, wrapping")
            merges = [merges]
        return merges
    except (json.JSONDecodeError, ValueError) as e:
        log.error(f"Failed to parse Haiku response: {e}")
        log.error(f"Response was: {response[:500]}")
        return []


def execute_merge(conn: sqlite3.Connection, merge: dict) -> bool:
    """
    Execute a single entity merge:
    1. Collect all existing aliases from primary and merged entities
    2. Update the primary entity's aliases
    3. Update relationships referencing merged entities
    4. Update conflict_actors referencing merged entities
    5. Delete the merged entities
    """
    primary_id = merge["primary_id"]
    merge_ids = merge["merge_ids"]
    new_aliases = merge.get("aliases", [])

    if not merge_ids:
        return False

    # Collect existing aliases from all entities being merged
    all_ids = [primary_id] + merge_ids
    placeholders = ",".join("?" * len(all_ids))
    rows = conn.execute(
        f"SELECT id, name, aliases FROM entities WHERE id IN ({placeholders})",
        all_ids
    ).fetchall()

    if not rows:
        log.warning(f"No entities found for merge group primary={primary_id}")
        return False

    # Build comprehensive alias list
    existing_aliases = set()
    primary_name = None
    for row_id, row_name, row_aliases in rows:
        if row_id == primary_id:
            primary_name = row_name
        else:
            existing_aliases.add(row_name)  # merged entity names become aliases
        if row_aliases:
            try:
                for a in json.loads(row_aliases):
                    existing_aliases.add(a)
            except (json.JSONDecodeError, TypeError):
                pass

    # Add Haiku-suggested aliases
    for a in new_aliases:
        existing_aliases.add(a)

    # Remove primary name from aliases if present
    existing_aliases.discard(primary_name)

    final_aliases = sorted(existing_aliases) if existing_aliases else None
    aliases_json = json.dumps(final_aliases) if final_aliases else None

    # Update primary entity aliases
    conn.execute(
        "UPDATE entities SET aliases = ?, updated_at = ? WHERE id = ?",
        (aliases_json, datetime.now(timezone.utc).isoformat(), primary_id)
    )

    # Update relationships: point from_id and to_id to primary
    for mid in merge_ids:
        conn.execute(
            "UPDATE OR IGNORE relationships SET from_id = ? WHERE from_id = ?",
            (primary_id, mid)
        )
        conn.execute(
            "UPDATE OR IGNORE relationships SET to_id = ? WHERE to_id = ?",
            (primary_id, mid)
        )
        # Delete any relationships that became self-referential
        conn.execute(
            "DELETE FROM relationships WHERE from_id = ? AND to_id = ?",
            (primary_id, primary_id)
        )

    # Update conflict_actors: point entity_id to primary
    for mid in merge_ids:
        # Check if primary already has an entry for each conflict
        existing = conn.execute(
            "SELECT conflict_id FROM conflict_actors WHERE entity_id = ?",
            (primary_id,)
        ).fetchall()
        existing_conflicts = {r[0] for r in existing}

        # Get the merged entity's conflict_actors
        merged_actors = conn.execute(
            "SELECT conflict_id, alignment, side, notes FROM conflict_actors WHERE entity_id = ?",
            (mid,)
        ).fetchall()

        for conflict_id, alignment, side, notes in merged_actors:
            if conflict_id not in existing_conflicts:
                conn.execute(
                    "INSERT OR IGNORE INTO conflict_actors (conflict_id, entity_id, alignment, side, notes) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (conflict_id, primary_id, alignment, side, notes)
                )

        # Delete merged entity's conflict_actors
        conn.execute("DELETE FROM conflict_actors WHERE entity_id = ?", (mid,))

    # Delete merged entities
    placeholders = ",".join("?" * len(merge_ids))
    conn.execute(f"DELETE FROM entities WHERE id IN ({placeholders})", merge_ids)

    conn.commit()
    log.info(
        f"Merged: '{primary_name}' (id={primary_id}) absorbed "
        f"{len(merge_ids)} entities. Aliases: {final_aliases}"
    )
    return True


def deduplicate_entities(conn: sqlite3.Connection) -> tuple[int, int]:
    """
    Main deduplication flow. Returns (groups_found, entities_merged).
    """
    entities = get_all_entities(conn)
    log.info(f"Loaded {len(entities)} entities")

    candidate_groups = build_candidate_groups(entities)
    log.info(f"Found {len(candidate_groups)} candidate duplicate groups")

    if not candidate_groups:
        return 0, 0

    # Log candidate groups for review
    for i, group in enumerate(candidate_groups):
        names = [f"{e['name']} (id={e['id']})" for e in group]
        log.info(f"Candidate group {i + 1}: {', '.join(names)}")

    # Process in batches of up to 30 groups
    batch_size = 30
    total_merged = 0
    total_groups = 0

    for batch_start in range(0, len(candidate_groups), batch_size):
        batch = candidate_groups[batch_start:batch_start + batch_size]
        merges = ask_haiku_for_merges(batch)

        for merge in merges:
            try:
                if execute_merge(conn, merge):
                    total_groups += 1
                    total_merged += len(merge.get("merge_ids", []))
                    log.info(f"  Reason: {merge.get('reason', 'N/A')}")
            except Exception as e:
                log.error(f"Failed to execute merge {merge}: {e}")

    return total_groups, total_merged


# ---------------------------------------------------------------------------
# Part 2: Brief-Entity Linking
# ---------------------------------------------------------------------------

def ensure_brief_entities_table(conn: sqlite3.Connection):
    """Create the brief_entities junction table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS brief_entities (
            brief_id INTEGER NOT NULL,
            entity_id INTEGER NOT NULL,
            mention_count INTEGER DEFAULT 1,
            PRIMARY KEY (brief_id, entity_id),
            FOREIGN KEY (brief_id) REFERENCES briefs(id),
            FOREIGN KEY (entity_id) REFERENCES entities(id)
        )
    """)
    conn.commit()
    log.info("Ensured brief_entities table exists")


def build_entity_search_terms(conn: sqlite3.Connection) -> list[tuple[int, list[str]]]:
    """
    Build a list of (entity_id, [search_terms]) for text matching.
    Each entity contributes its name plus all aliases.
    Terms are sorted longest-first to prefer specific matches.
    """
    cur = conn.execute("SELECT id, name, aliases FROM entities")
    result = []
    for eid, name, aliases_json in cur.fetchall():
        terms = [name]
        if aliases_json:
            try:
                aliases = json.loads(aliases_json)
                if isinstance(aliases, list):
                    terms.extend(aliases)
            except (json.JSONDecodeError, TypeError):
                pass
        # Deduplicate, sort longest first
        seen = set()
        unique_terms = []
        for t in terms:
            t_lower = t.lower().strip()
            if t_lower and t_lower not in seen:
                seen.add(t_lower)
                unique_terms.append(t)
        unique_terms.sort(key=len, reverse=True)
        result.append((eid, unique_terms))
    return result


def count_mentions(text: str, terms: list[str]) -> int:
    """
    Count how many times any of the given terms appear in the text.
    Case-insensitive, word-boundary aware for short terms (<=4 chars).
    """
    text_lower = text.lower()
    total = 0
    for term in terms:
        term_lower = term.lower()
        if len(term_lower) <= 4:
            # Use word boundary matching for short terms/acronyms
            pattern = r"\b" + re.escape(term_lower) + r"\b"
            total += len(re.findall(pattern, text_lower))
        else:
            # Simple substring count for longer terms
            total += text_lower.count(term_lower)
    return total


def link_briefs_to_entities(conn: sqlite3.Connection) -> int:
    """
    Scan each brief's content for entity mentions and insert into brief_entities.
    Returns the number of links created.
    """
    ensure_brief_entities_table(conn)

    # Clear existing links for a clean run
    conn.execute("DELETE FROM brief_entities")
    conn.commit()

    # Get all briefs
    briefs = conn.execute("SELECT id, title, content FROM briefs").fetchall()
    log.info(f"Scanning {len(briefs)} briefs for entity mentions")

    # Get entity search terms
    entity_terms = build_entity_search_terms(conn)
    log.info(f"Matching against {len(entity_terms)} entities")

    links_created = 0
    for brief_id, title, content in briefs:
        # Combine title and content for matching
        full_text = f"{title} {content}"
        for entity_id, terms in entity_terms:
            mentions = count_mentions(full_text, terms)
            if mentions > 0:
                conn.execute(
                    "INSERT INTO brief_entities (brief_id, entity_id, mention_count) "
                    "VALUES (?, ?, ?)",
                    (brief_id, entity_id, mentions)
                )
                links_created += 1

    conn.commit()
    log.info(f"Created {links_created} brief-entity links")
    return links_created


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log.info("=" * 60)
    log.info("Entity Resolution and Linking - starting")
    log.info("=" * 60)

    conn = sqlite3.connect(_INTEL_DB, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=120000")

    # Part 1: Deduplication
    log.info("--- Part 1: Entity Deduplication ---")
    groups_found, entities_merged = deduplicate_entities(conn)
    log.info(f"Deduplication complete: {groups_found} groups merged, {entities_merged} entities absorbed")

    # Part 2: Brief-Entity Linking
    log.info("--- Part 2: Brief-Entity Linking ---")
    links_created = link_briefs_to_entities(conn)
    log.info(f"Linking complete: {links_created} brief-entity links created")

    # Summary
    remaining = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    log.info("=" * 60)
    log.info(f"SUMMARY")
    log.info(f"  Duplicate groups resolved: {groups_found}")
    log.info(f"  Entities merged (removed): {entities_merged}")
    log.info(f"  Entities remaining: {remaining}")
    log.info(f"  Brief-entity links created: {links_created}")
    log.info("=" * 60)

    # Print summary to stdout for cron capture
    print(json.dumps({
        "duplicate_groups": groups_found,
        "entities_merged": entities_merged,
        "entities_remaining": remaining,
        "brief_entity_links": links_created,
    }, indent=2))

    conn.close()


if __name__ == "__main__":
    main()
