"""
Meridian Ontology - Core CRUD Operations

Provides typed, audited access to the intelligence ontology:
objects, properties, links, and changelog.

Usage:
    from ontology import Ontology
    ont = Ontology("~/.atrophy/agents/general_montgomery/data/intelligence.db")
    obj_id = ont.upsert_object("Russia", "country", source="brief")
    ont.set_property(obj_id, "gdp_usd", "1.86T", source="worldbank")
    ont.add_link(obj_id, target_id, "funds", confidence=0.9)
"""

import json
import os
import sqlite3
from collections import deque
from typing import Optional


class Ontology:
    """Core CRUD operations for the Meridian ontology."""

    def __init__(self, db_path: str):
        self.db_path = os.path.expanduser(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def close(self):
        """Close the database connection."""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ------------------------------------------------------------------
    # Object operations
    # ------------------------------------------------------------------

    def upsert_object(
        self,
        name: str,
        type: str,
        subtype: str = None,
        aliases: list = None,
        lat: float = None,
        lon: float = None,
        country_code: str = None,
        description: str = None,
        status: str = "active",
        source: str = None,
        agent: str = None,
    ) -> int:
        """Find or create an object. Returns object ID.

        Match priority:
        1. Exact name+type match (case insensitive)
        2. Alias match (search aliases JSON array)
        3. Create if not found, update if found
        """
        cursor = self.conn.cursor()

        # Try exact name+type match (case insensitive)
        existing = cursor.execute(
            "SELECT id FROM objects WHERE LOWER(name) = LOWER(?) AND LOWER(type) = LOWER(?)",
            (name, type),
        ).fetchone()

        if existing is None:
            # Try alias match - search aliases JSON arrays
            existing = self._find_by_alias(name, type)

        if existing is not None:
            obj_id = existing["id"] if isinstance(existing, sqlite3.Row) else existing
            self._update_object(obj_id, name, type, subtype, aliases, lat, lon,
                                country_code, description, status, source, agent)
            return obj_id

        # Create new object
        aliases_json = json.dumps(aliases) if aliases else None
        cursor.execute(
            """INSERT INTO objects (type, subtype, name, aliases, status, description,
                                    lat, lon, country_code)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (type, subtype, name, aliases_json, status, description, lat, lon, country_code),
        )
        obj_id = cursor.lastrowid
        self.conn.commit()

        self._log_change(obj_id, "objects", obj_id, "create", source=source, agent=agent)
        return obj_id

    def _find_by_alias(self, name: str, type: str = None) -> Optional[int]:
        """Search aliases JSON arrays for a matching name."""
        query = "SELECT id, aliases FROM objects WHERE aliases IS NOT NULL"
        params = []
        if type:
            query += " AND LOWER(type) = LOWER(?)"
            params.append(type)

        rows = self.conn.execute(query, params).fetchall()
        name_lower = name.lower()

        for row in rows:
            try:
                aliases = json.loads(row["aliases"])
                if isinstance(aliases, list):
                    for alias in aliases:
                        if isinstance(alias, str) and alias.lower() == name_lower:
                            return row["id"]
            except (json.JSONDecodeError, TypeError):
                continue

        return None

    def _update_object(
        self,
        obj_id: int,
        name: str,
        type: str,
        subtype: str = None,
        aliases: list = None,
        lat: float = None,
        lon: float = None,
        country_code: str = None,
        description: str = None,
        status: str = "active",
        source: str = None,
        agent: str = None,
    ):
        """Update an existing object, logging changes."""
        current = self.conn.execute(
            "SELECT * FROM objects WHERE id = ?", (obj_id,)
        ).fetchone()
        if not current:
            return

        updates = {}
        if subtype and subtype != current["subtype"]:
            updates["subtype"] = subtype
        if description and description != current["description"]:
            updates["description"] = description
        if status and status != current["status"]:
            updates["status"] = status
        if lat is not None and lat != current["lat"]:
            updates["lat"] = lat
        if lon is not None and lon != current["lon"]:
            updates["lon"] = lon
        if country_code and country_code != current["country_code"]:
            updates["country_code"] = country_code

        # Merge aliases
        if aliases:
            existing_aliases = []
            if current["aliases"]:
                try:
                    existing_aliases = json.loads(current["aliases"])
                except (json.JSONDecodeError, TypeError):
                    existing_aliases = []
            merged = list(set(existing_aliases + aliases))
            if set(merged) != set(existing_aliases):
                updates["aliases"] = json.dumps(merged)

        if not updates:
            # Touch last_seen even if nothing changed
            self.conn.execute(
                "UPDATE objects SET last_seen = CURRENT_TIMESTAMP WHERE id = ?",
                (obj_id,),
            )
            self.conn.commit()
            return

        # Build and execute UPDATE
        set_clauses = [f"{k} = ?" for k in updates]
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        set_clauses.append("last_seen = CURRENT_TIMESTAMP")
        values = list(updates.values()) + [obj_id]

        self.conn.execute(
            f"UPDATE objects SET {', '.join(set_clauses)} WHERE id = ?",
            values,
        )
        self.conn.commit()

        # Log each field change
        for field, new_val in updates.items():
            old_val = current[field]
            self._log_change(
                obj_id, "objects", obj_id, "update",
                field=field,
                old_value=str(old_val) if old_val is not None else None,
                new_value=str(new_val),
                source=source, agent=agent,
            )

    def get_object(self, object_id: int) -> Optional[dict]:
        """Get object with all current properties and links."""
        row = self.conn.execute(
            "SELECT * FROM objects WHERE id = ?", (object_id,)
        ).fetchone()
        if not row:
            return None

        obj = dict(row)

        # Parse aliases
        if obj["aliases"]:
            try:
                obj["aliases"] = json.loads(obj["aliases"])
            except (json.JSONDecodeError, TypeError):
                obj["aliases"] = []
        else:
            obj["aliases"] = []

        # Attach current properties (those without valid_to)
        obj["properties"] = self.get_properties(object_id)

        # Attach links
        obj["links"] = self.get_links(object_id)

        return obj

    def search_objects(self, query: str, type: str = None, limit: int = 20) -> list:
        """Search objects by name, aliases, or description."""
        params = []
        conditions = []
        search_pattern = f"%{query}%"

        # Name match
        conditions.append("(LOWER(name) LIKE LOWER(?) OR LOWER(aliases) LIKE LOWER(?) OR LOWER(description) LIKE LOWER(?))")
        params.extend([search_pattern, search_pattern, search_pattern])

        if type:
            conditions.append("LOWER(type) = LOWER(?)")
            params.append(type)

        where = " AND ".join(conditions)

        # Build final param list: WHERE params, then ORDER BY params, then LIMIT
        all_params = params + [query, f"{query}%", limit]

        rows = self.conn.execute(
            f"""SELECT id, type, subtype, name, aliases, status, description,
                       lat, lon, country_code
                FROM objects
                WHERE {where}
                ORDER BY
                    CASE WHEN LOWER(name) = LOWER(?) THEN 0
                         WHEN LOWER(name) LIKE LOWER(?) THEN 1
                         ELSE 2 END,
                    name
                LIMIT ?""",
            all_params,
        ).fetchall()

        results = []
        for row in rows:
            obj = dict(row)
            if obj["aliases"]:
                try:
                    obj["aliases"] = json.loads(obj["aliases"])
                except (json.JSONDecodeError, TypeError):
                    obj["aliases"] = []
            else:
                obj["aliases"] = []
            results.append(obj)

        return results

    def find_object(self, name: str, type: str = None) -> Optional[int]:
        """Find object by exact or fuzzy name match.

        Returns object ID or None.
        """
        # Exact match first
        if type:
            row = self.conn.execute(
                "SELECT id FROM objects WHERE LOWER(name) = LOWER(?) AND LOWER(type) = LOWER(?)",
                (name, type),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT id FROM objects WHERE LOWER(name) = LOWER(?)",
                (name,),
            ).fetchone()

        if row:
            return row["id"]

        # Alias match
        alias_match = self._find_by_alias(name, type)
        if alias_match:
            return alias_match

        # Fuzzy: LIKE match (prefix)
        if type:
            row = self.conn.execute(
                "SELECT id FROM objects WHERE LOWER(name) LIKE LOWER(?) AND LOWER(type) = LOWER(?) LIMIT 1",
                (f"{name}%", type),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT id FROM objects WHERE LOWER(name) LIKE LOWER(?) LIMIT 1",
                (f"{name}%",),
            ).fetchone()

        return row["id"] if row else None

    # ------------------------------------------------------------------
    # Property operations
    # ------------------------------------------------------------------

    def set_property(
        self,
        object_id: int,
        key: str,
        value: str,
        value_type: str = "string",
        confidence: float = 1.0,
        source: str = None,
        valid_from: str = None,
    ) -> None:
        """Set a property on an object. Supersedes previous value (sets valid_to)."""
        # Close any existing property with the same key
        existing = self.conn.execute(
            """SELECT id, value FROM properties
               WHERE object_id = ? AND key = ? AND valid_to IS NULL""",
            (object_id, key),
        ).fetchone()

        old_value = None
        if existing:
            old_value = existing["value"]
            if old_value == value:
                # Same value, no change needed
                return
            self.conn.execute(
                "UPDATE properties SET valid_to = CURRENT_TIMESTAMP WHERE id = ?",
                (existing["id"],),
            )

        self.conn.execute(
            """INSERT INTO properties (object_id, key, value, value_type,
                                       confidence, source, valid_from)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (object_id, key, value, value_type, confidence, source, valid_from),
        )
        self.conn.commit()

        self._log_change(
            object_id, "properties", object_id, "set",
            field=key, old_value=old_value, new_value=value, source=source,
        )

    def get_properties(self, object_id: int) -> list:
        """Get all current properties for an object (valid_to IS NULL)."""
        rows = self.conn.execute(
            """SELECT key, value, value_type, confidence, source, valid_from, created_at
               FROM properties
               WHERE object_id = ? AND valid_to IS NULL
               ORDER BY key""",
            (object_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Link operations
    # ------------------------------------------------------------------

    def add_link(
        self,
        from_id: int,
        to_id: int,
        type: str,
        subtype: str = None,
        confidence: float = 0.8,
        source: str = None,
        description: str = None,
    ) -> int:
        """Add a link between objects. Deduplicates by from+to+type+source."""
        # Check for existing duplicate
        existing = self.conn.execute(
            """SELECT id FROM links
               WHERE from_id = ? AND to_id = ? AND type = ?
                 AND (source = ? OR (source IS NULL AND ? IS NULL))""",
            (from_id, to_id, type, source, source),
        ).fetchone()

        if existing:
            # Update confidence and description if provided
            self.conn.execute(
                """UPDATE links SET confidence = ?, description = COALESCE(?, description)
                   WHERE id = ?""",
                (confidence, description, existing["id"]),
            )
            self.conn.commit()
            return existing["id"]

        cursor = self.conn.execute(
            """INSERT INTO links (from_id, to_id, type, subtype, description,
                                  confidence, source)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (from_id, to_id, type, subtype, description, confidence, source),
        )
        link_id = cursor.lastrowid
        self.conn.commit()

        self._log_change(
            from_id, "links", link_id, "create",
            new_value=f"{from_id} -> {to_id} ({type})", source=source,
        )
        return link_id

    def get_links(self, object_id: int, direction: str = "both") -> list:
        """Get all links for an object.

        Args:
            object_id: The object to get links for
            direction: 'outgoing', 'incoming', or 'both'
        """
        results = []

        if direction in ("outgoing", "both"):
            rows = self.conn.execute(
                """SELECT l.*, o.name as to_name, o.type as to_type
                   FROM links l
                   JOIN objects o ON o.id = l.to_id
                   WHERE l.from_id = ?
                   ORDER BY l.type, l.confidence DESC""",
                (object_id,),
            ).fetchall()
            for r in rows:
                d = dict(r)
                d["direction"] = "outgoing"
                results.append(d)

        if direction in ("incoming", "both"):
            rows = self.conn.execute(
                """SELECT l.*, o.name as from_name, o.type as from_type
                   FROM links l
                   JOIN objects o ON o.id = l.from_id
                   WHERE l.to_id = ?
                   ORDER BY l.type, l.confidence DESC""",
                (object_id,),
            ).fetchall()
            for r in rows:
                d = dict(r)
                d["direction"] = "incoming"
                results.append(d)

        return results

    # ------------------------------------------------------------------
    # Graph operations
    # ------------------------------------------------------------------

    def get_network(self, object_id: int, depth: int = 1) -> dict:
        """Get ego network - object + N hops of connected objects.

        Returns:
            {
                "root": <object dict>,
                "nodes": {id: <object summary>},
                "edges": [<link dicts>],
            }
        """
        visited = set()
        nodes = {}
        edges = []
        frontier = {object_id}

        for hop in range(depth + 1):
            next_frontier = set()
            for oid in frontier:
                if oid in visited:
                    continue
                visited.add(oid)

                # Get node summary
                row = self.conn.execute(
                    "SELECT id, type, subtype, name, status FROM objects WHERE id = ?",
                    (oid,),
                ).fetchone()
                if row:
                    nodes[oid] = dict(row)

                if hop < depth:
                    # Get outgoing links
                    out_links = self.conn.execute(
                        "SELECT * FROM links WHERE from_id = ?", (oid,)
                    ).fetchall()
                    for link in out_links:
                        edges.append(dict(link))
                        next_frontier.add(link["to_id"])

                    # Get incoming links
                    in_links = self.conn.execute(
                        "SELECT * FROM links WHERE to_id = ?", (oid,)
                    ).fetchall()
                    for link in in_links:
                        edges.append(dict(link))
                        next_frontier.add(link["from_id"])

            frontier = next_frontier - visited

        # Deduplicate edges by ID
        seen_edge_ids = set()
        unique_edges = []
        for e in edges:
            if e["id"] not in seen_edge_ids:
                seen_edge_ids.add(e["id"])
                unique_edges.append(e)

        root = self.get_object(object_id)

        return {
            "root": root,
            "nodes": nodes,
            "edges": unique_edges,
        }

    def find_path(self, from_id: int, to_id: int, max_hops: int = 3) -> list:
        """Find shortest path between two objects using BFS.

        Returns list of (object_id, link_id, link_type) tuples from source to target.
        Empty list if no path found.
        """
        if from_id == to_id:
            return [(from_id, None, None)]

        # BFS
        queue = deque()
        queue.append((from_id, [(from_id, None, None)]))
        visited = {from_id}

        while queue:
            current, path = queue.popleft()

            if len(path) - 1 >= max_hops:
                continue

            # Check all links from current node
            links = self.conn.execute(
                """SELECT id, from_id, to_id, type FROM links
                   WHERE from_id = ? OR to_id = ?""",
                (current, current),
            ).fetchall()

            for link in links:
                neighbor = link["to_id"] if link["from_id"] == current else link["from_id"]
                if neighbor in visited:
                    continue

                new_path = path + [(neighbor, link["id"], link["type"])]

                if neighbor == to_id:
                    return new_path

                visited.add(neighbor)
                queue.append((neighbor, new_path))

        return []  # No path found

    # ------------------------------------------------------------------
    # Changelog
    # ------------------------------------------------------------------

    def _log_change(
        self,
        object_id: int,
        table: str,
        record_id: int,
        action: str,
        field: str = None,
        old_value: str = None,
        new_value: str = None,
        source: str = None,
        agent: str = None,
    ):
        """Record a change in the audit log."""
        self.conn.execute(
            """INSERT INTO changelog (object_id, table_name, record_id, action,
                                      field, old_value, new_value, source, agent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (object_id, table, record_id, action, field, old_value, new_value, source, agent),
        )
        self.conn.commit()

    def get_changelog(self, object_id: int = None, limit: int = 50) -> list:
        """Get changelog entries, optionally filtered by object."""
        if object_id:
            rows = self.conn.execute(
                """SELECT * FROM changelog WHERE object_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (object_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM changelog ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Get summary statistics for the ontology."""
        return {
            "objects": self.conn.execute("SELECT COUNT(*) FROM objects").fetchone()[0],
            "properties": self.conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0],
            "links": self.conn.execute("SELECT COUNT(*) FROM links").fetchone()[0],
            "changelog": self.conn.execute("SELECT COUNT(*) FROM changelog").fetchone()[0],
            "brief_objects": self.conn.execute("SELECT COUNT(*) FROM brief_objects").fetchone()[0],
            "types": [
                r[0] for r in self.conn.execute(
                    "SELECT DISTINCT type FROM objects ORDER BY type"
                ).fetchall()
            ],
            "link_types": [
                r[0] for r in self.conn.execute(
                    "SELECT DISTINCT type FROM links ORDER BY type"
                ).fetchall()
            ],
        }
