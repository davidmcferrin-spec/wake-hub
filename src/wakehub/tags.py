"""Free-form tags shared by computers and hardware.

#Office and office are the same tag. The oldest saved spelling is the one that is stored.
"""

from __future__ import annotations

import json
import logging
import sqlite3

from wakehub.errors import WakeHubError
from wakehub.hub import Hub

log = logging.getLogger("wakehub.tags")

TABLES = ("devices", "pdus", "amt_endpoints", "jetkvm_endpoints", "plugs", "ups_cards", "rokus", "pdu_outlets")


def tag_key(value: object) -> str:
    return str(value).strip().lstrip("#").strip().casefold()


def normalize_tags(values: list[str] | None, known: dict[str, str] | None = None, *, validate: bool = True) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    spellings = known or {}
    for value in values or []:
        for piece in str(value).replace(",", " ").split():
            text = piece.strip().lstrip("#").strip()
            if not text:
                continue
            key = text.casefold()
            if key in spellings:
                display = spellings[key]
            else:
                if validate and len(text) > 32:
                    raise WakeHubError("a tag must be 32 characters or fewer")
                display = text
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(display)
    if validate and len(cleaned) > 20:
        raise WakeHubError("a record can have at most 20 tags")
    return cleaned


def canonical_tags(hub: Hub, values: list[str] | None) -> list[str]:
    with hub.lock:
        return normalize_tags(values, spellings(hub.db))


def has_tags(owned: list[str], wanted: list[str]) -> bool:
    keys = {tag_key(item) for item in owned}
    keys.discard("")
    return all(tag_key(item) in keys for item in wanted)


def list_tags(hub: Hub) -> list[str]:
    with hub.lock:
        found = spellings(hub.db)
    return [found[key] for key in sorted(found)]


def spellings(conn: sqlite3.Connection) -> dict[str, str]:
    known: dict[str, str] = {}
    for _created, _rank, _row_id, table, raw in _tag_rows(conn):
        for tags in _tag_lists(table, raw):
            _remember(known, normalize_tags(tags, known, validate=False))
    return known


def migrate_tag_case(conn: sqlite3.Connection) -> None:
    """One spelling per tag. The oldest row keeps the letters it was saved with."""
    known: dict[str, str] = {}
    for _created, _rank, row_id, table, raw in _tag_rows(conn):
        if table == "salvos":
            _migrate_salvo(conn, row_id, raw, known)
            continue
        tags = _load_list(raw, table, row_id)
        if tags is None:
            continue
        cleaned = normalize_tags(tags, known, validate=False)
        _remember(known, cleaned)
        if cleaned != tags:
            conn.execute(f"UPDATE {table} SET tags = ? WHERE id = ?", (json.dumps(cleaned), row_id))


def _remember(known: dict[str, str], tags: list[str]) -> None:
    for tag in tags:
        known.setdefault(tag.casefold(), tag)


def _has_column(conn: sqlite3.Connection, table: str, name: str) -> bool:
    return name in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _tag_rows(conn: sqlite3.Connection) -> list[tuple[str, int, int, str, str]]:
    found: list[tuple[str, int, int, str, str]] = []
    for rank, table in enumerate(TABLES):
        if not _has_column(conn, table, "tags"):
            continue
        if table == "pdu_outlets":
            query = (
                "SELECT o.id AS id, o.tags AS tags, COALESCE(p.created_at, '') AS created_at "
                "FROM pdu_outlets AS o LEFT JOIN pdus AS p ON p.id = o.pdu_id"
            )
        elif _has_column(conn, table, "created_at"):
            query = f"SELECT id, tags, created_at FROM {table}"
        else:
            query = f"SELECT id, tags, '' AS created_at FROM {table}"
        for row in conn.execute(query):
            found.append((row["created_at"] or "", rank, int(row["id"]), table, row["tags"] or "[]"))
    if _has_column(conn, "salvos", "steps"):
        for row in conn.execute("SELECT id, steps, created_at FROM salvos"):
            found.append((row["created_at"] or "", len(TABLES), int(row["id"]), "salvos", row["steps"] or "[]"))
    found.sort()
    return found


def _load_list(raw: str, table: str, row_id: int) -> list | None:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        log.warning("left unreadable tags on %s %s", table, row_id)
        return None
    if not isinstance(value, list):
        log.warning("left non-list tags on %s %s", table, row_id)
        return None
    return value


def _tag_lists(table: str, raw: str) -> list[list]:
    if table == "salvos":
        try:
            steps = json.loads(raw or "[]")
        except json.JSONDecodeError:
            return []
        if not isinstance(steps, list):
            return []
        return [
            step["tags"]
            for step in steps
            if isinstance(step, dict) and step.get("target_kind") == "tag" and isinstance(step.get("tags"), list)
        ]
    loaded = _load_list(raw, table, 0)
    if loaded is None:
        return []
    return [loaded]


def _migrate_salvo(conn: sqlite3.Connection, row_id: int, raw: str, known: dict[str, str]) -> None:
    try:
        steps = json.loads(raw or "[]")
    except json.JSONDecodeError:
        log.warning("left unreadable salvo steps on %s", row_id)
        return
    if not isinstance(steps, list):
        return
    changed = False
    for step in steps:
        if not isinstance(step, dict) or step.get("target_kind") != "tag" or not isinstance(step.get("tags"), list):
            continue
        cleaned = normalize_tags(step["tags"], known, validate=False)
        _remember(known, cleaned)
        if cleaned != step["tags"]:
            step["tags"] = cleaned
            changed = True
    if changed:
        conn.execute("UPDATE salvos SET steps = ? WHERE id = ?", (json.dumps(steps), row_id))
